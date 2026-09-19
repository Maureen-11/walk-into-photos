from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.pixel_scene import build_pixel_corridor_v06, build_pixel_living_v06


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an isolated V06 pixel-detail refinement candidate.")
    parser.add_argument("--input", type=Path, required=True, help="Source image path")
    parser.add_argument("--output", type=Path, required=True, help="New output scene directory")
    parser.add_argument("--scene-id", required=True, help="Manifest scene id")
    parser.add_argument("--profile", choices=("corridor", "living_room"), required=True)
    parser.add_argument("--layout-variant", choices=("generic", "i01"), default="generic", help="Photo-specific layout basis")
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"input image does not exist: {args.input}")
    if args.profile == "corridor":
        payload = build_pixel_corridor_v06(args.input, args.output, args.scene_id, layout_variant=args.layout_variant)
    else:
        payload = build_pixel_living_v06(args.input, args.output, args.scene_id)
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
