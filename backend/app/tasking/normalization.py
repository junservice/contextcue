"""Lossless semantic spelling normalization for AI proposals, before admission.

Never repairs references, inserts/removes steps or targets, reverses roles, invents
qualifiers, binds observations or modifies the independently reviewed request.
Only exact approved identities may receive a closed, explicit spelling alias.
"""

import re
from dataclasses import dataclass
from types import MappingProxyType

from .models import TaskPlan
from .semantics import SemanticReview

ALIASES = MappingProxyType(
    {
        "door_opening_button": "door_open_button",
        # No 'button', 'automatic_door', 'passageway', 'cup', or guessed identity.
    }
)


class NormalizationError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizationChange:
    target_key: str
    original_concept: str
    canonical_concept: str
    original_qualifiers: tuple[tuple[str, str], ...]
    canonical_qualifiers: tuple[tuple[str, str], ...]


def normalize_proposal(
    plan: TaskPlan, review: SemanticReview
) -> tuple[TaskPlan, tuple[NormalizationChange, ...]]:
    """Normalize only to one exact reviewed concept+qualifier identity.

    Parsing/reference validation MUST precede this call. Alias evidence is the
    proposal's literal spelling, never a guessed target or observation position.
    """
    parsed = TaskPlan.model_validate(plan.model_dump())
    allowed = {
        (target.concept, tuple(sorted(target.qualifiers))) for target in review.intent.targets
    }
    changes = []
    for target in parsed.targets:
        spelling = re.sub(r"[ -]+", "_", target.concept.casefold())
        concept = ALIASES.get(spelling, spelling)
        qualifiers = dict(target.qualifiers)
        color = re.fullmatch(r"(red|blue|green)_mug", concept)
        if color:
            if "color" in qualifiers and qualifiers["color"] != color[1]:
                raise NormalizationError("normalization_conflict")
            concept = "mug"
            qualifiers["color"] = color[1]  # Explicit in the literal concept, not inferred.
        identity = (concept, tuple(sorted(qualifiers.items())))
        if identity not in allowed:
            continue  # Retain original; strict semantic admission will reject it.
        if target.concept != concept or target.qualifiers != qualifiers:
            changes.append(
                NormalizationChange(
                    target.target_key,
                    target.concept,
                    concept,
                    tuple(sorted(target.qualifiers.items())),
                    tuple(sorted(qualifiers.items())),
                )
            )
            target.concept = concept
            target.qualifiers = qualifiers
    if changes:
        identities = [(t.concept, tuple(sorted(t.qualifiers.items()))) for t in parsed.targets]
        if len(identities) != len(set(identities)):
            raise NormalizationError("normalization_conflict")
    return parsed, tuple(changes)
