"""Synthetic backend contexts/receipts: not real authentication or sensor validation."""

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import Profile
from app.tasking.engine import apply_event, create_task_state
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
from app.tasking.verification import (
    ACTION_POLICIES,
    ActionPolicy,
    EvidenceReceipt,
    VerificationContext,
    profile_to_capabilities,
    trusted_completion_evaluator,
    verify_event,
    verify_step,
)


def context_for(plan):
    """Assumed backend facts with synthetic receipts added separately by each test."""
    snapshot = ObservationSnapshot(
        revision="r1",
        objects=[
            ObservedObject(
                object_id=f"obj-{t.target_key}", concept=t.concept, qualifiers=t.qualifiers
            )
            for t in plan.targets
        ],
    )
    bindings = {
        t.target_key: TargetBinding(
            target_key=t.target_key, object_id=f"obj-{t.target_key}", observation_revision="r1"
        )
        for t in plan.targets
    }
    context = VerificationContext(
        task_id="synthetic-task",
        plan_id=plan.plan_id,
        snapshot=snapshot,
        capabilities=CapabilityFacts(
            can_grasp=True,
            can_press_button=True,
            can_extend_arm=True,
            can_place_inside=True,
            can_traverse=True,
        ),
        camera_principals=frozenset({"camera-1"}),
        caregiver_principals=frozenset({"caregiver-1"}),
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
    return bindings, context


def single_plan(action="locate", outcome=None):
    outcome = outcome or next(iter(dict(ACTION_POLICIES[action].outcomes)))
    count = dict(ACTION_POLICIES[action].outcomes)[outcome]
    targets = [{"target_key": f"target-{i}", "concept": f"concept-{i}"} for i in range(count)]
    keys = [t["target_key"] for t in targets]
    return TaskPlan.model_validate(
        {
            "plan_id": "synthetic-plan",
            "goal": "synthetic-goal",
            "targets": targets,
            "steps": [
                {
                    "step_id": "step",
                    "action": action,
                    "target_keys": keys,
                    "completion_goal": {"outcome": outcome, "target_keys": keys},
                }
            ],
        }
    )


def evidence_for(
    plan, bindings, evidence_id="e1", source="camera_observation", relation="supports", step_index=0
):
    step = plan.steps[step_index]
    return Evidence(
        evidence_id=evidence_id,
        step_id=step.step_id,
        source=source,
        outcome=step.completion_goal.outcome,
        target_keys=step.completion_goal.target_keys,
        object_ids=[bindings[k].object_id for k in step.target_keys],
        observation_revision="r1",
        provenance_id=f"receipt-{evidence_id}",
        confidence=0.99 if source == "camera_observation" else None,
        relation=relation,
    )


def attest(context, evidence, principal=None):
    # Test-only attestation in the BACKEND context, not a field in the external candidate.
    principal = principal or (
        "camera-1" if evidence.source == "camera_observation" else "caregiver-1"
    )
    receipt = EvidenceReceipt(
        evidence.provenance_id,
        principal,
        evidence.model_copy(deep=True),
        task_id=context.task_id,
        plan_id=context.plan_id,
    )
    return replace(context, receipts={**context.receipts, evidence.provenance_id: receipt})


def state_for(plan, bindings):
    state = create_task_state(plan, "synthetic-task")
    state.target_bindings = {k: b.model_copy(deep=True) for k, b in bindings.items()}
    return state


def test_registry_contains_only_reviewed_generic_actions_and_cannot_be_replaced():
    assert set(ACTION_POLICIES) == {"locate", "press", "observe_state", "traverse", "place_inside"}
    with pytest.raises(TypeError):
        ACTION_POLICIES["invented"] = ACTION_POLICIES["locate"]
    with pytest.raises(ValidationError):
        ACTION_POLICIES["press"].required_capabilities = ()
    with pytest.raises(ValidationError):
        ActionPolicy(action="press", outcomes=(("pressed", 1),), required_capabilities=("can_fly",))
    with pytest.raises(ValidationError):
        ActionPolicy(
            action="press", outcomes=(("pressed", 1),), allowed_sources={"manual_progress"}
        )


@pytest.mark.parametrize("capability", [False, None, True])
def test_profile_adapter_preserves_known_unknown_and_does_not_infer_extra_abilities(capability):
    facts = profile_to_capabilities(
        Profile(
            user_id="synthetic",
            can_grasp=capability,
            can_press_button=capability,
            can_extend_arm=capability,
        )
    )
    assert facts.can_grasp is capability
    assert facts.can_press_button is capability
    assert facts.can_extend_arm is capability
    assert facts.can_place_inside is None
    assert facts.can_traverse is None
    with pytest.raises(ValidationError):
        CapabilityFacts(can_fly=True)
    with pytest.raises(ValidationError):
        CapabilityFacts(can_press_button="unknown")


def test_locate_allows_unresolved_target_and_does_not_require_pressing_or_physical_context():
    plan = single_plan()
    context = VerificationContext(
        task_id="synthetic-task",
        plan_id=plan.plan_id,
        snapshot=ObservationSnapshot(revision="r1"),
        capabilities=CapabilityFacts(can_press_button=False, can_extend_arm=None),
    )
    assert verify_step(plan, "step", {}, context).decision == "allow"
    state = create_task_state(plan, "synthetic-task")
    cue = verify_event(plan, state, {"type": "cue_issued", "step_id": "step"}, context)
    assert cue.decision == "allow"
    assert "bbox" not in cue.event.model_dump()


@pytest.mark.parametrize("action", ["press", "observe_state", "traverse", "place_inside"])
def test_binding_required_for_bound_actions(action):
    plan = single_plan(action)
    _, context = context_for(plan)
    result = verify_step(plan, "step", {}, context)
    assert result.decision == "confirm"
    assert result.reason_code == "target_unresolved"


@pytest.mark.parametrize("key", ["can_press_button", "can_extend_arm"])
@pytest.mark.parametrize(
    "value,decision,reason",
    [
        (False, "assist", "capability_blocked"),
        (None, "confirm", "capability_unknown"),
        (True, "allow", "constraints_satisfied"),
    ],
)
def test_press_checks_each_capability_independently(key, value, decision, reason):
    plan = single_plan("press")
    bindings, context = context_for(plan)
    facts = context.capabilities.model_copy(update={key: value})
    result = verify_step(plan, "step", bindings, replace(context, capabilities=facts))
    assert result.decision == decision
    assert result.reason_code == reason


@pytest.mark.parametrize(
    "action,key",
    [
        ("place_inside", "can_grasp"),
        ("place_inside", "can_extend_arm"),
        ("place_inside", "can_place_inside"),
        ("traverse", "can_traverse"),
    ],
)
def test_placement_and_traversal_do_not_infer_independent_abilities(action, key):
    plan = single_plan(action)
    bindings, context = context_for(plan)
    for value, expected in ((False, "assist"), (None, "confirm")):
        facts = context.capabilities.model_copy(update={key: value})
        assert (
            verify_step(plan, "step", bindings, replace(context, capabilities=facts)).decision
            == expected
        )


def test_true_motor_abilities_are_not_proof_of_reachability_or_context_safety():
    plan = single_plan("press")
    bindings, context = context_for(plan)
    result = verify_step(plan, "step", bindings, replace(context, feasibility={}))
    assert result.decision == "confirm"
    assert result.reason_code == "context_review_required"
    for value, decision in ((False, "assist"), (None, "confirm"), (True, "allow")):
        assessment = context.feasibility["step"].model_copy(update={"feasible": value})
        result = verify_step(
            plan, "step", bindings, replace(context, feasibility={"step": assessment})
        )
        assert result.decision == decision
    stale = context.feasibility["step"].model_copy(update={"observation_revision": "old"})
    assert (
        verify_step(
            plan, "step", bindings, replace(context, feasibility={"step": stale})
        ).reason_code
        == "stale_physical_context"
    )


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("object_id", "not-observed", "ungrounded_binding"),
        ("observation_revision", "old", "stale_binding"),
        ("target_key", "undeclared", "unknown_target_key"),
    ],
)
def test_stale_unknown_binding_candidates_never_become_engine_events(field, value, reason):
    plan = single_plan()
    bindings, context = context_for(plan)
    candidate = next(iter(bindings.values())).model_copy(update={field: value})
    state = create_task_state(plan, "synthetic-task")
    result = verify_event(plan, state, TaskEvent(type="target_bound", binding=candidate), context)
    assert result.decision == "confirm"
    assert result.reason_code == reason
    assert result.event is None
    assert state.target_bindings == {}
    assert "bbox" not in candidate.model_dump()


def test_binding_ambiguity_missing_detections_and_qualifiers():
    plan = single_plan()
    bindings, context = context_for(plan)
    obj = context.snapshot.objects[0]
    second = obj.model_copy(update={"object_id": "second", "qualifiers": {"color": "red"}})
    snapshot = ObservationSnapshot(revision="r1", objects=[obj, second])
    assert (
        verify_step(plan, "step", bindings, replace(context, snapshot=snapshot)).reason_code
        == "ambiguous_or_missing_target"
    )
    plan.targets[0].qualifiers = {"color": "red"}
    bindings["target-0"].object_id = "second"
    assert (
        verify_step(plan, "step", bindings, replace(context, snapshot=snapshot)).decision == "allow"
    )
    assert (
        verify_step(
            plan, "step", bindings, replace(context, snapshot=ObservationSnapshot(revision="r1"))
        ).reason_code
        == "ambiguous_or_missing_target"
    )
    with pytest.raises(ValidationError):
        ObservationSnapshot(revision="r1", objects=[obj, obj])


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"action": "invented"}, "unsupported_action"),
        (
            {"completion_goal": {"outcome": "invented", "target_keys": ["target-0"]}},
            "unsupported_outcome",
        ),
        ({"target_keys": ["missing"]}, "invalid_plan_structure"),
        ({"allowed_sources": ["manual_progress"]}, "invalid_plan_structure"),
    ],
)
def test_structure_policy_failures_stop_before_bindings_or_context_review(change, reason):
    plan = single_plan("press").model_dump()
    plan["steps"][0].update(change)
    # Invalid snapshot would fail if the structure gate were skipped.
    context = VerificationContext(
        task_id="synthetic-task", plan_id="synthetic-plan", snapshot=None, capabilities=None
    )
    result = verify_step(plan, "step", {}, context)
    assert result.decision == "stop"
    assert result.reason_code == reason


def test_false_capability_stops_before_any_later_context_review():
    class NoReview(dict):
        def get(self, key, default=None):
            pytest.fail("hard rejection must not reach context/AI review")

    plan = single_plan("press")
    bindings, context = context_for(plan)
    facts = context.capabilities.model_copy(
        update={"can_press_button": False, "can_extend_arm": None}
    )
    result = verify_step(
        plan, "step", bindings, replace(context, capabilities=facts, feasibility=NoReview())
    )
    assert result.decision == "assist"


@pytest.mark.parametrize(
    "field,value",
    [
        ("outcome", "placed_inside"),
        ("target_keys", []),
        ("observation_revision", "old"),
        ("observation_revision", None),
        ("provenance_id", None),
        ("object_ids", ["unknown"]),
        ("step_id", "other"),
    ],
)
def test_evidence_must_match_step_targets_objects_revision_and_provenance(field, value):
    plan = single_plan()
    bindings, context = context_for(plan)
    evidence = evidence_for(plan, bindings)
    context = attest(context, evidence)
    modified = evidence.model_copy(update={field: value})
    result = verify_event(
        plan,
        state_for(plan, bindings),
        TaskEvent(type="evidence_received", evidence=modified),
        context,
    )
    assert result.decision == "confirm"
    assert result.event is None


@pytest.mark.parametrize("source", ["camera_observation", "caregiver_report"])
def test_source_label_or_fabricated_provenance_alone_does_not_authenticate(source):
    plan = single_plan()
    bindings, context = context_for(plan)
    evidence = evidence_for(plan, bindings, source=source)
    state = state_for(plan, bindings)
    event = TaskEvent(type="evidence_received", evidence=evidence)
    assert verify_event(plan, state, event, context).reason_code == "provenance_missing"
    context = attest(context, evidence, principal="unauthorized")
    assert (
        verify_event(plan, state, event, context).reason_code == "source_principal_not_authorized"
    )
    context = attest(context, evidence)
    result = verify_event(plan, state, event, context)
    assert result.decision == "allow"
    assert result.event == event
    # Exact attested payload matters, not just an authenticated principal/source name.
    tampered = evidence.model_copy(update={"relation": "contradicts"})
    assert (
        verify_event(
            plan, state, TaskEvent(type="evidence_received", evidence=tampered), context
        ).reason_code
        == "provenance_claim_mismatch"
    )


@pytest.mark.parametrize("source", ["manual_progress", "model_assessment", "cue_issued", "unknown"])
def test_receipt_cannot_make_manual_model_or_unknown_sources_completion_evidence(source):
    plan = single_plan()
    bindings, context = context_for(plan)
    evidence = evidence_for(plan, bindings, source=source)
    context = attest(context, evidence)
    result = verify_event(
        plan,
        state_for(plan, bindings),
        TaskEvent(type="evidence_received", evidence=evidence),
        context,
    )
    assert result.event is None
    assert result.reason_code == "evidence_source_not_allowed"


@pytest.mark.parametrize("confidence", [None, 0.0, 0.89, 0.9, 1.0])
def test_camera_confidence_threshold_is_trusted_policy_not_plan_input(confidence):
    plan = single_plan()
    bindings, context = context_for(plan)
    evidence = evidence_for(plan, bindings).model_copy(update={"confidence": confidence})
    result = verify_event(
        plan,
        state_for(plan, bindings),
        TaskEvent(type="evidence_received", evidence=evidence),
        attest(context, evidence),
    )
    assert result.decision == (
        "allow" if confidence is not None and confidence >= 0.9 else "confirm"
    )
    data = plan.model_dump()
    data["steps"][0]["completion_goal"]["confidence_threshold"] = 0
    assert verify_step(data, "step", bindings, context).decision == "stop"


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), -0.1, 1.1, True, "0.99"])
def test_invalid_confidence_is_rejected(confidence):
    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="e",
            step_id="s",
            source="camera_observation",
            outcome="pressed",
            relation="supports",
            confidence=confidence,
        )


@pytest.mark.parametrize(
    "relation,status",
    [("supports", "satisfied"), ("contradicts", "conflicting"), ("inconclusive", "pending")],
)
def test_trusted_evaluator_has_three_outcomes_with_attested_current_claims(relation, status):
    plan = single_plan()
    bindings, context = context_for(plan)
    evidence = evidence_for(plan, bindings, relation=relation)
    evaluator = trusted_completion_evaluator(plan, bindings, attest(context, evidence))
    result = evaluator(plan.steps[0], (evidence,))
    assert result.status == status
    assert result.considered_evidence_ids == (evidence.evidence_id,)


def test_conflicting_attested_history_is_never_silently_overwritten_by_later_support():
    plan = single_plan()
    bindings, context = context_for(plan)
    first = evidence_for(plan, bindings, "e1", relation="contradicts")
    second = evidence_for(plan, bindings, "e2", source="caregiver_report")
    context = attest(attest(context, first), second)
    result = trusted_completion_evaluator(plan, bindings, context)(plan.steps[0], (first, second))
    assert result.status == "conflicting"
    assert result.supporting_evidence_ids == ("e2",)
    assert result.conflicting_evidence_ids == ("e1",)


def test_unverified_history_or_changed_context_never_completes_even_through_internal_engine():
    plan = single_plan()
    bindings, context = context_for(plan)
    evidence = evidence_for(plan, bindings)
    event = TaskEvent(type="evidence_received", evidence=evidence)
    state = state_for(plan, bindings)
    evaluator = trusted_completion_evaluator(plan, bindings, context)
    context.receipts[evidence.provenance_id] = EvidenceReceipt(
        evidence.provenance_id,
        "camera-1",
        evidence,
        task_id=context.task_id,
        plan_id=context.plan_id,
    )
    # The evaluator took a snapshot before the receipt existed.
    result = apply_event(plan, state, event, evaluator=evaluator)
    assert result.evaluation.status == "pending"
    assert result.reason_code == "unverified_evidence"
    assert result.state.current_step_id == "step"
    stale_context = replace(
        context, snapshot=context.snapshot.model_copy(update={"revision": "r2"})
    )
    result = apply_event(
        plan, state, event, evaluator=trusted_completion_evaluator(plan, bindings, stale_context)
    )
    assert result.evaluation.status == "pending"
    assert result.evaluation.reason_code == "stale_binding"


@pytest.mark.parametrize("filename", ["automatic_door.json", "packing_bag.json"])
def test_both_fixtures_use_same_verified_event_and_trusted_evaluator_boundary(filename):
    # Every fact, receipt and principal here is synthetic and supplied in the backend context.
    path = Path(__file__).parent / "fixtures" / "plans" / filename
    plan = TaskPlan.model_validate_json(path.read_text(encoding="utf-8"))
    bindings, context = context_for(plan)
    state = create_task_state(plan, "synthetic-task")
    for binding in bindings.values():
        result = verify_event(plan, state, TaskEvent(type="target_bound", binding=binding), context)
        assert result.decision == "allow"
        state = apply_event(plan, state, result.event).state
    for index, step in enumerate(plan.steps):
        assert state.current_step_id == step.step_id
        cue = verify_event(plan, state, TaskEvent(type="cue_issued", step_id=step.step_id), context)
        assert cue.decision == "allow"
        state = apply_event(plan, state, cue.event).state
        assert state.steps[index].status == "awaiting_evidence"
        evidence = evidence_for(plan, bindings, f"e{index}", step_index=index)
        context = attest(context, evidence)
        verified = verify_event(
            plan, state, TaskEvent(type="evidence_received", evidence=evidence), context
        )
        assert verified.decision == "allow"
        result = apply_event(
            plan,
            state,
            verified.event,
            evaluator=trusted_completion_evaluator(plan, state.target_bindings, context),
        )
        assert result.accepted
        assert result.evaluation.status == "satisfied"
        state = result.state
    assert state.status == "completed"
    assert all(s.status == "completed" for s in state.steps)


@pytest.mark.parametrize(
    "status", ["paused", "stopped", "completed", "needs_assistance", "needs_confirmation"]
)
def test_verifier_does_not_promote_events_while_inactive(status):
    plan = single_plan()
    bindings, context = context_for(plan)
    state = state_for(plan, bindings)
    state.status = status
    event = TaskEvent(type="evidence_received", evidence=evidence_for(plan, bindings))
    assert verify_event(plan, state, event, context).event is None


def test_candidate_cannot_supply_verified_flag_or_bypass_step_state():
    plan = single_plan()
    bindings, context = context_for(plan)
    state = state_for(plan, bindings)
    data = TaskEvent(type="evidence_received", evidence=evidence_for(plan, bindings)).model_dump()
    data["evidence"]["verified"] = True
    assert verify_event(plan, state, data, context).decision == "stop"
    state.steps[0].status = "completed"
    assert (
        verify_event(plan, state, {"type": "cue_issued", "step_id": "step"}, context).reason_code
        == "invalid_step_state"
    )


@pytest.mark.parametrize("field", ["task_id", "plan_id"])
def test_provenance_cannot_be_replayed_into_another_task_or_plan(field):
    plan = single_plan()
    bindings, context = context_for(plan)
    evidence = evidence_for(plan, bindings)
    context = attest(context, evidence)
    receipt = context.receipts[evidence.provenance_id]
    context = replace(
        context, receipts={evidence.provenance_id: replace(receipt, **{field: "other"})}
    )
    result = verify_event(
        plan,
        state_for(plan, bindings),
        TaskEvent(type="evidence_received", evidence=evidence),
        context,
    )
    assert result.decision == "confirm"
    assert result.reason_code == "provenance_scope_mismatch"
    assert result.event is None
    assert (
        trusted_completion_evaluator(plan, bindings, context)(plan.steps[0], (evidence,)).status
        == "pending"
    )


def test_context_cannot_be_used_with_another_task_or_plan():
    plan = single_plan()
    bindings, context = context_for(plan)
    state = state_for(plan, bindings)
    state.task_id = "another-task"
    result = verify_event(plan, state, TaskEvent(type="cue_issued", step_id="step"), context)
    assert result.event is None
    plan.plan_id = "another-plan"
    assert verify_step(plan, "step", bindings, context).reason_code == "plan_context_mismatch"


@pytest.mark.parametrize("source", ["camera_observation", "caregiver_report"])
def test_relabelling_model_evidence_cannot_reuse_an_existing_receipt(source):
    plan = single_plan()
    bindings, context = context_for(plan)
    original = evidence_for(plan, bindings, source="model_assessment")
    context = attest(context, original)
    relabelled = original.model_copy(update={"source": source, "confidence": 0.99})
    event = TaskEvent(type="evidence_received", evidence=relabelled)
    assert verify_event(plan, state_for(plan, bindings), event, context).event is None
    assert (
        trusted_completion_evaluator(plan, bindings, context)(plan.steps[0], (relabelled,)).status
        == "pending"
    )


def test_completion_cardinality_and_ordered_target_roles_cannot_be_changed():
    plan = single_plan("place_inside")
    bindings, context = context_for(plan)
    plan.steps[0].completion_goal.target_keys.reverse()
    assert verify_step(plan, "step", bindings, context).reason_code == "invalid_target_roles"
    plan = single_plan("observe_state")
    bindings, context = context_for(plan)
    plan.steps[0].completion_goal.outcome = "items_inside"
    assert verify_step(plan, "step", bindings, context).reason_code == "invalid_target_roles"


def test_tampered_capability_facts_and_noncurrent_assessment_are_not_accepted():
    plan = single_plan("press")
    bindings, context = context_for(plan)
    bad = context.capabilities.model_copy(update={"can_press_button": "true"})
    assert (
        verify_step(plan, "step", bindings, replace(context, capabilities=bad)).reason_code
        == "invalid_capability_facts"
    )
    wrong = context.feasibility["step"].model_copy(update={"object_ids": ("another-object",)})
    assert (
        verify_step(
            plan, "step", bindings, replace(context, feasibility={"step": wrong})
        ).reason_code
        == "stale_physical_context"
    )
