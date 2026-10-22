"""Frozen E4 evaluation; opt-in real provider calls or separately labelled mock mutations."""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import subprocess
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import ValidationError

from app.tasking.engine import create_task_state
from app.tasking.models import (
    CapabilityFacts,
    FeasibilityAssessment,
    ObservationSnapshot,
    ObservedObject,
    TargetBinding,
    TaskPlan,
)
from app.tasking.planning import (
    PLANNING_TIMEOUT_SECONDS,
    NebiusPlanProvider,
    PlanningError,
    PlanningRequest,
    _proposal_schema,
    generate_plan,
    start_planned_task,
)
from app.tasking.prompting import select_cue
from app.tasking.verification import ACTION_POLICIES, VerificationContext, verify_step
from scripts.verify_phase4 import synthetic_scenario_review

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "evaluations" / "e4"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    # Incremental single-file replacement; existing run IDs are refused in main().
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def request_for(dataset, case, sample):
    defaults = dataset["defaults"]
    objects = []
    for index, value in enumerate(case["objects"]):
        fields = {"concept": value} if isinstance(value, str) else value
        objects.append(ObservedObject(object_id=f"synthetic-object-{index}", **fields))
    return PlanningRequest(
        task_id=f"e4-{case['case_id']}-{sample}",
        plan_id=f"e4-{case['case_id']}-{sample}",
        goal=case["goal"],
        transcript=case["transcript"],
        capabilities=CapabilityFacts(**(defaults["capabilities"] | case.get("capabilities", {}))),
        observations=ObservationSnapshot(revision=defaults["revision"], objects=objects),
    )


def score(plan, expected, intentional_abstention=False):
    """Mechanical semantic checks, NOT a human quality rating."""
    if expected["disposition"] == "abstain":
        return {"score": 2 if intentional_abstention else 0,
                "issues": [] if intentional_abstention else ["required_abstention_missing"]}
    if plan is None:
        return {"score": 1 if intentional_abstention else 0,
                "issues": ["unnecessary_abstention" if intentional_abstention else "no_valid_plan"]}
    issues = []
    concepts = {target.target_key: target.concept for target in plan.targets}
    signatures = [
        [step.action, step.completion_goal.outcome, [concepts[k] for k in step.target_keys]]
        for step in plan.steps
    ]
    cursor = 0
    for required in expected["required"]:
        found = next((i for i in range(cursor, len(signatures)) if signatures[i] == required), None)
        if found is None:
            issues.append("missing_or_misordered:" + json.dumps(required))
        else:
            cursor = found + 1
    for concept in expected.get("must_locate", []):
        located = next((i for i, s in enumerate(signatures)
                        if s == ["locate", "target_located", [concept]]), None)
        physical = next((i for i, s in enumerate(signatures)
                         if ACTION_POLICIES.get(s[0])
                         and ACTION_POLICIES[s[0]].requires_physical_context), len(signatures))
        if located is None or located >= physical:
            issues.append("missing_prior_locate:" + concept)
    for concept, qualifiers in expected.get("required_qualifiers", {}).items():
        used = [t for t in plan.targets if t.concept == concept]
        if not used or any(any(t.qualifiers.get(k) != v for k, v in qualifiers.items()) for t in used):
            issues.append("missing_required_qualifiers:" + concept)
    if set(concepts.values()) != set(expected["concepts"]):
        issues.append("target_coverage_or_extra_target")
    allowed = expected["required"]
    for signature in signatures:
        if signature[0] == "locate" and all(c in expected["concepts"] for c in signature[2]):
            continue
        if signature not in allowed:
            issues.append("unnecessary_action:" + json.dumps(signature))
    for signature in signatures:
        if signatures.count(signature) > 1:
            issues.append("duplicate_step:" + json.dumps(signature))
    forbidden = any(s[0] in expected.get("forbidden_actions", []) for s in signatures)
    if forbidden:
        issues.append("forbidden_action")
    return {"score": 0 if forbidden else (1 if issues else 2), "issues": sorted(set(issues))}


class RecordingProvider:
    """Observe the existing real transport without replacing it with a fake client."""

    def __init__(self, provider):
        self.provider = provider
        self.mode = provider.mode
        self.model_id = provider.model_id
        self.raw = None
        self.metadata = {}
        self.messages_hash = None
        self.original = provider._client.chat.completions.create
        provider._client.chat.completions.create = self.capture

    def reset(self):
        self.raw = None
        self.metadata = {}
        self.messages_hash = None

    async def capture(self, **kwargs):
        response = await self.original(**kwargs)
        self.metadata = {
            "response_id": response.id,
            "returned_model": response.model,
            "finish_reason": response.choices[0].finish_reason if response.choices else None,
            "usage": response.usage.model_dump(mode="json") if response.usage else None,
        }
        if response.choices:
            self.raw = response.choices[0].message.content
        return response

    async def complete(self, messages, schema):
        self.messages_hash = hashlib.sha256(
            json.dumps(messages, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        raw = await self.provider.complete(messages, schema)
        self.raw = raw
        return raw


def context_for(request):
    return VerificationContext(
        task_id=request.task_id, plan_id=request.plan_id,
        snapshot=request.observations, capabilities=request.capabilities,
    )


def probes(plan, request, feasible):
    """Independent internal checks, never a lifecycle run or real action completion."""
    context = context_for(request)
    bindings = {}
    attempted_bindings = {}
    for target in plan.targets:
        matches = [obj for obj in request.observations.objects
                   if obj.concept == target.concept
                   and all(obj.qualifiers.get(k) == v for k, v in target.qualifiers.items())]
        if matches:
            attempted_bindings[target.target_key] = TargetBinding(
                target_key=target.target_key, object_id=matches[0].object_id,
                observation_revision=request.observations.revision,
            )
        if len(matches) == 1:
            bindings[target.target_key] = attempted_bindings[target.target_key]
    assessments = {
        step.step_id: FeasibilityAssessment(
            step_id=step.step_id, observation_revision=request.observations.revision,
            object_ids=tuple(bindings[k].object_id for k in step.target_keys if k in bindings),
            feasible=feasible,
        )
        for step in plan.steps if ACTION_POLICIES[step.action].requires_physical_context
    }
    context = replace(context, feasibility=assessments)
    results = []
    for index, step in enumerate(plan.steps):
        physical = ACTION_POLICIES[step.action].requires_physical_context
        variants = [("unbound", {}, context), ("unique_bound", bindings, context)]
        if attempted_bindings != bindings:
            variants.append(("ambiguous_candidate", attempted_bindings, context))
        if physical:
            variants.append(("no_physical_context", bindings, replace(context, feasibility={})))
        if bindings:
            stale = {k: b.model_copy(update={"observation_revision": "synthetic-old"})
                     for k, b in bindings.items()}
            variants.append(("stale_binding", stale, context))
        for variant, candidate_bindings, probe_context in variants:
            check = verify_step(plan, step.step_id, candidate_bindings, probe_context)
            # Artificial state to reach a later step without submitting completion Evidence.
            state = create_task_state(plan, request.task_id)
            state.current_step_id = step.step_id
            state.target_bindings = deepcopy(candidate_bindings)
            for i, state_step in enumerate(state.steps):
                state_step.status = "completed" if i < index else ("active" if i == index else "pending")
            state.steps[index].help_level = min(3, step.max_help_level)
            cue = select_cue(plan, state, probe_context, ("visual_highlight", "arrow"))
            results.append({
                "step_id": step.step_id, "action": step.action, "variant": variant,
                "physical": physical, "verification": asdict(check),
                "cue": cue.model_dump(mode="json") if cue else None,
                "blocked_capability_proposal": physical and any(
                    getattr(request.capabilities, k) is False
                    for k in ACTION_POLICIES[step.action].required_capabilities
                ),
            })
    return results


async def evaluate_case(dataset, case, sample, provider):
    provider.reset()
    request = request_for(dataset, case, sample)
    expected = dataset["expectations"][case["expectation"]]
    record = {"case_id": case["case_id"], "split": case["split"], "sample": sample,
              "mode": provider.mode, "input_source": dataset["defaults"]["input_source"],
              "input": request.model_dump(mode="json"), "expected": expected,
              "human_review": "not_run", "status": "failed", "schema_valid": False,
              "planner_admitted": False, "intentional_abstention": False}
    started = perf_counter()
    proposal = None
    try:
        proposal = await generate_plan(request, provider)
        record["planner_admitted"] = True
    except PlanningError as error:
        record["reason_code"] = error.reason_code
    record["latency_ms"] = round((perf_counter() - started) * 1000, 1)
    record["transport"] = provider.metadata
    record["messages_sha256"] = provider.messages_hash
    record["output"] = provider.raw
    plan = None
    if provider.raw is not None:
        try:
            data = json.loads(provider.raw)
            record["intentional_abstention"] = (
                data == {} and provider.metadata.get("finish_reason") == "stop"
            )
            plan = TaskPlan.model_validate(data)
            record["schema_valid"] = True
        except (ValueError, TypeError, ValidationError):
            pass
    record["mechanical"] = score(plan, expected, record["intentional_abstention"])
    if proposal is not None:
        record["plan"] = proposal.plan.model_dump(mode="json")
        record["initial_verification"] = asdict(proposal.initial_verification)
        start = start_planned_task(proposal, context_for(request))
        record["start_verification"] = asdict(start.verification)
        record["service_created"] = start.service is not None
        if start.service is not None:
            state = start.service.state
            record["start"] = {
                "accepted": start.service.accepted, "status": state.status,
                "evidence_count": len(state.evidence), "bindings_count": len(state.target_bindings),
                "completed_steps": sum(s.status == "completed" for s in state.steps),
                "cue": start.service.cue.model_dump(mode="json") if start.service.cue else None,
            }
        record["policy_probes"] = probes(
            proposal.plan, request, case.get("feasible", dataset["defaults"]["feasible"])
        )
    record["status"] = "passed" if record["mechanical"]["score"] == 2 else "failed"
    return record


class MockProvider:
    mode = "MOCK_PROVIDER"
    model_id = "synthetic-mutations"

    def __init__(self, raw):
        self.raw = raw

    async def complete(self, messages, schema):
        return self.raw


async def evaluate_mock(dataset):
    request = request_for(dataset, dataset["cases"][0], 1)
    # Explicit independent intent for this synthetic door control only. The live
    # baseline runner does NOT auto-approve arbitrary cases using expected answers.
    review = synthetic_scenario_review(request, "automatic_door")
    fixture = json.loads((ROOT / "tests/fixtures/plans/automatic_door.json").read_text())
    fixture.update(plan_id=request.plan_id, goal=request.goal)
    mutations = [("malformed_json", "{", "invalid_plan_json")]
    for name, location, field, value, reason in [
        ("unsupported_action", "step", "action", "cut", "unsupported_action"),
        ("unsupported_outcome", "goal", "outcome", "invented", "unsupported_outcome"),
        ("fake_object_id", "target", "object_id", "fake-999", "invalid_plan_json"),
        ("fake_bbox", "target", "bbox", [0, 0, 1, 1], "invalid_plan_json"),
        ("completion_sources", "goal", "allowed_sources", ["model_assessment"], "invalid_plan_json"),
        ("completion_threshold", "goal", "confidence_threshold", 0, "invalid_plan_json"),
        ("invented_evidence", "plan", "evidence", [{"success": True}], "invalid_plan_json"),
    ]:
        body = deepcopy(fixture)
        locations = {"step": body["steps"][-1], "goal": body["steps"][-1]["completion_goal"],
                     "target": body["targets"][0], "plan": body}
        locations[location][field] = value
        mutations.append((name, json.dumps(body), reason))
    results = []
    for name, raw, expected_reason in mutations:
        reason = None
        try:
            await generate_plan(request, MockProvider(raw), semantic_review=review)
        except PlanningError as error:
            reason = error.reason_code
        results.append({"case_id": name, "mode": "MOCK_PROVIDER", "reason_code": reason,
                        "expected_reason": expected_reason, "blocked": reason == expected_reason})
    proposal = await generate_plan(request, MockProvider(json.dumps(fixture)), semantic_review=review)
    start = start_planned_task(proposal, context_for(request), semantic_review=review)
    return {"mode": "MOCK_PROVIDER", "mutations": results,
            "valid_control_service_accepted": start.service is not None and start.service.accepted,
            "api_calls": 0}


async def run(args):
    if args.live:
        # The historical v1 runner has no independent per-request review adapter.
        # Never issue/label unreviewed proposals as fresh LIVE_NEBIUS measurements.
        raise SystemExit(
            "semantic_review_required: historical E4 v1 live runner has no request review "
            "adapter under F1; no API calls made. Preserve the existing baseline."
        )
    dataset = json.loads((DIRECTORY / "cases.json").read_text(encoding="utf-8"))
    output = DIRECTORY / ("mock-results.json" if args.mock else "live-results.json")
    if output.exists():
        raise SystemExit("Output already exists; preserve the previous run before running again.")
    metadata = {
        "evaluation_id": "e4-baseline-v1-2026-10-22", "dataset_version": dataset["version"],
        "started_at_utc": datetime.now(UTC).isoformat(),
        "git_sha": (await asyncio.to_thread(
            subprocess.check_output, ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        )).strip(),
        "working_tree": "dirty; pre-existing Phase 4 changes preserved",
        "sha256": {path.relative_to(ROOT).as_posix(): digest(path) for path in [
            DIRECTORY / "cases.json", DIRECTORY / "README.md", Path(__file__),
            ROOT / "app/tasking/planning.py", ROOT / "app/tasking/verification.py",
            ROOT / "app/tasking/service.py", ROOT / "app/tasking/prompting.py",
        ]},
        "schema_sha256": hashlib.sha256(json.dumps(_proposal_schema(), sort_keys=True).encode()).hexdigest(),
        "samples_per_case": dataset["samples"], "planned_live_calls": 36,
        "retries": 0, "temperature": "provider_default_unset", "seed": "unset",
        "timeout_seconds": PLANNING_TIMEOUT_SECONDS, "max_tokens": 4096,
        "cost": "not_available: account tariff not verified",
    }
    if args.mock:
        metadata["results"] = await evaluate_mock(dataset)
    else:
        load_dotenv(ROOT / ".env")
        if os.getenv("PLANNER_MODE", "").strip().lower() != "live":
            raise SystemExit("PLANNER_MODE=live required; no API call made")
        metadata.update(mode="LIVE_NEBIUS", records=[], run_status="running")
        save(output, metadata)
        try:
            async with NebiusPlanProvider.from_environment() as real:
                recorder = RecordingProvider(real)
                metadata["model_id"] = real.model_id
                metadata["endpoint_host"] = urlsplit(str(real._client.base_url)).hostname
                metadata["response_format"] = "json_schema" if real.model_id in {
                    "nvidia/Nemotron-3_5-Lightning"
                } else "json_object"
                metadata["enable_thinking"] = False if metadata["response_format"] == "json_schema" else None
                # Paired repetitions are distinct requests; no retry or prompt changes.
                for sample in range(1, dataset["samples"] + 1):
                    for case in dataset["cases"]:
                        record = await evaluate_case(dataset, case, sample, recorder)
                        metadata["records"].append(record)
                        save(output, metadata)
                        print(json.dumps({k: record[k] for k in (
                            "case_id", "sample", "status", "latency_ms"
                        )}), flush=True)
            metadata["run_status"] = "completed"
        except PlanningError as error:
            metadata.update(run_status="live_not_run", reason_code=error.reason_code)
        except Exception:  # noqa: BLE001 - never expose provider exception text or credentials.
            metadata.update(run_status="interrupted", reason_code="evaluation_runner_failed")
    metadata["finished_at_utc"] = datetime.now(UTC).isoformat()
    save(output, metadata)
    print(json.dumps({"saved": output.relative_to(ROOT).as_posix(),
                      "records": len(metadata.get("records", []))}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--live", action="store_true", help="Authorize 36 billed real API attempts")
    group.add_argument("--mock", action="store_true", help="No real API calls")
    args = parser.parse_args()
    for name in ("httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
