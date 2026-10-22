"""Deterministic gate from external candidates to internal Engine events.

VerificationContext is supplied by trusted backend code, NEVER deserialized from
planner/client input. Its receipts/principals/assessments must come from authenticated
adapters. This module checks that contract; it does not implement real adapters,
camera signatures, caregiver authentication, AI verification, or task orchestration.
"""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from pydantic import ConfigDict, Field, ValidationError

from ..schemas import Profile
from .engine import CompletionEvaluation, CompletionEvaluator
from .models import (
    CapabilityFacts,
    CapabilityKey,
    Evidence,
    FeasibilityAssessment,
    ObservationSnapshot,
    TargetBinding,
    TaskEvent,
    TaskModel,
    TaskPlan,
    TaskState,
    TaskStep,
    Text,
)
from .semantics import SemanticReview

ObservationSource = Literal["camera_observation", "caregiver_report"]


class ActionPolicy(TaskModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["locate", "press", "observe_state", "traverse", "place_inside"]
    # (outcome, number of ordered target roles); never provided by a TaskPlan.
    outcomes: tuple[tuple[Text, int], ...]
    requires_binding: bool = True
    required_capabilities: tuple[CapabilityKey, ...] = ()
    requires_physical_context: bool = False
    allowed_sources: frozenset[ObservationSource] = frozenset(
        {
            "camera_observation",
            "caregiver_report",
        }
    )
    camera_confidence_threshold: float = Field(default=0.9, ge=0, le=1, allow_inf_nan=False)


ACTION_POLICIES: Mapping[str, ActionPolicy] = MappingProxyType(
    {
        "locate": ActionPolicy(
            action="locate", outcomes=(("target_located", 1),), requires_binding=False
        ),
        "press": ActionPolicy(
            action="press",
            outcomes=(("pressed", 1),),
            required_capabilities=("can_press_button", "can_extend_arm"),
            requires_physical_context=True,
        ),
        "observe_state": ActionPolicy(
            action="observe_state", outcomes=(("state_open", 1), ("items_inside", 2))
        ),
        "traverse": ActionPolicy(
            action="traverse",
            outcomes=(("passed_through", 1),),
            required_capabilities=("can_traverse",),
            requires_physical_context=True,
        ),
        "place_inside": ActionPolicy(
            action="place_inside",
            outcomes=(("placed_inside", 2),),
            required_capabilities=("can_grasp", "can_extend_arm", "can_place_inside"),
            requires_physical_context=True,
        ),
    }
)


@dataclass(frozen=True)
class EvidenceReceipt:
    """Exact claim attested by a backend adapter, not a candidate's verified flag."""

    receipt_id: str
    principal_id: str
    evidence: Evidence
    task_id: str
    plan_id: str


@dataclass(frozen=True)
class VerificationContext:
    task_id: str
    plan_id: str
    snapshot: ObservationSnapshot
    capabilities: CapabilityFacts
    receipts: Mapping[str, EvidenceReceipt] = field(default_factory=dict)
    camera_principals: frozenset[str] = frozenset()
    caregiver_principals: frozenset[str] = frozenset()
    feasibility: Mapping[str, FeasibilityAssessment] = field(default_factory=dict)
    # Separate request semantics dependency. Action Policy itself remains unchanged;
    # Service and Prompting enforce this before progressing or emitting a cue.
    semantic_review: SemanticReview | None = None


@dataclass(frozen=True)
class VerificationResult:
    decision: Literal["allow", "confirm", "assist", "stop"]
    reason_code: str
    event: TaskEvent | None = None


def profile_to_capabilities(profile: Profile) -> CapabilityFacts:
    """Map only existing facts; grasp/arm extension do not prove placement/traversal."""
    return CapabilityFacts(
        can_grasp=profile.can_grasp,
        can_press_button=profile.can_press_button,
        can_extend_arm=profile.can_extend_arm,
    )


def _plan(value: TaskPlan | dict) -> TaskPlan:
    parsed = TaskPlan.model_validate(value.model_dump() if isinstance(value, TaskPlan) else value)
    for step in parsed.steps:
        policy = ACTION_POLICIES.get(step.action)
        if policy is None:
            raise ValueError("unsupported_action")
        cardinality = dict(policy.outcomes).get(step.completion_goal.outcome)
        if cardinality is None:
            raise ValueError("unsupported_outcome")
        if (
            len(step.target_keys) != cardinality
            or step.completion_goal.target_keys != step.target_keys
        ):
            raise ValueError("invalid_target_roles")
    return parsed


def _bindings(
    plan: TaskPlan,
    bindings: Mapping[str, TargetBinding],
    snapshot: ObservationSnapshot,
) -> str | None:
    targets = {target.target_key: target for target in plan.targets}
    for key, value in bindings.items():
        binding = TargetBinding.model_validate(value.model_dump())
        if key != binding.target_key or key not in targets:
            return "unknown_target_key"
        if binding.observation_revision != snapshot.revision:
            return "stale_binding"
        target = targets[key]
        matches = [
            obj
            for obj in snapshot.objects
            if obj.concept == target.concept
            and all(obj.qualifiers.get(k) == v for k, v in target.qualifiers.items())
        ]
        if len(matches) != 1:
            return "ambiguous_or_missing_target"
        if binding.object_id != matches[0].object_id:
            return "ungrounded_binding"
    return None


def verify_step(
    plan: TaskPlan | dict,
    step_id: str,
    bindings: Mapping[str, TargetBinding],
    context: VerificationContext,
) -> VerificationResult:
    """Check structure, existing bindings, capability/hard constraints, then context.

    An allow result is scoped to these inputs and must be recomputed when they change.
    No AI callable exists here; context_review_required is only a request for review.
    """
    try:
        parsed = _plan(plan)
    except ValidationError:
        return VerificationResult("stop", "invalid_plan_structure")
    except ValueError as exc:
        return VerificationResult("stop", str(exc))
    if context.plan_id != parsed.plan_id:
        return VerificationResult("stop", "plan_context_mismatch")
    step = next((step for step in parsed.steps if step.step_id == step_id), None)
    if step is None:
        return VerificationResult("stop", "unknown_step")
    try:
        snapshot = ObservationSnapshot.model_validate(context.snapshot.model_dump())
        binding_error = _bindings(parsed, bindings, snapshot)
    except (ValidationError, AttributeError, TypeError):
        return VerificationResult("confirm", "invalid_observation_or_binding")
    if binding_error:
        return VerificationResult("confirm", binding_error)
    policy = ACTION_POLICIES[step.action]
    if policy.requires_binding and any(key not in bindings for key in step.target_keys):
        return VerificationResult("confirm", "target_unresolved")
    object_ids = tuple(bindings[key].object_id for key in step.target_keys if key in bindings)
    if len(object_ids) != len(set(object_ids)):
        return VerificationResult("confirm", "ambiguous_target_roles")
    try:
        capabilities = CapabilityFacts.model_validate(dict(context.capabilities))
    except (ValidationError, AttributeError, TypeError):
        return VerificationResult("stop", "invalid_capability_facts")
    required = [getattr(capabilities, key) for key in policy.required_capabilities]
    if any(value is False for value in required):
        return VerificationResult("assist", "capability_blocked")
    if any(value is None for value in required):
        return VerificationResult("confirm", "capability_unknown")
    if policy.requires_physical_context:
        assessment = context.feasibility.get(step_id)
        if assessment is None:
            return VerificationResult("confirm", "context_review_required")
        try:
            assessment = FeasibilityAssessment.model_validate(dict(assessment))
        except (ValidationError, AttributeError, TypeError):
            return VerificationResult("confirm", "invalid_physical_context")
        if (
            assessment.step_id != step_id
            or assessment.observation_revision != snapshot.revision
            or assessment.object_ids != object_ids
        ):
            return VerificationResult("confirm", "stale_physical_context")
        if assessment.feasible is False:
            return VerificationResult("assist", "physical_action_infeasible")
        if assessment.feasible is None:
            return VerificationResult("confirm", "context_review_required")
    return VerificationResult("allow", "constraints_satisfied")


def _evidence_error(
    step: TaskStep,
    evidence: Evidence,
    bindings: Mapping[str, TargetBinding],
    context: VerificationContext,
) -> str | None:
    policy = ACTION_POLICIES[step.action]
    if evidence.source not in policy.allowed_sources:
        return "evidence_source_not_allowed"
    if evidence.step_id != step.step_id or evidence.outcome != step.completion_goal.outcome:
        return "evidence_claim_mismatch"
    if evidence.target_keys != step.completion_goal.target_keys:
        return "evidence_target_mismatch"
    if any(key not in bindings for key in evidence.target_keys):
        return "evidence_target_unresolved"
    expected_ids = [bindings[key].object_id for key in evidence.target_keys]
    if evidence.object_ids != expected_ids:
        return "evidence_object_mismatch"
    if evidence.observation_revision != context.snapshot.revision:
        return "evidence_revision_mismatch"
    receipt = context.receipts.get(evidence.provenance_id)
    if receipt is None or receipt.receipt_id != evidence.provenance_id:
        return "provenance_missing"
    if receipt.task_id != context.task_id or receipt.plan_id != context.plan_id:
        return "provenance_scope_mismatch"
    principals = (
        context.camera_principals
        if evidence.source == "camera_observation"
        else context.caregiver_principals
    )
    if not receipt.principal_id or receipt.principal_id not in principals:
        return "source_principal_not_authorized"
    if receipt.evidence.model_dump() != evidence.model_dump():
        return "provenance_claim_mismatch"
    if evidence.source == "camera_observation" and (
        evidence.confidence is None or evidence.confidence < policy.camera_confidence_threshold
    ):
        return "insufficient_observation_confidence"
    return None


def verify_event(
    plan: TaskPlan | dict,
    state: TaskState,
    candidate: TaskEvent | dict,
    context: VerificationContext,
) -> VerificationResult:
    """Promote only validated data/cue events. Controls remain internal Engine inputs."""
    try:
        parsed = _plan(plan)
        current = TaskState.model_validate(state.model_dump())
        event = TaskEvent.model_validate(
            candidate.model_dump() if isinstance(candidate, TaskEvent) else candidate
        )
    except ValidationError:
        return VerificationResult("stop", "invalid_candidate_structure")
    except ValueError as exc:
        return VerificationResult("stop", str(exc))
    if (
        current.task_id != context.task_id
        or current.plan_id != parsed.plan_id
        or current.status != "active"
        or [step.step_id for step in current.steps] != [step.step_id for step in parsed.steps]
    ):
        return VerificationResult("confirm", "inactive_or_mismatched_state")
    index = next(
        (i for i, s in enumerate(current.steps) if s.step_id == current.current_step_id), None
    )
    if (
        index is None
        or current.steps[index].status not in ("active", "awaiting_target", "awaiting_evidence")
        or any(s.status != "completed" for s in current.steps[:index])
        or any(s.status != "pending" for s in current.steps[index + 1 :])
        or any(s.help_level > p.max_help_level for s, p in zip(current.steps, parsed.steps))
    ):
        return VerificationResult("confirm", "invalid_step_state")
    if event.type not in ("target_bound", "evidence_received", "cue_issued"):
        return VerificationResult("stop", "unsupported_candidate_event")
    if event.step_id not in (None, current.current_step_id):
        return VerificationResult("confirm", "step_mismatch")
    bindings = dict(current.target_bindings)
    if event.type == "target_bound":
        bindings[event.binding.target_key] = event.binding
    decision = verify_step(parsed, current.current_step_id, bindings, context)
    if decision.decision != "allow":
        return decision
    step = next(step for step in parsed.steps if step.step_id == current.current_step_id)
    if event.type == "evidence_received":
        if event.evidence.evidence_id in {item.evidence_id for item in current.evidence}:
            return VerificationResult("confirm", "duplicate_evidence_id")
        error = _evidence_error(step, event.evidence, bindings, context)
        if error:
            return VerificationResult("confirm", error)
    return VerificationResult("allow", "candidate_verified", event.model_copy(deep=True))


def trusted_completion_evaluator(
    plan: TaskPlan,
    bindings: Mapping[str, TargetBinding],
    context: VerificationContext,
) -> CompletionEvaluator:
    """Snapshot a trusted policy context; recheck every claim at evaluation time.

    This is the Engine injection point. Never replace it with an AI/test evaluator
    when accepting external candidates. Recreate it when observations/bindings change.
    """
    saved_plan, saved_bindings, saved_context = deepcopy((plan, dict(bindings), context))

    def evaluate(step: TaskStep, history: tuple[Evidence, ...]) -> CompletionEvaluation:
        considered = tuple(e.evidence_id for e in history)

        def pending(reason: str) -> CompletionEvaluation:
            return CompletionEvaluation(
                status="pending", considered_evidence_ids=considered, reason_code=reason
            )

        decision = verify_step(saved_plan, step.step_id, saved_bindings, saved_context)
        if decision.decision != "allow":
            return pending(decision.reason_code)
        expected = next(s for s in saved_plan.steps if s.step_id == step.step_id)
        if expected.model_dump() != step.model_dump():
            return pending("step_policy_mismatch")
        parsed = tuple(Evidence.model_validate(e.model_dump()) for e in history)
        if any(_evidence_error(step, e, saved_bindings, saved_context) for e in parsed):
            return pending("unverified_evidence")
        supporting = tuple(e.evidence_id for e in parsed if e.relation == "supports")
        conflicting = tuple(e.evidence_id for e in parsed if e.relation == "contradicts")
        status = "conflicting" if conflicting else "satisfied" if supporting else "pending"
        return CompletionEvaluation(
            status=status,
            considered_evidence_ids=considered,
            supporting_evidence_ids=supporting,
            conflicting_evidence_ids=conflicting,
            reason_code={
                "conflicting": "contradictory_evidence",
                "satisfied": "criterion_satisfied",
                "pending": "insufficient_evidence",
            }[status],
        )

    return evaluate
