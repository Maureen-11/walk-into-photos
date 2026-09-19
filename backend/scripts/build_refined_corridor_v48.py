"""Build the additive, detail-preserving V48 corridor candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.detail_refinement import build_refined_corridor_v48


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--scene-id", default="pixel-q05-r48-i01")
    args = parser.parse_args()
    manifest = build_refined_corridor_v48(
        args.image.resolve(), args.output.resolve(), args.scene_id
    )
    print(
        json.dumps(
            {
                "scene_id": manifest["scene_id"],
                "version": manifest["version"],
                "style_route": manifest["style_route"],
                "output": str(args.output.resolve()),
                "quality_status": manifest.get("quality_status"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
