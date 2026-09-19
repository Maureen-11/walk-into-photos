"""Verify the offline (file://) verdict of a Luna pixel delivery catalog.

背景
----
``verify_export.py`` 只是「包完整性检查」，它的状态永远停在 ``needs_offline_run``
（"仍需在另一台电脑断网双击打开"）。本脚本补上这一步的终点：

    真正用本机浏览器以 ``file://`` 打开产物并断言结果。

它调用 ``offline-verify`` 工具（Playwright 直接驱动本机 Chrome，**不经过** Codex
浏览器插件——插件的导航 URL 策略硬编码只允许 about:blank/http/https，永远打不开
``file://``），然后把终态 verdict 合并回 ``catalog.json``：

    records[].offline_verification = { status, verdict, checked_at, report, screenshots, ... }
    all_offline_verification       = "pass" | "fail" | "unverified"

``quality_status``（来自 manifest，表示场景质量）保持不变，离线可运行性单独记录。

用法
----
    # 校验整个 catalog（每个 archive 跑一次真实 file:// 验证，并回写 verdict）
    python backend/scripts/verify_offline_delivery.py --catalog <run>/catalog.json

    # 只验一个包
    python backend/scripts/verify_offline_delivery.py --archive <run>/pixel-v05-b01-offline.zip

    # 真实 GPU 结论（会弹出浏览器窗口）；默认无头 + SwiftShader 软件渲染
    python backend/scripts/verify_offline_delivery.py --catalog <catalog.json> --headed

    # 把 skipped/fail 也当作失败退出（CI / 严格交付）
    python backend/scripts/verify_offline_delivery.py --catalog <catalog.json> --strict

退出码：0 = 全部 pass（或未加 --strict 时无非 pass 也可）；1 = 存在 fail/skipped 且 --strict；
2 = 用法或环境错误。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_VERIFY_CMD_CANDIDATES = (
    Path(r"D:\CodexProjects\offline-verify\run-verify.cmd"),
    Path(__file__).resolve().parents[3] / "offline-verify" / "run-verify.cmd",
)
REPORT_NAME = "verify-report.json"
SCREENSHOTS = ("shot-file.png", "shot-http.png")


def find_verify_cmd(explicit: Path | None) -> Path | None:
    """Locate the offline-verify entry point (.cmd preferred; .ps1 needs Bypass so it is not used here)."""
    candidates: list[Path] = []
    env_value = os.environ.get("OFFLINE_VERIFY_CMD")
    if env_value:
        candidates.append(Path(env_value))
    if explicit:
        candidates.insert(0, explicit)
    candidates.extend(DEFAULT_VERIFY_CMD_CANDIDATES)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    found = shutil.which("run-verify.cmd") or shutil.which("run-verify")
    return Path(found) if found else None


def _rel(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def run_offline_verify(
    archive: Path,
    out_dir: Path,
    verify_cmd: Path,
    timeout: int,
    headed: bool = False,
) -> dict[str, Any]:
    """Run the offline-verify harness for one archive and read its report."""
    out_dir.mkdir(parents=True, exist_ok=True)
    command = ["cmd.exe", "/c", str(verify_cmd), "-Zip", str(archive.resolve()), "-OutDir", str(out_dir.resolve())]
    if headed:
        command.append("-Headed")
    result: dict[str, Any] = {
        "status": "skipped",
        "verdict": None,
        "mode": "headed" if headed else "headless-swiftshader",
        "tool": "offline-verify",
        "command": " ".join(command[2:]),
    }
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        result["error"] = f"timeout after {timeout}s"
        result["status"] = "fail"
        return result
    except OSError as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["status"] = "skipped"
        return result

    result["exit_code"] = process.returncode
    report_path = out_dir / REPORT_NAME
    if not report_path.is_file():
        result["status"] = "fail" if process.returncode == 1 else "skipped"
        result["error"] = (process.stderr or process.stdout or "").strip()[-400:] or "no verify-report.json produced"
        return result

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result["status"] = "fail"
        result["error"] = f"unreadable report: {exc}"
        return result

    l1 = report.get("l1_static") or {}
    l2 = report.get("l2_file_protocol") or {}
    l3 = report.get("l3_http_crosscheck") or {}
    webgl = ((l2.get("gl") or {}).get("webgl") or {})
    result.update(
        {
            "status": "pass" if report.get("verdict") == "pass" else "fail",
            "verdict": report.get("verdict"),
            "checked_at": report.get("generatedAt"),
            "tool_schema": report.get("schema"),
            "report": str(report_path.resolve()),
            "screenshots": [str((out_dir / name).resolve()) for name in SCREENSHOTS if (out_dir / name).is_file()],
            "static_audit": {
                "external_refs": len(l1.get("externalRefs") or []),
                "blockers": [item.get("label") for item in (l1.get("blockers") or [])],
                "warnings": {item.get("label"): item.get("count") for item in (l1.get("warnings") or [])},
            },
            "file_protocol": {
                "requests": len(l2.get("requests") or []),
                "failures": len(l2.get("failures") or []),
                "console_errors": len(l2.get("consoleErrors") or []),
                "page_errors": len(l2.get("pageErrors") or []),
                "image": l2.get("image"),
                "webgl": webgl.get("version"),
                "renderer": webgl.get("renderer"),
            },
            "http_crosscheck": (
                {"verdict": l3.get("verdict"), "requests": len(l3.get("requests") or [])} if l3 else None
            ),
            "blockers": list(l2.get("blockers") or []),
            "notes": list(report.get("notes") or []),
        }
    )
    return result


def run_integrity_check(archive: Path, out_dir: Path, timeout: int = 60) -> dict[str, Any] | None:
    """Reuse the existing verify_export.py integrity check (package contents + no remote imports)."""
    script = Path(__file__).resolve().parent / "verify_export.py"
    if not script.is_file():
        return None
    json_out = out_dir / "integrity-report.json"
    command = [
        os.environ.get("PYTHON", "python"),
        str(script),
        "--package",
        str(archive.resolve()),
        "--json",
        str(json_out.resolve()),
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if not json_out.is_file():
        return None
    try:
        return json.loads(json_out.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def verify_catalog(
    catalog_path: Path,
    verify_cmd: Path | None = None,
    out_root: Path | None = None,
    timeout: int = 240,
    headed: bool = False,
    only: str | None = None,
    integrity: bool = True,
    gpu_check: bool = False,
) -> dict[str, Any]:
    """Verify every archive referenced by the catalog and merge the verdicts back into it."""
    catalog_path = catalog_path.resolve()
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    records = payload.get("records") or []
    base_dir = catalog_path.parent
    out_root = (out_root or (base_dir / "offline-verify")).resolve()
    gpu_root = out_root.parent / f"{out_root.name}-gpu"
    resolved_cmd = find_verify_cmd(verify_cmd)
    if resolved_cmd is None:
        raise FileNotFoundError(
            "找不到 offline-verify 的 run-verify.cmd；用 --verify-cmd 指定，或设置环境变量 OFFLINE_VERIFY_CMD"
        )

    tally = {"pass": 0, "fail": 0, "skipped": 0}
    gpu_tally = {"pass": 0, "fail": 0, "skipped": 0}
    for record in records:
        scene_id = record.get("scene_id") or "unknown"
        if only and scene_id != only:
            continue
        archive_raw = record.get("archive")
        if not archive_raw:
            record["offline_verification"] = {"status": "skipped", "error": "record has no archive path"}
            tally["skipped"] += 1
            continue
        archive = Path(archive_raw)
        if not archive.is_file():
            record["offline_verification"] = {"status": "skipped", "error": f"archive missing: {archive}"}
            tally["skipped"] += 1
            continue

        out_dir = out_root / scene_id
        previous = record.get("offline_verification") or {}
        block = run_offline_verify(archive, out_dir, resolved_cmd, timeout, headed)
        if integrity:
            integrity_report = run_integrity_check(archive, out_dir)
            if integrity_report is not None:
                block["package_integrity"] = {
                    "package_status": integrity_report.get("package_status"),
                    "required_entries_present": integrity_report.get("required_entries_present"),
                    "missing_entries": integrity_report.get("missing_entries"),
                    "contains_source_photo": integrity_report.get("contains_source_photo"),
                    "has_remote_import": integrity_report.get("has_remote_import"),
                }
        block["report"] = _rel(Path(block["report"]), base_dir) if block.get("report") else None
        block["screenshots"] = [_rel(Path(item), base_dir) for item in block.get("screenshots") or []]

        if gpu_check:
            gpu_block = run_offline_verify(archive, gpu_root / scene_id, resolved_cmd, timeout, headed=True)
            gpu_block["report"] = _rel(Path(gpu_block["report"]), base_dir) if gpu_block.get("report") else None
            gpu_block["screenshots"] = [_rel(Path(item), base_dir) for item in gpu_block.get("screenshots") or []]
            block["gpu_check"] = gpu_block
        elif isinstance(previous.get("gpu_check"), dict) and previous["gpu_check"].get("report"):
            # 保留此前已收集的 GPU 复核结论，避免"重跑门槛"把证据抹掉
            block["gpu_check"] = previous["gpu_check"]
        if isinstance(block.get("gpu_check"), dict):
            gpu_status = block["gpu_check"].get("status", "skipped")
            gpu_tally[gpu_status] = gpu_tally.get(gpu_status, 0) + 1

        record["offline_verification"] = block
        tally[block["status"]] = tally.get(block["status"], 0) + 1

    stamp = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    payload["offline_verification_summary"] = {
        "pass": tally["pass"],
        "fail": tally["fail"],
        "skipped": tally["skipped"],
        "tool": str(resolved_cmd),
        "mode": "headed" if headed else "headless-swiftshader",
        "updated_at": stamp,
    }
    if gpu_check or any(gpu_tally.values()):
        payload["offline_verification_summary"]["gpu_check"] = gpu_tally
    if tally["fail"]:
        payload["all_offline_verification"] = "fail"
    elif tally["skipped"] or not records:
        payload["all_offline_verification"] = "unverified"
    else:
        payload["all_offline_verification"] = "pass"

    tmp_path = catalog_path.with_suffix(catalog_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, catalog_path)
    return {"catalog": str(catalog_path), **payload["offline_verification_summary"], "all_offline_verification": payload["all_offline_verification"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="跑真实 file:// 离线验证，把 verdict 写回 catalog.json（补上 verify_export.py 的 needs_offline_run 终点）")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--catalog", type=Path, help="Catalog JSON to verify and update")
    target.add_argument("--archive", type=Path, help="单个离线 ZIP；只打印结果，不改 catalog")
    parser.add_argument("--verify-cmd", type=Path, help="run-verify.cmd 路径（默认自动探测）")
    parser.add_argument("--out-root", type=Path, help="验证报告目录（默认 <catalog 同级>/offline-verify）")
    parser.add_argument("--timeout", type=int, default=240, help="每个产物的验证超时秒数")
    parser.add_argument("--headed", action="store_true", help="用真实 GPU 跑（弹出浏览器窗口）")
    parser.add_argument("--only", help="只验证指定 scene_id")
    parser.add_argument("--no-integrity", action="store_true", help="跳过 verify_export.py 的包完整性检查")
    parser.add_argument("--gpu-check", action="store_true", help="额外用真实 GPU（--headed）再验证一遍，结果存 records[].offline_verification.gpu_check")
    parser.add_argument("--strict", action="store_true", help="存在 fail/skipped 时返回退出码 1")
    args = parser.parse_args()

    if args.archive:
        cmd = find_verify_cmd(args.verify_cmd)
        if cmd is None:
            print(json.dumps({"error": "run-verify.cmd not found"}, ensure_ascii=False))
            return 2
        out_dir = (args.out_root or (args.archive.resolve().parent / "offline-verify")).resolve() / args.archive.stem
        block = run_offline_verify(args.archive, out_dir, cmd, args.timeout, args.headed)
        print(json.dumps(block, ensure_ascii=False, indent=2))
        if args.strict and block["status"] != "pass":
            return 1
        return 0

    try:
        summary = verify_catalog(
            args.catalog,
            verify_cmd=args.verify_cmd,
            out_root=args.out_root,
            timeout=args.timeout,
            headed=args.headed,
            only=args.only,
            integrity=not args.no_integrity,
            gpu_check=args.gpu_check,
        )
    except FileNotFoundError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    if args.strict and (summary["fail"] or summary["skipped"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
