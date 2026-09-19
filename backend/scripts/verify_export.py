"""Verify the contents of a walk-into-photos offline export.

This is a package-integrity check, not by itself proof that the package opens on
another computer. 给它 ``--catalog`` 时，它会读取同一 run 的 ``catalog.json`` 里
``records[].offline_verification``（由 ``verify_offline_delivery.py`` 通过真实浏览器
以 ``file://`` 跑出来的结论），把状态从 ``needs_offline_run`` 升级为
``offline_verified``；否则维持 ``needs_offline_run``。

状态含义：
    ``failed``             包内容不合格（缺文件、含原图、含远程引用等）
    ``needs_offline_run``  包内容合格，但尚无真实 file:// 运行结论
    ``offline_verified``   包内容合格，且已在本机浏览器以 file:// 打开并通过
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path


REQUIRED = {"index.html", "scene.glb", "manifest.json", "three.module.js", "GLTFLoader.js", "BufferGeometryUtils.js", "README.txt"}


def _catalog_verdict(catalog_path: Path, package_path: Path) -> dict[str, object] | None:
    """Return the offline_verification block recorded for this package, if any."""
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        target = package_path.resolve()
    except OSError:
        target = package_path
    for record in payload.get("records") or []:
        archive = record.get("archive")
        if not archive:
            continue
        try:
            if Path(archive).resolve() == target:
                return record.get("offline_verification")
        except OSError:
            continue
    return None


def verify(package_path: Path, offline_verdict: dict[str, object] | None = None) -> dict[str, object]:
    try:
        with zipfile.ZipFile(package_path) as archive:
            names = set(archive.namelist())
            missing = sorted(REQUIRED - names)
            unexpected_source = "source.jpg" in names
            index = archive.read("index.html").decode("utf-8", errors="replace") if "index.html" in names else ""
            manifest = json.loads(archive.read("manifest.json")) if "manifest.json" in names else {}
            collision_resource = manifest.get("collision_resource")
            collision_resource_present = not collision_resource or collision_resource in names
            collision_resource_listed = not collision_resource or collision_resource in manifest.get("resource_manifest", [])
            has_remote_import = bool(re.search(
                r"(?im)^\s*import\b[^\n]*(?:https?:|from\s+['\"](?:https?:|\./))"
                r"|\bfetch\(\s*['\"]https?:",
                index,
            ))
            content_failed = missing or unexpected_source or has_remote_import or not collision_resource_present or not collision_resource_listed
            verified = bool(offline_verdict) and offline_verdict.get("status") == "pass"
            if content_failed:
                package_status = "failed"
                interpretation = "包内容不合格，先修包再谈离线验收。"
            elif verified:
                package_status = "offline_verified"
                interpretation = "包内容完整，且已在本机浏览器以 file:// 打开并通过（离线验证由 verify_offline_delivery.py 背书）。"
            else:
                package_status = "needs_offline_run"
                interpretation = "包内容完整；尚无真实 file:// 运行结论，请跑 verify_offline_delivery.py。"
            result = {
                "package": package_path.name,
                "bytes": package_path.stat().st_size,
                "required_entries_present": not missing,
                "missing_entries": missing,
                "contains_source_photo": unexpected_source,
                "has_remote_import": has_remote_import,
                "scene_id": manifest.get("scene_id"),
                "template": manifest.get("template"),
                "collision_resource": collision_resource,
                "collision_resource_present": collision_resource_present,
                "collision_resource_listed": collision_resource_listed,
                "package_status": package_status,
                "interpretation": interpretation,
            }
            if offline_verdict is not None:
                result["offline_verification"] = {
                    "status": offline_verdict.get("status"),
                    "mode": offline_verdict.get("mode"),
                    "checked_at": offline_verdict.get("checked_at"),
                    "report": offline_verdict.get("report"),
                }
            return result
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        return {"package": package_path.name, "package_status": "failed", "error": type(exc).__name__}


def main() -> int:
    parser = argparse.ArgumentParser(description="检查离线场景包完整性；给出 --catalog 时按真实 file:// 验证结论升级状态")
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--catalog", type=Path, help="同 run 的 catalog.json；用其中的 offline_verification 升级状态")
    args = parser.parse_args()
    offline_verdict = _catalog_verdict(args.catalog, args.package) if args.catalog else None
    result = verify(args.package, offline_verdict)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0 if result.get("package_status") != "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
