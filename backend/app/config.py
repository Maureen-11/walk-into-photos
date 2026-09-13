from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    # The demo still works without python-dotenv when variables are supplied
    # by the shell or process manager.
    pass


def _truthy(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_vision_model: str = os.getenv(
        "DEEPSEEK_VISION_MODEL", "deepseek-v4-flash-vision-exp"
    )
    invite_code: str = os.getenv("INVITE_CODE", "walk-demo")
    mock_mode: bool = _truthy("MOCK_MODE", True)
    mock_geometry: bool = _truthy("MOCK_GEOMETRY", True)
    moge_version: str = os.getenv("MOGE_VERSION", "v2")
    moge_pretrained: str = os.getenv("MOGE_PRETRAINED", "Ruicheng/moge-2-vits-normal")
    moge_resize: int = int(os.getenv("MOGE_RESIZE", "1024"))
    scene_ttl_hours: int = int(os.getenv("SCENE_TTL_HOURS", "24"))
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    data_dir: Path = Path(os.getenv("DATA_DIR", "../data")).resolve()

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def intermediates_dir(self) -> Path:
        return self.data_dir / "intermediates"

    @property
    def scenes_dir(self) -> Path:
        return self.data_dir / "scenes"

    def ensure_dirs(self) -> None:
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.intermediates_dir.mkdir(parents=True, exist_ok=True)
        self.scenes_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
