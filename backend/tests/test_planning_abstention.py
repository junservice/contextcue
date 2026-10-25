"""F4: untrusted abstention is a no-task result, distinct from malformed output."""

import asyncio
import json
from dataclasses import FrozenInstanceError

import pytest

from app.tasking import planning
from app.tasking.planning import (
    PlanningAbstained,
    PlanningError,
    generate_plan,
    generate_reviewed_plan,
)
from app.tasking.request_review import ControlledRequestReviewer
from scripts.evaluate_e4_f1 import ReplayProvider
from scripts.evaluate_e4_f23 import controls, datasets


@pytest.fixture
def ready_request():
    original, _ = datasets()
    return next(controls(original))[0]


@pytest.mark.parametrize(
    "reason", ["needs_clarification", "unsupported_request", "safety_concern", "user_refusal"]
)
def test_declared_reason_is_diagnostic_only_and_never_starts_task(
    ready_request, reason, monkeypatch
):
    monkeypatch.setattr(
        planning, "start_task", lambda *a, **k: pytest.fail("no task on abstention")
    )
    raw = json.dumps({"status": "abstain", "reason_code": reason})
    provider = ReplayProvider(raw)
    result = asyncio.run(generate_reviewed_plan(ready_request, provider))
    assert result.review.disposition == "ready"  # Model cannot rewrite trusted request review.
    assert result.verification.decision == "confirm"
    assert result.verification.reason_code == "model_abstained"
    assert result.proposal is None
    abstention = result.abstention
    assert abstention.kind == "declared" and abstention.declared_reason == reason
    assert abstention.task_id == ready_request.task_id
    assert abstention.plan_id == ready_request.plan_id
    assert abstention.request_fingerprint == result.review.request_fingerprint
    assert abstention.mode == "MOCK_PROVIDER" and abstention.model_id == provider.model_id
    assert abstention.latency_ms >= 0
    with pytest.raises(FrozenInstanceError):
        abstention.kind = "approved"


def test_legacy_empty_object_is_unspecified_not_an_inferred_safety_refusal(ready_request):
    result = asyncio.run(generate_reviewed_plan(ready_request, ReplayProvider(" \n {} \t")))
    assert result.verification.reason_code == "model_no_plan"
    assert result.verification.decision == "confirm" and result.proposal is None
    assert result.abstention.kind == "legacy_empty_object"
    assert result.abstention.declared_reason is None


@pytest.mark.parametrize(
    "raw,code",
    [
        ("{}", "model_no_plan"),
        ('{"status":"abstain","reason_code":"safety_concern"}', "model_abstained"),
    ],
)
def test_low_level_no_plan_remains_compatible_with_fail_closed_error_handlers(
    ready_request, raw, code
):
    review = ControlledRequestReviewer().review(ready_request)
    with pytest.raises(PlanningAbstained) as caught:
        asyncio.run(generate_plan(ready_request, ReplayProvider(raw), semantic_review=review))
    assert isinstance(caught.value, PlanningError)
    assert str(caught.value) == code
    assert "safety_concern" not in repr(caught.value)


@pytest.mark.parametrize(
    "raw",
    [
        "{",
        "[]",
        "null",
        '{"status":"abstain"}',
        '{"status":"abstain","reason_code":"invented"}',
        '{"status":"abstain","reason_code":null}',
        '{"status":"abstain","reason_code":"user_refusal","text":"private injection"}',
        '{"status":"abstain","reason_code":"user_refusal","plan_id":"x"}',
        '{"status":"abstain","status":"abstain","reason_code":"user_refusal"}',
        '{"status":"abstain","reason_code":NaN}',
    ],
)
def test_invalid_declarations_are_errors_and_not_typed_abstentions(ready_request, raw):
    with pytest.raises(PlanningError) as caught:
        asyncio.run(generate_reviewed_plan(ready_request, ReplayProvider(raw)))
    assert type(caught.value) is PlanningError
    assert caught.value.reason_code == "invalid_plan_json"
    assert "private" not in str(caught.value)


def test_empty_transport_and_provider_failures_stay_errors(ready_request):
    class Broken(ReplayProvider):
        async def complete(self, messages, schema):
            raise RuntimeError("private provider error")

    for provider, reason in (
        (ReplayProvider(""), "empty_response"),
        (Broken(""), "provider_failed"),
    ):
        with pytest.raises(PlanningError, match=reason) as caught:
            asyncio.run(generate_reviewed_plan(ready_request, provider))
        assert type(caught.value) is PlanningError
        assert "private" not in str(caught.value)


def test_independent_veto_precedes_model_and_has_no_model_abstention(ready_request):
    request = ready_request.model_copy(update={"transcript": "Stop. I refuse."})
    provider = ReplayProvider('{"status":"abstain","reason_code":"user_refusal"}')
    result = asyncio.run(generate_reviewed_plan(request, provider))
    assert result.review.disposition == "refused"
    assert result.verification.decision == "stop"
    assert result.abstention is None and result.proposal is None
    assert provider.messages_hash is None


def test_schema_and_prompt_keep_declared_no_plan_separate_from_taskplan(ready_request):
    review = ControlledRequestReviewer().review(ready_request)
    schema = planning._proposal_schema(review)
    branch = next(s for s in schema["anyOf"] if "status" in s.get("properties", {}))
    assert set(branch["required"]) == {"status", "reason_code"}
    assert branch["additionalProperties"] is False
    assert "plan_id" not in branch["properties"]
    prompt = planning._messages(ready_request, review)[0]["content"]
    assert '"status":"abstain"' in prompt and "untrusted declaration" in prompt
