import pytest

from app.planner import ModelPick, demo_pick, validate_pick
from app.schemas import PlanRequest, Profile, SceneObject


def request_for(transcript="A야, 우유 가져와", can_grasp=True, scene=None):
    return PlanRequest(
        transcript=transcript,
        user_profile=Profile(user_id="demo_A", can_grasp=can_grasp, can_press_button=True),
        scene_objects=scene if scene is not None else [
            SceneObject(id="milk_1", label="milk_carton", bbox=(0.42, 0.3, 0.6, 0.72))
        ],
    )


def door_request(can_press_button=True, can_extend_arm=True, scene=None):
    return PlanRequest(
        transcript="Open the door",
        user_profile=Profile(
            user_id="demo_A",
            can_press_button=can_press_button,
            can_extend_arm=can_extend_arm,
        ),
        scene_objects=scene
        if scene is not None
        else [SceneObject(id="button_1", label="door_button", bbox=(0.7, 0.3, 0.8, 0.5))],
    )


def test_grounded_cue_comes_from_observation():
    req = request_for()
    result = validate_pick(req, demo_pick(req), live=False)
    assert result.status == "cue"
    assert result.object_id == "milk_1"
    assert result.bbox == req.scene_objects[0].bbox
    assert result.mode == "DEMO_RULES"


def test_cannot_grasp_requires_assistance():
    req = request_for(can_grasp=False)
    result = validate_pick(req, demo_pick(req), live=False)
    assert result.status == "needs_assistance"
    assert result.bbox is None


def test_unknown_capability_requires_assistance():
    req = request_for(can_grasp=None)
    assert validate_pick(req, demo_pick(req), live=False).status == "needs_assistance"


@pytest.mark.parametrize("can_press_button", [True, False, None])
@pytest.mark.parametrize("can_extend_arm", [True, False, None])
def test_automatic_door_requires_press_and_extend_capabilities(
    can_press_button, can_extend_arm
):
    req = door_request(
        can_press_button=can_press_button,
        can_extend_arm=can_extend_arm,
    )

    result = validate_pick(req, demo_pick(req), live=False)

    if can_press_button is True and can_extend_arm is True:
        assert result.status == "cue"
        assert result.object_id == "button_1"
        assert result.bbox == req.scene_objects[0].bbox
    else:
        assert result.status == "needs_assistance"
        assert result.reason == "capability_blocked_or_unknown"
        assert result.object_id is None
        assert result.bbox is None


def test_extending_arm_alone_does_not_confirm_door_button_is_actionable():
    req = door_request(can_press_button=None, can_extend_arm=True)

    result = validate_pick(req, demo_pick(req), live=False)

    assert result.status == "needs_assistance"
    assert result.reason == "capability_blocked_or_unknown"
    assert result.bbox is None


def test_hallucinated_object_id_is_rejected():
    req = request_for()
    result = validate_pick(
        req, ModelPick(intent="retrieve_object", object_id="not_a_real_object"), live=True
    )
    assert result.status == "needs_confirmation"
    assert result.bbox is None


def test_multiple_milks_require_confirmation():
    a = SceneObject(id="a", label="milk_carton", bbox=(0.1, 0.1, 0.2, 0.2))
    b = SceneObject(id="b", label="milk_carton", bbox=(0.4, 0.3, 0.6, 0.7))
    req = request_for(scene=[a, b])
    result = validate_pick(req, ModelPick(intent="retrieve_object", object_id="a"), live=True)
    assert result.status == "needs_confirmation"


def test_multiple_door_buttons_require_confirmation_before_capability_check():
    a = SceneObject(id="a", label="door_button", bbox=(0.1, 0.1, 0.2, 0.2))
    b = SceneObject(id="b", label="button", bbox=(0.4, 0.3, 0.6, 0.7))
    req = door_request(can_press_button=False, can_extend_arm=False, scene=[a, b])

    result = validate_pick(req, ModelPick(intent="open_door", object_id="a"), live=True)

    assert result.status == "needs_confirmation"
    assert result.reason == "ambiguous_or_missing_target"
    assert result.bbox is None


def test_invalid_bbox_rejected():
    with pytest.raises(ValueError):
        SceneObject(id="broken", label="milk", bbox=(0.7, 0.2, 0.1, 0.9))


def test_duplicate_id_rejected():
    milk = SceneObject(id="duplicate", label="milk", bbox=(0.1, 0.1, 0.2, 0.2))
    cup = SceneObject(id="duplicate", label="cup", bbox=(0.3, 0.3, 0.4, 0.4))
    with pytest.raises(ValueError):
        request_for(scene=[milk, cup])
