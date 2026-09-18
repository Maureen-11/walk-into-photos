from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
for extra in (BACKEND_DIR, SCRIPT_DIR):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

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
    if manifest.style_route not in {"pixel_style_sample_v2", "pixel_style_sample_v3", "pixel_style_sample_v5", "pixel_style_sample_v6", "pixel_style_sample_v7", "pixel_style_sample_v8", "pixel_style_sample_v9", "pixel_style_sample_v10", "pixel_style_sample_v11", "pixel_style_sample_v12", "pixel_style_sample_v13", "pixel_style_sample_v14", "pixel_style_sample_v15", "pixel_style_sample_v16", "pixel_style_sample_v17", "pixel_style_sample_v18", "pixel_style_sample_v19", "pixel_style_sample_v20", "pixel_style_sample_v21", "pixel_style_sample_v22", "pixel_style_sample_v23", "pixel_style_sample_v24", "pixel_style_sample_v25", "pixel_style_sample_v26", "pixel_style_sample_v27", "pixel_style_sample_v28", "pixel_style_sample_v29", "pixel_style_sample_v30", "pixel_style_sample_v31", "pixel_style_sample_v32", "pixel_style_sample_v33", "pixel_style_sample_v34", "pixel_style_sample_v35", "pixel_style_sample_v36", "pixel_style_sample_v37", "pixel_style_sample_v38", "pixel_style_sample_v39", "pixel_style_sample_v40", "pixel_style_sample_v41", "pixel_style_sample_v42"}:
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
    parser.add_argument("--verify", action="store_true", help="写完 catalog 后立即跑真实 file:// 离线验证，并把 verdict 合并进 catalog")
    parser.add_argument("--verify-cmd", type=Path, help="offline-verify 的 run-verify.cmd 路径（默认自动探测）")
    parser.add_argument("--verify-timeout", type=int, default=240, help="每个产物验证超时秒数")
    parser.add_argument("--verify-headed", action="store_true", help="离线验证用真实 GPU（弹出浏览器窗口）")
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

    if args.verify:
        from verify_offline_delivery import verify_catalog

        summary = verify_catalog(
            args.output,
            verify_cmd=args.verify_cmd,
            timeout=args.verify_timeout,
            headed=args.verify_headed,
        )
        print(json.dumps(summary, ensure_ascii=False))
        return 1 if (summary["fail"] or summary["skipped"]) else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
