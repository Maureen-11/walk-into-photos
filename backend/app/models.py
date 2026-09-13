from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Suitability(StrEnum):
    suitable = "suitable"
    conditional = "conditional"
    reject = "reject"


class SceneType(StrEnum):
    corridor = "corridor"
    room = "room"
    other = "other"


class ExperiencePreset(StrEnum):
    corridor_forward = "corridor_forward"
    room_explore = "room_explore"
    conservative = "conservative"


class PhotoPlan(BaseModel):
    analysis_id: str
    suitability: Suitability
    scene_type: SceneType
    title: str
    summary: str
    experience_preset: ExperiencePreset
    warnings: list[str] = Field(default_factory=list)
    estimated_seconds: int = 90
    mock: bool = False


class JobState(StrEnum):
    uploaded = "UPLOADED"
    analyzed = "ANALYZED"
    waiting_confirmation = "WAITING_CONFIRMATION"
    queued = "QUEUED"
    generating = "GENERATING"
    validating = "VALIDATING"
    ready = "READY"
    rejected = "REJECTED"
    failed = "FAILED"
    expired = "EXPIRED"


class Job(BaseModel):
    job_id: str
    analysis_id: str
    filename: str
    state: JobState
    progress: int = 0
    message: str = ""
    scene_id: str | None = None
    created_at: datetime
    expires_at: datetime | None = None
    error: str | None = None


class SceneManifest(BaseModel):
    scene_id: str
    scene_url: str
    download_url: str
    movement_radius: float
    generated_region_note: str
    expires_at: datetime
    mock: bool = False
