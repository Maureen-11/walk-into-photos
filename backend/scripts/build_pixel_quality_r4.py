from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.pixel_scene import (
    build_pixel_building_v07,
    build_pixel_corridor_v08,
    build_pixel_living_v08,
    build_pixel_nature_v05,
    build_pixel_street_v07,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build isolated Q03 r4 authored pixel-composition candidates without changing the default route."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scene-id", required=True)
    parser.add_argument("--profile", choices=("living", "corridor", "nature", "street", "building"), required=True)
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"input image does not exist: {args.input}")
    builders = {
        "living": build_pixel_living_v08,
        "corridor": build_pixel_corridor_v08,
        "nature": build_pixel_nature_v05,
        "street": build_pixel_street_v07,
        "building": build_pixel_building_v07,
    }
    payload = builders[args.profile](args.input, args.output, args.scene_id)
    layout = json.loads((args.output / "layout.json").read_text(encoding="utf-8"))
    print(json.dumps({
        "scene_id": payload["scene_id"],
        "profile": layout["profile"],
        "output": str(args.output.resolve()),
        "style_route": payload["style_route"],
        "layout_version": payload["layout_version"],
        "quality_status": payload["quality_status"],
        "input_sha256": payload["input_sha256"],
        "object_count": len(layout["objects"]),
        "collision_count": len(payload["movement"]["collision_boxes"]),
        "detail_grids": sorted({item["voxel_grid"] for item in layout["objects"]}),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
