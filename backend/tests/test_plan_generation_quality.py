"""F2/F3 generation/normalization regressions; synthetic providers only."""

import asyncio
import json
from dataclasses import replace

import pytest

from app.tasking.models import ObservedObject, TargetBinding, TaskPlan
from app.tasking.normalization import normalize_proposal
from app.tasking.planning import (
    _messages,
    _proposal_schema,
    generate_reviewed_plan,
    start_planned_task,
)
from app.tasking.request_review import ControlledRequestReviewer
from app.tasking.verification import VerificationContext, verify_step
from scripts.evaluate_e4_f1 import ReplayProvider
from scripts.evaluate_e4_f23 import controls, datasets, evaluate


def control_cases():
    original, _ = datasets()
    return list(controls(original))


@pytest.mark.parametrize(
    "planning_request,case,raw",
    control_cases(),
    ids=lambda value: value.get("case_id") if isinstance(value, dict) else None,
)
def test_fixed_valid_aliases_and_unsafe_mutations(planning_request, case, raw):
    row = asyncio.run(evaluate(planning_request, case, 1, ReplayProvider(raw)))
    assert row["accepted"] == (case["control_kind"] == "valid")
    if row["accepted"]:
        assert row["mechanical"]["score"] == 2
        assert row["initial_completed"] is False
        assert row["initial_evidence_count"] == 0
        assert len(row["canonical_plan"]["steps"]) == len(json.loads(raw)["steps"])


def test_review_specific_schema_excludes_extra_effects_and_pairs_ordered_refs():
    request, _, _ = control_cases()[0]
    review = ControlledRequestReviewer().review(request)
    schema = _proposal_schema(review)
    root = schema["anyOf"][0]
    assert root["properties"]["steps"]["minItems"] == 4
    assert root["properties"]["steps"]["maxItems"] == 4
    assert root["properties"]["targets"]["minItems"] == 2
    declared = {
        t["properties"]["target_key"]["enum"][0] for t in schema["$defs"]["TargetRef"]["oneOf"]
    }
    assert declared == {"item", "container"}
    signatures = []
    for variant in schema["$defs"]["TaskStep"]["oneOf"]:
        props = variant["properties"]
        keys = props["target_keys"]["enum"][0]
        completion = props["completion_goal"]["properties"]
        assert completion["target_keys"]["enum"] == [keys]
        assert set(keys) <= declared
        signatures.append(
            (props["action"]["enum"][0], completion["outcome"]["enum"][0], tuple(keys))
        )
    assert ("place_inside", "placed_inside", ("item", "container")) in signatures
    assert ("place_inside", "placed_inside", ("container", "item")) not in signatures
    assert not any(a == "press" or o == "state_open" for a, o, _ in signatures)


def test_prompt_passes_independent_contract_not_model_derived_repair():
    request, _, _ = control_cases()[0]
    review = ControlledRequestReviewer().review(request)
    messages = _messages(request, review)
    assert "required_operations" in messages[0]["content"]
    assert '"concept": "mug"' in messages[0]["content"]
    assert "false/unknown" in messages[0]["content"].casefold()
    assert json.loads(messages[1]["content"])["transcript"] == request.transcript


def test_normalization_is_non_mutating_idempotent_and_leaves_references_and_steps_intact():
    request, _, raw = next(c for c in control_cases() if c[1]["case_id"] == "explicit_color_alias")
    plan = TaskPlan.model_validate_json(raw)
    before = plan.model_dump()
    review = ControlledRequestReviewer().review(request)
    normalized, audit = normalize_proposal(plan, review)
    assert plan.model_dump() == before
    assert normalized.steps == plan.steps
    assert [t.target_key for t in normalized.targets] == [t.target_key for t in plan.targets]
    assert audit[0].original_concept == "blue mug"
    assert audit[0].canonical_concept == "mug"
    again, changes = normalize_proposal(normalized, review)
    assert again == normalized and not changes


def test_canonicalization_does_not_create_observations_bindings_or_resolve_ambiguity():
    request, _, raw = next(c for c in control_cases() if c[1]["case_id"] == "explicit_color_alias")
    snapshot = request.observations.model_copy(deep=True)
    snapshot.objects.append(
        ObservedObject(object_id="second-blue-mug", concept="mug", qualifiers={"color": "blue"})
    )
    request = request.model_copy(update={"observations": snapshot})
    before = snapshot.model_dump()
    result = asyncio.run(generate_reviewed_plan(request, ReplayProvider(raw)))
    context = VerificationContext(
        task_id=request.task_id,
        plan_id=request.plan_id,
        snapshot=snapshot,
        capabilities=request.capabilities,
        semantic_review=result.review,
    )
    start = start_planned_task(result.proposal, context)
    assert start.service.accepted and not start.service.state.target_bindings
    plan = result.proposal.plan
    bindings = {
        "m": TargetBinding(
            target_key="m",
            object_id=snapshot.objects[0].object_id,
            observation_revision=snapshot.revision,
        )
    }
    physical = plan.steps[2]
    assert (
        verify_step(plan, physical.step_id, bindings, context).reason_code
        == "ambiguous_or_missing_target"
    )
    stale = replace(context, snapshot=snapshot.model_copy(update={"revision": "next"}))
    assert verify_step(plan, physical.step_id, bindings, stale).reason_code == "stale_binding"
    assert snapshot.model_dump() == before


def test_previous_evaluation_assets_are_preserved():
    import hashlib

    from scripts.evaluate_e4_f23 import OUT, ROOT, read

    for path, digest in read(OUT / "preserved-sha256.json").items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
