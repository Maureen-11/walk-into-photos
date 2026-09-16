from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models import SceneManifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _scene_record(scene_dir: Path, archive: Path) -> dict[str, object]:
    manifest = SceneManifest.model_validate_json((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    layout = json.loads((scene_dir / "layout.json").read_text(encoding="utf-8"))
    collision = json.loads((scene_dir / "collision.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
        bad_member = package.testzip()
    required = {"index.html", "scene.glb", "manifest.json", "layout.json", "collision.json", "three.module.js", "GLTFLoader.js", "BufferGeometryUtils.js", "README.txt"}
    missing = sorted(required - names)
    if bad_member is not None or missing:
        raise ValueError(f"invalid archive {archive}: bad={bad_member!r}, missing={missing}")
    if manifest.style_route not in {"pixel_style_sample_v2", "pixel_style_sample_v3", "pixel_style_sample_v5"}:
        raise ValueError(f"unexpected style route: {manifest.style_route}")
    if not manifest.movement.collision_boxes:
        raise ValueError(f"no collision boxes: {scene_dir}")
    return {
        "scene_id": manifest.scene_id,
        "template": manifest.template.value,
        "profile": layout.get("profile"),
        "style_route": manifest.style_route,
        "version": manifest.version,
        "quality_status": manifest.quality_status,
        "input_sha256": manifest.input_sha256,
        "layout_version": manifest.layout_version,
        "object_count": len(layout.get("objects", [])),
        "collision_count": len(collision.get("boxes", [])),
        "scene_glb_sha256": _sha256(scene_dir / "scene.glb"),
        "manifest_sha256": _sha256(scene_dir / "manifest.json"),
        "layout_sha256": _sha256(scene_dir / "layout.json"),
        "zip_sha256": _sha256(archive),
        "zip_bytes": archive.stat().st_size,
        "archive": str(archive.resolve()),
        "scene_dir": str(scene_dir.resolve()),
        "offline_resources": sorted(required),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and catalogue isolated Luna pixel delivery candidates.")
    parser.add_argument("--output", type=Path, required=True, help="Catalog JSON output path")
    parser.add_argument("--scene", action="append", required=True, metavar="LABEL=SCENE_DIR", help="Scene directory")
    parser.add_argument("--archive", action="append", required=True, metavar="LABEL=ZIP", help="Matching offline ZIP")
    args = parser.parse_args()
    scenes = dict(item.split("=", 1) for item in args.scene)
    archives = dict(item.split("=", 1) for item in args.archive)
    if set(scenes) != set(archives):
        parser.error("scene labels and archive labels must match")
    records = [_scene_record(Path(scenes[label]), Path(archives[label])) for label in sorted(scenes)]
    payload = {"catalog_version": "pixel-delivery-v1", "records": records, "all_quality_status": "unverified"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "count": len(records), "scene_ids": [record["scene_id"] for record in records]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
