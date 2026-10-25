"""F5: synthetic text composition and safe fallback; no usability/clinical claims."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.tasking.engine import create_task_state
from app.tasking.models import (
    CapabilityFacts,
    FeasibilityAssessment,
    ObservationSnapshot,
    ObservedObject,
    TargetBinding,
    TaskPlan,
)
from app.tasking.prompting import select_cue
from app.tasking.semantics import CONCEPT_ROLES, SemanticIntent, review_request
from app.tasking.verification import VerificationContext


def scenario(targets, operations):
    plan = TaskPlan.model_validate(
        {
            "plan_id": "synthetic",
            "goal": "manually_reviewed_synthetic_goal",
            "targets": [
                {"target_key": key, "concept": concept, "qualifiers": qualifiers}
                for key, concept, qualifiers in targets
            ],
            "steps": [
                {
                    "step_id": f"s{i}",
                    "action": action,
                    "target_keys": keys,
                    "completion_goal": {"outcome": outcome, "target_keys": keys},
                }
                for i, (action, outcome, keys) in enumerate(operations)
            ],
        }
    )
    intent = SemanticIntent.model_validate(
        {
            "targets": [
                {"role": key, "concept": concept, "qualifiers": list(qualifiers.items())}
                for key, concept, qualifiers in targets
            ],
            "operations": [{"action": a, "outcome": o, "roles": keys} for a, o, keys in operations],
        }
    )
    review = review_request(
        SimpleNamespace(
            task_id="task",
            plan_id=plan.plan_id,
            goal=plan.goal,
            transcript="Independently reviewed synthetic cue case.",
        ),
        review_id="synthetic-text-review",
        disposition="ready",
        intent=intent,
    )
    snapshot = ObservationSnapshot(
        revision="r1",
        objects=[
            ObservedObject(object_id=f"obj-{k}", concept=c, qualifiers=q) for k, c, q in targets
        ],
    )
    context = VerificationContext(
        task_id="task",
        plan_id=plan.plan_id,
        snapshot=snapshot,
        semantic_review=review,
        capabilities=CapabilityFacts(
            can_grasp=True,
            can_extend_arm=True,
            can_place_inside=True,
            can_press_button=True,
            can_traverse=True,
        ),
        feasibility={
            s.step_id: FeasibilityAssessment(
                step_id=s.step_id,
                observation_revision="r1",
                object_ids=tuple(f"obj-{k}" for k in s.target_keys),
                feasible=True,
            )
            for s in plan.steps
        },
    )
    state = create_task_state(plan, "task")
    state.target_bindings = {
        k: TargetBinding(target_key=k, object_id=f"obj-{k}", observation_revision="r1")
        for k, _, _ in targets
    }
    return plan, state, context


def at_step(plan, state, index):
    state.current_step_id = plan.steps[index].step_id
    for i, entry in enumerate(state.steps):
        entry.status = "completed" if i < index else "active" if i == index else "pending"
    state.steps[index].help_level = 3


@pytest.mark.parametrize(
    "concept,text",
    [
        ("book", "책을 찾아보세요."),
        ("box", "상자를 찾아보세요."),
        ("pen", "펜을 찾아보세요."),
        ("pouch", "파우치를 찾아보세요."),
        ("basket", "바구니를 찾아보세요."),
        ("towel", "수건을 찾아보세요."),
        ("mug", "머그잔을 찾아보세요."),
        ("paper", "종이를 찾아보세요."),
        ("elevator_call_button", "엘리베이터 호출 버튼을 찾아보세요."),
        ("garden_gate_opening", "정원 출입구를 찾아보세요."),
        ("corridor", "복도를 찾아보세요."),
        ("automatic_door_opening", "자동문 출입구를 찾아보세요."),
        ("door_open_button", "열림 버튼을 찾아보세요."),
        ("bag", "가방을 찾아보세요."),
        ("water_bottle", "물병을 찾아보세요."),
    ],
)
def test_catalog_names_and_korean_particles(concept, text):
    plan, state, context = scenario(
        [("target", concept, {})], [("locate", "target_located", ["target"])]
    )
    at_step(plan, state, 0)
    cue = select_cue(plan, state, context, ("arrow",))
    assert cue.text == text and cue.object_id == "obj-target"
    assert "대상" not in cue.text and "bbox" not in cue.model_dump()


def test_both_roles_and_qualifiers_survive_all_containment_cues_without_mutation():
    plan, state, context = scenario(
        [
            ("item", "mug", {"color": "blue", "relative_position": "left"}),
            ("container", "basket", {"color": "green"}),
        ],
        [
            ("locate", "target_located", ["item"]),
            ("locate", "target_located", ["container"]),
            ("place_inside", "placed_inside", ["item", "container"]),
            ("observe_state", "items_inside", ["item", "container"]),
        ],
    )
    expected = [
        "왼쪽 파란 머그잔을 찾아보세요.",
        "초록색 바구니를 찾아보세요.",
        "왼쪽 파란 머그잔을 초록색 바구니 안에 넣어 보세요.",
        "왼쪽 파란 머그잔이 초록색 바구니 안에 있는지 확인해 보세요.",
    ]
    for i, text in enumerate(expected):
        at_step(plan, state, i)
        before = (plan.model_dump(), state.model_dump(), context.snapshot.model_dump())
        cue = select_cue(plan, state, context, ("voice",))
        assert cue.text == text and cue.kind == "voice" and cue.object_id is None
        assert (plan.model_dump(), state.model_dump(), context.snapshot.model_dump()) == before
        assert not state.evidence


@pytest.mark.parametrize(
    "concept,qualifiers",
    [
        ("untranslated_injection", {}),
        ("mug", {"color": "private instruction"}),
        ("mug", {"relative_position": "unreviewed-frame"}),
    ],
)
def test_unrenderable_description_offers_neutral_assistance_without_echo_or_visual(
    concept, qualifiers
):
    plan, state, context = scenario(
        [("target", concept, qualifiers)], [("locate", "target_located", ["target"])]
    )
    at_step(plan, state, 0)
    cue = select_cue(plan, state, context, ("arrow", "voice"))
    assert cue.kind == "assistance" and cue.object_id is None
    assert cue.text == "물건 설명을 확인하기 어려워요. 보조자에게 확인해 주세요."
    assert "private" not in cue.text and "untranslated" not in cue.text
    state.steps[0].help_level = 0
    assert select_cue(plan, state, context, ("voice",)) is None


def test_qualified_unresolved_locate_does_not_guess_binding_and_stale_or_ambiguous_still_blocks():
    plan, state, context = scenario(
        [("target", "mug", {"color": "red"})], [("locate", "target_located", ["target"])]
    )
    at_step(plan, state, 0)
    bound = state.target_bindings.copy()
    state.target_bindings.clear()
    cue = select_cue(plan, state, context, ("arrow", "voice"))
    assert cue.text == "빨간 머그잔을 찾아보세요." and cue.kind == "voice"
    assert cue.object_id is None and not state.target_bindings
    state.target_bindings.update(bound)
    stale = replace(context, snapshot=context.snapshot.model_copy(update={"revision": "r2"}))
    assert select_cue(plan, state, stale, ("arrow",)) is None
    context.snapshot.objects.append(
        context.snapshot.objects[0].model_copy(update={"object_id": "second"})
    )
    assert select_cue(plan, state, context, ("arrow",)) is None


def test_passage_names_do_not_claim_success_and_physical_policy_still_applies():
    plan, state, context = scenario(
        [("opening", "corridor", {})],
        [
            ("locate", "target_located", ["opening"]),
            ("observe_state", "state_open", ["opening"]),
            ("traverse", "passed_through", ["opening"]),
        ],
    )
    at_step(plan, state, 2)
    assert select_cue(plan, state, context).text == "복도로 이동해 보세요."
    blocked = replace(context, capabilities=CapabilityFacts(can_traverse=False))
    assert select_cue(plan, state, blocked) is None
    assert select_cue(plan, state, replace(context, feasibility={})) is None


def test_all_current_reviewed_concepts_have_explicit_cue_regressions():
    assert len(CONCEPT_ROLES) == 15  # Expand catalog naming tests when concepts are added.
