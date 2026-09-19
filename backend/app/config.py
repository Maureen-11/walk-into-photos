from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(_ENV_FILE)
except ImportError:
    # The demo still works without python-dotenv when variables are supplied
    # by the shell or process manager.
    pass


def _truthy(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _path_from_env(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    path = Path(value)
    return path if path.is_absolute() else (_ENV_FILE.parent / path).resolve()


@dataclass(frozen=True)
class Settings:
    mock_mode: bool = _truthy("MOCK_MODE", True)
    mock_geometry: bool = _truthy("MOCK_GEOMETRY", True)
    local_planner_enabled: bool = _truthy("LOCAL_PLANNER_ENABLED", True)
    local_planner_model: str = os.getenv("LOCAL_PLANNER_MODEL", "vikhyatk/moondream2")
    local_planner_revision: str = os.getenv("LOCAL_PLANNER_REVISION", "2025-06-21")
    local_files_only: bool = _truthy("LOCAL_FILES_ONLY", False)
    local_planner_detect_regions: bool = _truthy("LOCAL_PLANNER_DETECT_REGIONS", False)
    local_planner_cache: Path = _path_from_env("LOCAL_PLANNER_CACHE", os.getenv("HF_HOME", "../model-cache/huggingface"))
    moge_version: str = os.getenv("MOGE_VERSION", "v2")
    moge_pretrained: str = os.getenv("MOGE_PRETRAINED", "Ruicheng/moge-2-vits-normal")
    moge_resize: int = int(os.getenv("MOGE_RESIZE", "1024"))
    moge_quick_resize: int = int(os.getenv("MOGE_QUICK_RESIZE", "768"))
    moge_full_resize: int = int(os.getenv("MOGE_FULL_RESIZE", "1280"))
    # The deadline route uses a deterministic coarse scene so a valid upload
    # always produces a walkable result when the quality route cannot run.
    coarse_scene_enabled: bool = _truthy("COARSE_SCENE_ENABLED", True)
    # Real runs use the photo-supported MoGe route by default. Demo/mock runs
    # still use the deterministic coarse scene because no model is required.
    quality_scene_enabled: bool = _truthy("QUALITY_SCENE_ENABLED", True)
    scene_ttl_hours: int = int(os.getenv("SCENE_TTL_HOURS", "24"))
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    experimental_context_shell: bool = _truthy("EXPERIMENTAL_CONTEXT_SHELL", True)
    cors_allow_origins: tuple[str, ...] = tuple(
        origin.strip()
        for origin in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
        if origin.strip()
    )
    data_dir: Path = _path_from_env("DATA_DIR", "../data")

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def intermediates_dir(self) -> Path:
        return self.data_dir / "intermediates"

    @property
    def scenes_dir(self) -> Path:
        return self.data_dir / "scenes"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "state.sqlite3"

    def ensure_dirs(self) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.intermediates_dir.mkdir(parents=True, exist_ok=True)
        self.scenes_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
