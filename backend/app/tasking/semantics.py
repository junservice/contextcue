"""Backend-reviewed request semantics, independent of AI and execution feasibility.

No natural-language safety classifier lives here. Unreviewed text fails closed.
An authenticated adapter/human must resolve intent, addressee, refusal and hazards
BEFORE issuing a review. Neither a model's goal string nor its own approval counts.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from .models import TaskModel, TaskPlan, Text

# Reviewed semantic affordances, not observed presence, reachability or success.
# Unknown concepts can be located after review; physical use needs catalog review.
CONCEPT_ROLES = MappingProxyType(
    {
        "door_open_button": frozenset({"control"}),
        "elevator_call_button": frozenset({"control"}),
        "automatic_door_opening": frozenset({"passage"}),
        "garden_gate_opening": frozenset({"passage"}),
        "corridor": frozenset({"passage"}),
        "bag": frozenset({"container"}),
        "box": frozenset({"container"}),
        "pouch": frozenset({"container"}),
        "basket": frozenset({"container"}),
        "water_bottle": frozenset({"item"}),
        "book": frozenset({"item"}),
        "pen": frozenset({"item"}),
        "paper": frozenset({"item"}),
        "towel": frozenset({"item"}),
        "mug": frozenset({"item"}),
    }
)
SEMANTIC_ROLES = MappingProxyType(
    {
        ("locate", "target_located"): (None,),
        ("press", "pressed"): (frozenset({"control"}),),
        ("traverse", "passed_through"): (frozenset({"passage"}),),
        ("place_inside", "placed_inside"): (frozenset({"item"}), frozenset({"container"})),
        ("observe_state", "items_inside"): (frozenset({"item"}), frozenset({"container"})),
        ("observe_state", "state_open"): (frozenset({"passage", "container"}),),
    }
)


class IntentTarget(TaskModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    role: Text
    concept: Text
    qualifiers: tuple[tuple[Literal["color", "relative_position"], Text], ...] = ()


class IntentOperation(TaskModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal["locate", "press", "observe_state", "traverse", "place_inside"]
    outcome: Text
    roles: tuple[Text, ...] = Field(min_length=1)


class SemanticIntent(TaskModel):
    """Reviewed desired effects/roles; never derived from the candidate TaskPlan."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    targets: tuple[IntentTarget, ...] = Field(min_length=1)
    operations: tuple[IntentOperation, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_semantics(self):
        targets = {target.role: target for target in self.targets}
        identities = {(t.concept, tuple(sorted(t.qualifiers))) for t in self.targets}
        if len(targets) != len(self.targets) or len(identities) != len(self.targets):
            raise ValueError("ambiguous intent roles")
        for target in self.targets:
            if len(dict(target.qualifiers)) != len(target.qualifiers):
                raise ValueError("duplicate intent qualifiers")
        for operation in self.operations:
            requirements = SEMANTIC_ROLES.get((operation.action, operation.outcome))
            if requirements is None or len(requirements) != len(operation.roles):
                raise ValueError("unsupported semantic operation")
            if len(set(operation.roles)) != len(operation.roles):
                raise ValueError("ambiguous operation roles")
            for role, required in zip(operation.roles, requirements):
                target = targets.get(role)
                if target is None or (
                    required is not None
                    and not (CONCEPT_ROLES.get(target.concept, frozenset()) & required)
                ):
                    raise ValueError("inappropriate action target")
        if {role for operation in self.operations for role in operation.roles} != set(targets):
            raise ValueError("unused intent target")
        return self


@dataclass(frozen=True)
class SemanticReview:
    """Trusted dependency only, not a request/AI JSON field or source authentication.

    The backend reviewer owns the truth of this decision just as a physical adapter
    owns feasibility. Production authentication/review UI is not implemented here.
    """

    task_id: str
    plan_id: str
    goal: str
    request_fingerprint: str
    review_id: str
    disposition: Literal["ready", "unsupported", "ambiguous", "unsafe", "refused", "unknown"]
    intent: SemanticIntent | None = None


@dataclass(frozen=True)
class SemanticVerdict:
    decision: Literal["allow", "confirm", "stop"]
    reason_code: str


def request_fingerprint(request) -> str:
    # Capability/observation changes belong to Action Policy, not intent approval.
    fields = {name: getattr(request, name) for name in ("task_id", "plan_id", "goal", "transcript")}
    return hashlib.sha256(
        json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def review_request(request, *, review_id: str, disposition, intent=None) -> SemanticReview:
    """Issue a scoped backend review AFTER independent request interpretation.

    This helper does not interpret or approve text; callers must not derive intent
    from a generated plan or mark arbitrary text ready based only on its goal ID.
    """
    return SemanticReview(
        request.task_id,
        request.plan_id,
        request.goal,
        request_fingerprint(request),
        review_id,
        disposition,
        intent,
    )


def verify_review(review, *, task_id, plan_id, goal, fingerprint) -> SemanticVerdict:
    if not isinstance(review, SemanticReview):
        return SemanticVerdict("confirm", "semantic_review_required")
    if (
        not all(
            isinstance(value, str) and value.strip()
            for value in (review.task_id, review.plan_id, review.goal, review.review_id)
        )
        or not isinstance(review.request_fingerprint, str)
        or re.fullmatch(r"[0-9a-f]{64}", review.request_fingerprint) is None
    ):
        return SemanticVerdict("confirm", "invalid_semantic_review")
    if (review.task_id, review.plan_id, review.goal, review.request_fingerprint) != (
        task_id,
        plan_id,
        goal,
        fingerprint,
    ):
        return SemanticVerdict("confirm", "semantic_review_scope_mismatch")
    if not isinstance(review.disposition, str) or review.disposition not in {
        "ready",
        "unsupported",
        "ambiguous",
        "unsafe",
        "refused",
        "unknown",
    }:
        return SemanticVerdict("confirm", "invalid_semantic_review")
    if review.disposition != "ready":
        decision = "stop" if review.disposition in {"unsafe", "refused"} else "confirm"
        return SemanticVerdict(decision, "request_" + review.disposition)
    if not isinstance(review.intent, SemanticIntent):
        return SemanticVerdict("confirm", "invalid_semantic_review")
    try:
        SemanticIntent.model_validate(review.intent.model_dump())
    except (ValueError, TypeError, AttributeError):
        return SemanticVerdict("confirm", "invalid_semantic_review")
    return SemanticVerdict("allow", "request_semantics_reviewed")


def verify_plan_semantics(plan: TaskPlan, review: SemanticReview) -> SemanticVerdict:
    """Full-plan checks against independently reviewed desired effects and roles.

    No bindings, capabilities, coordinates, feasibility or Evidence are authorized.
    Call verify_review for the current request scope before this function.
    """
    if not isinstance(review, SemanticReview) or review.disposition != "ready":
        return SemanticVerdict("confirm", "semantic_review_required")
    intent = review.intent
    if not isinstance(intent, SemanticIntent):
        return SemanticVerdict("confirm", "invalid_semantic_review")
    identities = {(t.concept, tuple(sorted(t.qualifiers))): t.role for t in intent.targets}
    roles = {}
    for target in plan.targets:
        role = identities.get((target.concept, tuple(sorted(target.qualifiers.items()))))
        if role is None or role in roles.values():
            return SemanticVerdict("confirm", "semantic_target_mismatch")
        roles[target.target_key] = role
    if set(roles.values()) != {t.role for t in intent.targets}:
        return SemanticVerdict("confirm", "semantic_target_mismatch")
    expected = [(op.action, op.outcome, op.roles) for op in intent.operations]
    expected_effects = [op for op in expected if op[0] != "locate"]
    actual_effects = []
    located = set()
    required_locates = {op[2][0] for op in expected if op[0] == "locate"}
    if plan.steps[0].action != "locate":
        return SemanticVerdict("confirm", "semantic_plan_mismatch")
    for step in plan.steps:
        operation = (
            step.action,
            step.completion_goal.outcome,
            tuple(roles[key] for key in step.target_keys),
        )
        if operation[0] == "locate":
            if operation[1] != "target_located" or len(operation[2]) != 1:
                return SemanticVerdict("confirm", "semantic_plan_mismatch")
            role = operation[2][0]
            if role in located:
                return SemanticVerdict("confirm", "semantic_plan_mismatch")
            located.add(role)
        else:
            if any(role in required_locates and role not in located for role in operation[2]):
                return SemanticVerdict("confirm", "semantic_plan_mismatch")
            actual_effects.append(operation)
    if actual_effects != expected_effects or not required_locates <= located:
        return SemanticVerdict("confirm", "semantic_plan_mismatch")
    return SemanticVerdict("allow", "plan_semantics_verified")


def verify_execution_semantics(plan, context) -> SemanticVerdict:
    """Recheck reviewed intent on each Service/cue use, independently of Action Policy."""
    try:
        parsed = TaskPlan.model_validate(plan.model_dump())
    except (ValueError, AttributeError, TypeError):
        return SemanticVerdict("stop", "invalid_plan_structure")
    review = context.semantic_review
    if parsed.plan_id != context.plan_id:
        return SemanticVerdict("confirm", "semantic_review_scope_mismatch")
    result = verify_review(
        review,
        task_id=context.task_id,
        plan_id=context.plan_id,
        goal=parsed.goal,
        fingerprint=review.request_fingerprint if isinstance(review, SemanticReview) else None,
    )
    if result.decision != "allow":
        return result
    return verify_plan_semantics(parsed, review)
