"""Integrity/denominator tests for the new evaluation, no network or writes."""

import asyncio
import hashlib

from app.tasking.request_review import ControlledRequestReviewer
from scripts.evaluate_e4 import request_for
from scripts.evaluate_e4_f1 import OUT, ROOT, datasets, read, run_mock, summarize


def test_old_e4_artifacts_are_unchanged_and_new_cohorts_are_disjoint():
    for path, expected in read(OUT / "preserved-e4-sha256.json").items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected
    _, cases = datasets()
    assert len(cases) == len({c["case_id"] for c in cases}) == 30
    assert sum(c["cohort"] == "regression" for c in cases) == 18
    assert sum(c["cohort"] == "new_holdout" for c in cases) == 12
    assert sum(c["expected_kind"] == "normal" for c in cases) == 20


def test_fixed_adapter_coverage_retains_false_holds_in_normal_denominator():
    original, cases = datasets()
    ready = [
        c
        for c in cases
        if ControlledRequestReviewer().review(request_for(original, c, 1)).disposition == "ready"
    ]
    assert len(ready) == 18
    assert all(c["expected_kind"] == "normal" for c in ready)
    # The unsupported benign annotations/injection quotation are intentionally
    # NOT relabelled as negatives to inflate normal coverage.
    held_normal = [c["case_id"] for c in cases if c["expected_kind"] == "normal" and c not in ready]
    assert set(held_normal) == {"d06_door_unreachable", "d12_untrusted_injection"}


def test_full_original_output_replay_and_adversarial_mocks_are_separate_from_live():
    original, cases = datasets()
    result = asyncio.run(run_mock(original, cases))
    assert result["api_calls"] == 0
    assert len(result["records"]) == 36
    assert len(result["mutations"]) == 9
    for row in result["records"]:
        assert row["evaluation_mode"] == "MOCK_REPLAY"
        assert row["mode"] != "LIVE_NEBIUS"
        if row["baseline_score"] == 0:
            assert not row["accepted"]
    controls = [r for r in result["mutations"] if r["case_id"] == "positive_control"]
    bad = [r for r in result["mutations"] if r["case_id"] != "positive_control"]
    assert controls[0]["accepted"]
    assert len(bad) == 8 and not any(r["accepted"] for r in bad)
    assert summarize(result["records"])["api_attempts"] == 0
