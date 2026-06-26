"""App-layer request models not part of the shilljudge-core foundation surface."""
from typing import Literal

from pydantic import BaseModel, Field


class UpdateUserRequest(BaseModel):
    is_admin: bool | None = None
    participation_status: Literal["active", "suspended"] | None = None


class OverrideScoreRequest(BaseModel):
    """Admin manual score override. ``override_score=None`` clears the override and
    reverts the thread to its computed score."""
    override_score: float | None = None
    note: str = Field(default="", max_length=500, description="Audit reason for the override")
