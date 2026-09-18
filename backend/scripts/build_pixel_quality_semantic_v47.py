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
    build_pixel_building_v47,
    build_pixel_corridor_v47,
    build_pixel_living_v47,
    build_pixel_nature_v47,
    build_pixel_street_v47,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Q03 V47 semantic surface hierarchy candidates.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("i01", "i02", "n01", "s01", "b01"), required=True)
    parser.add_argument("--scene-id", default=None)
    args = parser.parse_args()
    builders = {
        "i01": (build_pixel_corridor_v47, "pixel-q05-r47-i01"),
        "i02": (build_pixel_living_v47, "pixel-q05-r47-i02"),
        "n01": (build_pixel_nature_v47, "pixel-q05-r47-n01"),
        "s01": (build_pixel_street_v47, "pixel-q05-r47-s01"),
        "b01": (build_pixel_building_v47, "pixel-q05-r47-b01"),
    }
    builder, default_scene_id = builders[args.profile]
    manifest = builder(args.input, args.output, args.scene_id or default_scene_id)
    print(json.dumps({
        "scene_id": manifest["scene_id"],
        "output": str(args.output),
        "profile": args.profile,
        "style_route": manifest["style_route"],
        "layout_version": manifest["layout_version"],
        "quality_status": manifest["quality_status"],
        "input_sha256": manifest["input_sha256"],
        "detail_count": len(manifest.get("detail_object_ids", [])),
        "collision_count": len(manifest["movement"]["collision_boxes"]),
        "lighting_preset": manifest["pixel_spec"]["lighting_preset"],
        "detail_pass": manifest["quality_metrics"]["detail_pass"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
