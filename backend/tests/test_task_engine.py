"""Synthetic transitions with assumed upstream inputs, not source/authenticity verification."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.tasking.engine import CompletionEvaluation, apply_event, create_task_state
from app.tasking.models import Evidence, TargetBinding, TaskEvent, TaskPlan


@pytest.fixture(params=["automatic_door.json", "packing_bag.json"])
def plan(request):
    path = Path(__file__).parent / "fixtures" / "plans" / request.param
    return TaskPlan.model_validate_json(path.read_text(encoding="utf-8"))


@pytest.fixture
def state(plan):
    return create_task_state(plan, "synthetic-task")


def test_initial_state_is_independent_of_plan_and_other_tasks(plan, state):
    before = plan.model_dump()
    other = create_task_state(plan, "other-task")
    assert state.plan_id == plan.plan_id
    assert state.status == "active"
    assert state.current_step_id == plan.steps[0].step_id
    assert [step.step_id for step in state.steps] == [step.step_id for step in plan.steps]
    assert [step.status for step in state.steps] == ["active", "pending", "pending", "pending"]
    assert [step.help_level for step in state.steps] == [0, 0, 0, 0]
    assert state.target_bindings == {}
    assert state.evidence == []
    state.steps[0].help_level = 1
    assert other.steps[0].help_level == 0
    assert plan.model_dump() == before


def test_more_help_changes_only_current_help_and_respects_step_limit(plan, state):
    plan.steps[0].max_help_level = 2
    # A different later-step limit must not control the current step.
    plan.steps[1].max_help_level = 0
    for expected in (1, 2, 2):
        before = state.model_dump()
        result = apply_event(plan, state, TaskEvent(type="more_help"))
        assert result.accepted
        assert result.state.steps[0].help_level == expected
        previous_help = before["steps"][0]["help_level"]
        expected_reason = "help_limit_reached" if previous_help == 2 else "help_increased"
        assert result.reason_code == expected_reason
        after = result.state.model_dump()
        after["steps"][0]["help_level"] = before["steps"][0]["help_level"]
        assert after == before
        assert state.model_dump() == before
        state = result.state


def test_zero_help_limit_is_valid(plan, state):
    plan.steps[0].max_help_level = 0
    result = apply_event(plan, state, TaskEvent(type="more_help"))
    assert result.accepted
    assert result.reason_code == "help_limit_reached"
    assert result.state == state


def test_help_targets_current_step_independently_of_position(plan, state):
    # Assume an existing later-step state; this test does not execute a step advance.
    state.steps[0].status = "completed"
    state.steps[0].help_level = 3
    state.steps[1].status = "active"
    state.current_step_id = state.steps[1].step_id
    plan.steps[1].max_help_level = 1
    result = apply_event(plan, state, TaskEvent(type="more_help"))
    assert result.accepted
    assert result.state.current_step_id == state.current_step_id
    assert [step.help_level for step in result.state.steps] == [3, 1, 0, 0]
    assert [step.status for step in result.state.steps] == [step.status for step in state.steps]
    assert state.steps[1].help_level == 0


def test_pause_blocks_progress_and_resume_preserves_step_and_help(plan, state):
    state = apply_event(plan, state, TaskEvent(type="more_help")).state
    paused = apply_event(plan, state, TaskEvent(type="pause"))
    assert paused.accepted
    assert paused.state.status == "paused"
    assert state.status == "active"
    for event_type in ("more_help", "manual_advance", "cue_issued"):
        result = apply_event(
            plan, paused.state, TaskEvent(type=event_type, step_id=state.current_step_id),
        )
        assert not result.accepted
        assert result.reason_code == "task_paused"
        assert result.state == paused.state
    resumed = apply_event(plan, paused.state, TaskEvent(type="resume"))
    assert resumed.accepted
    assert resumed.state == state
    more_help = apply_event(plan, resumed.state, TaskEvent(type="more_help"))
    assert more_help.state.steps[0].help_level == 2
    assert more_help.state.current_step_id == state.current_step_id


@pytest.mark.parametrize("event_type,expected_status,reason", [
    ("manual_advance", "needs_confirmation", "confirmation_required"),
    ("help_requested", "needs_assistance", "assistance_requested"),
    ("stop", "stopped", "task_stopped"),
    ("refusal", "stopped", "user_refused"),
])
def test_controls_never_advance_or_complete_steps(plan, state, event_type, expected_status, reason):
    state.steps[0].help_level = 2
    before = state.model_dump()
    result = apply_event(plan, state, TaskEvent(type=event_type))
    assert result.accepted
    assert result.reason_code == reason
    assert result.state.status == expected_status
    after = result.state.model_dump()
    after["status"] = before["status"]
    assert after == before
    assert state.model_dump() == before


@pytest.mark.parametrize("terminal", ["stop", "refusal", "completed"])
def test_terminal_states_reject_all_controls(plan, state, terminal):
    if terminal == "completed":
        # Assumed pre-existing terminal state, not completion produced by this phase.
        state.status = "completed"
        for step in state.steps:
            step.status = "completed"
    else:
        state = apply_event(plan, state, TaskEvent(type=terminal)).state
    for event_type in (
        "pause", "resume", "stop", "refusal", "more_help", "help_requested", "manual_advance",
    ):
        result = apply_event(plan, state, TaskEvent(type=event_type))
        assert not result.accepted
        assert result.reason_code == "terminal_state"
        assert result.state == state


@pytest.mark.parametrize("hold_event", ["manual_advance", "help_requested"])
def test_confirmation_and_assistance_cannot_be_cleared_by_controls(plan, state, hold_event):
    held = apply_event(plan, state, TaskEvent(type=hold_event)).state
    for event_type in ("pause", "resume", "more_help", "manual_advance"):
        result = apply_event(plan, held, TaskEvent(type=event_type))
        assert not result.accepted
        assert result.reason_code == "invalid_transition"
        assert result.state == held


@pytest.mark.parametrize("status", ["active", "paused", "needs_confirmation", "needs_assistance"])
def test_silence_never_changes_any_state_or_help(plan, state, status):
    state.status = status
    state.steps[0].help_level = 1
    before = state.model_dump()
    # No call also leaves the original untouched; None is the explicit polling path.
    for _ in range(3):
        result = apply_event(plan, state)
        assert result.accepted
        assert result.reason_code == "no_event"
        assert result.state.model_dump() == before
        assert state.model_dump() == before


def test_invalid_resume_and_stale_step_controls_preserve_state(plan, state):
    result = apply_event(plan, state, TaskEvent(type="resume"))
    assert not result.accepted
    assert result.reason_code == "invalid_transition"
    for event_type in ("pause", "more_help", "manual_advance"):
        result = apply_event(plan, state, TaskEvent(type=event_type, step_id=plan.steps[1].step_id))
        assert not result.accepted
        assert result.reason_code == "step_mismatch"
        assert result.state == state


@pytest.mark.parametrize("status", ["active", "paused", "needs_confirmation", "needs_assistance"])
@pytest.mark.parametrize("event_type", ["stop", "refusal", "help_requested"])
def test_safety_and_assistance_requests_remain_available(plan, state, status, event_type):
    state.status = status
    # These are task-wide requests; a stale step hint must not suppress refusal/help.
    result = apply_event(plan, state, TaskEvent(type=event_type, step_id="stale-step"))
    assert result.accepted
    assert result.state.status == ("needs_assistance" if event_type == "help_requested" else "stopped")
    assert result.state.steps == state.steps


def test_binding_cue_and_evidence_without_evaluator_never_complete(plan, state):
    target_key = plan.targets[0].target_key
    events = [
        TaskEvent(type="cue_issued", step_id=state.current_step_id),
        TaskEvent(type="target_bound", binding=TargetBinding(
            target_key=target_key, object_id="synthetic-object", observation_revision="r1",
        )),
        TaskEvent(type="evidence_received", evidence=Evidence(
            evidence_id="synthetic-evidence", step_id=state.current_step_id,
            source="camera_observation", outcome="target_located", relation="supports",
            target_keys=[target_key],
        )),
    ]
    for event in events:
        result = apply_event(plan, state, event)
        assert result.accepted
        assert result.state.status == "active"
        assert result.state.current_step_id == state.current_step_id
        assert result.state.steps[0].status != "completed"
        state = result.state
    assert result.reason_code == "evaluator_not_configured"
    assert len(state.evidence) == 1
    assert state.steps[0].status == "awaiting_evidence"


@pytest.mark.parametrize("event_type", ["stop", "refusal", "help_requested"])
def test_safety_requests_are_not_blocked_by_plan_mismatch_or_invalid_help(plan, state, event_type):
    plan.plan_id = "mismatched-plan"
    state.steps[0].help_level = plan.steps[0].max_help_level + 1
    before = state.model_dump()
    result = apply_event(plan, state, TaskEvent(type=event_type))
    assert result.accepted
    expected = "needs_assistance" if event_type == "help_requested" else "stopped"
    assert result.state.status == expected
    assert result.state.steps == state.steps
    assert state.model_dump() == before


def test_mismatched_plan_and_invalid_current_state_are_rejected(plan, state):
    bad_plan = plan.model_copy(deep=True)
    bad_plan.plan_id = "another-plan"
    result = apply_event(bad_plan, state, TaskEvent(type="more_help"))
    assert result.reason_code == "plan_state_mismatch"
    assert not result.accepted
    assert result.state == state
    bad_state = state.model_copy(deep=True)
    bad_state.steps.reverse()
    result = apply_event(plan, bad_state, TaskEvent(type="more_help"))
    assert result.reason_code == "plan_state_mismatch"
    assert not result.accepted
    assert result.state == bad_state
    for status, event_type in (("active", "more_help"), ("paused", "resume")):
        for current_step in (None, plan.steps[1].step_id):
            bad_state = state.model_copy(deep=True)
            bad_state.status = status
            bad_state.current_step_id = current_step
            result = apply_event(plan, bad_state, TaskEvent(type=event_type))
            assert result.reason_code == "invalid_current_step"
            assert not result.accepted
            assert result.state == bad_state
    bad_state = state.model_copy(deep=True)
    bad_state.steps[0].help_level = plan.steps[0].max_help_level + 1
    result = apply_event(plan, bad_state, TaskEvent(type="more_help"))
    assert result.reason_code == "invalid_help_level"
    assert not result.accepted
    assert result.state == bad_state


def test_results_share_no_nested_mutable_state_with_inputs(plan, state):
    # Assumed synthetic records; their authenticity is not checked by this phase.
    key = plan.targets[0].target_key
    state.target_bindings[key] = TargetBinding(
        target_key=key, object_id="synthetic-object", observation_revision="r1",
    )
    state.evidence.append(Evidence(
        evidence_id="e1", step_id=state.current_step_id, source="unknown",
        outcome="target_located", relation="inconclusive", target_keys=[key],
    ))
    before = state.model_dump()
    for event in (None, TaskEvent(type="resume"), TaskEvent(type="more_help")):
        result = apply_event(plan, state, event)
        result.state.steps[0].help_level = 3
        result.state.target_bindings[key].object_id = "changed"
        result.state.evidence[0].target_keys.clear()
        assert state.model_dump() == before


def assumed_evidence(plan, state, evidence_id="e1", source="camera_observation", relation="supports"):
    """Fabricated internal record assumed verified upstream, not real camera/caregiver proof."""
    step = next(step for step in plan.steps if step.step_id == state.current_step_id)
    return Evidence(
        evidence_id=evidence_id, step_id=step.step_id, source=source,
        outcome=step.completion_goal.outcome, relation=relation,
        target_keys=step.completion_goal.target_keys,
    )


def assumed_test_evaluator(step, history):
    """Test stub only; matching labels is NOT production authentication or action policy."""
    support = tuple(e.evidence_id for e in history if e.relation == "supports"
                    and e.source in ("camera_observation", "caregiver_report")
                    and e.outcome == step.completion_goal.outcome)
    conflict = tuple(e.evidence_id for e in history if e.relation == "contradicts"
                     and e.source in ("camera_observation", "caregiver_report"))
    status = "conflicting" if conflict else "satisfied" if support else "pending"
    return CompletionEvaluation(
        status=status, considered_evidence_ids=tuple(e.evidence_id for e in history),
        supporting_evidence_ids=support, conflicting_evidence_ids=conflict,
        reason_code={"conflicting": "contradictory_evidence", "satisfied": "criterion_satisfied",
                     "pending": "insufficient_evidence"}[status],
    )


def test_internal_bindings_update_only_declared_targets_without_completion(plan, state):
    key = plan.targets[0].target_key
    for revision in ("r1", "r2"):
        binding = TargetBinding(target_key=key, object_id="assumed-object", observation_revision=revision)
        event = TaskEvent(type="target_bound", binding=binding)
        before = state.model_dump()
        result = apply_event(plan, state, event)
        assert result.accepted
        assert result.state.target_bindings[key] == binding
        assert result.state.steps == state.steps
        assert result.state.current_step_id == state.current_step_id
        assert state.model_dump() == before
        event.binding.object_id = "event-mutated"
        assert result.state.target_bindings[key].object_id == "assumed-object"
        state = result.state
    bad = TargetBinding(target_key="undeclared", object_id="assumed", observation_revision="r3")
    result = apply_event(plan, state, TaskEvent(type="target_bound", binding=bad))
    assert not result.accepted
    assert result.reason_code == "unknown_target_key"
    assert result.state == state


@pytest.mark.parametrize("source,relation", [
    ("manual_progress", "supports"), ("cue_issued", "supports"),
    ("model_assessment", "supports"), ("unknown", "supports"),
    ("camera_observation", "inconclusive"), ("caregiver_report", "inconclusive"),
])
def test_non_observational_or_inconclusive_evidence_stays_pending(plan, state, source, relation):
    state.steps[0].help_level = 2
    event = TaskEvent(type="evidence_received", evidence=assumed_evidence(
        plan, state, source=source, relation=relation,
    ))
    result = apply_event(plan, state, event, evaluator=assumed_test_evaluator)
    assert result.accepted
    assert result.evaluation.status == "pending"
    assert result.state.current_step_id == state.current_step_id
    assert result.state.steps[0].status == "awaiting_evidence"
    assert result.state.steps[0].help_level == 2
    assert result.state.evidence == [event.evidence]
    assert state.evidence == []


def test_cue_does_not_call_evaluator_or_create_success(plan, state):
    def forbidden_evaluator(step, history):
        pytest.fail("cue issuance must not invoke completion evaluation")

    result = apply_event(plan, state, TaskEvent(type="cue_issued", step_id=state.current_step_id),
                         evaluator=forbidden_evaluator)
    assert result.accepted
    assert result.evaluation is None
    assert result.state.steps[0].status == "awaiting_evidence"
    assert result.state.evidence == []
    assert result.state.current_step_id == state.current_step_id


def test_pending_evaluator_receives_accumulated_current_step_history(plan, state):
    seen = []

    def pending(step, history):
        seen.append(tuple(e.evidence_id for e in history))
        return CompletionEvaluation(status="pending", considered_evidence_ids=seen[-1],
                                    reason_code="insufficient_evidence")

    state.steps[0].help_level = 1
    for evidence_id in ("first", "second"):
        before = state.model_dump()
        event = TaskEvent(type="evidence_received", evidence=assumed_evidence(plan, state, evidence_id))
        result = apply_event(plan, state, event, evaluator=pending)
        assert result.accepted
        assert result.state.status == "active"
        assert result.state.current_step_id == state.current_step_id
        assert result.state.steps[0].help_level == 1
        assert result.state.steps[0].status == "awaiting_evidence"
        assert result.state.evidence[:-1] == state.evidence
        assert state.model_dump() == before
        state = result.state
    assert seen == [("first",), ("first", "second")]
    duplicate = TaskEvent(type="evidence_received", evidence=state.evidence[0])
    result = apply_event(plan, state, duplicate, evaluator=pending)
    assert not result.accepted
    assert result.reason_code == "duplicate_evidence_id"
    assert result.state == state
    assert len(seen) == 2


def test_conflicting_evaluation_retains_both_claims_and_requests_confirmation(plan, state):
    support = assumed_evidence(plan, state, "support", source="caregiver_report")
    state = apply_event(plan, state, TaskEvent(type="evidence_received", evidence=support)).state
    conflict = assumed_evidence(plan, state, "conflict", relation="contradicts")
    result = apply_event(plan, state, TaskEvent(type="evidence_received", evidence=conflict),
                         evaluator=assumed_test_evaluator)
    assert result.accepted
    assert result.evaluation.status == "conflicting"
    assert result.evaluation.considered_evidence_ids == ("support", "conflict")
    assert result.evaluation.supporting_evidence_ids == ("support",)
    assert result.evaluation.conflicting_evidence_ids == ("conflict",)
    assert result.state.status == "needs_confirmation"
    assert result.state.current_step_id == state.current_step_id
    assert result.state.steps[0].status == "awaiting_evidence"
    assert result.state.evidence == [support, conflict]


def test_same_engine_and_evaluator_finish_each_fixture_only_after_all_steps(plan, state):
    histories = []

    def evaluator(step, history):
        assert all(e.step_id == step.step_id for e in history)
        histories.append(tuple(e.evidence_id for e in history))
        return assumed_test_evaluator(step, history)

    for index, step in enumerate(plan.steps):
        assert state.current_step_id == step.step_id
        state = apply_event(plan, state, TaskEvent(type="more_help")).state
        if index + 1 < len(plan.steps):
            state.steps[index + 1].help_level = 3
        event = TaskEvent(type="evidence_received", evidence=assumed_evidence(plan, state, f"e{index}"))
        result = apply_event(plan, state, event, evaluator=evaluator)
        assert result.accepted
        assert result.evaluation.status == "satisfied"
        assert result.state.steps[index].status == "completed"
        assert result.state.steps[index].help_level == 1
        assert result.state.evidence[:-1] == state.evidence
        if index < len(plan.steps) - 1:
            assert result.state.status == "active"
            assert result.state.current_step_id == plan.steps[index + 1].step_id
            assert result.state.steps[index + 1].help_level == 0
        else:
            assert result.state.status == "completed"
            assert result.state.current_step_id is None
            assert all(s.status == "completed" for s in result.state.steps)
        state = result.state
    assert histories == [(f"e{i}",) for i in range(len(plan.steps))]
    stopped = apply_event(plan, state, TaskEvent(type="resume"))
    assert not stopped.accepted
    assert stopped.reason_code == "terminal_state"


@pytest.mark.parametrize("invalid", [
    {"status": "satisfied"},
    {"status": "satisfied", "considered_evidence_ids": ["e1", "e2"],
     "supporting_evidence_ids": ["e1"], "conflicting_evidence_ids": ["e2"]},
    {"status": "conflicting"},
    {"status": "pending", "considered_evidence_ids": ["e1"], "conflicting_evidence_ids": ["e1"]},
    {"status": "satisfied", "supporting_evidence_ids": ["e1"]},
    {"status": "conflicting", "considered_evidence_ids": ["e1"],
     "supporting_evidence_ids": ["e1"], "conflicting_evidence_ids": ["e1"]},
    {"status": "pending", "considered_evidence_ids": ["e1", "e1"]},
    {"status": "satisfied", "considered_evidence_ids": ["e1"],
     "supporting_evidence_ids": ["e1", "e1"]},
    {"status": "satisfied", "considered_evidence_ids": ["missing"],
     "supporting_evidence_ids": ["missing"]},
    {"status": "unknown"},
])
def test_invalid_evaluation_is_revalidated_and_never_advances(plan, state, invalid):
    def bad_evaluator(step, history):
        # Bypass Pydantic deliberately to test the Engine's internal boundary.
        return CompletionEvaluation.model_construct(reason_code="bad_test_result", **invalid)

    evidence = assumed_evidence(plan, state)
    result = apply_event(plan, state, TaskEvent(type="evidence_received", evidence=evidence),
                         evaluator=bad_evaluator)
    assert not result.accepted
    assert result.reason_code == "invalid_completion_evaluation"
    assert result.state.status == "needs_confirmation"
    assert result.state.current_step_id == state.current_step_id
    assert result.state.evidence == [evidence]
    assert result.state.steps[0].status == "awaiting_evidence"
    assert state.evidence == []


def test_evaluation_has_only_small_result_fields_and_round_trips():
    evaluation = CompletionEvaluation(
        status="satisfied", considered_evidence_ids=("e1",),
        supporting_evidence_ids=("e1",), reason_code="criterion_satisfied",
    )
    assert CompletionEvaluation.model_validate_json(evaluation.model_dump_json()) == evaluation
    with pytest.raises(ValidationError):
        CompletionEvaluation(status="pending", reason_code="pending", force_complete=True)


def test_previous_step_evidence_cannot_complete_current_step(plan, state):
    first = assumed_evidence(plan, state, "previous-step")
    state = apply_event(plan, state, TaskEvent(type="evidence_received", evidence=first),
                        evaluator=assumed_test_evaluator).state

    def stale_basis(step, history):
        return CompletionEvaluation(status="satisfied", considered_evidence_ids=("previous-step",),
                                    supporting_evidence_ids=("previous-step",), reason_code="stale")

    event = TaskEvent(type="evidence_received", evidence=assumed_evidence(plan, state, "current-step"))
    result = apply_event(plan, state, event, evaluator=stale_basis)
    assert not result.accepted
    assert result.reason_code == "invalid_completion_evaluation"
    assert result.state.current_step_id == state.current_step_id
    assert result.state.evidence == [first, event.evidence]


@pytest.mark.parametrize("source,relation", [
    ("manual_progress", "supports"), ("cue_issued", "supports"),
    ("model_assessment", "supports"), ("unknown", "supports"),
    ("camera_observation", "inconclusive"), ("caregiver_report", "contradicts"),
])
def test_evaluator_cannot_promote_non_observations_to_support(plan, state, source, relation):
    def invalid_support(step, history):
        ids = (history[-1].evidence_id,)
        return CompletionEvaluation(status="satisfied", considered_evidence_ids=ids,
                                    supporting_evidence_ids=ids, reason_code="invalid_support")

    event = TaskEvent(type="evidence_received", evidence=assumed_evidence(
        plan, state, source=source, relation=relation,
    ))
    result = apply_event(plan, state, event, evaluator=invalid_support)
    assert not result.accepted
    assert result.reason_code == "invalid_completion_evaluation"
    assert result.state.current_step_id == state.current_step_id
    assert result.state.status == "needs_confirmation"


def test_evaluator_failure_and_wrong_result_fail_safely_with_evidence_retained(plan, state):
    def failed(step, history):
        raise RuntimeError("synthetic failure")

    for evaluator, reason in ((failed, "completion_evaluator_failed"),
                              (lambda step, history: True, "invalid_completion_evaluation")):
        event = TaskEvent(type="evidence_received", evidence=assumed_evidence(plan, state))
        result = apply_event(plan, state, event, evaluator=evaluator)
        assert not result.accepted
        assert result.reason_code == reason
        assert result.state.status == "needs_confirmation"
        assert result.state.evidence == [event.evidence]
        assert result.state.current_step_id == state.current_step_id


def test_evaluator_and_event_cannot_mutate_plan_or_preserved_history(plan, state):
    evidence = assumed_evidence(plan, state)
    before = plan.model_dump()

    def mutating_evaluator(step, history):
        step.completion_goal.outcome = "changed"
        history[0].target_keys.clear()
        return CompletionEvaluation(status="pending", reason_code="insufficient_evidence")

    event = TaskEvent(type="evidence_received", evidence=evidence)
    result = apply_event(plan, state, event, evaluator=mutating_evaluator)
    assert result.accepted
    assert plan.model_dump() == before
    assert result.state.evidence == [evidence]
    event.evidence.target_keys.clear()
    assert result.state.evidence[0].target_keys
    assert state.evidence == []


def test_wrong_step_target_and_skipped_steps_do_not_reach_evaluator(plan, state):
    def forbidden(step, history):
        pytest.fail("invalid internal references must not reach evaluator")

    evidence = assumed_evidence(plan, state)
    for field, value, reason in (
        ("step_id", plan.steps[1].step_id, "step_mismatch"),
        ("target_keys", ["undeclared"], "unknown_target_key"),
    ):
        bad = evidence.model_copy(deep=True, update={field: value})
        result = apply_event(plan, state, TaskEvent(type="evidence_received", evidence=bad),
                             evaluator=forbidden)
        assert not result.accepted
        assert result.reason_code == reason
        assert result.state == state
    skipped = state.model_copy(deep=True)
    skipped.steps[0].status = "pending"
    skipped.steps[-1].status = "active"
    skipped.current_step_id = skipped.steps[-1].step_id
    event = TaskEvent(type="evidence_received", evidence=assumed_evidence(plan, skipped))
    result = apply_event(plan, skipped, event, evaluator=forbidden)
    assert not result.accepted
    assert result.reason_code == "invalid_step_sequence"
    assert result.state == skipped


@pytest.mark.parametrize("event_type", ["target_bound", "evidence_received", "cue_issued"])
@pytest.mark.parametrize("status", ["paused", "stopped", "completed", "needs_confirmation"])
def test_data_events_do_not_bypass_holds_or_terminal_states(plan, state, event_type, status):
    state.status = status
    payload = {"type": event_type, "step_id": state.current_step_id}
    if event_type == "target_bound":
        payload["binding"] = TargetBinding(target_key=plan.targets[0].target_key,
                                           object_id="assumed", observation_revision="r1")
    if event_type == "evidence_received":
        payload["evidence"] = assumed_evidence(plan, state)
    result = apply_event(plan, state, TaskEvent(**payload), evaluator=assumed_test_evaluator)
    assert not result.accepted
    assert result.state == state
