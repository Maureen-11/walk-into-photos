from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.pixel_scene import build_pixel_indoor_sample


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an isolated pixel-style indoor sample scene.")
    parser.add_argument("--input", type=Path, required=True, help="Source image path")
    parser.add_argument("--output", type=Path, required=True, help="New output scene directory")
    parser.add_argument("--scene-id", default="pixel-v01-i02", help="Manifest scene id")
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"input image does not exist: {args.input}")
    payload = build_pixel_indoor_sample(args.input, args.output, args.scene_id)
    print(json.dumps({
        "scene_id": payload["scene_id"],
        "output": str(args.output.resolve()),
        "style_route": payload["style_route"],
        "quality_status": payload["quality_status"],
        "input_sha256": payload["input_sha256"],
        "object_count": len(json.loads((args.output / "layout.json").read_text(encoding="utf-8"))["objects"]),
        "collision_count": len(payload["movement"]["collision_boxes"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
