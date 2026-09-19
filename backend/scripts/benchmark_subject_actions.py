"""Validate the safety contract for photo-subject interactions.

T08 is not complete when a button exists.  An action needs a target region,
an explicitly accepted asset, a cooldown, and a non-target no-op rule.  This
script checks those facts in a manifest and produces a conservative report;
it never turns an ``experimental`` action into an available one.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _inside_unit_box(region: dict[str, Any]) -> bool:
    values = [region.get(key) for key in ("x", "y", "width", "height")]
    if any(value is None for value in values):
        return False
    try:
        x, y, width, height = [float(value) for value in values]
    except (TypeError, ValueError):
        return False
    return 0 <= x <= 1 and 0 <= y <= 1 and 0 < width <= 1 and 0 < height <= 1 and x + width <= 1 and y + height <= 1


def validate_manifest(payload: dict[str, Any], asset_root: Path | None = None) -> dict[str, Any]:
    regions = {str(item.get("region_id")): item for item in payload.get("subject_regions", []) if isinstance(item, dict)}
    actions = payload.get("actions", [])
    if not isinstance(actions, list):
        actions = []
    checks: list[dict[str, Any]] = []
    for item in actions:
        if not isinstance(item, dict):
            checks.append({"valid": False, "reason": "action_not_object"})
            continue
        action_id = str(item.get("action_id", ""))
        target_id = item.get("target_region_id")
        target = regions.get(str(target_id)) if target_id is not None else None
        asset_url = item.get("asset_url")
        asset_exists = False
        if asset_root is not None and isinstance(asset_url, str) and asset_url and not asset_url.startswith(("http://", "https://")):
            asset_exists = (asset_root / asset_url.lstrip("/\\")).is_file()
        status = str(item.get("status", "unverified"))
        reasons: list[str] = []
        if not action_id:
            reasons.append("missing_action_id")
        if target is None or not _inside_unit_box(target):
            reasons.append("missing_or_invalid_target_region")
        try:
            cooldown = int(item.get("cooldown_ms", 0))
        except (TypeError, ValueError):
            cooldown = 0
        if cooldown < 300:
            reasons.append("cooldown_too_short")
        if status == "available" and not asset_exists and asset_root is not None:
            reasons.append("available_asset_missing")
        if status != "available":
            reasons.append("asset_not_accepted")
        checks.append({"action_id": action_id, "status": status, "target_region_id": target_id, "asset_exists": asset_exists, "valid": not reasons, "reasons": reasons})
    available = [item for item in checks if item.get("valid")]
    return {
        "template": payload.get("template"),
        "experience_kind": payload.get("experience_kind"),
        "action_count": len(checks),
        "accepted_action_count": len(available),
        "checks": checks,
        "non_target_click": "no-op",
        "repeat_click": "blocked_until_cooldown",
        "machine_status": "needs_visual_review" if checks else "unverified",
        "interpretation": "动作状态和目标区域已结构化检查；尚未证明主体局部运动时背景稳定。" if checks else "没有动作候选，不能显示交互按钮。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="检查主体动作清单、目标区域和冷却约束，不把未验收动作标为可用")
    parser.add_argument("--manifest", type=Path, required=True, help="包含 actions 和 subject_regions 的 manifest.json")
    parser.add_argument("--output", type=Path, required=True, help="报告输出目录")
    parser.add_argument("--json", type=Path, help="可选 JSON 输出路径")
    parser.add_argument("--asset-root", type=Path, help="可选动作素材根目录，用于检查 available 素材")
    args = parser.parse_args()
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = validate_manifest(payload, args.asset_root)
    args.output.mkdir(parents=True, exist_ok=True)
    report_path = args.output / "subject-action-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
