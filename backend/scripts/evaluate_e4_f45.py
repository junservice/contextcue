"""F4/F5 contract and cue replay; opt-in live check, with old evidence read-only."""

import argparse
import asyncio
import hashlib
import json
import logging
import os
from collections import Counter
from datetime import UTC, datetime

from dotenv import load_dotenv

from app.tasking.planning import NebiusPlanProvider, PlanningRequest
from scripts.evaluate_e4 import ROOT, request_for, save
from scripts.evaluate_e4_f1 import ReplayProvider, read
from scripts.evaluate_e4_f23 import TracedProvider, controls, datasets, evaluate

OUT = ROOT / "evaluations/e4_f4_f5_v4"
HISTORY = (
    "e4/live-results.json",
    "e4_f1_v2/live-results.json",
    "e4_f2_f3_v3/before-live.json",
    "e4_f2_f3_v3/after-live.json",
)
# Fixed independent cue rubric: name each referenced concept and explicit qualifier.
LABELS = {
    "door_open_button": "열림 버튼",
    "automatic_door_opening": "자동문 출입구",
    "elevator_call_button": "엘리베이터 호출 버튼",
    "garden_gate_opening": "정원 출입구",
    "corridor": "복도",
    "bag": "가방",
    "water_bottle": "물병",
    "book": "책",
    "box": "상자",
    "pen": "펜",
    "pouch": "파우치",
    "basket": "바구니",
    "towel": "수건",
    "mug": "머그잔",
    "paper": "종이",
}
QUALIFIERS = {
    "red": "빨간",
    "blue": "파란",
    "green": "초록색",
    "left": "왼쪽",
    "right": "오른쪽",
    "front": "앞쪽",
    "back": "뒤쪽",
}


def classification(row):
    code = row.get("reason_code") or row.get("decision", {}).get("reason_code")
    if row["accepted"]:
        return "accepted_plan"
    if not row["provider_called"]:
        return "independent_review_hold"
    return {"model_abstained": "declared_abstention", "model_no_plan": "unspecified_no_plan"}.get(
        code, "error"
    )


def cue_scores(rows):
    counts = Counter()
    for row in rows:
        if not row.get("canonical_plan"):
            continue
        plan = row["canonical_plan"]
        targets = {t["target_key"]: t for t in plan["targets"]}
        steps = {s["step_id"]: s for s in plan["steps"]}
        for probe in row.get("policy_probes", []):
            cue = probe.get("cue")
            if probe["policy"]["decision"] != "allow":
                counts["denied_probes"] += 1
                counts["cue_despite_deny"] += cue is not None
            if cue is None or probe["policy"]["decision"] != "allow":
                continue
            counts["allowed_cues"] += 1
            names, attrs = [], []
            for key in steps[probe["step_id"]]["target_keys"]:
                t = targets[key]
                names.append(LABELS.get(t["concept"], "UNSUPPORTED_LABEL"))
                attrs += [
                    QUALIFIERS.get(v, "UNSUPPORTED_QUALIFIER")
                    for v in t.get("qualifiers", {}).values()
                ]
            complete = all(name in cue["text"] for name in names + attrs)
            counts["all_target_names_and_qualifiers_present"] += complete
            counts["generic_target_text"] += "대상" in cue["text"]
            if attrs:
                counts["qualified_cues"] += 1
                counts["qualifiers_preserved"] += all(a in cue["text"] for a in attrs)
    return dict(counts)


async def mock_rows(original, cases):
    lookup = {c["case_id"]: c for c in cases}
    replay = []
    for rel in HISTORY:
        for old in read(ROOT / "evaluations" / rel)["records"]:
            if old.get("output") is None:
                continue
            row = await evaluate(
                PlanningRequest.model_validate(old["input"]),
                lookup[old["case_id"]],
                old["sample"],
                ReplayProvider(old["output"]),
            )
            row.update(source=rel, response_class=classification(row))
            replay.append(row)
    request, case, valid = next(controls(original))
    control_rows = []
    payloads = [
        ("valid_plan", valid, "accepted_plan"),
        ("legacy_empty", "{}", "unspecified_no_plan"),
        ("malformed_json", "{", "error"),
        ("empty_response", "", "error"),
        ("unknown_reason", '{"status":"abstain","reason_code":"invented"}', "error"),
        ("missing_reason", '{"status":"abstain"}', "error"),
        (
            "extra_free_text",
            '{"status":"abstain","reason_code":"safety_concern","text":"untrusted"}',
            "error",
        ),
        (
            "mixed_plan",
            json.dumps(json.loads(valid) | {"status": "abstain", "reason_code": "safety_concern"}),
            "error",
        ),
        (
            "duplicate_status",
            '{"status":"plan","status":"abstain","reason_code":"safety_concern"}',
            "error",
        ),
    ]
    payloads += [
        (reason, json.dumps({"status": "abstain", "reason_code": reason}), "declared_abstention")
        for reason in (
            "needs_clarification",
            "unsupported_request",
            "safety_concern",
            "user_refusal",
        )
    ]
    for name, raw, expected in payloads:
        row = await evaluate(request, case | {"case_id": name}, 1, ReplayProvider(raw))
        row.update(response_class=classification(row), expected_response_class=expected)
        control_rows.append(row)
    return replay, control_rows


async def run(args):
    output = OUT / f"{args.arm}-{'live' if args.live else 'mock'}.json"
    if output.exists():
        raise SystemExit("Refusing to overwrite existing evidence")
    original, cases = datasets()
    sources = [
        ROOT / "app/tasking" / name
        for name in (
            "planning.py",
            "prompting.py",
            "normalization.py",
            "semantics.py",
            "request_review.py",
            "verification.py",
            "engine.py",
            "models.py",
            "service.py",
        )
    ]
    sources += [ROOT / "scripts/evaluate_e4_f45.py", OUT / "README.md"]
    result = {
        "evaluation_id": "e4-f4-f5-v4",
        "arm": args.arm,
        "mode": "LIVE_NEBIUS_AND_DETERMINISTIC_REVIEW" if args.live else "MOCK_REPLAY",
        "started_at_utc": datetime.now(UTC).isoformat(),
        "run_status": "running",
        "source_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources
        },
        "records": [],
    }
    if args.live:
        load_dotenv(ROOT / ".env")
        if os.getenv("PLANNER_MODE", "").lower().strip() != "live":
            raise SystemExit("PLANNER_MODE=live required")
        save(output, result)
        async with NebiusPlanProvider.from_environment() as real:
            result.update(
                model_id=real.model_id,
                endpoint_host=real._client.base_url.host,
                max_tokens=4096,
                timeout_seconds=60,
                retries=0,
                temperature="provider_default",
                seed="unset",
            )
            provider = TracedProvider(real)
            for case in cases:
                row = await evaluate(request_for(original, case, 1), case, 1, provider)
                row["response_class"] = classification(row)
                result["records"].append(row)
                save(output, result)
                print(json.dumps({k: row[k] for k in ("case_id", "response_class")}), flush=True)
    else:
        result["records"], result["controls"] = await mock_rows(original, cases)
    result.update(run_status="completed", finished_at_utc=datetime.now(UTC).isoformat())
    result["summary"] = {
        "pipeline_attempts": len(result["records"]),
        "api_calls": sum(r["provider_called"] for r in result["records"]) if args.live else 0,
        "classes": dict(Counter(r["response_class"] for r in result["records"])),
        "normal_admission": {
            "accepted": sum(
                r["accepted"] for r in result["records"] if r["expected_kind"] == "normal"
            ),
            "total": sum(r["expected_kind"] == "normal" for r in result["records"]),
        },
        "required_holds": {
            "blocked": sum(
                not r["accepted"] for r in result["records"] if r["expected_kind"] == "abstain"
            ),
            "total": sum(r["expected_kind"] == "abstain" for r in result["records"]),
        },
        "cue_rubric": cue_scores(result["records"]),
        "control_classifications_correct": sum(
            r["response_class"] == r["expected_response_class"] for r in result.get("controls", [])
        ),
        "controls_total": len(result.get("controls", [])),
        "initial_false_completion": sum(
            r.get("initial_completed", False) for r in result["records"]
        ),
        "human_rating": "not_run",
        "ui_exposure": "not_run",
    }
    save(output, result)
    print(json.dumps(result["summary"], indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, choices=("before", "after"))
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--mock", action="store_true")
    group.add_argument("--live", action="store_true")
    args = parser.parse_args()
    for name in ("httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
