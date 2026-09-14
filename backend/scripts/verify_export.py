"""Verify the contents of a walk-into-photos offline export.

This is a package-integrity check, not proof that another computer can open
the file. The report deliberately ends in ``needs_offline_run`` until a
second machine has opened the package with networking disabled.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path


REQUIRED = {"index.html", "scene.glb", "manifest.json", "three.module.js", "GLTFLoader.js", "BufferGeometryUtils.js", "README.txt"}


def verify(package_path: Path) -> dict[str, object]:
    try:
        with zipfile.ZipFile(package_path) as archive:
            names = set(archive.namelist())
            missing = sorted(REQUIRED - names)
            unexpected_source = "source.jpg" in names
            index = archive.read("index.html").decode("utf-8", errors="replace") if "index.html" in names else ""
            manifest = json.loads(archive.read("manifest.json")) if "manifest.json" in names else {}
            has_remote_import = "https://" in index or "http://" in index
            return {
                "package": package_path.name,
                "bytes": package_path.stat().st_size,
                "required_entries_present": not missing,
                "missing_entries": missing,
                "contains_source_photo": unexpected_source,
                "has_remote_import": has_remote_import,
                "scene_id": manifest.get("scene_id"),
                "template": manifest.get("template"),
                "package_status": "failed" if missing or unexpected_source or has_remote_import else "needs_offline_run",
                "interpretation": "包内容完整；仍需在另一台电脑断网双击打开并记录加载、移动和帧率。",
            }
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        return {"package": package_path.name, "package_status": "failed", "error": type(exc).__name__}


def main() -> int:
    parser = argparse.ArgumentParser(description="检查离线场景包完整性，不替代第二台电脑断网验收")
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    result = verify(args.package)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0 if result.get("package_status") != "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
