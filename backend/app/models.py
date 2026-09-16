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


class RegionConfirmation(BaseModel):
    """Optional small user annotation used to disambiguate a photo region.

    Coordinates are normalized image coordinates.  The record is intentionally
    small and serializable so it can be hashed into the scene provenance.
    """

    region_id: str
    role: str
    label: str | None = None
    x: float
    y: float
    width: float
    height: float


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
    # Hash of the bytes received at the upload boundary. This is kept through
    # analysis so a generated manifest can be compared with the user's actual
    # input rather than a normalized JPEG saved for local processing.
    input_sha256: str | None = None
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
    cancelled = "CANCELLED"
    expired = "EXPIRED"
    interrupted = "INTERRUPTED"


class Job(BaseModel):
    job_id: str
    analysis_id: str
    filename: str
    generation_mode: GenerationMode
    # The quality route is the default delivery route. Older job records omit
    # this field and remain readable as the historical quick/full workflow.
    quality_route: bool = False
    region_confirmations: list[RegionConfirmation] = Field(default_factory=list)
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
    # Machine quality is kept separate from generation state. Older records
    # default conservatively and must not be treated as passed.
    quality_status: str = "unverified"
    stage_timings_ms: dict[str, int] = Field(default_factory=dict)
    generation_started_at: datetime | None = None
    generation_finished_at: datetime | None = None
    # Cancellation is cooperative: an in-flight model call is allowed to
    # finish, then the worker preserves any completed quick result without
    # promoting a full candidate.
    cancel_requested: bool = False


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
    # Optional coarse-scene collision data. Older manifests omit this field
    # and continue to use their historical AABB-only movement contract.
    collision_boxes: list["CollisionBox"] = Field(default_factory=list)


class CollisionBox(BaseModel):
    box_id: str
    bounds: dict[str, list[float]]
    label: str | None = None


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
    # Optional provenance and hand-off fields introduced for safe quick/full
    # comparison. Older manifests remain readable and conservatively default
    # to missing/unverified values.
    input_sha256: str | None = None
    provider_version: str | None = None
    coordinate_frame_id: str | None = None
    resource_manifest: list[str] = Field(default_factory=list)
    collision_resource: str | None = None
    acceptance_evidence: list[str] = Field(default_factory=list)
    # Delivery-sprint provenance for the automatic coarse route. These fields
    # are optional so old generated scenes remain readable.
    generation_source: str = "legacy"
    fallback_reason: str | None = None
    layout_version: str | None = None
    estimated_scale: float | None = None
    quality_route: bool = False
    manual_assisted: bool = False
    manual_region_sha256: str | None = None
    photo_supported_regions: list[str] = Field(default_factory=list)
    generated_regions: list[str] = Field(default_factory=list)
