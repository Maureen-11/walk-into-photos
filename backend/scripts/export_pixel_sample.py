from __future__ import annotations

import argparse
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import _build_offline_archive


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a generated pixel sample as a self-contained offline ZIP.")
    parser.add_argument("--scene-dir", type=Path, required=True, help="Generated scene directory")
    parser.add_argument("--output", type=Path, required=True, help="ZIP output path")
    args = parser.parse_args()
    for name in ("scene.glb", "manifest.json"):
        if not (args.scene_dir / name).is_file():
            parser.error(f"missing {name} in scene directory")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_build_offline_archive(args.scene_dir))
    print(f"archive={args.output.resolve()}")
    print(f"bytes={args.output.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
