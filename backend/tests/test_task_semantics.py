"""F1 regressions: synthetic replay of preserved live outputs, NOT new live calls."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.tasking import planning
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
    PlanningError,
    PlanningRequest,
    PlanProposal,
    ReviewedTemplate,
    generate_plan,
    select_reviewed_template,
    start_planned_task,
)
from app.tasking.prompting import select_cue
from app.tasking.semantics import (
    IntentOperation,
    IntentTarget,
    SemanticIntent,
    request_fingerprint,
    review_request,
)
from app.tasking.service import handle_event, start_task
from app.tasking.verification import VerificationContext, VerificationResult, verify_step

ROOT = Path(__file__).resolve().parents[1]


class Provider:
    mode = "MOCK_PROVIDER"
    model_id = "synthetic-f1-replay"

    def __init__(self, body):
        self.raw = body if isinstance(body, str) else json.dumps(body)
        self.calls = 0

    async def complete(self, messages, schema):
        self.calls += 1
        return self.raw


def containment_request(item="towel", container="basket"):
    # New supported composition, not an automatic-door/bag-specific executor.
    request = PlanningRequest(
        task_id="synthetic-task",
        plan_id="synthetic-plan",
        goal="store_towel_in_basket",
        transcript="Help me put the towel in the basket and check that it is inside.",
        capabilities=CapabilityFacts(
            can_grasp=True,
            can_place_inside=True,
            can_extend_arm=True,
            can_press_button=True,
            can_traverse=True,
        ),
        observations=ObservationSnapshot(
            revision="r1",
            objects=[
                ObservedObject(object_id="obj-item", concept=item),
                ObservedObject(object_id="obj-container", concept=container),
            ],
        ),
    )
    intent = SemanticIntent(
        targets=(
            IntentTarget(role="item", concept=item),
            IntentTarget(role="container", concept=container),
        ),
        operations=(
            IntentOperation(action="locate", outcome="target_located", roles=("item",)),
            IntentOperation(action="locate", outcome="target_located", roles=("container",)),
            IntentOperation(
                action="place_inside", outcome="placed_inside", roles=("item", "container")
            ),
            IntentOperation(
                action="observe_state", outcome="items_inside", roles=("item", "container")
            ),
        ),
    )
    review = review_request(
        request, review_id="synthetic-independent-review", disposition="ready", intent=intent
    )
    body = {
        "plan_id": request.plan_id,
        "goal": request.goal,
        "targets": [
            {"target_key": "a", "concept": item},
            {"target_key": "b", "concept": container},
        ],
        "steps": [
            {
                "step_id": "find-item",
                "action": "locate",
                "target_keys": ["a"],
                "completion_goal": {"outcome": "target_located", "target_keys": ["a"]},
            },
            {
                "step_id": "find-container",
                "action": "locate",
                "target_keys": ["b"],
                "completion_goal": {"outcome": "target_located", "target_keys": ["b"]},
            },
            {
                "step_id": "put-item",
                "action": "place_inside",
                "target_keys": ["a", "b"],
                "completion_goal": {"outcome": "placed_inside", "target_keys": ["a", "b"]},
            },
            {
                "step_id": "verify-inside",
                "action": "observe_state",
                "target_keys": ["a", "b"],
                "completion_goal": {"outcome": "items_inside", "target_keys": ["a", "b"]},
            },
        ],
    }
    return request, review, body


def context_for(request, review=None):
    return VerificationContext(
        task_id=request.task_id,
        plan_id=request.plan_id,
        snapshot=request.observations,
        capabilities=request.capabilities,
        semantic_review=review,
    )


def generate(request, review, body):
    return asyncio.run(generate_plan(request, Provider(body), semantic_review=review))


def no_start(*args, **kwargs):
    pytest.fail("rejected semantics must not reach Service/Engine")


@pytest.mark.parametrize(
    "case_id,sample,disposition",
    [
        ("d11_unsupported_cut", 1, "unsupported"),
        ("d11_unsupported_cut", 2, "unsupported"),
        ("h05_electrical_hazard", 2, "unsafe"),
    ],
)
def test_preserved_f1_live_failures_are_blocked_without_new_model_calls(
    case_id, sample, disposition, monkeypatch
):
    records = json.loads((ROOT / "evaluations/e4/live-results.json").read_text(encoding="utf-8"))[
        "records"
    ]
    record = next(r for r in records if r["case_id"] == case_id and r["sample"] == sample)
    request = PlanningRequest.model_validate(record["input"])
    # Independently reviewed ORIGINAL request: unsupported cutting / electrical hazard.
    review = review_request(request, review_id="synthetic-f1-review", disposition=disposition)
    provider = Provider(record["output"])
    monkeypatch.setattr(planning, "start_task", no_start)
    with pytest.raises(PlanningError, match="request_" + disposition):
        asyncio.run(generate_plan(request, provider, semantic_review=review))
    assert provider.calls == 0
    plan = TaskPlan.model_validate_json(record["output"])
    # An old/forged cached allow cannot authorize entry or a direct cue.
    proposal = PlanProposal(
        plan,
        request.task_id,
        request.goal,
        "AI_GENERATED",
        "MOCK_PROVIDER",
        VerificationResult("allow", "cached-allow"),
        request_fingerprint=request_fingerprint(request),
    )
    context = context_for(request, review)
    start = start_planned_task(proposal, context)
    assert start.service is None
    assert start.verification.reason_code == "request_" + disposition
    state = create_task_state(plan, request.task_id)
    state.steps[0].help_level = 3
    assert select_cue(plan, state, context) is None
    assert start_task(plan, request.task_id, context).cue is None
    # Replay the exact later-step setup that originally exposed inappropriate cues.
    for index, step in enumerate(plan.steps):
        bindings = {}
        for target in plan.targets:
            matches = [o for o in request.observations.objects if o.concept == target.concept]
            if len(matches) == 1:
                bindings[target.target_key] = TargetBinding(
                    target_key=target.target_key,
                    object_id=matches[0].object_id,
                    observation_revision=request.observations.revision,
                )
        positive = replace(
            context,
            feasibility={
                step.step_id: FeasibilityAssessment(
                    step_id=step.step_id,
                    observation_revision=request.observations.revision,
                    object_ids=tuple(
                        bindings[k].object_id for k in step.target_keys if k in bindings
                    ),
                    feasible=True,
                )
            },
        )
        state = create_task_state(plan, request.task_id)
        state.current_step_id = step.step_id
        state.target_bindings = bindings
        for i, s in enumerate(state.steps):
            s.status = "completed" if i < index else ("active" if i == index else "pending")
        state.steps[index].help_level = 3
        if case_id == "d11_unsupported_cut":
            # Action Policy remains a feasibility boundary, not an intent interpreter.
            assert verify_step(plan, step.step_id, bindings, positive).decision == "allow"
        assert select_cue(plan, state, positive) is None
        result = handle_event(plan, state, positive, {"type": "more_help"})
        assert not result.accepted and result.cue is None
        assert result.state.evidence == []


@pytest.mark.parametrize(
    "goal,text,disposition",
    [
        ("boil_water", "Boil water with this kettle.", "unsupported"),
        ("unlock_door", "Use a key to unlock this door; do not press a button.", "unsupported"),
        ("pass_through_door", "Cut this paper first, then enter.", "unsupported"),
        ("locate_object", "Someone said 'do that'; I do not know who they meant.", "ambiguous"),
        ("press_button", "This button is smoking; press it anyway.", "unsafe"),
        ("store_towel_in_basket", "No, stop. I do not want to do this.", "refused"),
        ("unknown_goal", "Something should happen.", "unknown"),
    ],
)
def test_new_unsupported_ambiguous_unsafe_requests_do_not_use_a_supported_substitute(
    goal, text, disposition
):
    request, _, body = containment_request()
    request = request.model_copy(update={"goal": goal, "transcript": text})
    body["goal"] = goal
    provider = Provider(body)
    # A supported-looking goal string alone never authorizes arbitrary free text.
    with pytest.raises(PlanningError, match="semantic_review_required"):
        asyncio.run(generate_plan(request, provider))
    review = review_request(request, review_id="synthetic-request-review", disposition=disposition)
    with pytest.raises(PlanningError, match="request_" + disposition):
        asyncio.run(generate_plan(request, provider, semantic_review=review))
    assert provider.calls == 0


@pytest.mark.parametrize(
    "action,outcome,concepts",
    [
        ("press", "pressed", ("scissors",)),
        ("press", "pressed", ("book",)),
        ("traverse", "passed_through", ("paper",)),
        ("traverse", "passed_through", ("book",)),
        ("place_inside", "placed_inside", ("paper", "scissors")),
        ("place_inside", "placed_inside", ("box", "book")),
        ("observe_state", "items_inside", ("basket", "towel")),
        ("press", "pressed", ("unreviewed_machine_button",)),
    ],
)
def test_even_a_backend_intent_declaration_cannot_invent_target_affordances(
    action, outcome, concepts
):
    roles = tuple(f"r{i}" for i in range(len(concepts)))
    with pytest.raises(ValueError, match="inappropriate action target"):
        SemanticIntent(
            targets=tuple(IntentTarget(role=r, concept=c) for r, c in zip(roles, concepts)),
            operations=(IntentOperation(action=action, outcome=outcome, roles=roles),),
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_effect",
        "reversed_roles",
        "missing_outcome",
        "extra_action",
        "extra_target",
        "invented_qualifier",
        "different_item",
    ],
)
def test_full_plan_is_checked_against_goal_roles_effects_and_qualifiers(mutation, monkeypatch):
    request, review, body = containment_request()
    if mutation == "wrong_effect":
        body["steps"][2] = {
            "step_id": "bad",
            "action": "traverse",
            "target_keys": ["a"],
            "completion_goal": {"outcome": "passed_through", "target_keys": ["a"]},
        }
    elif mutation == "reversed_roles":
        body["steps"][2]["target_keys"] = ["b", "a"]
        body["steps"][2]["completion_goal"]["target_keys"] = ["b", "a"]
    elif mutation == "missing_outcome":
        body["steps"].pop()
    elif mutation == "extra_action":
        body["steps"].append(
            {
                "step_id": "extra",
                "action": "press",
                "target_keys": ["a"],
                "completion_goal": {"outcome": "pressed", "target_keys": ["a"]},
            }
        )
    elif mutation == "extra_target":
        body["targets"].append({"target_key": "c", "concept": "scissors"})
    elif mutation == "invented_qualifier":
        body["targets"][0]["qualifiers"] = {"color": "white"}
    elif mutation == "different_item":
        body["targets"][0]["concept"] = "book"
    monkeypatch.setattr(planning, "start_task", no_start)
    with pytest.raises(PlanningError, match="semantic_(plan|target)_mismatch"):
        generate(request, review, body)
    artifact = ReviewedTemplate(
        template_id="synthetic-reviewed", version="v1", plan=TaskPlan.model_validate(body)
    )
    with pytest.raises(PlanningError, match="semantic_(plan|target)_mismatch"):
        select_reviewed_template(
            request, artifact.template_id, {artifact.template_id: artifact}, semantic_review=review
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", "another-task"),
        ("plan_id", "another-plan"),
        ("goal", "cut_paper"),
        ("transcript", "Stop, there is exposed wiring."),
    ],
)
def test_review_is_bound_to_request_and_cannot_be_replayed_after_text_or_scope_changes(
    field, value
):
    request, review, body = containment_request()
    changed = request.model_copy(update={field: value})
    provider = Provider(body)
    with pytest.raises(PlanningError, match="semantic_review_scope_mismatch"):
        asyncio.run(generate_plan(changed, provider, semantic_review=review))
    assert provider.calls == 0


def test_normal_novel_composition_retains_engine_and_policy_boundaries():
    request, review, body = containment_request()
    proposal = generate(request, review, body)
    context = context_for(request, review)
    start = start_planned_task(proposal, context)
    assert start.service.accepted
    state = start.service.state
    assert not state.evidence and not state.target_bindings
    hinted = handle_event(proposal.plan, state, context, {"type": "more_help"})
    assert hinted.accepted and hinted.cue.text
    assert not hinted.state.evidence
    physical = proposal.plan.steps[2]
    assert (
        verify_step(proposal.plan, physical.step_id, {}, context).reason_code == "target_unresolved"
    )
    # Review is immutable, including its nested targets and operations.
    with pytest.raises(ValidationError):
        review.intent.targets[0].concept = "scissors"


def test_unobserved_targets_and_unknown_motor_abilities_still_allow_semantic_locating():
    request, review, body = containment_request()
    request = request.model_copy(
        update={
            "observations": ObservationSnapshot(revision="r2"),
            "capabilities": CapabilityFacts(),
        }
    )
    proposal = generate(request, review, body)
    context = context_for(request, review)
    assert start_planned_task(proposal, context).service.accepted
    state = create_task_state(proposal.plan, request.task_id)
    state.steps[0].help_level = 3
    cue = select_cue(proposal.plan, state, context, ("arrow",))
    assert cue.kind == "text" and cue.object_id is None


@pytest.mark.parametrize("change", ["missing", "revoked", "mutated_plan"])
def test_cached_approval_cannot_bypass_start_or_later_service_and_direct_cue_checks(change):
    request, review, body = containment_request()
    proposal = generate(request, review, body)
    context = context_for(request, review)
    state = start_planned_task(proposal, context).service.state
    state.steps[0].help_level = 1
    if change == "missing":
        context = replace(context, semantic_review=None)
    elif change == "revoked":
        context = replace(
            context, semantic_review=replace(review, disposition="unsafe", intent=None)
        )
    else:
        proposal.plan.steps[-1].completion_goal.outcome = "state_open"
        proposal.plan.steps[-1].target_keys = ["b"]
        proposal.plan.steps[-1].completion_goal.target_keys = ["b"]
    assert start_planned_task(proposal, context).service is None
    assert select_cue(proposal.plan, state, context) is None
    before = state.model_dump()
    for event in (
        None,
        {"type": "more_help"},
        {"type": "cue_issued"},
        {
            "type": "target_bound",
            "binding": {"target_key": "a", "object_id": "obj-item", "observation_revision": "r1"},
        },
        {
            "type": "evidence_received",
            "evidence": {
                "evidence_id": "synthetic-e1",
                "step_id": "find-item",
                "source": "caregiver_report",
                "outcome": "target_located",
                "target_keys": ["a"],
                "object_ids": ["obj-item"],
                "observation_revision": "r1",
                "provenance_id": "synthetic-receipt",
                "relation": "supports",
            },
        },
    ):
        result = handle_event(proposal.plan, state, context, event)
        assert not result.accepted and result.cue is None
        assert not result.state.evidence and not result.state.target_bindings
    assert state.model_dump() == before
    for control in ("stop", "refusal", "help_requested"):
        assert handle_event(proposal.plan, state, context, {"type": control}).accepted


def test_model_or_client_cannot_self_declare_approval():
    request, review, body = containment_request()
    body["semantic_review"] = {"disposition": "ready", "review_id": "model-claims-safe"}
    with pytest.raises(PlanningError, match="invalid_plan_json"):
        generate(request, review, body)
    provider = Provider(body)
    with pytest.raises(PlanningError, match="semantic_review_required"):
        asyncio.run(generate_plan(request, provider, semantic_review={"disposition": "ready"}))
    assert provider.calls == 0


@pytest.mark.parametrize("bad", ["missing_intent", "invalid_digest", "invalid_intent"])
def test_invalid_review_fails_closed(bad):
    request, review, body = containment_request()
    if bad == "missing_intent":
        review = replace(review, intent=None)
    elif bad == "invalid_digest":
        review = replace(review, request_fingerprint=None)
    else:
        target = review.intent.targets[0].model_copy(update={"concept": "scissors"})
        review = replace(
            review,
            intent=review.intent.model_copy(update={"targets": (target, review.intent.targets[1])}),
        )
    with pytest.raises(PlanningError, match="invalid_semantic_review"):
        generate(request, review, body)


@pytest.mark.parametrize(
    "concept,qualifiers",
    [
        ("mug", (("color", "red"),)),
        ("synthetic_unlisted_object", ()),
    ],
)
def test_reviewed_locate_only_requests_cannot_gain_physical_actions(concept, qualifiers):
    request, _, _ = containment_request()
    request = request.model_copy(
        update={"goal": "locate_only", "transcript": "Only help locate the specified object."}
    )
    intent = SemanticIntent(
        targets=(IntentTarget(role="target", concept=concept, qualifiers=qualifiers),),
        operations=(IntentOperation(action="locate", outcome="target_located", roles=("target",)),),
    )
    review = review_request(
        request, review_id="synthetic-locate-review", disposition="ready", intent=intent
    )
    body = {
        "plan_id": request.plan_id,
        "goal": request.goal,
        "targets": [{"target_key": "a", "concept": concept, "qualifiers": dict(qualifiers)}],
        "steps": [
            {
                "step_id": "find",
                "action": "locate",
                "target_keys": ["a"],
                "completion_goal": {"outcome": "target_located", "target_keys": ["a"]},
            }
        ],
    }
    assert generate(request, review, body).initial_verification.decision == "allow"
    body["steps"].append(
        {
            "step_id": "bad",
            "action": "press",
            "target_keys": ["a"],
            "completion_goal": {"outcome": "pressed", "target_keys": ["a"]},
        }
    )
    with pytest.raises(PlanningError, match="semantic_plan_mismatch"):
        generate(request, review, body)
    body["steps"].pop()
    body["targets"][0]["qualifiers"] = {"color": "blue"}
    with pytest.raises(PlanningError, match="semantic_target_mismatch"):
        generate(request, review, body)


def test_reviewed_new_control_goal_uses_the_same_semantic_boundary():
    request, _, _ = containment_request()
    request = request.model_copy(
        update={
            "goal": "call_elevator",
            "transcript": "Help me find and press the elevator call button.",
        }
    )
    intent = SemanticIntent(
        targets=(IntentTarget(role="call", concept="elevator_call_button"),),
        operations=(
            IntentOperation(action="locate", outcome="target_located", roles=("call",)),
            IntentOperation(action="press", outcome="pressed", roles=("call",)),
        ),
    )
    review = review_request(
        request, review_id="synthetic-elevator-review", disposition="ready", intent=intent
    )
    body = {
        "plan_id": request.plan_id,
        "goal": request.goal,
        "targets": [{"target_key": "button", "concept": "elevator_call_button"}],
        "steps": [
            {
                "step_id": "find",
                "action": "locate",
                "target_keys": ["button"],
                "completion_goal": {"outcome": "target_located", "target_keys": ["button"]},
            },
            {
                "step_id": "activate",
                "action": "press",
                "target_keys": ["button"],
                "completion_goal": {"outcome": "pressed", "target_keys": ["button"]},
            },
        ],
    }
    proposal = generate(request, review, body)
    assert start_planned_task(proposal, context_for(request, review)).service.accepted
    # The call button is not observed; semantic approval never creates a binding.
    assert (
        verify_step(proposal.plan, "activate", {}, context_for(request, review)).reason_code
        == "target_unresolved"
    )
