"""Pure task transitions with an injected completion evaluator.

An active step is a control-state marker, not authorization to perform its action.
Bindings/Evidence are internal inputs assumed verified upstream, not authenticated
observations. Action policy and real source verification are outside this module.
"""

from dataclasses import dataclass
from typing import Literal, Protocol, Self

from pydantic import model_validator

from .models import Evidence, StepState, TaskEvent, TaskModel, TaskPlan, TaskState, TaskStep, Text


class CompletionEvaluation(TaskModel):
    status: Literal["satisfied", "pending", "conflicting"]
    considered_evidence_ids: tuple[Text, ...] = ()
    supporting_evidence_ids: tuple[Text, ...] = ()
    conflicting_evidence_ids: tuple[Text, ...] = ()
    reason_code: Text

    @model_validator(mode="after")
    def check_basis(self) -> Self:
        considered = set(self.considered_evidence_ids)
        supporting = set(self.supporting_evidence_ids)
        conflicting = set(self.conflicting_evidence_ids)
        for ids in (
            self.considered_evidence_ids, self.supporting_evidence_ids,
            self.conflicting_evidence_ids,
        ):
            if len(ids) != len(set(ids)):
                raise ValueError("evaluation Evidence IDs must be unique")
        if not (supporting | conflicting) <= considered or supporting & conflicting:
            raise ValueError("support/conflict must be disjoint subsets of considered Evidence")
        if self.status == "satisfied" and (not supporting or conflicting):
            raise ValueError("satisfied requires supporting Evidence and no conflict")
        if self.status == "conflicting" and not conflicting:
            raise ValueError("conflicting requires conflicting Evidence")
        if self.status == "pending" and conflicting:
            raise ValueError("conflicting Evidence requires a conflicting status")
        return self


class CompletionEvaluator(Protocol):
    def __call__(
        self, step: TaskStep, evidence_history: tuple[Evidence, ...],
    ) -> CompletionEvaluation: ...


@dataclass(frozen=True)
class TransitionResult:
    state: TaskState
    accepted: bool
    reason_code: str
    evaluation: CompletionEvaluation | None = None


def create_task_state(plan: TaskPlan, task_id: str) -> TaskState:
    """Start at the first step with independent zero help levels and no bindings."""
    return TaskState(
        task_id=task_id,
        plan_id=plan.plan_id,
        status="active",
        current_step_id=plan.steps[0].step_id,
        steps=[
            StepState(step_id=step.step_id, status="active" if index == 0 else "pending")
            for index, step in enumerate(plan.steps)
        ],
    )


def apply_event(
    plan: TaskPlan, state: TaskState, event: TaskEvent | None = None,
    *, evaluator: CompletionEvaluator | None = None,
) -> TransitionResult:
    """Apply one typed internal event without mutating or sharing the input state.

    No event means no response has been observed; it never implies difficulty.
    Stop/refusal/help requests are task-wide. Other controls may name the current
    step, and stale step references are rejected. Only active tasks can pause;
    confirmation/assistance holds cannot be cleared through pause/resume.
    """
    updated = state.model_copy(deep=True)

    def result(accepted: bool, reason: str) -> TransitionResult:
        return TransitionResult(state=updated, accepted=accepted, reason_code=reason)

    if event is None:
        return result(True, "no_event")
    if state.status in ("stopped", "completed"):
        return result(False, "terminal_state")
    # Safety/handoff requests must remain possible even with a mismatched plan.
    if event.type in ("stop", "refusal"):
        updated.status = "stopped"
        return result(True, "user_refused" if event.type == "refusal" else "task_stopped")
    if event.type == "help_requested":
        updated.status = "needs_assistance"
        return result(True, "assistance_requested")

    if state.plan_id != plan.plan_id or [s.step_id for s in state.steps] != [
        s.step_id for s in plan.steps
    ]:
        return result(False, "plan_state_mismatch")
    if any(s.help_level > p.max_help_level for s, p in zip(state.steps, plan.steps)):
        return result(False, "invalid_help_level")
    if event.step_id is not None and event.step_id != state.current_step_id:
        return result(False, "step_mismatch")
    current_index = next(
        (i for i, step in enumerate(state.steps) if step.step_id == state.current_step_id), None,
    )
    if state.status in ("active", "paused") and (
        current_index is None or state.steps[current_index].status not in (
            "active", "awaiting_target", "awaiting_evidence",
        )
    ):
        return result(False, "invalid_current_step")
    if state.status in ("active", "paused") and (
        any(step.status != "completed" for step in state.steps[:current_index])
        or any(step.status != "pending" for step in state.steps[current_index + 1:])
    ):
        return result(False, "invalid_step_sequence")
    if event.type == "resume":
        if state.status != "paused":
            return result(False, "invalid_transition")
        updated.status = "active"
        return result(True, "task_resumed")
    if state.status == "paused":
        return result(False, "task_paused")
    if state.status != "active":
        return result(False, "invalid_transition")

    if event.type == "pause":
        updated.status = "paused"
        return result(True, "task_paused")
    if event.type == "more_help":
        step = updated.steps[current_index]
        maximum = plan.steps[current_index].max_help_level
        if step.help_level == maximum:
            return result(True, "help_limit_reached")
        step.help_level += 1
        return result(True, "help_increased")
    if event.type == "manual_advance":
        updated.status = "needs_confirmation"
        return result(True, "confirmation_required")
    if event.type == "target_bound":
        if event.binding.target_key not in {target.target_key for target in plan.targets}:
            return result(False, "unknown_target_key")
        updated.target_bindings[event.binding.target_key] = event.binding.model_copy(deep=True)
        return result(True, "target_bound")
    if event.type == "cue_issued":
        updated.steps[current_index].status = "awaiting_evidence"
        return result(True, "cue_recorded")
    if event.type == "evidence_received":
        return _receive_evidence(plan, updated, current_index, event.evidence, evaluator)
    return result(False, "unsupported_event")


def _receive_evidence(
    plan: TaskPlan, state: TaskState, index: int, evidence: Evidence,
    evaluator: CompletionEvaluator | None,
) -> TransitionResult:
    step = plan.steps[index]
    if evidence.step_id != step.step_id:
        return TransitionResult(state, False, "step_mismatch")
    if evidence.evidence_id in {item.evidence_id for item in state.evidence}:
        return TransitionResult(state, False, "duplicate_evidence_id")
    known = set(step.target_keys) | set(step.completion_goal.target_keys)
    if not set(evidence.target_keys) <= known:
        return TransitionResult(state, False, "unknown_target_key")

    state.evidence.append(evidence.model_copy(deep=True))
    state.steps[index].status = "awaiting_evidence"
    if evaluator is None:
        return TransitionResult(state, True, "evaluator_not_configured")

    history = tuple(item for item in state.evidence if item.step_id == step.step_id)

    def invalid(reason: str) -> TransitionResult:
        # Retain the received record, but never advance on a broken evaluator.
        state.status = "needs_confirmation"
        return TransitionResult(state, False, reason)

    try:
        proposed = evaluator(
            step.model_copy(deep=True), tuple(item.model_copy(deep=True) for item in history),
        )
    except Exception:  # noqa: BLE001 - an injected evaluator must fail closed and retain Evidence.
        return invalid("completion_evaluator_failed")
    try:
        # Revalidate even constructed/mutated model instances from an internal callable.
        if not isinstance(proposed, CompletionEvaluation):
            raise TypeError("expected CompletionEvaluation")
        evaluation = CompletionEvaluation.model_validate(dict(proposed))
        by_id = {item.evidence_id: item for item in history}
        if not set(evaluation.considered_evidence_ids) <= by_id.keys():
            raise ValueError("evaluation must reference current-step Evidence")
        # Generic non-observation exclusions, not an action-specific/source trust policy.
        non_observations = {"cue_issued", "manual_progress", "model_assessment", "unknown"}
        for ids, relation in (
            (evaluation.supporting_evidence_ids, "supports"),
            (evaluation.conflicting_evidence_ids, "contradicts"),
        ):
            if any(by_id[key].source in non_observations or by_id[key].relation != relation
                   for key in ids):
                raise ValueError("evaluation requires decisive observational claims")
    except (ValueError, TypeError):
        return invalid("invalid_completion_evaluation")

    if evaluation.status == "conflicting":
        state.status = "needs_confirmation"
    elif evaluation.status == "satisfied":
        state.steps[index].status = "completed"
        if index + 1 == len(plan.steps):
            state.status = "completed"
            state.current_step_id = None
        else:
            next_step = state.steps[index + 1]
            next_step.status = "active"
            next_step.help_level = 0
            state.current_step_id = next_step.step_id
    return TransitionResult(state, True, evaluation.reason_code, evaluation)
