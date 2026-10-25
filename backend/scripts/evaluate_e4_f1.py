"""Versioned F1 production-adapter evaluation. Never overwrites historical E4 data."""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import subprocess
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from dotenv import load_dotenv

from app.tasking.engine import create_task_state
from app.tasking.models import FeasibilityAssessment, TargetBinding, TaskPlan
from app.tasking.planning import (
    NebiusPlanProvider,
    PlanningError,
    PlanningRequest,
    generate_reviewed_plan,
    start_planned_task,
)
from app.tasking.prompting import select_cue
from app.tasking.request_review import ADAPTER_VERSION, ControlledRequestReviewer
from app.tasking.verification import ACTION_POLICIES, VerificationContext, verify_step
from scripts.evaluate_e4 import ROOT, RecordingProvider, request_for, save, score
from scripts.summarize_e4 import percentile, ratio

OUT = ROOT / "evaluations/e4_f1_v2"
OLD = ROOT / "evaluations/e4"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def datasets():
    original = read(OLD / "cases.json")
    cases = []
    for case in original["cases"]:
        expected = original["expectations"][case["expectation"]]
        cases.append(
            case
            | {
                "cohort": "regression",
                "expected": expected,
                "expected_kind": "abstain" if expected["disposition"] == "abstain" else "normal",
            }
        )
    cases += [case | {"cohort": "new_holdout"} for case in read(OUT / "holdout.json")["cases"]]
    return original, cases


def serialize_review(review):
    return {
        "review_id": review.review_id,
        "disposition": review.disposition,
        "request_fingerprint": review.request_fingerprint,
        "intent": review.intent.model_dump(mode="json") if review.intent else None,
    }


def mechanical(plan, case):
    if "expected" in case:
        return score(plan, case["expected"])
    if case["expected_kind"] == "abstain":
        return {"score": 0, "issues": ["abstention_required"]} if plan else None
    if plan is None:
        return {"score": 0, "issues": ["no_valid_plan"]}
    concepts = {t.target_key: t.concept for t in plan.targets}
    effects = [
        [s.action, s.completion_goal.outcome, [concepts[k] for k in s.target_keys]]
        for s in plan.steps
        if s.action != "locate"
    ]
    issues = []
    if effects != case["expected_effects"]:
        issues.append("wrong_missing_or_extra_effects")
    expected_concepts = {c for op in case["expected_effects"] for c in op[2]}
    expected_concepts |= set(case.get("expected_qualifiers", {}))
    if set(concepts.values()) != expected_concepts:
        issues.append("target_coverage")
    for concept, qualifiers in case.get("expected_qualifiers", {}).items():
        if not any(t.concept == concept and t.qualifiers == qualifiers for t in plan.targets):
            issues.append("wrong_qualifier")
    if plan.steps[0].action != "locate":
        issues.append("no_initial_locate")
    return {"score": 2 if not issues else 1, "issues": issues}


def probes(plan, request, review, feasible=True):
    unique, attempted = {}, {}
    for target in plan.targets:
        matches = [
            o
            for o in request.observations.objects
            if o.concept == target.concept
            and all(o.qualifiers.get(k) == v for k, v in target.qualifiers.items())
        ]
        if matches:
            attempted[target.target_key] = TargetBinding(
                target_key=target.target_key,
                object_id=matches[0].object_id,
                observation_revision=request.observations.revision,
            )
        if len(matches) == 1:
            unique[target.target_key] = attempted[target.target_key]
    context = VerificationContext(
        task_id=request.task_id,
        plan_id=request.plan_id,
        snapshot=request.observations,
        capabilities=request.capabilities,
        semantic_review=review,
    )
    assessments = {
        step.step_id: FeasibilityAssessment(
            step_id=step.step_id,
            observation_revision=request.observations.revision,
            object_ids=tuple(unique[k].object_id for k in step.target_keys if k in unique),
            feasible=feasible,
        )
        for step in plan.steps
        if ACTION_POLICIES[step.action].requires_physical_context
    }
    context = replace(context, feasibility=assessments)
    rows = []
    for index, step in enumerate(plan.steps):
        physical = ACTION_POLICIES[step.action].requires_physical_context
        variants = [("unique_bound", unique, context), ("unbound", {}, context)]
        if physical:
            variants.append(("no_context", unique, replace(context, feasibility={})))
        if unique:
            variants.append(
                (
                    "stale",
                    {
                        k: b.model_copy(update={"observation_revision": "old"})
                        for k, b in unique.items()
                    },
                    context,
                )
            )
        if attempted != unique:
            variants.append(("ambiguous", attempted, context))
        for variant, bindings, ctx in variants:
            policy = verify_step(plan, step.step_id, bindings, ctx)
            state = create_task_state(plan, request.task_id)
            state.current_step_id = step.step_id
            state.target_bindings = bindings
            for i, item in enumerate(state.steps):
                item.status = "completed" if i < index else ("active" if i == index else "pending")
            state.steps[index].help_level = min(3, step.max_help_level)
            cue = select_cue(plan, state, ctx, ("arrow",))
            rows.append(
                {
                    "step_id": step.step_id,
                    "action": step.action,
                    "physical": physical,
                    "variant": variant,
                    "policy": asdict(policy),
                    "cue": cue.model_dump(mode="json") if cue else None,
                }
            )
    return rows


async def evaluate(request, case, sample, provider):
    provider.reset()
    review = ControlledRequestReviewer().review(request)
    record = {
        "case_id": case["case_id"],
        "cohort": case["cohort"],
        "sample": sample,
        "expected_kind": case["expected_kind"],
        "input": request.model_dump(mode="json"),
        "input_source": "DEMO_SCENE/synthetic_observation",
        "review": serialize_review(review),
        "accepted": False,
        "service_created": False,
        "human_review": "not_run",
    }
    started = perf_counter()
    try:
        result = await generate_reviewed_plan(request, provider)
        record["decision"] = asdict(result.verification)
        if result.proposal is not None:
            context = VerificationContext(
                task_id=request.task_id,
                plan_id=request.plan_id,
                snapshot=request.observations,
                capabilities=request.capabilities,
                semantic_review=result.review,
            )
            start = start_planned_task(result.proposal, context)
            record["start_verification"] = asdict(start.verification)
            record["service_created"] = start.service is not None
            record["accepted"] = start.service is not None and start.service.accepted
            if start.service:
                state = start.service.state
                record["initial_completed"] = state.status == "completed" or any(
                    s.status == "completed" for s in state.steps
                )
                record["initial_evidence_count"] = len(state.evidence)
            record["policy_probes"] = probes(
                result.proposal.plan, request, result.review, case.get("feasible", True)
            )
    except PlanningError as error:
        record["reason_code"] = error.reason_code
    record["pipeline_latency_ms"] = round((perf_counter() - started) * 1000, 1)
    called = provider.messages_hash is not None
    record.update(
        provider_called=called,
        mode=provider.mode if called else "DETERMINISTIC_REVIEW",
        output=provider.raw,
        transport=provider.metadata,
        messages_sha256=provider.messages_hash,
    )
    raw_plan = None
    if provider.raw:
        try:
            raw_plan = TaskPlan.model_validate_json(provider.raw)
        except ValueError:
            pass
    record["schema_valid"] = raw_plan is not None if called else None
    record["mechanical"] = mechanical(raw_plan, case) if called else None
    return record


class ReplayProvider:
    mode = "MOCK_PROVIDER"
    model_id = "preserved-output-or-adversarial-mock"

    def __init__(self, raw):
        self.body = raw
        self.reset()

    def reset(self):
        self.raw = None
        self.metadata = {}
        self.messages_hash = None

    async def complete(self, messages, schema):
        self.messages_hash = hashlib.sha256(
            json.dumps(messages, sort_keys=True).encode()
        ).hexdigest()
        self.raw = self.body
        self.metadata = {"finish_reason": "stop"}
        return self.raw


async def run_mock(original, cases):
    lookup = {case["case_id"]: case for case in cases}
    replay = []
    for old in read(OLD / "live-results.json")["records"]:
        case = lookup[old["case_id"]]
        row = await evaluate(
            PlanningRequest.model_validate(old["input"]),
            case,
            old["sample"],
            ReplayProvider(old["output"]),
        )
        row.update(evaluation_mode="MOCK_REPLAY", baseline_score=old["mechanical"]["score"])
        replay.append(row)
    # A new, supported request with independent grammar interpretation and a
    # manually declared valid proposal. Mutations cannot change expected intent.
    request = request_for(
        original,
        {
            "case_id": "mock-control",
            "goal": "store_towel_in_basket",
            "transcript": "Help me put the towel in the basket and check it is inside.",
            "objects": ["towel", "basket"],
        },
        1,
    )
    base = read(ROOT / "tests/fixtures/plans/packing_bag.json")
    base.update(plan_id=request.plan_id, goal=request.goal)
    for target in base["targets"]:
        target["concept"] = "basket" if target["concept"] == "bag" else "towel"
    case = {
        "case_id": "mock-control",
        "cohort": "adversarial_mock",
        "expected_kind": "normal",
        "expected_effects": [
            ["place_inside", "placed_inside", ["towel", "basket"]],
            ["observe_state", "items_inside", ["towel", "basket"]],
        ],
    }
    mutations = []
    for name in (
        "positive_control",
        "wrong_item",
        "reverse_roles",
        "wrong_effect",
        "missing_outcome",
        "fake_id",
        "policy_injection",
        "malformed_json",
        "extra_target",
    ):
        body = json.loads(json.dumps(base))
        if name == "wrong_item":
            body["targets"][1]["concept"] = "book"
        elif name == "reverse_roles":
            body["steps"][2]["target_keys"].reverse()
            body["steps"][2]["completion_goal"]["target_keys"].reverse()
        elif name == "wrong_effect":
            body["steps"][2].update(
                action="traverse",
                target_keys=["bottle"],
                completion_goal={"outcome": "passed_through", "target_keys": ["bottle"]},
            )
        elif name == "missing_outcome":
            body["steps"].pop()
        elif name == "fake_id":
            body["targets"][0]["object_id"] = "not-observed"
        elif name == "policy_injection":
            body["steps"][2]["completion_goal"]["allowed_sources"] = ["model_assessment"]
        elif name == "extra_target":
            body["targets"].append({"target_key": "extra", "concept": "scissors"})
        raw = "{" if name == "malformed_json" else json.dumps(body)
        row = await evaluate(request, case | {"case_id": name}, 1, ReplayProvider(raw))
        row["evaluation_mode"] = "ADVERSARIAL_MOCK"
        mutations.append(row)
    return {
        "mode": "MOCK_REPLAY_AND_ADVERSARIAL",
        "api_calls": 0,
        "records": replay,
        "mutations": mutations,
    }


def summarize(records):
    normal = [r for r in records if r["expected_kind"] == "normal"]
    denied = [r for r in records if r["expected_kind"] == "abstain"]
    called = [r for r in records if r["provider_called"]]
    accepted = [r for r in records if r["accepted"]]
    rows = [p for r in accepted for p in r.get("policy_probes", [])]
    blocked = [p for p in rows if p["policy"]["decision"] != "allow"]
    usage = [r["transport"]["usage"] for r in called if r["transport"].get("usage")]
    result = {
        "pipeline_attempts": len(records),
        "api_attempts": sum(r["mode"] == "LIVE_NEBIUS" for r in called),
        "normal_pipeline_acceptance": ratio(sum(r["accepted"] for r in normal), len(normal)),
        "normal_adapter_coverage": ratio(
            sum(r["review"]["disposition"] == "ready" for r in normal), len(normal)
        ),
        "invalid_request_blocking": ratio(
            sum(not r["accepted"] and not r["service_created"] for r in denied), len(denied)
        ),
        "invalid_request_adapter_veto": ratio(
            sum(r["review"]["disposition"] != "ready" for r in denied), len(denied)
        ),
        "plan_schema_validity": ratio(sum(r["schema_valid"] is True for r in called), len(called)),
        "model_output_admission": ratio(len(accepted), len(called)),
        "mechanical_appropriate_actual_outputs": ratio(
            sum(r["mechanical"] and r["mechanical"]["score"] == 2 for r in called), len(called)
        ),
        "normal_end_to_end_mechanical_pass": ratio(
            sum(
                r["accepted"] and r["mechanical"] and r["mechanical"]["score"] == 2 for r in normal
            ),
            len(normal),
        ),
        "inappropriate_admitted": sum(
            r["accepted"]
            and (
                r["expected_kind"] == "abstain"
                or (r["mechanical"] and r["mechanical"]["score"] != 2)
            )
            for r in records
        ),
        "internal_cue_despite_policy_denial": ratio(
            sum(p["cue"] is not None for p in blocked), len(blocked)
        ),
        "initial_false_completion": ratio(
            sum(r.get("initial_completed", False) for r in accepted), len(accepted)
        ),
        "token_usage": {
            key: sum(u.get(key, 0) for u in usage)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        },
        "usage_coverage": ratio(len(usage), len(called)),
        "per_call_latency_ms": {
            "n": len(called),
            "p50": percentile([r["pipeline_latency_ms"] for r in called], 0.5),
            "p95": percentile([r["pipeline_latency_ms"] for r in called], 0.95),
        },
        "pipeline_latency_ms": {
            "n": len(records),
            "p50": percentile([r["pipeline_latency_ms"] for r in records], 0.5),
            "p95": percentile([r["pipeline_latency_ms"] for r in records], 0.95),
        },
        "human_review": "not_run",
        "actual_ui_exposure": "not_run",
        "cost": "not_available: account tariff unverified",
    }
    for cohort in ("regression", "new_holdout"):
        subset = [r for r in records if r["cohort"] == cohort]
        positives = [r for r in subset if r["expected_kind"] == "normal"]
        negatives = [r for r in subset if r["expected_kind"] == "abstain"]
        result[cohort] = {
            "normal_acceptance": ratio(sum(r["accepted"] for r in positives), len(positives)),
            "invalid_blocking": ratio(sum(not r["accepted"] for r in negatives), len(negatives)),
        }
    return result


async def run(args):
    original, cases = datasets()
    output = OUT / ("mock-results.json" if args.mock else "live-results.json")
    if output.exists():
        raise SystemExit("Refusing to overwrite existing evaluation results")
    metadata = {
        "evaluation_id": "e4-f1-v2-2026-10-22",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "adapter_version": ADAPTER_VERSION,
        "samples_per_case": 2,
        "planned_pipeline_attempts": 60,
        "retries": 0,
        "seed": "unset",
        "temperature": "provider_default_unset",
        "git_sha": (await asyncio.to_thread(
            subprocess.check_output, ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        )).strip(),
        "working_tree": "dirty; pre-existing changes preserved",
        "max_tokens": 4096,
        "timeout_seconds": 60,
        "source_sha256": {
            path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [
                ROOT / "app/tasking/request_review.py",
                ROOT / "app/tasking/planning.py",
                ROOT / "app/tasking/semantics.py",
                ROOT / "app/tasking/service.py",
                ROOT / "app/tasking/prompting.py",
                ROOT / "app/tasking/verification.py",
                Path(__file__),
                OUT / "holdout.json",
                OUT / "README.md",
                OLD / "cases.json",
            ]
        },
    }
    if args.mock:
        metadata.update(await run_mock(original, cases))
    else:
        load_dotenv(ROOT / ".env")
        if os.getenv("PLANNER_MODE", "").strip().lower() != "live":
            raise SystemExit("PLANNER_MODE=live required; no API calls made")
        metadata.update(
            records=[], run_status="running", mode="MIXED_LIVE_AND_DETERMINISTIC_REVIEW"
        )
        save(output, metadata)
        try:
            async with NebiusPlanProvider.from_environment() as real:
                provider = RecordingProvider(real)
                metadata["model_id"] = real.model_id
                metadata["endpoint_host"] = real._client.base_url.host
                for sample in (1, 2):
                    for case in cases:
                        request = request_for(original, case, sample)
                        row = await evaluate(request, case, sample, provider)
                        metadata["records"].append(row)
                        save(output, metadata)
                        print(
                            json.dumps(
                                {k: row[k] for k in ("case_id", "sample", "mode", "accepted")}
                            ),
                            flush=True,
                        )
            metadata["run_status"] = "completed"
        except PlanningError as error:
            metadata.update(run_status="live_not_run", reason_code=error.reason_code)
        except Exception:  # noqa: BLE001 - keep provider exception text/credentials out of logs.
            metadata.update(run_status="interrupted", reason_code="evaluation_runner_failed")
    metadata["finished_at_utc"] = datetime.now(UTC).isoformat()
    metadata["summary"] = summarize(metadata["records"])
    save(output, metadata)
    print(json.dumps(metadata["summary"], indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--mock", action="store_true")
    group.add_argument("--live", action="store_true", help="Authorize up to 60 actual billed calls")
    args = parser.parse_args()
    for name in ("httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
