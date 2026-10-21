"""Pure minimal-cue selection. No audio playback, coordinates or action execution."""

from collections.abc import Sequence
from typing import Literal, Self

from pydantic import ConfigDict, model_validator

from .models import HelpLevel, TaskEvent, TaskModel, TaskPlan, TaskState, Text
from .verification import VerificationContext, verify_event

Guidance = Literal["visual_highlight", "arrow", "voice"]


class Cue(TaskModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: Text
    help_level: HelpLevel
    kind: Literal["text", "voice", "visual_highlight", "arrow", "assistance"]
    text: Text
    object_id: Text | None = None
    observation_revision: Text | None = None

    @model_validator(mode="after")
    def check_visual_reference(self) -> Self:
        visual = self.kind in ("visual_highlight", "arrow")
        if visual and (self.object_id is None or self.observation_revision is None):
            raise ValueError("visual cues require an observed object ID and revision")
        if not visual and (self.object_id is not None or self.observation_revision is not None):
            raise ValueError("non-visual cues do not carry visual references")
        return self


def select_cue(
    plan: TaskPlan,
    state: TaskState,
    context: VerificationContext,
    preferred_guidance: Sequence[Guidance] = (),
) -> Cue | None:
    """Select one cue after verification, preserving state and preferences.

    Level 0 leaves an opportunity for independent action. Level 1 uses text/voice;
    level 2 permits highlight; level 3 permits arrow; level 4+ offers assistance.
    Visual cues carry only a verified ID/revision. A renderer must look up the
    matching observation's bbox, never synthesize one from this cue's text.
    """
    if any(mode not in ("visual_highlight", "arrow", "voice") for mode in preferred_guidance):
        raise ValueError("unsupported guidance preference")
    if state.current_step_id is None:
        return None
    check = verify_event(
        plan,
        state,
        TaskEvent(type="cue_issued", step_id=state.current_step_id),
        context,
    )
    if check.decision != "allow":
        return None
    step = next(step for step in plan.steps if step.step_id == state.current_step_id)
    level = next(s.help_level for s in state.steps if s.step_id == step.step_id)
    if level == 0:
        return None
    if level >= 4:
        return Cue(
            step_id=step.step_id,
            help_level=level,
            kind="assistance",
            text="도움이 필요하면 보조자에게 요청해 주세요.",
        )
    concepts = {target.target_key: target.concept for target in plan.targets}
    labels = {
        "door_open_button": "열림 버튼",
        "automatic_door_opening": "출입구",
        "bag": "가방",
        "water_bottle": "물병",
    }
    names = [labels.get(concepts[key], "대상") for key in step.target_keys]
    text = {
        "locate": f"{names[0]}을 찾아보세요.",
        "press": f"{names[0]}을 눌러 보세요.",
        "observe_state": f"{names[0]}의 열림 상태를 확인해 보세요.",
        "traverse": "확인된 통로로 이동해 보세요.",
        "place_inside": f"{names[0]}을 용기 안에 넣어 보세요.",
    }[step.action]
    if step.action == "place_inside":
        text = f"{names[0]}을 {names[1]} 안에 넣어 보세요."
    elif step.action == "observe_state" and step.completion_goal.outcome == "items_inside":
        text = f"{names[0]}이 {names[1]} 안에 있는지 확인해 보세요."
    kind = "voice" if "voice" in preferred_guidance else "text"
    binding = state.target_bindings.get(step.target_keys[0])
    if binding is not None:
        if level >= 3 and "arrow" in preferred_guidance:
            kind = "arrow"
        elif level >= 2 and "visual_highlight" in preferred_guidance:
            kind = "visual_highlight"
    visual = kind in ("visual_highlight", "arrow")
    return Cue(
        step_id=step.step_id,
        help_level=level,
        kind=kind,
        text=text,
        object_id=binding.object_id if visual else None,
        observation_revision=binding.observation_revision if visual else None,
    )
