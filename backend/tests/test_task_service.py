"""Offline orchestration tests using synthetic trusted context/receipts only."""

from dataclasses import replace
from pathlib import Path

import pytest

from app.tasking.models import (
    CapabilityFacts,
    Evidence,
    FeasibilityAssessment,
    ObservationSnapshot,
    ObservedObject,
    TargetBinding,
    TaskEvent,
    TaskPlan,
)
from app.tasking.service import handle_event, start_task
from app.tasking.verification import EvidenceReceipt, VerificationContext


@pytest.fixture(params=["automatic_door.json", "packing_bag.json"])
def service_case(request):
    path = Path(__file__).parent / "fixtures" / "plans" / request.param
    plan = TaskPlan.model_validate_json(path.read_text(encoding="utf-8"))
    bindings = {
        t.target_key: TargetBinding(
            target_key=t.target_key, object_id=f"obj-{t.target_key}", observation_revision="r1"
        )
        for t in plan.targets
    }
    context = VerificationContext(
        task_id="task",
        plan_id=plan.plan_id,
        snapshot=ObservationSnapshot(
            revision="r1",
            objects=[
                ObservedObject(object_id=f"obj-{t.target_key}", concept=t.concept)
                for t in plan.targets
            ],
        ),
        capabilities=CapabilityFacts(
            can_grasp=True,
            can_extend_arm=True,
            can_press_button=True,
            can_place_inside=True,
            can_traverse=True,
        ),
        camera_principals=frozenset({"camera-1"}),
        feasibility={
            s.step_id: FeasibilityAssessment(
                step_id=s.step_id,
                observation_revision="r1",
                object_ids=tuple(bindings[key].object_id for key in s.target_keys),
                feasible=True,
            )
            for s in plan.steps
        },
    )
    return plan, bindings, context


def bind_all(plan, bindings, context):
    state = start_task(plan, "task", context).state
    for binding in bindings.values():
        result = handle_event(plan, state, context, TaskEvent(type="target_bound", binding=binding))
        assert result.accepted
        state = result.state
    return state


def attested_event(plan, state, context, evidence_id="e1", relation="supports"):
    """Receipt is fabricated in the BACKEND context, not self-asserted by the candidate."""
    step = next(step for step in plan.steps if step.step_id == state.current_step_id)
    evidence = Evidence(
        evidence_id=evidence_id,
        step_id=step.step_id,
        source="camera_observation",
        outcome=step.completion_goal.outcome,
        target_keys=step.completion_goal.target_keys,
        object_ids=[state.target_bindings[key].object_id for key in step.target_keys],
        observation_revision="r1",
        provenance_id=f"receipt-{evidence_id}",
        confidence=0.99,
        relation=relation,
    )
    receipt = EvidenceReceipt(
        evidence.provenance_id,
        "camera-1",
        evidence.model_copy(deep=True),
        task_id="task",
        plan_id=plan.plan_id,
    )
    context = replace(context, receipts={**context.receipts, evidence.provenance_id: receipt})
    return TaskEvent(type="evidence_received", evidence=evidence), context


def test_start_and_silence_preserve_independent_opportunity(service_case):
    plan, _, context = service_case
    result = start_task(plan, "task", context, ("voice",))
    assert result.accepted
    assert result.cue is None
    assert [record.kind for record in result.events] == ["task_started"]
    state = result.state
    for _ in range(3):
        result = handle_event(plan, state, context, preferred_guidance=("voice",))
        assert result.accepted
        assert result.state == state
        assert result.cue is None
        assert result.events == ()
        assert all(step.help_level == 0 for step in state.steps)


def test_more_help_issues_one_cue_and_never_completes_or_repeats_on_poll(service_case):
    plan, bindings, context = service_case
    state = bind_all(plan, bindings, context)
    before = state.model_dump()
    result = handle_event(plan, state, context, {"type": "more_help"}, ("voice",))
    assert result.accepted
    assert result.cue.kind == "voice"
    assert result.state.steps[0].help_level == 1
    assert result.state.steps[0].status == "awaiting_evidence"
    assert result.state.current_step_id == state.current_step_id
    assert result.state.evidence == []
    assert [record.kind for record in result.events] == ["control_accepted", "cue_issued"]
    assert state.model_dump() == before
    polled = handle_event(plan, result.state, context, preferred_guidance=("voice",))
    assert polled.state == result.state
    assert polled.cue is None
    assert polled.events == ()


def test_ltm_modalities_and_upper_limit_do_not_infer_help_acceptance(service_case):
    plan, bindings, context = service_case
    state = bind_all(plan, bindings, context)
    for kind in ("voice", "visual_highlight", "arrow", "assistance"):
        result = handle_event(
            plan, state, context, {"type": "more_help"}, ("voice", "visual_highlight", "arrow")
        )
        assert result.cue.kind == kind
        assert sum(record.kind == "cue_issued" for record in result.events) == 1
        assert not any(record.kind == "step_completed" for record in result.events)
        state = result.state
    limited = handle_event(plan, state, context, {"type": "more_help"}, ("voice",))
    assert limited.reason_code == "help_limit_reached"
    assert limited.cue is None
    assert limited.state == state
    assert limited.state.status == "active"


def test_binding_enables_visual_cue_without_becoming_completion(service_case):
    plan, bindings, context = service_case
    state = start_task(plan, "task", context).state
    for _ in range(2):
        result = handle_event(plan, state, context, {"type": "more_help"}, ("visual_highlight",))
        assert result.cue.kind == "text"
        assert result.cue.object_id is None
        state = result.state
    binding = bindings[plan.steps[0].target_keys[0]]
    result = handle_event(
        plan, state, context, TaskEvent(type="target_bound", binding=binding), ("visual_highlight",)
    )
    assert result.cue.kind == "visual_highlight"
    assert result.cue.object_id == binding.object_id
    assert result.cue.observation_revision == context.snapshot.revision
    assert "bbox" not in result.cue.model_dump()
    assert result.state.steps[0].status == "awaiting_evidence"
    assert result.state.evidence == []


def test_complete_fixture_with_separate_cue_evidence_and_completion_records(service_case):
    plan, bindings, context = service_case
    state = bind_all(plan, bindings, context)
    for index, step in enumerate(plan.steps):
        result = handle_event(plan, state, context, {"type": "more_help"}, ("voice",))
        assert result.accepted and result.cue is not None
        assert result.cue.step_id == step.step_id
        assert [record.kind for record in result.events].count("cue_issued") == 1
        state = result.state
        event, context = attested_event(plan, state, context, f"e{index}")
        result = handle_event(plan, state, context, event, ("voice",))
        assert result.accepted
        assert result.evaluation.status == "satisfied"
        assert result.cue is None
        assert result.events[0].kind == "evidence_accepted"
        assert result.events[1].kind == "step_completed"
        assert result.events[1].step_id == step.step_id
        assert result.events[1].evidence_ids == (event.evidence.evidence_id,)
        assert result.state.steps[index].status == "completed"
        state = result.state
        if index + 1 < len(plan.steps):
            assert state.steps[index + 1].help_level == 0
    assert state.status == "completed"
    assert result.events[-1].kind == "task_completed"
    assert len(state.evidence) == len(plan.steps)


def test_unverified_receipt_is_rejected_before_engine_or_prompting(service_case, monkeypatch):
    from app.tasking import service

    plan, bindings, context = service_case
    state = bind_all(plan, bindings, context)
    event, _ = attested_event(plan, state, context)

    def forbidden(*args, **kwargs):
        pytest.fail("rejected Evidence must not reach Engine or prompting")

    monkeypatch.setattr(service, "apply_event", forbidden)
    monkeypatch.setattr(service, "select_cue", forbidden)
    result = service.handle_event(plan, state, context, event)
    assert not result.accepted
    assert result.reason_code == "provenance_missing"
    assert result.state.status == "needs_confirmation"
    assert result.state.evidence == []
    assert result.cue is None
    assert state.status == "active"


def test_context_revision_changes_revalidate_without_silence_escalation(service_case):
    plan, bindings, context = service_case
    state = bind_all(plan, bindings, context)
    state = handle_event(plan, state, context, {"type": "more_help"}, ("voice",)).state
    changed = replace(context, snapshot=context.snapshot.model_copy(update={"revision": "r2"}))
    result = handle_event(plan, state, changed)
    assert not result.accepted
    assert result.reason_code == "stale_binding"
    assert result.state.status == "needs_confirmation"
    assert result.state.steps == state.steps
    assert result.cue is None
    assert state.status == "active"


def test_resume_rechecks_context_and_data_events_cannot_release_pause(service_case):
    plan, bindings, context = service_case
    state = bind_all(plan, bindings, context)
    state = handle_event(plan, state, context, {"type": "more_help"}, ("voice",)).state
    paused = handle_event(plan, state, context, {"type": "pause"})
    assert paused.state.status == "paused"
    assert paused.cue is None
    rejected = handle_event(
        plan, paused.state, context, {"type": "cue_issued", "step_id": state.current_step_id}
    )
    assert not rejected.accepted and rejected.state == paused.state
    changed = replace(context, snapshot=context.snapshot.model_copy(update={"revision": "r2"}))
    assert handle_event(plan, paused.state, changed).state == paused.state
    resumed = handle_event(plan, paused.state, changed, {"type": "resume"}, ("voice",))
    assert resumed.state.status == "needs_confirmation"
    assert resumed.cue is None
    assert resumed.state.steps == paused.state.steps


@pytest.mark.parametrize(
    "control,status",
    [
        ("stop", "stopped"),
        ("refusal", "stopped"),
        ("help_requested", "needs_assistance"),
        ("manual_advance", "needs_confirmation"),
    ],
)
def test_safety_help_and_manual_controls_do_not_issue_action_cues(service_case, control, status):
    plan, bindings, context = service_case
    state = bind_all(plan, bindings, context)
    changed = replace(context, snapshot=context.snapshot.model_copy(update={"revision": "r2"}))
    result = handle_event(plan, state, changed, {"type": control})
    assert result.accepted
    assert result.state.status == status
    assert result.state.steps == state.steps
    assert result.state.evidence == []
    assert result.cue is None


def test_new_step_is_reverified_before_any_action_cue(service_case):
    plan, bindings, context = service_case
    # Block every physical action; locating remains possible and is not pressing.
    facts = context.capabilities.model_copy(
        update={"can_press_button": False, "can_place_inside": False}
    )
    context = replace(context, capabilities=facts)
    state = bind_all(plan, bindings, context)
    physical_index = next(
        i for i, step in enumerate(plan.steps) if step.action in ("press", "place_inside")
    )
    for index in range(physical_index):
        event, context = attested_event(plan, state, context, f"e{index}")
        result = handle_event(plan, state, context, event, ("voice",))
        state = result.state
    assert not result.accepted
    assert state.status == "needs_assistance"
    assert result.reason_code == "capability_blocked"
    assert state.current_step_id == plan.steps[physical_index].step_id
    assert state.steps[physical_index - 1].status == "completed"
    assert state.steps[physical_index].status == "active"
    assert any(record.kind == "step_completed" for record in result.events)
    assert result.events[-1].kind == "verification_blocked"
    assert result.cue is None


def test_pending_and_conflicting_evidence_preserve_history_without_new_cues(service_case):
    plan, bindings, context = service_case
    state = bind_all(plan, bindings, context)
    state = handle_event(plan, state, context, {"type": "more_help"}, ("voice",)).state
    event, context = attested_event(plan, state, context, "pending", "inconclusive")
    pending = handle_event(plan, state, context, event)
    assert pending.accepted
    assert pending.evaluation.status == "pending"
    assert pending.cue is None
    assert pending.state.steps[0].help_level == 1
    event, context = attested_event(plan, pending.state, context, "conflict", "contradicts")
    conflict = handle_event(plan, pending.state, context, event)
    assert conflict.evaluation.status == "conflicting"
    assert conflict.state.status == "needs_confirmation"
    assert conflict.evaluation.conflicting_evidence_ids == ("conflict",)
    assert len(conflict.state.evidence) == 2
    assert conflict.cue is None
    assert not any(record.kind == "step_completed" for record in conflict.events)


def test_offline_service_has_no_ai_network_or_database_dependency(service_case, monkeypatch):
    import socket
    import sqlite3

    import app.planner

    def forbidden(*args, **kwargs):
        pytest.fail("pure Task Service must not invoke AI, sockets or database connections")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(app.planner, "live_pick", forbidden)
    plan, bindings, context = service_case
    state = bind_all(plan, bindings, context)
    hinted = handle_event(plan, state, context, {"type": "more_help"}, ("voice",))
    assert hinted.cue is not None
    event, context = attested_event(plan, hinted.state, context)
    assert handle_event(plan, hinted.state, context, event).evaluation.status == "satisfied"


def test_event_order_is_verification_then_engine_then_prompting(service_case, monkeypatch):
    from app.tasking import service

    plan, bindings, context = service_case
    state = bind_all(plan, bindings, context)
    trace = []
    for name in ("verify_event", "apply_event", "select_cue"):
        original = getattr(service, name)

        def track(*args, _name=name, _original=original, **kwargs):
            trace.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(service, name, track)
    result = service.handle_event(plan, state, context, {"type": "more_help"}, ("voice",))
    assert result.cue is not None
    assert trace.index("verify_event") < trace.index("apply_event") < trace.index("select_cue")
