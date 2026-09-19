"""Build the V49 role-material and lighting candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.material_refinement import build_refined_corridor_v49


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--scene-id", default="pixel-q05-r49-i01")
    args = parser.parse_args()
    manifest = build_refined_corridor_v49(args.image.resolve(), args.output.resolve(), args.scene_id)
    print(json.dumps({
        "scene_id": manifest["scene_id"],
        "version": manifest["version"],
        "style_route": manifest["style_route"],
        "lighting_preset": manifest["pixel_spec"]["lighting_preset"],
        "material_adjustment_count": manifest["material_adjustment_count"],
        "quality_status": manifest["quality_status"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
