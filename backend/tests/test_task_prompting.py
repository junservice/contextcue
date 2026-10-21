"""Pure cue tests with synthetic backend observations, not camera/accessibility QA."""

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.tasking.engine import create_task_state
from app.tasking.models import (
    CapabilityFacts,
    ObservationSnapshot,
    ObservedObject,
    TargetBinding,
    TaskPlan,
)
from app.tasking.prompting import Cue, select_cue
from app.tasking.verification import VerificationContext


@pytest.fixture
def prompt_case():
    path = Path(__file__).parent / "fixtures" / "plans" / "automatic_door.json"
    plan = TaskPlan.model_validate_json(path.read_text(encoding="utf-8"))
    snapshot = ObservationSnapshot(
        revision="r1",
        objects=[
            ObservedObject(object_id=f"obj-{t.target_key}", concept=t.concept) for t in plan.targets
        ],
    )
    context = VerificationContext(
        task_id="task",
        plan_id=plan.plan_id,
        snapshot=snapshot,
        capabilities=CapabilityFacts(can_press_button=True, can_extend_arm=True),
    )
    state = create_task_state(plan, "task")
    state.target_bindings = {
        t.target_key: TargetBinding(
            target_key=t.target_key,
            object_id=f"obj-{t.target_key}",
            observation_revision="r1",
        )
        for t in plan.targets
    }
    return plan, state, context


@pytest.mark.parametrize(
    "level,kind",
    [(0, None), (1, "voice"), (2, "visual_highlight"), (3, "arrow"), (4, "assistance")],
)
def test_one_minimal_cue_per_help_level_without_state_changes(prompt_case, level, kind):
    plan, state, context = prompt_case
    state.steps[0].help_level = level
    before = (plan.model_dump(), state.model_dump(), context.snapshot.model_dump())
    preferences = ["visual_highlight", "arrow", "voice"]
    cue = select_cue(plan, state, context, preferences)
    if kind is None:
        assert cue is None
    else:
        assert isinstance(cue, Cue)
        assert cue.kind == kind
        assert cue.help_level == level
        assert "bbox" not in cue.model_dump()
        if kind in ("visual_highlight", "arrow"):
            assert cue.object_id == "obj-open_button"
            assert cue.observation_revision == "r1"
        else:
            assert cue.object_id is None
            assert cue.observation_revision is None
    assert (plan.model_dump(), state.model_dump(), context.snapshot.model_dump()) == before
    assert preferences == ["visual_highlight", "arrow", "voice"]


@pytest.mark.parametrize(
    "preferences,level,kind",
    [
        ((), 1, "text"),
        (("voice",), 3, "voice"),
        (("arrow",), 2, "text"),
        (("arrow",), 3, "arrow"),
        (("visual_highlight",), 3, "visual_highlight"),
    ],
)
def test_guidance_preferences_limit_modalities(prompt_case, preferences, level, kind):
    plan, state, context = prompt_case
    state.steps[0].help_level = level
    assert select_cue(plan, state, context, preferences).kind == kind


@pytest.mark.parametrize("level", [1, 2, 3])
def test_unresolved_locate_only_offers_text_or_voice(prompt_case, level):
    plan, state, context = prompt_case
    state.target_bindings.clear()
    state.steps[0].help_level = level
    for preferences in (("visual_highlight", "arrow"), ("visual_highlight", "arrow", "voice")):
        cue = select_cue(plan, state, context, preferences)
        assert cue.kind in ("text", "voice")
        assert cue.object_id is None
        assert "bbox" not in cue.model_dump()


@pytest.mark.parametrize("bad", ["stale", "unknown", "ambiguous", "missing"])
def test_invalid_target_never_produces_visual_or_action_cue(prompt_case, bad):
    plan, state, context = prompt_case
    state.steps[0].help_level = 3
    if bad == "stale":
        state.target_bindings["open_button"].observation_revision = "old"
    elif bad == "unknown":
        state.target_bindings["open_button"].object_id = "not-observed"
    elif bad == "ambiguous":
        context.snapshot.objects.append(
            context.snapshot.objects[0].model_copy(update={"object_id": "other"})
        )
    else:
        context.snapshot.objects.clear()
    assert select_cue(plan, state, context, ("arrow", "visual_highlight")) is None


@pytest.mark.parametrize(
    "status", ["paused", "needs_confirmation", "needs_assistance", "stopped", "completed"]
)
def test_holds_and_terminal_states_offer_no_cue(prompt_case, status):
    plan, state, context = prompt_case
    state.status = status
    state.steps[0].help_level = 3
    assert select_cue(plan, state, context, ("arrow",)) is None


def test_motor_constraints_and_unreviewed_physical_context_block_press_cues(prompt_case):
    plan, state, context = prompt_case
    state.steps[0].status = "completed"
    state.steps[1].status = "active"
    state.steps[1].help_level = 2
    state.current_step_id = state.steps[1].step_id
    assert select_cue(plan, state, context, ("visual_highlight",)) is None
    context = replace(
        context, capabilities=CapabilityFacts(can_press_button=False, can_extend_arm=True)
    )
    assert select_cue(plan, state, context, ("voice",)) is None


def test_cue_contract_rejects_coordinates_or_missing_visual_references(prompt_case):
    with pytest.raises(ValidationError):
        Cue(step_id="step", help_level=2, kind="arrow", text="look")
    with pytest.raises(ValidationError):
        Cue(step_id="step", help_level=1, kind="text", text="look", object_id="invented")
    with pytest.raises(ValidationError):
        Cue(step_id="step", help_level=1, kind="text", text="look", bbox=[0, 0, 1, 1])
    plan, state, context = prompt_case
    with pytest.raises(ValueError, match="unsupported guidance"):
        select_cue(plan, state, context, ("touch",))
