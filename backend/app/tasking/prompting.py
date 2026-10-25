"""Pure minimal-cue selection. No audio playback, coordinates or action execution."""

from collections.abc import Sequence
from types import MappingProxyType
from typing import Literal, Self

from pydantic import ConfigDict, model_validator

from .models import HelpLevel, TargetRef, TaskEvent, TaskModel, TaskPlan, TaskState, Text
from .semantics import verify_execution_semantics
from .verification import VerificationContext, verify_event

Guidance = Literal["visual_highlight", "arrow", "voice"]

_LABELS = MappingProxyType(
    {
        "door_open_button": "열림 버튼",
        "elevator_call_button": "엘리베이터 호출 버튼",
        "automatic_door_opening": "자동문 출입구",
        "garden_gate_opening": "정원 출입구",
        "corridor": "복도",
        "bag": "가방",
        "water_bottle": "물병",
        "book": "책",
        "box": "상자",
        "pen": "펜",
        "pouch": "파우치",
        "basket": "바구니",
        "towel": "수건",
        "mug": "머그잔",
        "paper": "종이",
    }
)
_COLORS = MappingProxyType({"red": "빨간", "blue": "파란", "green": "초록색"})
_POSITIONS = MappingProxyType({"left": "왼쪽", "right": "오른쪽", "front": "앞쪽", "back": "뒤쪽"})


def _target_name(target: TargetRef) -> str | None:
    """Render only closed, reviewed vocabulary; never echo model strings as cues."""
    name = _LABELS.get(target.concept)
    if name is None:
        return None
    for key, vocabulary in (("color", _COLORS), ("relative_position", _POSITIONS)):
        value = target.qualifiers.get(key)
        if value is not None:
            label = vocabulary.get(value)
            if label is None:
                return None  # Never silently discard a distinguishing qualifier.
            name = f"{label} {name}"
    return name


def _particle(name: str, consonant: str, vowel: str, *, direction=False) -> str:
    final = (ord(name[-1]) - 0xAC00) % 28
    return name + (vowel if final == 0 or (direction and final == 8) else consonant)


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
    if verify_execution_semantics(plan, context).decision != "allow":
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
    targets = {target.target_key: target for target in plan.targets}
    names = [_target_name(targets[key]) for key in step.target_keys]
    if any(name is None for name in names):
        return Cue(
            step_id=step.step_id,
            help_level=level,
            kind="assistance",
            text="물건 설명을 확인하기 어려워요. 보조자에게 확인해 주세요.",
        )
    subject = _particle(names[0], "이", "가")
    direct_object = _particle(names[0], "을", "를")
    text = {
        "locate": f"{direct_object} 찾아보세요.",
        "press": f"{direct_object} 눌러 보세요.",
        "observe_state": f"{names[0]}의 열림 상태를 확인해 보세요.",
        "traverse": f"{_particle(names[0], '으로', '로', direction=True)} 이동해 보세요.",
        "place_inside": f"{direct_object} 용기 안에 넣어 보세요.",
    }[step.action]
    if step.action == "place_inside":
        text = f"{direct_object} {names[1]} 안에 넣어 보세요."
    elif step.action == "observe_state" and step.completion_goal.outcome == "items_inside":
        text = f"{subject} {names[1]} 안에 있는지 확인해 보세요."
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
