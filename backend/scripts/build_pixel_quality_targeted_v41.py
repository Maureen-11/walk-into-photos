from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.pixel_scene import build_pixel_building_v44, build_pixel_nature_v45


def main() -> int:
    parser = argparse.ArgumentParser(description="Build targeted Q03 pixel correction candidates without changing the street route.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("n01", "b01"), required=True)
    parser.add_argument("--scene-id")
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"input image does not exist: {args.input}")
    defaults = {
        "n01": (build_pixel_nature_v45, "pixel-q05-r45-n01"),
        "b01": (build_pixel_building_v44, "pixel-q05-r44-b01"),
    }
    builder, default_id = defaults[args.profile]
    payload = builder(args.input, args.output, args.scene_id or default_id)
    layout = json.loads((args.output / "layout.json").read_text(encoding="utf-8"))
    print(json.dumps({
        "scene_id": payload["scene_id"],
        "output": str(args.output.resolve()),
        "profile": args.profile,
        "style_route": payload["style_route"],
        "layout_version": payload["layout_version"],
        "quality_status": payload["quality_status"],
        "input_sha256": payload["input_sha256"],
        "object_count": len(layout["objects"]),
        "collision_count": len(payload["movement"]["collision_boxes"]),
        "lighting_preset": payload["pixel_spec"].get("lighting_preset"),
        "detail_pass": payload["pixel_spec"].get("detail_pass"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
