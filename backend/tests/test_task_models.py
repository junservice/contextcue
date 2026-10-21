"""Synthetic structural checks only, not observation/source or completion verification."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.tasking.models import (
    CompletionGoal,
    Evidence,
    StepState,
    TargetBinding,
    TargetRef,
    TaskEvent,
    TaskPlan,
    TaskState,
    TaskStep,
)


@pytest.fixture
def plan_data():
    # A minimal semantic example, not either Phase 1.2 scenario fixture.
    return {
        "schema_version": "1.0",
        "plan_id": "synthetic-plan",
        "goal": "find_target",
        "targets": [{"target_key": "item", "concept": "test_item"}],
        "steps": [{
            "step_id": "find",
            "action": "locate",
            "target_keys": ["item"],
            "completion_goal": {"outcome": "target_located", "target_keys": ["item"]},
        }],
    }


@pytest.fixture
def binding_data():
    return {"target_key": "item", "object_id": "synthetic-object", "observation_revision": "r1"}


@pytest.fixture
def evidence_data():
    return {
        "evidence_id": "synthetic-evidence",
        "step_id": "find",
        "source": "camera_observation",
        "outcome": "target_located",
        "target_keys": ["item"],
        "object_ids": ["synthetic-object"],
        "observation_revision": "r1",
        "relation": "supports",
    }


def test_unresolved_target_is_valid(plan_data):
    plan = TaskPlan.model_validate(plan_data)
    assert plan.targets[0].model_dump() == {
        "target_key": "item", "concept": "test_item", "qualifiers": {},
    }
    assert plan.steps[0].max_help_level == 4


@pytest.mark.parametrize("field", ["object_id", "bbox", "observation_revision"])
def test_target_rejects_observed_fields(plan_data, field):
    plan_data["targets"][0][field] = "not-a-semantic-field"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TaskPlan.model_validate(plan_data)


def test_qualifiers_are_limited_semantic_text():
    target = TargetRef(
        target_key="item", concept="test_item",
        qualifiers={"color": "blue", "relative_position": "left"},
    )
    assert target.qualifiers["color"] == "blue"
    with pytest.raises(ValidationError):
        TargetRef(target_key="item", concept="test_item", qualifiers={"object_id": "fake"})
    with pytest.raises(ValidationError):
        TargetRef(target_key="item", concept="test_item", qualifiers={"color": {"bbox": []}})


@pytest.mark.parametrize("collection", ["targets", "steps"])
def test_plan_rejects_duplicate_ids(plan_data, collection):
    plan_data[collection].append(deepcopy(plan_data[collection][0]))
    with pytest.raises(ValidationError, match="must be unique"):
        TaskPlan.model_validate(plan_data)


@pytest.mark.parametrize("completion", [False, True])
def test_plan_rejects_unknown_target_reference(plan_data, completion):
    node = plan_data["steps"][0]
    if completion:
        node = node["completion_goal"]
    node["target_keys"] = ["undeclared"]
    with pytest.raises(ValidationError, match="declared target keys"):
        TaskPlan.model_validate(plan_data)


@pytest.mark.parametrize("completion", [False, True])
def test_step_and_completion_reject_duplicate_target_references(plan_data, completion):
    node = plan_data["steps"][0]
    if completion:
        node = node["completion_goal"]
    node["target_keys"] = ["item", "item"]
    with pytest.raises(ValidationError, match="must be unique"):
        TaskPlan.model_validate(plan_data)


@pytest.mark.parametrize("level", ["plan", "step", "completion"])
@pytest.mark.parametrize("field", ["allowed_sources", "confidence_threshold", "quorum"])
def test_plan_cannot_define_trusted_completion_policy(plan_data, level, field):
    node = plan_data
    if level in ("step", "completion"):
        node = node["steps"][0]
    if level == "completion":
        node = node["completion_goal"]
    node[field] = ["manual_progress"] if field == "allowed_sources" else 0
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        TaskPlan.model_validate(plan_data)


@pytest.mark.parametrize("collection", ["targets", "steps"])
def test_plan_rejects_empty_structure(plan_data, collection):
    plan_data[collection] = []
    with pytest.raises(ValidationError):
        TaskPlan.model_validate(plan_data)


def test_plan_rejects_unknown_schema_version(plan_data):
    plan_data["schema_version"] = "2.0"
    with pytest.raises(ValidationError):
        TaskPlan.model_validate(plan_data)


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_identifiers_cannot_be_empty(bad):
    with pytest.raises(ValidationError):
        TargetRef(target_key=bad, concept="test_item")


@pytest.mark.parametrize("bad", [-1, True, 1.5, "2"])
def test_help_levels_require_nonnegative_integers(plan_data, bad):
    plan_data["steps"][0]["max_help_level"] = bad
    with pytest.raises(ValidationError):
        TaskPlan.model_validate(plan_data)
    with pytest.raises(ValidationError):
        StepState(step_id="find", help_level=bad)


def test_round_trip_preserves_all_domain_models(plan_data, binding_data, evidence_data):
    plan = TaskPlan.model_validate(plan_data)
    binding = TargetBinding.model_validate(binding_data)
    evidence = Evidence.model_validate(evidence_data)
    step_state = StepState(step_id="find", status="awaiting_evidence", help_level=2)
    state = TaskState(
        task_id="synthetic-task", plan_id=plan.plan_id, status="active",
        current_step_id="find", steps=[step_state],
        target_bindings={"item": binding}, evidence=[evidence],
    )
    models = [
        plan, plan.targets[0], plan.steps[0], plan.steps[0].completion_goal,
        binding, evidence, step_state, state,
        TaskEvent(type="target_bound", binding=binding),
        TaskEvent(type="evidence_received", evidence=evidence),
        TaskEvent(type="cue_issued", step_id="find"),
    ]
    for model in models:
        assert type(model).model_validate_json(model.model_dump_json()) == model


def test_mutable_defaults_are_independent():
    first_target = TargetRef(target_key="item", concept="test_item")
    second_target = TargetRef(target_key="item", concept="test_item")
    first_target.qualifiers["color"] = "blue"
    assert second_target.qualifiers == {}

    first = TaskState(task_id="first", plan_id="plan")
    second = TaskState(task_id="second", plan_id="plan")
    first.steps.append(StepState(step_id="find"))
    first.target_bindings["item"] = TargetBinding(
        target_key="item", object_id="synthetic-object", observation_revision="r1",
    )
    first.evidence.append(Evidence(
        evidence_id="e1", step_id="find", source="unknown",
        outcome="target_located", relation="inconclusive",
    ))
    assert second.steps == []
    assert second.target_bindings == {}
    assert second.evidence == []

    other_evidence = Evidence(
        evidence_id="e2", step_id="find", source="unknown",
        outcome="target_located", relation="inconclusive",
    )
    first.evidence[0].target_keys.append("item")
    first.evidence[0].object_ids.append("synthetic-object")
    assert other_evidence.target_keys == []
    assert other_evidence.object_ids == []


def test_step_position_and_help_level_are_independent():
    state = TaskState(
        task_id="task", plan_id="plan", current_step_id="second",
        steps=[StepState(step_id="first", help_level=3), StepState(step_id="second")],
    )
    assert state.current_step_id == "second"
    assert [step.help_level for step in state.steps] == [3, 0]


def test_binding_and_source_labels_do_not_prove_observation_trust(binding_data, evidence_data):
    """No snapshot/provider/authentication is consulted: Phase 2 must verify candidates.

    These fabricated labels parsing successfully prove only model shape validity.
    They do not prove camera/caregiver authenticity, grounding or action success.
    """
    binding_data["object_id"] = "not-observed-anywhere"
    binding_data["observation_revision"] = "not-a-real-revision"
    assert TargetBinding.model_validate(binding_data).object_id == "not-observed-anywhere"
    for source in ("camera_observation", "caregiver_report", "model_assessment"):
        evidence_data["source"] = source
        assert Evidence.model_validate(evidence_data).source == source


@pytest.mark.parametrize("event_type", [
    "pause", "resume", "stop", "refusal", "more_help", "help_requested", "manual_advance",
])
def test_control_events_are_data_only(event_type):
    event = TaskEvent(type=event_type)
    assert event.binding is None
    assert event.evidence is None


@pytest.mark.parametrize("data", [
    {"type": "target_bound"},
    {"type": "evidence_received"},
    {"type": "cue_issued"},
    {"type": "auto_complete"},
    {"type": "manual_advance", "completed": True},
])
def test_invalid_event_payload_is_rejected(data):
    with pytest.raises(ValidationError):
        TaskEvent.model_validate(data)


def test_control_events_cannot_smuggle_binding_or_evidence(binding_data, evidence_data):
    for data in ({"binding": binding_data}, {"evidence": evidence_data}):
        with pytest.raises(ValidationError):
            TaskEvent(type="pause", **data)
    with pytest.raises(ValidationError, match="must match"):
        TaskEvent(type="evidence_received", step_id="another-step", evidence=evidence_data)


@pytest.mark.parametrize("model,data", [
    (TargetBinding, {"target_key": "item", "object_id": "obj", "observation_revision": "r1"}),
    (CompletionGoal, {"outcome": "target_located", "target_keys": ["item"]}),
    (TaskStep, {
        "step_id": "find", "action": "locate", "target_keys": ["item"],
        "completion_goal": {"outcome": "target_located", "target_keys": ["item"]},
    }),
    (Evidence, {
        "evidence_id": "e1", "step_id": "find", "source": "unknown",
        "outcome": "target_located", "relation": "inconclusive",
    }),
    (StepState, {"step_id": "find"}),
    (TaskState, {"task_id": "task", "plan_id": "plan"}),
])
def test_domain_models_reject_unknown_control_fields(model, data):
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model.model_validate({**data, "force_complete": True})


def test_state_rejects_broken_internal_references(binding_data, evidence_data):
    valid = {
        "task_id": "task", "plan_id": "plan", "current_step_id": "find",
        "steps": [{"step_id": "find"}],
        "target_bindings": {"item": binding_data}, "evidence": [evidence_data],
    }
    invalid_variants = [
        {**valid, "current_step_id": "missing"},
        {**valid, "steps": [{"step_id": "find"}, {"step_id": "find"}]},
        {**valid, "evidence": [evidence_data, evidence_data]},
        {**valid, "evidence": [{**evidence_data, "step_id": "missing"}]},
        {**valid, "target_bindings": {"wrong-key": binding_data}},
    ]
    for data in invalid_variants:
        with pytest.raises(ValidationError):
            TaskState.model_validate(data)


@pytest.mark.parametrize("field,value", [("source", "trusted_ai"), ("relation", "completed")])
def test_evidence_rejects_unknown_labels(evidence_data, field, value):
    evidence_data[field] = value
    with pytest.raises(ValidationError):
        Evidence.model_validate(evidence_data)


PLAN_FIXTURES = Path(__file__).parent / "fixtures" / "plans"


@pytest.mark.parametrize("filename,goal,targets,expected_steps", [
    (
        "automatic_door.json",
        "pass_through_door",
        {"open_button": "door_open_button", "doorway": "automatic_door_opening"},
        [
            ("locate_button", "locate", ["open_button"], "target_located"),
            ("press_button", "press", ["open_button"], "pressed"),
            ("confirm_open", "observe_state", ["doorway"], "state_open"),
            ("pass_through", "traverse", ["doorway"], "passed_through"),
        ],
    ),
    (
        "packing_bag.json",
        "pack_bag",
        {"bag": "bag", "bottle": "water_bottle"},
        [
            ("locate_bag", "locate", ["bag"], "target_located"),
            ("locate_bottle", "locate", ["bottle"], "target_located"),
            ("place_bottle", "place_inside", ["bottle", "bag"], "placed_inside"),
            ("verify_items", "observe_state", ["bottle", "bag"], "items_inside"),
        ],
    ),
])
def test_scenario_fixtures_use_same_task_plan_model(filename, goal, targets, expected_steps):
    """Validate plan data only; no task-specific executor or completion policy is used."""
    plan = TaskPlan.model_validate_json((PLAN_FIXTURES / filename).read_text(encoding="utf-8"))
    assert plan.goal == goal
    assert {target.target_key: target.concept for target in plan.targets} == targets
    assert [
        (step.step_id, step.action, step.target_keys, step.completion_goal.outcome)
        for step in plan.steps
    ] == expected_steps
    for step in plan.steps:
        assert step.completion_goal.target_keys == step.target_keys
        assert step.step_id != "complete"
        assert step.action != "complete"
    # The final real action declares a desired result, not an already completed task.
    # Executing/evaluating trusted completion remains Phase 1.4 / Phase 2 work.
    assert TaskPlan.model_validate_json(plan.model_dump_json()) == plan


@pytest.mark.parametrize("filename", ["automatic_door.json", "packing_bag.json"])
def test_scenario_fixtures_have_no_observations_or_completion_policy(filename):
    data = json.loads((PLAN_FIXTURES / filename).read_text(encoding="utf-8"))
    forbidden = {
        "bbox", "object_id", "object_ids", "observation_revision", "target_bindings",
        "evidence", "allowed_sources", "confidence_threshold", "quorum",
    }

    def check_semantic_only(value):
        if isinstance(value, dict):
            assert forbidden.isdisjoint(value), f"observation/policy field in {filename}"
            for child in value.values():
                check_semantic_only(child)
        elif isinstance(value, list):
            for child in value:
                check_semantic_only(child)

    check_semantic_only(data)
