"""Frozen F2/F3 before/after measurement; old datasets/results are read-only."""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import subprocess
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from dotenv import load_dotenv

from app.tasking.models import TaskPlan
from app.tasking.planning import (
    NebiusPlanProvider,
    PlanningError,
    generate_reviewed_plan,
    start_planned_task,
)
from app.tasking.request_review import ControlledRequestReviewer
from app.tasking.verification import VerificationContext
from scripts.evaluate_e4 import ROOT, RecordingProvider, request_for, save
from scripts.evaluate_e4_f1 import (
    ReplayProvider,
    mechanical,
    probes,
    read,
    serialize_review,
    summarize,
)
from scripts.evaluate_e4_f1 import datasets as v2_datasets

OUT = ROOT / "evaluations/e4_f2_f3_v3"


def datasets():
    original, cases = v2_datasets()
    cases = [c | {"cohort": "regression"} for c in cases]
    cases += [c | {"cohort": "new_holdout"} for c in read(OUT / "holdout.json")["cases"]]
    return original, cases


class TracedProvider(RecordingProvider):
    def reset(self):
        super().reset()
        self.schema_hash = None

    async def complete(self, messages, schema):
        self.schema_hash = hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()
        return await super().complete(messages, schema)


async def evaluate(request, case, sample, provider):
    provider.reset()
    review = ControlledRequestReviewer().review(request)
    row = {
        "case_id": case["case_id"],
        "sample": sample,
        "cohort": case["cohort"],
        "expected_kind": case["expected_kind"],
        "input": request.model_dump(mode="json"),
        "input_source": "DEMO_SCENE/synthetic_observation",
        "review": serialize_review(review),
        "accepted": False,
        "service_created": False,
        "human_review": "not_run",
    }
    started = perf_counter()
    canonical = None
    try:
        result = await generate_reviewed_plan(request, provider)
        row["decision"] = asdict(result.verification)
        if result.proposal:
            proposal = result.proposal
            canonical = proposal.plan
            row["canonical_plan"] = canonical.model_dump(mode="json")
            row["normalizations"] = [
                asdict(change) for change in getattr(proposal, "normalizations", ())
            ]
            context = VerificationContext(
                task_id=request.task_id,
                plan_id=request.plan_id,
                snapshot=request.observations,
                capabilities=request.capabilities,
                semantic_review=result.review,
            )
            start = start_planned_task(proposal, context)
            row["service_created"] = start.service is not None
            row["accepted"] = start.service is not None and start.service.accepted
            if start.service:
                state = start.service.state
                row["initial_completed"] = state.status == "completed" or any(
                    s.status == "completed" for s in state.steps
                )
                row["initial_evidence_count"] = len(state.evidence)
            row["policy_probes"] = probes(
                canonical, request, result.review, case.get("feasible", True)
            )
    except PlanningError as error:
        row["reason_code"] = error.reason_code
    row["pipeline_latency_ms"] = round((perf_counter() - started) * 1000, 1)
    called = provider.messages_hash is not None
    row.update(
        provider_called=called,
        mode=provider.mode if called else "DETERMINISTIC_REVIEW",
        output=provider.raw,
        transport=provider.metadata,
        messages_sha256=provider.messages_hash,
        schema_sha256=getattr(provider, "schema_hash", None),
    )
    raw = None
    if provider.raw:
        try:
            raw = TaskPlan.model_validate_json(provider.raw)
        except ValueError:
            pass
    row["schema_valid"] = raw is not None if called else None
    row["raw_mechanical"] = mechanical(raw, case) if called else None
    row["mechanical"] = mechanical(canonical if row["accepted"] else raw, case) if called else None
    return row


def controls(original):
    case = {
        "case_id": "control",
        "cohort": "mock_controls",
        "expected_kind": "normal",
        "goal": "store_blue_mug_in_box",
        "transcript": "Help me put the blue mug in the box and check it is inside.",
        "objects": [{"concept": "mug", "qualifiers": {"color": "blue"}}, "box"],
        "expected_effects": [
            ["place_inside", "placed_inside", ["mug", "box"]],
            ["observe_state", "items_inside", ["mug", "box"]],
        ],
        "expected_qualifiers": {"mug": {"color": "blue"}},
    }
    request = request_for(original, case, 1)
    base = {
        "plan_id": request.plan_id,
        "goal": request.goal,
        "targets": [
            {"target_key": "m", "concept": "mug", "qualifiers": {"color": "blue"}},
            {"target_key": "b", "concept": "box"},
        ],
        "steps": [
            {
                "step_id": "find-m",
                "action": "locate",
                "target_keys": ["m"],
                "completion_goal": {"outcome": "target_located", "target_keys": ["m"]},
            },
            {
                "step_id": "find-b",
                "action": "locate",
                "target_keys": ["b"],
                "completion_goal": {"outcome": "target_located", "target_keys": ["b"]},
            },
            {
                "step_id": "place",
                "action": "place_inside",
                "target_keys": ["m", "b"],
                "completion_goal": {"outcome": "placed_inside", "target_keys": ["m", "b"]},
            },
            {
                "step_id": "check",
                "action": "observe_state",
                "target_keys": ["m", "b"],
                "completion_goal": {"outcome": "items_inside", "target_keys": ["m", "b"]},
            },
        ],
    }
    names = (
        "canonical",
        "explicit_color_alias",
        "case_alias",
        "wrong_item",
        "wrong_color",
        "conflicting_color",
        "missing_color",
        "vague_alias",
        "alias_collision",
        "extra_target",
        "extra_action",
        "missing_outcome",
        "reversed_roles",
        "different_completion_roles",
        "missing_declaration",
        "duplicate_key",
        "fake_id",
        "policy_injection",
        "wrong_order",
    )
    for name in names:
        body = json.loads(json.dumps(base))
        target = body["targets"][0]
        if name == "explicit_color_alias":
            target.update(concept="blue mug", qualifiers={})
        elif name == "case_alias":
            target["concept"] = "MUG"
        elif name == "wrong_item":
            target["concept"] = "book"
        elif name == "wrong_color":
            target["qualifiers"] = {"color": "red"}
        elif name == "conflicting_color":
            target.update(concept="blue mug", qualifiers={"color": "red"})
        elif name == "missing_color":
            target["qualifiers"] = {}
        elif name == "vague_alias":
            target["concept"] = "cup"
        elif name == "alias_collision":
            body["targets"].append({"target_key": "other", "concept": "blue mug"})
        elif name == "extra_target":
            body["targets"].append({"target_key": "extra", "concept": "scissors"})
        elif name == "extra_action":
            body["steps"].append(
                {
                    "step_id": "bad",
                    "action": "press",
                    "target_keys": ["b"],
                    "completion_goal": {"outcome": "pressed", "target_keys": ["b"]},
                }
            )
        elif name == "missing_outcome":
            body["steps"].pop()
        elif name == "reversed_roles":
            body["steps"][2]["target_keys"].reverse()
            body["steps"][2]["completion_goal"]["target_keys"].reverse()
        elif name == "different_completion_roles":
            body["steps"][2]["completion_goal"]["target_keys"].reverse()
        elif name == "missing_declaration":
            body["targets"].pop(0)
        elif name == "duplicate_key":
            body["targets"][1]["target_key"] = "m"
        elif name == "fake_id":
            target["object_id"] = "unobserved"
        elif name == "policy_injection":
            body["steps"][2]["completion_goal"]["allowed_sources"] = ["model_assessment"]
        elif name == "wrong_order":
            body["steps"][2], body["steps"][3] = body["steps"][3], body["steps"][2]
        yield (
            request,
            case | {"case_id": name, "control_kind": "valid" if name in names[:3] else "invalid"},
            json.dumps(body),
        )
    bottle_case = {
        "case_id": "bottle-space",
        "cohort": "mock_controls",
        "expected_kind": "normal",
        "goal": "store_water_bottle_in_box",
        "transcript": "Help me put the water bottle in the box and check it is inside.",
        "objects": ["water_bottle", "box"],
        "expected_effects": [
            ["place_inside", "placed_inside", ["water_bottle", "box"]],
            ["observe_state", "items_inside", ["water_bottle", "box"]],
        ],
    }
    request = request_for(original, bottle_case, 1)
    for alias in ("water bottle", "water-bottle"):
        body = json.loads(json.dumps(base))
        body.update(plan_id=request.plan_id, goal=request.goal)
        body["targets"][0] = {"target_key": "m", "concept": alias}
        yield request, bottle_case | {"case_id": alias, "control_kind": "valid"}, json.dumps(body)


async def run_mock(original, cases):
    lookup = {c["case_id"]: c for c in cases}
    records = []
    from app.tasking.planning import PlanningRequest

    for source in ("e4", "e4_f1_v2"):
        for old in read(ROOT / "evaluations" / source / "live-results.json")["records"]:
            if old.get("output") is None:
                continue
            row = await evaluate(
                PlanningRequest.model_validate(old["input"]),
                lookup[old["case_id"]],
                old["sample"],
                ReplayProvider(old["output"]),
            )
            row.update(evaluation_mode="MOCK_REPLAY", source=source)
            records.append(row)
    control_rows = []
    for request, case, raw in controls(original):
        row = await evaluate(request, case, 1, ReplayProvider(raw))
        row["control_kind"] = case["control_kind"]
        control_rows.append(row)
    return records, control_rows


async def run(args):
    original, cases = datasets()
    mode = "mock" if args.mock else "live"
    output = OUT / f"{args.arm}-{mode}.json"
    if output.exists():
        raise SystemExit("Refusing to overwrite an existing evaluation")
    paths = [
        ROOT / "app/tasking" / name
        for name in (
            "planning.py",
            "semantics.py",
            "request_review.py",
            "verification.py",
            "engine.py",
            "prompting.py",
            "models.py",
        )
    ]
    normalizer = ROOT / "app/tasking/normalization.py"
    if normalizer.exists():
        paths.append(normalizer)
    paths += [Path(__file__), OUT / "holdout.json", OUT / "README.md"]
    metadata = {
        "evaluation_id": "e4-f2-f3-v3",
        "arm": args.arm,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "git_sha": (
            await asyncio.to_thread(
                subprocess.check_output, ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            )
        ).strip(),
        "source_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths
        },
        "samples_per_case": 2,
        "max_tokens": 4096,
        "timeout_seconds": 60,
        "retries": 0,
        "temperature": "provider_default",
        "seed": "unset",
    }
    if args.mock:
        metadata["records"], metadata["controls"] = await run_mock(original, cases)
        metadata.update(mode="MOCK_REPLAY", run_status="completed", api_calls=0)
    else:
        load_dotenv(ROOT / ".env")
        if os.getenv("PLANNER_MODE", "").lower().strip() != "live":
            raise SystemExit("PLANNER_MODE=live required")
        metadata.update(
            records=[], mode="MIXED_LIVE_AND_DETERMINISTIC_REVIEW", run_status="running"
        )
        save(output, metadata)
        try:
            async with NebiusPlanProvider.from_environment() as real:
                provider = TracedProvider(real)
                metadata.update(model_id=real.model_id, endpoint_host=real._client.base_url.host)
                for sample in (1, 2):
                    for case in cases:
                        row = await evaluate(
                            request_for(original, case, sample), case, sample, provider
                        )
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
            metadata.update(run_status="unavailable", reason_code=error.reason_code)
        except Exception:  # noqa: BLE001 - no provider raw error/secret output.
            metadata.update(run_status="interrupted", reason_code="evaluation_failed")
    metadata["finished_at_utc"] = datetime.now(UTC).isoformat()
    metadata["summary"] = summarize(metadata["records"])
    metadata["summary"]["errors"] = dict(
        Counter(r["reason_code"] for r in metadata["records"] if "reason_code" in r)
    )
    save(output, metadata)
    print(json.dumps(metadata["summary"], indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("before", "after"), required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--live", action="store_true")
    group.add_argument("--mock", action="store_true")
    args = parser.parse_args()
    for name in ("httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
