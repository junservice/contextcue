"""HTTP lifecycle tests with synthetic backend adapters; API/live calls are mocked."""

import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from app import task_api
from app.main import app
from app.tasking.models import Evidence, ObservationSnapshot, ObservedObject
from app.tasking.planning import PlanningError
from app.tasking.verification import EvidenceReceipt


class SyntheticProvider:
    mode = "MOCK_PROVIDER"
    model_id = "synthetic"

    def __init__(self):
        self.calls = 0
        self.raw = None
        self.error = None

    async def complete(self, messages, schema):
        self.calls += 1
        if self.error:
            raise self.error
        if self.raw is not None:
            return self.raw
        root = schema["anyOf"][0]["properties"]
        targets = [
            {key: value["enum"][0] for key, value in variant["properties"].items()}
            for variant in schema["$defs"]["TargetRef"]["oneOf"]
        ]
        steps = []
        for index, variant in enumerate(schema["$defs"]["TaskStep"]["oneOf"]):
            props = variant["properties"]
            steps.append({
                "step_id": f"s{index}", "action": props["action"]["enum"][0],
                "target_keys": props["target_keys"]["enum"][0],
                "completion_goal": {
                    "outcome": props["completion_goal"]["properties"]["outcome"]["enum"][0],
                    "target_keys": props["target_keys"]["enum"][0],
                },
            })
        return json.dumps({
            "plan_id": root["plan_id"]["enum"][0], "goal": root["goal"]["enum"][0],
            "targets": targets, "steps": steps,
        })


class SyntheticSessions(task_api.TaskSessions):
    revision = "r1"

    def __init__(self):
        super().__init__()
        self.receipts = {}

    def context(self, task_id, plan_id, request):
        context = super().context(task_id, plan_id, request)
        return replace(
            context,
            snapshot=ObservationSnapshot(
                revision=self.revision,
                objects=[
                    ObservedObject(object_id="mug-1", concept="mug"),
                    ObservedObject(object_id="button-1", concept="elevator_call_button"),
                ],
            ),
            receipts=self.receipts,
            caregiver_principals=frozenset({"synthetic-caregiver"}),
        )


@pytest.fixture
def api(monkeypatch):
    store, provider = SyntheticSessions(), SyntheticProvider()
    monkeypatch.setattr(app.state, "task_sessions", store)
    monkeypatch.setattr(task_api, "provider", lambda: provider)
    with TestClient(app) as client:
        yield client, store, provider


def create(api, **changes):
    body = {
        "goal": "locate_mug_only", "transcript": "Only help me locate the mug.",
        "user_profile": {"user_id": "synthetic", "preferred_guidance": ["voice"]},
    }
    body.update(changes)
    return api[0].post("/api/v1/tasks", json=body)


def send(api, session, candidate, **changes):
    body = {
        "event_id": f"event-{session['version']}", "expected_version": session["version"],
        "event": candidate,
    }
    body.update(changes)
    return api[0].post(f"/api/v1/tasks/{session['task_id']}/events", json=body)


def started(api):
    result = create(api)
    assert result.status_code == 200, result.text
    session = result.json()["session"]
    assert session["mode"] == "MOCK_PROVIDER"
    assert session["version"] == 1
    assert session["state"]["status"] == "active"
    return session


def bind(api, session, revision="r1"):
    return send(api, session, {
        "type": "target_bound", "binding": {
            "target_key": session["plan"]["targets"][0]["target_key"],
            "object_id": "mug-1", "observation_revision": revision,
        },
    })


def evidence(session):
    step = session["plan"]["steps"][0]
    return Evidence(
        evidence_id="synthetic-evidence", step_id=step["step_id"], source="caregiver_report",
        outcome=step["completion_goal"]["outcome"], target_keys=step["target_keys"],
        object_ids=["mug-1"], observation_revision="r1", provenance_id="synthetic-receipt",
        relation="supports",
    )


def test_create_get_and_poll_have_no_completion_or_reissued_cue(api):
    session = started(api)
    for _ in range(2):
        result = api[0].get(f"/api/v1/tasks/{session['task_id']}").json()
        assert result["version"] == 1
        assert result["cue"] is None and result["events"] == []
        assert result["state"]["evidence"] == []
        assert result["state"]["steps"][0]["help_level"] == 0


def test_pause_resume_help_cue_and_manual_progress_are_distinct(api):
    session = started(api)
    for event_type, expected_status in [
        ("pause", "paused"), ("resume", "active"), ("more_help", "active"),
        ("cue_issued", "active"), ("manual_advance", "needs_confirmation"),
    ]:
        result = send(api, session, {"type": event_type, "step_id": "s0"})
        assert result.status_code == 200
        session = result.json()
        assert session["state"]["status"] == expected_status
        assert session["state"]["evidence"] == []
        if event_type in ("more_help", "cue_issued"):
            assert session["cue"]["kind"] == "voice"
            assert session["cue"]["object_id"] is None
            assert sum(e["kind"] == "cue_issued" for e in session["events"]) == 1


@pytest.mark.parametrize("event_type,status", [
    ("stop", "stopped"), ("refusal", "stopped"), ("help_requested", "needs_assistance"),
])
def test_safety_controls_remain_available_during_a_hold(api, event_type, status):
    session = send(api, started(api), {"type": "manual_advance"}).json()
    result = send(api, session, {"type": event_type})
    assert result.status_code == 200
    assert result.json()["state"]["status"] == status
    assert result.json()["cue"] is None


@pytest.mark.parametrize("event", [
    {"type": "resume"}, {"type": "pause", "step_id": "wrong-step"},
    {"type": "cue_issued", "step_id": "wrong-step"},
])
def test_invalid_transition_and_wrong_step_do_not_complete(api, event):
    result = send(api, started(api), event)
    assert result.status_code == 200
    assert not result.json()["accepted"]
    assert result.json()["state"]["status"] != "completed"
    assert result.json()["cue"] is None


@pytest.mark.parametrize("changes", [
    {"event": {"type": "invented"}}, {"event": {"type": "evidence_received"}},
    {"event": {"type": "pause", "trusted": True}}, {"expected_version": True},
    {"expected_version": 0}, {"receipts": {}},
])
def test_malformed_event_envelope_is_422_and_does_not_mutate(api, changes):
    session = started(api)
    assert send(api, session, {"type": "pause"}, **changes).status_code == 422
    assert api[1].get(session["task_id"]).version == 1


def test_duplicate_and_stale_version_are_409_without_repeating_help(api):
    session = started(api)
    updated = send(api, session, {"type": "more_help"}).json()
    duplicate = send(api, session, {"type": "more_help"})
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "duplicate_event_id"
    stale = send(api, session, {"type": "stop"}, event_id="another")
    assert stale.status_code == 409
    assert stale.json()["detail"] == "state_version_conflict"
    assert api[1].get(session["task_id"]).version == updated["version"]


def test_unattested_evidence_does_not_enter_engine(api):
    session = bind(api, started(api)).json()
    result = send(api, session, {"type": "evidence_received", "evidence": evidence(session).model_dump()})
    assert result.status_code == 200
    assert result.json()["reason_code"] == "provenance_missing"
    assert result.json()["state"]["status"] == "needs_confirmation"
    assert result.json()["state"]["evidence"] == []


def test_backend_attested_evidence_completes_and_retry_cannot_duplicate(api):
    session = bind(api, started(api)).json()
    claim = evidence(session)
    api[1].receipts[claim.provenance_id] = EvidenceReceipt(
        claim.provenance_id, "synthetic-caregiver", claim,
        session["task_id"], session["plan"]["plan_id"],
    )
    event = {"type": "evidence_received", "evidence": claim.model_dump()}
    result = send(api, session, event)
    assert result.status_code == 200
    updated = result.json()
    assert updated["state"]["status"] == "completed"
    assert len(updated["state"]["evidence"]) == 1
    assert [e["kind"] for e in updated["events"]] == [
        "evidence_accepted", "step_completed", "task_completed",
    ]
    assert send(api, session, event).status_code == 409
    assert send(api, updated, {"type": "more_help"}).json()["detail"] == "terminal_state"


@pytest.mark.parametrize("ability,reason,status", [
    (True, "context_review_required", "needs_confirmation"),
    (False, "capability_blocked", "needs_assistance"),
    (None, "capability_unknown", "needs_confirmation"),
])
def test_locating_button_does_not_authorize_pressing(api, ability, reason, status):
    result = create(
        api, goal="call_elevator", transcript="Help me find the elevator call button and press it.",
        user_profile={"user_id": "synthetic", "can_press_button": ability, "can_extend_arm": True},
    )
    session = result.json()["session"]
    key = session["plan"]["targets"][0]["target_key"]
    session = send(api, session, {"type": "target_bound", "binding": {
        "target_key": key, "object_id": "button-1", "observation_revision": "r1",
    }}).json()
    claim = evidence(session).model_copy(update={"object_ids": ["button-1"]})
    api[1].receipts[claim.provenance_id] = EvidenceReceipt(
        claim.provenance_id, "synthetic-caregiver", claim,
        session["task_id"], session["plan"]["plan_id"],
    )
    result = send(api, session, {"type": "evidence_received", "evidence": claim.model_dump()})
    assert result.status_code == 200
    body = result.json()
    assert body["reason_code"] == reason
    assert body["state"]["status"] == status
    assert body["state"]["steps"][0]["status"] == "completed"
    assert body["state"]["steps"][1]["status"] != "completed"
    assert body["cue"] is None


def test_receipt_from_another_task_cannot_complete(api):
    first, second = started(api), started(api)
    session = bind(api, second).json()
    claim = evidence(session)
    api[1].receipts[claim.provenance_id] = EvidenceReceipt(
        claim.provenance_id, "synthetic-caregiver", claim,
        first["task_id"], first["plan"]["plan_id"],
    )
    result = send(api, session, {"type": "evidence_received", "evidence": claim.model_dump()})
    assert result.json()["reason_code"] == "provenance_scope_mismatch"
    assert result.json()["state"]["evidence"] == []


@pytest.mark.parametrize("operation", ["poll", "help", "resume"])
def test_stale_observation_revalidates_before_any_cue(api, operation):
    session = bind(api, started(api)).json()
    session = send(api, session, {"type": "more_help"}).json()
    if operation == "resume":
        session = send(api, session, {"type": "pause"}).json()
    api[1].revision = "r2"
    if operation == "poll":
        result = api[0].get(f"/api/v1/tasks/{session['task_id']}")
    else:
        result = send(api, session, {"type": "resume" if operation == "resume" else "more_help"})
    assert result.status_code == 200
    body = result.json()
    assert body["reason_code"] == "stale_binding"
    assert body["state"]["status"] == "needs_confirmation"
    assert body["version"] == session["version"] + 1
    assert body["cue"] is None


@pytest.mark.parametrize("raw,reason", [
    ("{}", "model_no_plan"),
    ('{"status":"abstain","reason_code":"safety_concern"}', "model_abstained"),
])
def test_model_no_plan_never_creates_a_session(api, raw, reason):
    api[2].raw = raw
    result = create(api)
    assert result.status_code == 200
    assert result.json() == {"decision": "confirm", "reason_code": reason, "session": None}
    assert not api[1].sessions


@pytest.mark.parametrize("transcript", ["I refuse", "unsafe exposed live wires", "한국어 요청"])
def test_independent_veto_calls_no_provider_and_creates_no_session(api, transcript):
    result = create(api, transcript=transcript)
    assert result.status_code == 200
    assert result.json()["session"] is None
    assert api[2].calls == 0
    assert not api[1].sessions


@pytest.mark.parametrize("failure", ["invalid_json", "timeout", "api_failure"])
def test_provider_errors_are_sanitized_with_no_session_or_fallback(api, failure):
    if failure == "invalid_json":
        api[2].raw = "not json"
    elif failure == "timeout":
        api[2].error = PlanningError("provider_timeout")
    else:
        api[2].error = RuntimeError("synthetic-private-provider-detail")
    result = create(api)
    assert result.status_code == 502
    assert "synthetic-private" not in result.text
    assert not api[1].sessions and api[1].pending == 0


@pytest.mark.parametrize("field", ["state", "plan", "semantic_review", "observations", "receipts"])
def test_clients_cannot_supply_state_plans_or_trusted_context(api, field):
    assert create(api, **{field: {}}).status_code == 422
    assert api[2].calls == 0


def test_default_adapter_is_unobserved_and_never_attests_a_claim(api, monkeypatch):
    monkeypatch.setattr(app.state, "task_sessions", task_api.TaskSessions())
    session = started(api)
    result = bind(api, session)
    assert not result.json()["accepted"]
    assert result.json()["state"]["status"] == "needs_confirmation"
    assert result.json()["cue"] is None


def test_missing_task_restart_and_session_isolation(api):
    first, second = started(api), started(api)
    send(api, first, {"type": "stop"})
    assert api[1].get(second["task_id"]).result.state.status == "active"
    assert api[0].get("/api/v1/tasks/unknown").status_code == 404
    assert api[0].post("/api/v1/tasks/unknown/events", json={
        "event_id": "x", "expected_version": 1, "event": {"type": "stop"},
    }).status_code == 404
    api[1].sessions.clear()  # A new process/worker has no session memory.
    assert api[0].get(f"/api/v1/tasks/{second['task_id']}").status_code == 404


def test_capacity_is_bounded_but_stop_remains_available(api):
    api[1].max_sessions = 1
    session = started(api)
    assert create(api).status_code == 503
    assert api[2].calls == 1
    api[1].max_events = 1
    session = send(api, session, {"type": "more_help"}).json()
    assert send(api, session, {"type": "pause"}).json()["detail"] == "event_capacity_reached"
    assert send(api, session, {"type": "stop"}).json()["state"]["status"] == "stopped"


def test_concurrent_same_version_events_only_apply_once(api):
    session = started(api)

    async def race():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await asyncio.gather(*[
                client.post(f"/api/v1/tasks/{session['task_id']}/events", json={
                    "event_id": f"race-{i}", "expected_version": 1, "event": {"type": "more_help"},
                }) for i in range(2)
            ])

    results = asyncio.run(race())
    assert sorted(result.status_code for result in results) == [200, 409]
    stored = api[1].get(session["task_id"])
    assert stored.version == 2
    assert stored.result.state.steps[0].help_level == 1


def test_openapi_exposes_versioned_contract(api):
    document = api[0].get("/openapi.json").json()
    assert "/api/plan" in document["paths"]
    assert {"get"} <= document["paths"]["/api/v1/tasks/{task_id}"].keys()
    assert document["components"]["schemas"]["TaskCreateRequest"]["additionalProperties"] is False


def test_live_provider_requires_explicit_mode(monkeypatch):
    monkeypatch.setenv("PLANNER_MODE", "demo")
    with pytest.raises(PlanningError, match="live_mode_required"):
        task_api.provider()


def test_demo_mode_fails_closed_over_http_and_independent_veto_still_works(api, monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(app.state, "task_sessions", task_api.TaskSessions())
    monkeypatch.setenv("PLANNER_MODE", "demo")
    result = create(api)
    assert result.status_code == 502
    assert result.json()["detail"] == "live_mode_required"
    assert create(api, transcript="I refuse").json()["decision"] == "stop"
    assert app.state.task_sessions.sessions == {}
