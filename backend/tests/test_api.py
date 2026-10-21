import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import Profile

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_plan_demo(monkeypatch):
    monkeypatch.setenv("PLANNER_MODE", "demo")
    response = client.post(
        "/api/plan",
        json={
            "transcript": "A야, 우유 가져와야지",
            "user_profile": {
                "user_id": "demo_A", "can_grasp": True, "can_press_button": None
            },
            "scene_objects": [
                {"id": "milk_1", "label": "milk_carton", "bbox": [0.4, 0.25, 0.6, 0.72]}
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cue"
    assert response.json()["mode"] == "DEMO_RULES"
    assert response.json()["bbox"] == [0.4, 0.25, 0.6, 0.72]


@pytest.mark.parametrize(
    ("can_press_button", "can_extend_arm", "expected_status"),
    [
        (True, True, "cue"),
        (True, False, "needs_assistance"),
        (True, None, "needs_assistance"),
        (False, True, "needs_assistance"),
        (None, True, "needs_assistance"),
    ],
)
def test_plan_demo_door_checks_both_capabilities(
    monkeypatch, can_press_button, can_extend_arm, expected_status
):
    monkeypatch.setenv("PLANNER_MODE", "demo")
    response = client.post(
        "/api/plan",
        json={
            "transcript": "Open the door",
            "user_profile": {
                "user_id": "demo_A",
                "can_press_button": can_press_button,
                "can_extend_arm": can_extend_arm,
            },
            "scene_objects": [
                {
                    "id": "button_1",
                    "label": "door_button",
                    "bbox": [0.7, 0.3, 0.8, 0.5],
                }
            ],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == expected_status
    assert body["mode"] == "DEMO_RULES"
    if expected_status == "cue":
        assert body["object_id"] == "button_1"
        assert body["bbox"] == [0.7, 0.3, 0.8, 0.5]
    else:
        assert body["object_id"] is None
        assert body["bbox"] is None


def test_profile_defaults():
    profile = Profile(user_id="demo_A")
    assert profile.can_extend_arm is None
    assert profile.preferred_guidance == []
    other_profile = Profile(user_id="demo_B")
    profile.preferred_guidance.append("voice")
    assert other_profile.preferred_guidance == []


@pytest.mark.parametrize("can_extend_arm", [True, False, None])
@pytest.mark.parametrize(
    "preferred_guidance",
    [[], ["visual_highlight"], ["arrow"], ["voice"], ["visual_highlight", "arrow", "voice"]],
)
def test_plan_accepts_extended_profile(monkeypatch, can_extend_arm, preferred_guidance):
    monkeypatch.setenv("PLANNER_MODE", "demo")
    response = client.post(
        "/api/plan",
        json={
            "transcript": "우유 가져와",
            "user_profile": {
                "user_id": "demo_A",
                "can_grasp": True,
                "can_press_button": None,
                "can_extend_arm": can_extend_arm,
                "preferred_guidance": preferred_guidance,
            },
            "scene_objects": [
                {"id": "milk_1", "label": "milk_carton", "bbox": [0.4, 0.25, 0.6, 0.72]}
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cue"
    assert response.json()["mode"] == "DEMO_RULES"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("can_extend_arm", "unconfirmed"),
        ("preferred_guidance", ["touch"]),
        ("preferred_guidance", ["voice", "touch"]),
        ("preferred_guidance", "voice"),
        ("preferred_guidance", None),
    ],
)
def test_plan_rejects_invalid_profile(field, value):
    response = client.post(
        "/api/plan",
        json={
            "transcript": "우유 가져와",
            "user_profile": {"user_id": "demo_A", field: value},
            "scene_objects": [],
        },
    )
    assert response.status_code == 422
    assert any(
        error["loc"][:3] == ["body", "user_profile", field]
        for error in response.json()["detail"]
    )
