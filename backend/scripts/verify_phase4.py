"""Opt-in, synthetic Phase 4 checks. Prints metadata only, never prompts/keys/responses.

From backend/: uv run python -m scripts.verify_phase4 --live --samples 2
One smoke request plus two scenarios per sample; SDK retries remain disabled.
"""

import argparse
import asyncio
import json
import logging
import os
from time import perf_counter
from typing import Literal
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, ValidationError

from app.planner import BASE_URL
from app.tasking.models import CapabilityFacts, ObservationSnapshot, ObservedObject
from app.tasking.planning import (
    PLANNING_TIMEOUT_SECONDS,
    NebiusPlanProvider,
    PlanningError,
    PlanningRequest,
    generate_reviewed_plan,
    start_planned_task,
)
from app.tasking.semantics import IntentOperation, IntentTarget, SemanticIntent, review_request
from app.tasking.verification import ACTION_POLICIES, VerificationContext, verify_step


def synthetic_scenario_review(request, name):
    """Manual intent declarations for the two staged smoke scenarios only.

    This is not an interpreter for arbitrary user goals/transcripts or a production
    review adapter. Callers own the independently reviewed synthetic request text.
    """
    if name == "automatic_door":
        targets = (("button", "door_open_button"), ("opening", "automatic_door_opening"))
        operations = (
            ("locate", "target_located", ("button",)),
            ("press", "pressed", ("button",)),
            ("observe_state", "state_open", ("opening",)),
            ("traverse", "passed_through", ("opening",)),
        )
    elif name == "packing_bag":
        targets = (("bag", "bag"), ("bottle", "water_bottle"))
        operations = (
            ("locate", "target_located", ("bag",)),
            ("locate", "target_located", ("bottle",)),
            ("place_inside", "placed_inside", ("bottle", "bag")),
            ("observe_state", "items_inside", ("bottle", "bag")),
        )
    else:
        raise ValueError("unreviewed synthetic scenario")
    return review_request(
        request, review_id="synthetic-smoke-review", disposition="ready",
        intent=SemanticIntent(
            targets=tuple(IntentTarget(role=r, concept=c) for r, c in targets),
            operations=tuple(IntentOperation(action=a, outcome=o, roles=r) for a, o, r in operations),
        ),
    )

SCENARIOS = (
    (
        "automatic_door",
        "pass_through_door",
        (
            "In this synthetic consenting-adult demo, help me locate the door opening button, "
            "press it, confirm the automatic door is open, then pass through. "
            "The scene does not establish physical reachability."
        ),
        ("door_open_button", "automatic_door_opening"),
        ("locate", "press", "observe_state", "traverse"),
    ),
    (
        "packing_bag",
        "pack_bag",
        (
            "In this synthetic consenting-adult demo, help me locate my bag and water bottle, "
            "place the water bottle inside the bag, then check it is inside. "
            "The scene does not establish physical reachability."
        ),
        ("bag", "water_bottle"),
        ("locate", "place_inside", "observe_state"),
    ),
)


class SmokePick(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_id: Literal["synthetic-button-1"]


def emit(record):
    print(json.dumps(record), flush=True)


def reason(error):
    if isinstance(error, PlanningError):
        return error.reason_code
    if isinstance(error, TimeoutError):
        return "provider_timeout"
    if isinstance(error, ValidationError):
        return "invalid_smoke_schema"
    return "verification_failed"


async def verify(samples):
    load_dotenv(".env")
    if os.getenv("PLANNER_MODE", "").strip().lower() != "live":
        emit({"status": "not_run", "reason_code": "live_opt_in_required"})
        return False
    calls = 0
    try:
        async with NebiusPlanProvider.from_environment() as provider:
            emit(
                {
                    "endpoint_host": urlsplit(os.getenv("NEBIUS_BASE_URL") or BASE_URL).hostname,
                    "model_id": provider.model_id,
                    "mode": provider.mode,
                    "samples": samples,
                    "request_timeout_seconds": PLANNING_TIMEOUT_SECONDS,
                    "smoke_timeout_seconds": 30,
                }
            )
            started = perf_counter()
            calls += 1
            try:
                raw = await asyncio.wait_for(
                    provider.complete(
                        [
                            {
                                "role": "system",
                                "content": "Return only JSON matching this schema: "
                                + json.dumps(SmokePick.model_json_schema())
                                + ". Select only an existing object ID; no coordinates or extra fields.",
                            },
                            {
                                "role": "user",
                                "content": json.dumps(
                                    {
                                        "objects": [
                                            {
                                                "object_id": "synthetic-button-1",
                                                "concept": "door_open_button",
                                            }
                                        ],
                                        "request": "Select the door opening button in this synthetic scene.",
                                    }
                                ),
                            },
                        ],
                        SmokePick.model_json_schema(),
                    ),
                    timeout=30,
                )
                SmokePick.model_validate_json(raw)
            except Exception as error:  # noqa: BLE001 - metadata only, no provider traceback.
                emit(
                    {
                        "track": "early_smoke",
                        "status": "unavailable",
                        "reason_code": reason(error),
                        "api_calls": calls,
                        "latency_ms": round((perf_counter() - started) * 1000, 1),
                    }
                )
                return False
            emit(
                {
                    "track": "early_smoke",
                    "status": "passed",
                    "schema_passed": True,
                    "latency_ms": round((perf_counter() - started) * 1000, 1),
                }
            )
            passed = 0
            for sample in range(1, samples + 1):
                for name, goal, transcript, concepts, expected_actions in SCENARIOS:
                    request = PlanningRequest(
                        task_id=f"synthetic-{name}-{sample}",
                        plan_id=f"synthetic-{name}-{sample}",
                        goal=goal,
                        transcript=transcript,
                        capabilities=CapabilityFacts(
                            can_grasp=True,
                            can_press_button=True,
                            can_extend_arm=True,
                            can_place_inside=True,
                            can_traverse=True,
                        ),
                        observations=ObservationSnapshot(
                            revision="synthetic-r1",
                            objects=[
                                ObservedObject(object_id=f"synthetic-{i}", concept=concept)
                                for i, concept in enumerate(concepts)
                            ],
                        ),
                    )
                    started = perf_counter()
                    calls += 1
                    try:
                        reviewed = await generate_reviewed_plan(request, provider)
                        if reviewed.proposal is None:
                            raise PlanningError(reviewed.verification.reason_code)
                        review, proposal = reviewed.review, reviewed.proposal
                        context = VerificationContext(
                            task_id=request.task_id,
                            plan_id=request.plan_id,
                            snapshot=request.observations,
                            capabilities=request.capabilities,
                        )
                        start = start_planned_task(proposal, context, semantic_review=review)
                        actions = iter(step.action for step in proposal.plan.steps)
                        coverage = all(action in actions for action in expected_actions)
                        gated = (
                            start.service is not None
                            and start.verification.decision == "allow"
                            and start.service.accepted
                            and start.service.state.status == "active"
                            and not start.service.state.evidence
                            and not start.service.state.target_bindings
                        )
                        physical_gated = all(
                            verify_step(proposal.plan, step.step_id, {}, context).decision
                            != "allow"
                            for step in proposal.plan.steps
                            if ACTION_POLICIES[step.action].requires_physical_context
                        )
                        ok = (
                            coverage
                            and gated
                            and physical_gated
                            and proposal.mode == "LIVE_NEBIUS"
                            and proposal.source == "AI_GENERATED"
                        )
                        passed += ok
                        emit(
                            {
                                "track": "task_plan",
                                "scenario": name,
                                "sample": sample,
                                "status": "passed" if ok else "failed",
                                "schema_passed": True,
                                "scenario_action_coverage": coverage,
                                "execution_gate_passed": gated,
                                "unbound_physical_actions_blocked": physical_gated,
                                "source": proposal.source,
                                "initial_decision": start.verification.decision,
                                "initial_reason": start.verification.reason_code,
                                "steps": len(proposal.plan.steps),
                                "targets": len(proposal.plan.targets),
                                "latency_ms": proposal.latency_ms,
                            }
                        )
                    except Exception as error:  # noqa: BLE001 - never print raw JSON/error text.
                        emit(
                            {
                                "track": "task_plan",
                                "scenario": name,
                                "sample": sample,
                                "status": "failed",
                                "reason_code": reason(error),
                                "latency_ms": round((perf_counter() - started) * 1000, 1),
                            }
                        )
            emit(
                {
                    "track": "summary",
                    "api_calls": calls,
                    "task_plan_passed": passed,
                    "task_plan_total": samples * len(SCENARIOS),
                    "no_demo_fallback": True,
                }
            )
            return passed == samples * len(SCENARIOS)
    except Exception as error:  # noqa: BLE001 - config failures must not expose secrets either.
        emit({"status": "unavailable", "reason_code": reason(error), "api_calls": calls})
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Authorize actual billed API calls")
    parser.add_argument("--samples", type=int, choices=(1, 2, 3), default=2)
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; no API call was made")
    for name in ("httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    return 0 if asyncio.run(verify(args.samples)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
