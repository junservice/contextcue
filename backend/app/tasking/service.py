"""Stateless verification -> Engine -> prompting coordination; no I/O or persistence.

Callers own state and the returned audit events. VerificationContext is backend-only.
This module neither selects plans/templates nor authenticates external source adapters.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from .engine import CompletionEvaluation, apply_event, create_task_state
from .models import TaskEvent, TaskPlan, TaskState
from .prompting import Cue, Guidance, select_cue
from .semantics import verify_execution_semantics
from .verification import (
    VerificationContext,
    VerificationResult,
    trusted_completion_evaluator,
    verify_event,
)


@dataclass(frozen=True)
class ServiceEvent:
    kind: Literal[
        "task_started",
        "control_accepted",
        "binding_accepted",
        "evidence_accepted",
        "cue_issued",
        "step_completed",
        "task_completed",
        "verification_blocked",
    ]
    step_id: str | None
    reason_code: str
    evidence_ids: tuple[str, ...] = ()
    cue: Cue | None = None


@dataclass(frozen=True)
class ServiceResult:
    state: TaskState
    accepted: bool
    reason_code: str
    cue: Cue | None = None
    events: tuple[ServiceEvent, ...] = ()
    evaluation: CompletionEvaluation | None = None


def _probe(plan: TaskPlan, state: TaskState, context: VerificationContext) -> VerificationResult:
    semantic = verify_execution_semantics(plan, context)
    if semantic.decision != "allow":
        return VerificationResult(semantic.decision, semantic.reason_code)
    if state.current_step_id is None:
        return VerificationResult("confirm", "invalid_current_step")
    return verify_event(
        plan,
        state,
        TaskEvent(type="cue_issued", step_id=state.current_step_id),
        context,
    )


def _hold(
    state: TaskState,
    check: VerificationResult,
    events: tuple[ServiceEvent, ...] = (),
    evaluation: CompletionEvaluation | None = None,
) -> ServiceResult:
    updated = state.model_copy(deep=True)
    updated.status = {
        "confirm": "needs_confirmation",
        "assist": "needs_assistance",
        "stop": "stopped",
    }[check.decision]
    record = ServiceEvent("verification_blocked", state.current_step_id, check.reason_code)
    return ServiceResult(
        updated, False, check.reason_code, events=(*events, record), evaluation=evaluation
    )


def _finish(
    plan: TaskPlan,
    state: TaskState,
    context: VerificationContext,
    preferences: Sequence[Guidance],
    reason: str,
    events: tuple[ServiceEvent, ...],
    emit_cue: bool = False,
    evaluation: CompletionEvaluation | None = None,
) -> ServiceResult:
    if state.status != "active":
        return ServiceResult(state, True, reason, events=events, evaluation=evaluation)
    # Recheck after a transition, including entry into a new action or changed context.
    check = _probe(plan, state, context)
    if check.decision != "allow":
        return _hold(state, check, events, evaluation)
    cue = select_cue(plan, state, context, preferences) if emit_cue else None
    if cue is None:
        return ServiceResult(state, True, reason, events=events, evaluation=evaluation)
    issued = apply_event(plan, state, check.event)
    if not issued.accepted:
        return ServiceResult(
            issued.state, False, issued.reason_code, events=events, evaluation=evaluation
        )
    record = ServiceEvent("cue_issued", cue.step_id, "cue_issued", cue=cue)
    return ServiceResult(issued.state, True, reason, cue, (*events, record), evaluation)


def start_task(
    plan: TaskPlan,
    task_id: str,
    context: VerificationContext,
    preferred_guidance: Sequence[Guidance] = (),
) -> ServiceResult:
    """Accept a supplied structurally valid plan. No AI/template selection or session storage."""
    parsed = TaskPlan.model_validate(plan.model_dump())
    state = create_task_state(parsed, task_id)
    record = ServiceEvent("task_started", state.current_step_id, "task_started")
    return _finish(
        parsed, state, context, preferred_guidance, "task_started", (record,), emit_cue=True
    )


def handle_event(
    plan: TaskPlan,
    state: TaskState,
    context: VerificationContext,
    candidate: TaskEvent | dict | None = None,
    preferred_guidance: Sequence[Guidance] = (),
) -> ServiceResult:
    """Apply one event with freshly supplied trusted context; None only revalidates.

    Polling never emits a cue or clears confirmation/assistance holds. Safety controls
    remain available even when context is stale. Resolving holds needs a separately
    designed authorized review flow; resume only releases an explicit pause.
    """
    current = TaskState.model_validate(state.model_dump())
    if current.status in ("stopped", "completed"):
        return ServiceResult(current, False, "terminal_state")
    if candidate is None:
        return _finish(plan, current, context, preferred_guidance, "no_event", ())
    try:
        event = TaskEvent.model_validate(
            candidate.model_dump() if isinstance(candidate, TaskEvent) else candidate
        )
    except ValidationError:
        if current.status != "active":
            return ServiceResult(current, False, "invalid_event_structure")
        return _hold(current, VerificationResult("confirm", "invalid_event_structure"))
    controls = {
        "pause",
        "resume",
        "stop",
        "refusal",
        "help_requested",
        "manual_advance",
        "more_help",
    }
    if event.type in controls:
        if event.type == "more_help" and current.status == "active":
            check = _probe(plan, current, context)
            if check.decision != "allow":
                return _hold(current, check)
        transition = apply_event(plan, current, event)
        if not transition.accepted:
            return ServiceResult(transition.state, False, transition.reason_code)
        record = ServiceEvent("control_accepted", current.current_step_id, transition.reason_code)
        emit = event.type == "resume" or transition.reason_code == "help_increased"
        return _finish(
            plan,
            transition.state,
            context,
            preferred_guidance,
            transition.reason_code,
            (record,),
            emit_cue=emit,
        )

    if current.status != "active":
        return ServiceResult(current, False, "invalid_transition")
    semantic = verify_execution_semantics(plan, context)
    if semantic.decision != "allow":
        return _hold(current, VerificationResult(semantic.decision, semantic.reason_code))
    if event.type == "cue_issued":
        check = verify_event(plan, current, event, context)
        if check.decision != "allow":
            return _hold(current, check)
        return _finish(
            plan, current, context, preferred_guidance, "cue_requested", (), emit_cue=True
        )
    check = verify_event(plan, current, event, context)
    if check.decision != "allow":
        return _hold(current, check)
    evaluator = (
        trusted_completion_evaluator(plan, current.target_bindings, context)
        if event.type == "evidence_received"
        else None
    )
    transition = apply_event(plan, current, check.event, evaluator=evaluator)
    kind = "binding_accepted" if event.type == "target_bound" else "evidence_accepted"
    ids = (event.evidence.evidence_id,) if event.evidence is not None else ()
    events = (ServiceEvent(kind, current.current_step_id, transition.reason_code, ids),)
    if not transition.accepted:
        return ServiceResult(
            transition.state,
            False,
            transition.reason_code,
            events=events,
            evaluation=transition.evaluation,
        )
    moved = transition.state.current_step_id != current.current_step_id
    if moved:
        completed = ServiceEvent(
            "step_completed",
            current.current_step_id,
            transition.reason_code,
            transition.evaluation.supporting_evidence_ids,
        )
        events = (*events, completed)
        if transition.state.status == "completed":
            events = (*events, ServiceEvent("task_completed", None, "task_completed"))
    return _finish(
        plan,
        transition.state,
        context,
        preferred_guidance,
        transition.reason_code,
        events,
        emit_cue=moved or event.type == "target_bound",
        evaluation=transition.evaluation,
    )
