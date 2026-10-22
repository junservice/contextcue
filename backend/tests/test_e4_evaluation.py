"""Evaluator regression checks; synthetic only, never live provider calls."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.tasking.models import TaskPlan
from scripts.evaluate_e4 import DIRECTORY, ROOT, evaluate_mock, request_for, run, score


def dataset():
    return json.loads((DIRECTORY / "cases.json").read_text(encoding="utf-8"))


def door_plan():
    return TaskPlan.model_validate_json(
        (ROOT / "tests/fixtures/plans/automatic_door.json").read_text(encoding="utf-8")
    )


def test_frozen_dataset_has_disjoint_splits_and_valid_real_contract_inputs():
    data = dataset()
    assert data["samples"] == 2
    assert len(data["cases"]) == len({c["case_id"] for c in data["cases"]}) == 18
    assert sum(c["split"] == "development" for c in data["cases"]) == 12
    assert sum(c["split"] == "holdout" for c in data["cases"]) == 6
    for case in data["cases"]:
        request_for(data, case, 1)
        assert case["expectation"] in data["expectations"]


def test_refusal_does_not_pass_for_provider_error_or_an_executable_plan():
    expected = dataset()["expectations"]["abstain"]
    assert score(None, expected)["score"] == 0
    assert score(door_plan(), expected)["score"] == 0
    assert score(None, expected, intentional_abstention=True)["score"] == 2


def test_valid_structure_cannot_mask_wrong_order_or_unnecessary_physical_action():
    expected = dataset()["expectations"]["door"]
    plan = door_plan()
    assert score(plan, expected)["score"] == 2
    plan.steps[1], plan.steps[2] = plan.steps[2], plan.steps[1]
    assert score(plan, expected)["score"] == 1
    assert score(door_plan(), dataset()["expectations"]["button_only"])["score"] == 0


def test_profile_pairs_differ_only_in_capability_and_scope_identifiers():
    data = dataset()
    capable, blocked, unknown = [request_for(data, c, 1) for c in data["cases"][:3]]
    assert capable.transcript == blocked.transcript == unknown.transcript
    assert capable.observations == blocked.observations == unknown.observations
    assert blocked.capabilities.can_press_button is False
    assert unknown.capabilities.can_extend_arm is None


def test_mock_mutations_reject_each_attack_and_accept_positive_control():
    result = asyncio.run(evaluate_mock(dataset()))
    assert result["api_calls"] == 0
    assert result["valid_control_service_accepted"]
    assert len(result["mutations"]) == 8
    assert all(item["blocked"] for item in result["mutations"])


def test_historical_live_runner_requires_review_adapter_before_new_api_calls(monkeypatch):
    def forbidden():
        pytest.fail("no provider initialization for unreviewed baseline rerun")

    monkeypatch.setattr("scripts.evaluate_e4.NebiusPlanProvider.from_environment", forbidden)
    with pytest.raises(SystemExit, match="semantic_review_required.*no API calls made"):
        asyncio.run(run(SimpleNamespace(live=True, mock=False)))
