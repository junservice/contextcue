"""Internal task data contracts, independent of providers, APIs and execution policy.

Binding/Evidence parsing checks structure only, not observation authenticity,
freshness or source trust. The verification module owns the trusted input boundary.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
HelpLevel = Annotated[int, Field(strict=True, ge=0)]


class TaskModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def require_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


class TargetRef(TaskModel):
    """An unresolved semantic target, never an observed object or coordinates."""

    target_key: Text
    concept: Text
    qualifiers: dict[Literal["color", "relative_position"], Text] = Field(default_factory=dict)


class TargetBinding(TaskModel):
    """Internal input assumed verified upstream; this model does not prove grounding."""

    target_key: Text
    object_id: Text
    observation_revision: Text


class ObservedObject(TaskModel):
    """Semantic observation supplied by a backend adapter, not an AI proposal.

    Pixel coordinates remain in perception data; verification never creates them.
    """

    object_id: Text
    concept: Text
    qualifiers: dict[Literal["color", "relative_position"], Text] = Field(default_factory=dict)


class ObservationSnapshot(TaskModel):
    revision: Text
    objects: list[ObservedObject] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_ids(self) -> Self:
        require_unique([obj.object_id for obj in self.objects], "observation object IDs")
        return self


CapabilityKey = Literal[
    "can_grasp", "can_press_button", "can_extend_arm", "can_place_inside", "can_traverse",
]


class CapabilityFacts(TaskModel):
    can_grasp: StrictBool | None = None
    can_press_button: StrictBool | None = None
    can_extend_arm: StrictBool | None = None
    can_place_inside: StrictBool | None = None
    can_traverse: StrictBool | None = None


class FeasibilityAssessment(TaskModel):
    """Backend-provided physical context fact, scoped to a step/revision/objects."""

    step_id: Text
    observation_revision: Text
    object_ids: tuple[Text, ...]
    feasible: StrictBool | None = None


class CompletionGoal(TaskModel):
    """Desired semantic result; no Evidence acceptance policy may be specified."""

    outcome: Text
    target_keys: list[Text] = Field(min_length=1)

    @model_validator(mode="after")
    def check_targets(self) -> Self:
        require_unique(self.target_keys, "completion target keys")
        return self


class TaskStep(TaskModel):
    step_id: Text
    # Action/outcome support and cardinality are checked by Phase 2 policy.
    action: Text
    target_keys: list[Text] = Field(min_length=1)
    completion_goal: CompletionGoal
    max_help_level: HelpLevel = 4

    @model_validator(mode="after")
    def check_targets(self) -> Self:
        require_unique(self.target_keys, "step target keys")
        return self


class TaskPlan(TaskModel):
    schema_version: Literal["1.0"] = "1.0"
    plan_id: Text
    goal: Text
    targets: list[TargetRef] = Field(min_length=1)
    steps: list[TaskStep] = Field(min_length=1)

    @model_validator(mode="after")
    def check_references(self) -> Self:
        keys = [target.target_key for target in self.targets]
        require_unique(keys, "target keys")
        require_unique([step.step_id for step in self.steps], "step IDs")
        known = set(keys)
        for step in self.steps:
            references = set(step.target_keys) | set(step.completion_goal.target_keys)
            if not references <= known:
                raise ValueError("step and completion targets must reference declared target keys")
        return self


class Evidence(TaskModel):
    """A declared claim, not proof of its source or of actual action completion."""

    evidence_id: Text
    step_id: Text
    source: Literal[
        "camera_observation", "caregiver_report", "manual_progress",
        "cue_issued", "model_assessment", "unknown",
    ]
    outcome: Text
    target_keys: list[Text] = Field(default_factory=list)
    object_ids: list[Text] = Field(default_factory=list)
    observation_revision: Text | None = None
    provenance_id: Text | None = None
    confidence: float | None = Field(default=None, strict=True, ge=0, le=1, allow_inf_nan=False)
    relation: Literal["supports", "contradicts", "inconclusive"]

    @model_validator(mode="after")
    def check_references(self) -> Self:
        require_unique(self.target_keys, "Evidence target keys")
        require_unique(self.object_ids, "Evidence object IDs")
        return self


class TaskEvent(TaskModel):
    """Typed event data only; interpreting transitions is the Engine's job."""

    type: Literal[
        "pause", "resume", "stop", "refusal", "more_help", "help_requested",
        "manual_advance", "cue_issued", "target_bound", "evidence_received",
    ]
    step_id: Text | None = None
    binding: TargetBinding | None = None
    evidence: Evidence | None = None

    @model_validator(mode="after")
    def check_payload(self) -> Self:
        if (self.binding is not None) != (self.type == "target_bound"):
            raise ValueError("only target_bound requires a binding")
        if (self.evidence is not None) != (self.type == "evidence_received"):
            raise ValueError("only evidence_received requires Evidence")
        if self.type == "cue_issued" and self.step_id is None:
            raise ValueError("cue_issued requires a step ID")
        if self.evidence is not None and self.step_id not in (None, self.evidence.step_id):
            raise ValueError("event step ID must match Evidence step ID")
        return self


class StepState(TaskModel):
    step_id: Text
    status: Literal[
        "pending", "active", "awaiting_target", "awaiting_evidence", "completed", "blocked",
    ] = "pending"
    help_level: HelpLevel = 0


class TaskState(TaskModel):
    task_id: Text
    plan_id: Text
    status: Literal[
        "idle", "active", "paused", "needs_confirmation", "needs_assistance",
        "stopped", "completed",
    ] = "idle"
    current_step_id: Text | None = None
    steps: list[StepState] = Field(default_factory=list)
    target_bindings: dict[Text, TargetBinding] = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_references(self) -> Self:
        ids = [step.step_id for step in self.steps]
        require_unique(ids, "state step IDs")
        require_unique([item.evidence_id for item in self.evidence], "Evidence IDs")
        if self.current_step_id is not None and self.current_step_id not in ids:
            raise ValueError("current step ID must reference a state step")
        if any(item.step_id not in ids for item in self.evidence):
            raise ValueError("Evidence must reference a state step")
        if any(key != binding.target_key for key, binding in self.target_bindings.items()):
            raise ValueError("binding map key must match target key")
        return self
