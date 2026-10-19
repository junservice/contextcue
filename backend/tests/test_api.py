from fastapi.testclient import TestClient

from app.main import app

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
