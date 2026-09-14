from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class PhotoCategory(StrEnum):
    natural_landscape = "natural_landscape"
    indoor_space = "indoor_space"
    street_city = "street_city"
    architecture = "architecture"
    animal_closeup = "animal_closeup"
    people = "people"
    food_tabletop = "food_tabletop"
    art_memory = "art_memory"
    other = "other"


class SceneTemplate(StrEnum):
    landscape_journey = "landscape_journey"
    indoor_walk = "indoor_walk"
    street_descent = "street_descent"
    facade_flight = "facade_flight"
    animal_diorama = "animal_diorama"
    memory_stage = "memory_stage"
    tabletop_world = "tabletop_world"
    layered_canvas = "layered_canvas"
    generic_layers = "generic_layers"


class GenerationMode(StrEnum):
    quick = "quick"
    full = "full"
    progressive = "progressive"


class ExperienceKind(StrEnum):
    spatial_scene = "spatial_scene"
    interactive_subject = "interactive_subject"
    still_fallback = "still_fallback"


class SceneEngine(StrEnum):
    terrain = "terrain"
    space = "space"
    street = "street"
    facade = "facade"
    diorama = "diorama"
    portrait_stage = "portrait_stage"
    tabletop = "tabletop"
    layered_canvas = "layered_canvas"
    generic_layers = "generic_layers"


class CapabilityStatus(StrEnum):
    available = "available"
    experimental = "experimental"
    unverified = "unverified"
    unavailable = "unavailable"


class ActionTrigger(StrEnum):
    mouse_stroke = "mouse_stroke"
    click = "click"
    future_gesture = "future_gesture"


class SubjectRegion(BaseModel):
    region_id: str
    label: str
    # Normalized image coordinates.  None means the local planner did not
    # produce a trustworthy box yet; clients must not invent one.
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    confidence: float | None = None
    occluded: bool = False


class ActionSpec(BaseModel):
    action_id: str
    label: str
    trigger: ActionTrigger
    target_region_id: str | None = None
    asset_url: str | None = None
    status: CapabilityStatus = CapabilityStatus.unverified
    cooldown_ms: int = 1200
    hint: str | None = None


class PhotoPlan(BaseModel):
    analysis_id: str
    category: PhotoCategory
    title: str
    summary: str
    recommended_template: SceneTemplate
    compatible_templates: list[SceneTemplate]
    rationale: str
    scene_description: str
    warnings: list[str] = Field(default_factory=list)
    estimated_quick_seconds: int = 240
    estimated_full_seconds: int = 720
    planner_backend: str = "local-rules"
    experimental: bool = False
    mock: bool = False
    experience_kind: ExperienceKind = ExperienceKind.spatial_scene
    capability_status: CapabilityStatus = CapabilityStatus.unverified
    subject_regions: list[SubjectRegion] = Field(default_factory=list)
    actions: list[ActionSpec] = Field(default_factory=list)
    capability_notes: list[str] = Field(default_factory=list)
    analysis_confidence: float | None = None


class JobState(StrEnum):
    queued = "QUEUED"
    quick_generating = "QUICK_GENERATING"
    quick_ready = "QUICK_READY"
    full_generating = "FULL_GENERATING"
    full_ready = "FULL_READY"
    failed = "FAILED"
    expired = "EXPIRED"
    interrupted = "INTERRUPTED"


class Job(BaseModel):
    job_id: str
    analysis_id: str
    filename: str
    generation_mode: GenerationMode
    selected_template: SceneTemplate
    state: JobState
    progress: int = 0
    progress_kind: str = "stage"
    message: str = ""
    quick_scene_id: str | None = None
    full_scene_id: str | None = None
    scene_id: str | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    error: str | None = None
    # Generation completion and visual quality validation are separate facts.
    # Existing SQLite JSON records remain readable because these fields have
    # defaults for older jobs.
    validation_status: str = "not_run"
    stage_timings_ms: dict[str, int] = Field(default_factory=dict)
    generation_started_at: datetime | None = None
    generation_finished_at: datetime | None = None


class MovementProfile(BaseModel):
    kind: str
    start: list[float]
    bounds: dict[str, list[float]]
    walk_speed: float = 1.8
    fly_speed: float = 3.2
    allow_flight: bool = True
    ground_follow: bool = False
    ground_y: float | None = None
    collision_radius: float = 0.25
    route_checkpoints: list[list[float]] = Field(default_factory=list)


class CameraSpec(BaseModel):
    """Camera contract shared by MoGe output and every viewer.

    Coordinates use the OpenGL convention produced by MoGe: x right, y up,
    and the camera looks down negative z.  Keeping this explicit prevents the
    viewer from silently adding a second scale, translation, or field of view.
    """

    position: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    intrinsics: list[list[float]] | None = None
    image_size: list[int] | None = None
    camera_to_world: list[list[float]] = Field(default_factory=lambda: [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ])
    world_scale: float = 1.0
    near: float = 0.01
    far: float = 200.0
    fov_x: float | None = None
    fov_y: float | None = None
    coordinate_frame_id: str = "moge-opengl-camera-v1"


class SceneManifest(BaseModel):
    scene_id: str
    scene_url: str
    download_url: str
    export_url: str
    version: str
    template: SceneTemplate
    engine: SceneEngine = SceneEngine.generic_layers
    movement: MovementProfile
    camera: CameraSpec | None = None
    source_url: str | None = None
    generated_region_note: str
    expires_at: datetime
    mock: bool = False
    experience_kind: ExperienceKind = ExperienceKind.spatial_scene
    actions: list[ActionSpec] = Field(default_factory=list)
    subject_regions: list[SubjectRegion] = Field(default_factory=list)
    capability_status: CapabilityStatus = CapabilityStatus.unverified
    coverage: float | None = None
    quality_status: str = "unverified"
    quality_metrics: dict[str, object] = Field(default_factory=dict)
