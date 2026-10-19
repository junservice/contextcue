"""Backend contract. Coordinate changes with frontend/src/types.ts."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Profile(BaseModel):
    user_id: str = Field(min_length=1, max_length=40)
    # Demo only. In real deployments, caregiver-verifiable granular ability profiles are required.
    can_grasp: bool | None = None
    can_press_button: bool | None = None


class SceneObject(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=80)
    # Normalized coordinates: (left, top, right, bottom), from validated perception output.
    bbox: tuple[float, float, float, float]

    @model_validator(mode="after")
    def check_bbox(self):
        left, top, right, bottom = self.bbox
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError("bbox must be normalized (left, top, right, bottom)")
        return self


class PlanRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=500)
    user_profile: Profile
    scene_objects: list[SceneObject] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def check_unique_ids(self):
        ids = [item.id for item in self.scene_objects]
        if len(ids) != len(set(ids)):
            raise ValueError("scene object IDs must be unique")
        return self


class PlanResponse(BaseModel):
    status: Literal["cue", "needs_confirmation", "needs_assistance", "unavailable"]
    cue_text: str
    object_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    mode: Literal["DEMO_RULES", "LIVE_NEBIUS"]
    scene_mode: Literal["DEMO_SCENE"] = "DEMO_SCENE"
    reason: str
