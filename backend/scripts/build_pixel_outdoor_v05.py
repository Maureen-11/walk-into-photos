from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.pixel_scene import build_pixel_building_v05, build_pixel_street_v05


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an isolated V05 pixel-style street or building candidate.")
    parser.add_argument("--input", type=Path, required=True, help="Source image path")
    parser.add_argument("--output", type=Path, required=True, help="New output scene directory")
    parser.add_argument("--scene-id", required=True, help="Manifest scene id")
    parser.add_argument("--profile", choices=("street", "building"), required=True)
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"input image does not exist: {args.input}")
    if args.profile == "street":
        payload = build_pixel_street_v05(args.input, args.output, args.scene_id)
    else:
        payload = build_pixel_building_v05(args.input, args.output, args.scene_id)
    layout = json.loads((args.output / "layout.json").read_text(encoding="utf-8"))
    print(json.dumps({
        "scene_id": payload["scene_id"],
        "profile": layout["profile"],
        "output": str(args.output.resolve()),
        "style_route": payload["style_route"],
        "quality_status": payload["quality_status"],
        "input_sha256": payload["input_sha256"],
        "object_count": len(layout["objects"]),
        "collision_count": len(payload["movement"]["collision_boxes"]),
        "detail_grids": sorted({item["voxel_grid"] for item in layout["objects"]}),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
