from __future__ import annotations

"""Run the local quality route over a photo folder and write an evidence table.

This intentionally runs one image at a time.  It is a local acceptance helper,
not a production queue, and never uploads the source photos anywhere.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

from app.config import Settings
from app.services.geometry import generate_scene
from app.services.photo_plan import analyze_photo


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="按顺序运行本地照片支持质量路线")
    parser.add_argument("--photos", type=Path, required=True, help="输入照片目录")
    parser.add_argument("--output", type=Path, required=True, help="新的证据输出目录")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    settings = Settings(data_dir=args.output / "data")
    suffixes = {".jpg", ".jpeg", ".png", ".webp"}
    photos = sorted(path for path in args.photos.iterdir() if path.is_file() and path.suffix.lower() in suffixes)
    rows: list[dict[str, object]] = []
    for index, photo in enumerate(photos, start=1):
        row: dict[str, object] = {
            "index": index,
            "filename": photo.name,
            "input_sha256": _sha256(photo),
        }
        started = time.perf_counter()
        try:
            plan = analyze_photo(photo, settings)
            row.update({
                "analysis_id": plan.analysis_id,
                "category": plan.category.value,
                "template": plan.recommended_template.value,
                "planner_backend": plan.planner_backend,
            })
            scene_path = args.output / f"{index:02d}-{photo.stem[:12]}" / "scene.glb"
            result = generate_scene(
                photo,
                scene_path,
                mock=False,
                settings=settings,
                version="full",
                template=plan.recommended_template,
                quality_route=True,
            )
            row.update({
                "scene_source": result.get("scene_source"),
                "provider_version": result.get("provider_version"),
                "fallback_reason": result.get("fallback_reason"),
                "quality_route_error": result.get("quality_route_error"),
                "coverage": result.get("coverage"),
                "stage_timings_ms": result.get("stage_timings_ms", {}),
                "output_sha256": _sha256(scene_path) if scene_path.is_file() else None,
                "resource_files": result.get("resource_files", []),
            })
        except Exception as exc:
            row.update({"scene_source": "failed", "error": type(exc).__name__})
        row["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
        rows.append(row)
        (args.output / "quality-batch.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(row, ensure_ascii=False))
    return 0 if rows and all(row.get("scene_source") != "failed" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
