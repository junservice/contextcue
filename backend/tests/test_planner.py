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


def test_invalid_bbox_rejected():
    with pytest.raises(ValueError):
        SceneObject(id="broken", label="milk", bbox=(0.7, 0.2, 0.1, 0.9))


def test_duplicate_id_rejected():
    milk = SceneObject(id="duplicate", label="milk", bbox=(0.1, 0.1, 0.2, 0.2))
    cup = SceneObject(id="duplicate", label="cup", bbox=(0.3, 0.3, 0.4, 0.4))
    with pytest.raises(ValueError):
        request_for(scene=[milk, cup])
