"""Production, bounded-language request interpretation, independent of plan output.

Only fully consumed supported requests are approved. Unknown syntax, extra
commands and goal/text disagreement require confirmation. Denial term checks are
additional conservative vetoes, NEVER sufficient conditions for approval.
No LLM, case IDs, evaluation labels, observations or proposed plan are consulted.
"""

import re
from dataclasses import dataclass

from .semantics import (
    IntentOperation,
    IntentTarget,
    SemanticIntent,
    SemanticReview,
    request_fingerprint,
    review_request,
)

ADAPTER_VERSION = "controlled-request-v1"
ALIASES = {
    "door opening button": "door_open_button",
    "door open button": "door_open_button",
    "automatic door": "automatic_door_opening",
    "automatic door opening": "automatic_door_opening",
    "garden gate": "garden_gate_opening",
    "garden gate opening": "garden_gate_opening",
    "elevator call button": "elevator_call_button",
    "corridor": "corridor",
    "bag": "bag",
    "water bottle": "water_bottle",
    "bottle": "water_bottle",
    "book": "book",
    "box": "box",
    "pen": "pen",
    "pouch": "pouch",
    "basket": "basket",
    "towel": "towel",
    "mug": "mug",
}


@dataclass(frozen=True)
class Entity:
    concept: str
    qualifiers: tuple[tuple[str, str], ...] = ()


def _entity(text):
    text = re.sub(r"^(?:the|my|a|an) ", "", text.strip())
    color = re.fullmatch(r"(red|blue|green) (.+)", text)
    qualifiers = ()
    if color:
        qualifiers = (("color", color[1]),)
        text = color[2]
    concept = ALIASES.get(text)
    return Entity(concept, qualifiers) if concept else None


def _intent(targets, operations):
    if any(entity is None for _, entity in targets):
        return None
    try:
        return SemanticIntent(
            targets=tuple(
                IntentTarget(role=r, concept=e.concept, qualifiers=e.qualifiers) for r, e in targets
            ),
            operations=tuple(
                IntentOperation(action=a, outcome=o, roles=r) for a, o, r in operations
            ),
        )
    except ValueError:
        return None


def _contain(item, container):
    return _intent(
        (("item", item), ("container", container)),
        (
            ("locate", "target_located", ("item",)),
            ("locate", "target_located", ("container",)),
            ("place_inside", "placed_inside", ("item", "container")),
            ("observe_state", "items_inside", ("item", "container")),
        ),
    )


def _locate(target):
    return _intent((("target", target),), (("locate", "target_located", ("target",)),))


def _activate(control):
    return _intent(
        (("control", control),),
        (
            ("locate", "target_located", ("control",)),
            ("press", "pressed", ("control",)),
        ),
    )


def _passage(opening, control=None):
    targets = (("opening", opening),)
    operations = [("locate", "target_located", ("opening",))]
    if control:
        targets = (("control", control), *targets)
        operations = [
            ("locate", "target_located", ("control",)),
            ("press", "pressed", ("control",)),
        ]
    operations += [
        ("observe_state", "state_open", ("opening",)),
        ("traverse", "passed_through", ("opening",)),
    ]
    return _intent(targets, operations)


def _goal(goal):
    if goal == "pack_bag":
        return _contain(Entity("water_bottle"), Entity("bag"))
    if goal == "pass_through_door":
        return _passage(Entity("automatic_door_opening"), Entity("door_open_button"))
    if goal == "call_elevator":
        return _activate(Entity("elevator_call_button"))
    match = re.fullmatch(r"store_(.+)_in_(.+)", goal)
    if match:
        return _contain(_entity(match[1].replace("_", " ")), _entity(match[2].replace("_", " ")))
    if goal.startswith("locate_"):
        noun = goal.removeprefix("locate_").removesuffix("_only")
        return _locate(_entity(noun.replace("_", " ")))
    if goal.startswith("press_"):
        return _activate(_entity(goal.removeprefix("press_").replace("_", " ")))
    if goal.startswith("pass_through_"):
        return _passage(_entity(goal.removeprefix("pass_through_").replace("_", " ")))
    return None


def _parse_text(text):
    # Structural grammar: entity captures are independently parsed and all input
    # must match. Pronouns are only accepted where exactly one role is possible.
    prefix = r"(?:help me )?"
    check = r"(?:check|confirm|verify) (?:that )?(?:it is|it ended up) inside"
    match = re.fullmatch(
        prefix + r"(?:put|place|store) (.+?) (?:in|inside|into) (.+?),? (?:and|then) " + check, text
    )
    if match:
        return _contain(_entity(match[1]), _entity(match[2]))
    match = re.fullmatch(
        prefix
        + r"(?:find|locate) (.+?) and (.+?), (?:put|place) (.+?) (?:in|inside|into) (.+?), then "
        + check,
        text,
    )
    if match:
        container, item, moved, destination = (_entity(match[i]) for i in range(1, 5))
        if item and container and moved == item and destination == container:
            return _contain(item, container)
        return None
    match = re.fullmatch(
        prefix
        + r"(?:find|locate) (.+?), press it, (?:check|confirm) (?:that )?(.+?) is open, (?:and |then )(?:go|pass) through(?: it)?",
        text,
    )
    if match:
        control, opening = _entity(match[1]), _entity(match[2])
        if control:
            return _passage(opening, control)
        return None
    match = re.fullmatch(
        prefix
        + r"(?:find|locate) (.+?), (?:check|confirm) (?:that )?it is open, (?:and |then )(?:go|pass) through it",
        text,
    )
    if match:
        return _passage(_entity(match[1]))
    match = re.fullmatch(prefix + r"(?:find|locate) (.+?) and press it", text)
    if match:
        return _activate(_entity(match[1]))
    match = re.fullmatch(r"only help (?:me )?(?:find|locate) (.+)", text)
    if match:
        return _locate(_entity(match[1]))
    return None


class ControlledRequestReviewer:
    """Backend-owned deterministic adapter, not a client-approved review ledger.

    Supported English grammar only; anything outside it is safely held. A ready
    result is a semantic interpretation, never a physical feasibility assessment.
    """

    version = ADAPTER_VERSION

    def review(self, request) -> SemanticReview:
        def result(disposition, intent=None):
            return review_request(
                request,
                review_id=f"{self.version}:{request_fingerprint(request)}",
                disposition=disposition,
                intent=intent,
            )

        text = " ".join(request.transcript.casefold().split()).rstrip(".")
        safety_text = text + " " + request.goal.casefold().replace("_", " ")
        if re.search(r"\bi refuse\b|\bstop\b|\bi do not want\b|거부|그만|멈춰", safety_text):
            return result("refused")
        if re.search(
            r"\b(?:unsafe|electrified|smoking|hazard|exposed|live wires?|burning)\b|위험|노출된 전선",
            safety_text,
        ):
            return result("unsafe")
        if re.search(r"\b(?:someone|who|which|whichever|unclear|ambiguous)\b", safety_text):
            return result("ambiguous")
        goal_intent = _goal(request.goal)
        if goal_intent is None:
            return result("unsupported")
        # Only these closed, non-authorizing annotations can accompany a parsed
        # request. No untrusted quoted instruction or arbitrary suffix is ignored.
        text = text.removeprefix("in this synthetic consenting-adult demo, ")
        annotation = None
        missing = re.fullmatch(r"(.+)\. i have not found (.+) yet", text)
        if missing:
            text, annotation = missing[1], _entity(missing[2])
            if annotation is None:
                return result("ambiguous")
        suffixes = (
            (". the scene does not establish physical reachability", None),
            (". do not assume i can move through it without checking my capability", "traverse"),
            (". do not pick it up, put it somewhere or press anything", "locate_only"),
        )
        restriction = None
        for suffix, allowed in suffixes:
            if text.endswith(suffix):
                text, restriction = text.removesuffix(suffix), allowed
                break
        intent = _parse_text(text)
        if intent is None or intent != goal_intent:
            return result("ambiguous")
        if annotation and not any(
            t.concept == annotation.concept and t.qualifiers == annotation.qualifiers
            for t in intent.targets
        ):
            return result("ambiguous")
        actions = {op.action for op in intent.operations}
        if (restriction == "traverse" and "traverse" not in actions) or (
            restriction == "locate_only" and actions != {"locate"}
        ):
            return result("ambiguous")
        return result("ready", intent)
