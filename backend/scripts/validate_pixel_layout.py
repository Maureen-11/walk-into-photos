"""Preflight the shared pixel layout/collision contract.

This is a static Q04 precheck.  It does not claim that a browser route has
been walked or that a collision looks correct in the rendered scene; those
claims still require the synchronized route recording and visual review.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{label} must be finite")
    return float(value)


def _pair(value: Any, label: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} must contain two numbers")
    return _finite(value[0], label), _finite(value[1], label)


def _point(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{label} must contain three numbers")
    return tuple(_finite(item, label) for item in value)  # type: ignore[return-value]


def _inside_box(point: tuple[float, float, float], box: dict[str, Any], radius: float) -> bool:
    x_bounds = _pair(box["bounds"]["x"], "collision x bounds")
    z_bounds = _pair(box["bounds"]["z"], "collision z bounds")
    return (
        x_bounds[0] - radius <= point[0] <= x_bounds[1] + radius
        and z_bounds[0] - radius <= point[2] <= z_bounds[1] + radius
    )


def validate_layout(scene_dir: Path) -> dict[str, Any]:
    layout = json.loads((scene_dir / "layout.json").read_text(encoding="utf-8"))
    collision = json.loads((scene_dir / "collision.json").read_text(encoding="utf-8"))
    manifest = json.loads((scene_dir / "manifest.json").read_text(encoding="utf-8"))
    movement = layout.get("movement")
    if not isinstance(movement, dict):
        raise ValueError("layout movement is missing")
    movement_boxes = movement.get("collision_boxes", [])
    collision_boxes = collision.get("boxes", [])
    if not isinstance(movement_boxes, list) or not isinstance(collision_boxes, list) or not movement_boxes:
        raise ValueError("collision boxes are missing")
    movement_ids = {str(item.get("box_id")) for item in movement_boxes if isinstance(item, dict)}
    collision_ids = {str(item.get("box_id")) for item in collision_boxes if isinstance(item, dict)}
    object_ids = {
        str(item.get("collision_box_id"))
        for item in layout.get("objects", [])
        if isinstance(item, dict) and item.get("collision_box_id")
    }
    checks: dict[str, bool] = {
        "manifest_layout_version_matches": manifest.get("layout_version") == layout.get("layout_version") == collision.get("layout_version"),
        "movement_collision_ids_match": movement_ids == collision_ids,
        "collision_ids_have_visible_objects": collision_ids <= object_ids,
        "collision_bounds_valid": True,
        "start_inside_bounds": True,
        "start_outside_expanded_collisions": True,
        "route_checkpoints_inside_bounds": True,
        "route_checkpoints_outside_expanded_collisions": True,
    }
    for index, box in enumerate(collision_boxes):
        x_bounds = _pair(box.get("bounds", {}).get("x"), f"collision[{index}] x bounds")
        z_bounds = _pair(box.get("bounds", {}).get("z"), f"collision[{index}] z bounds")
        if not x_bounds[0] < x_bounds[1] or not z_bounds[0] < z_bounds[1]:
            checks["collision_bounds_valid"] = False

    start = _point(movement.get("start"), "movement start")
    bounds = movement.get("bounds")
    if not isinstance(bounds, dict):
        raise ValueError("movement bounds are missing")
    for axis, value in zip(("x", "y", "z"), start):
        pair = _pair(bounds.get(axis), f"movement {axis} bounds")
        if not pair[0] <= value <= pair[1]:
            checks["start_inside_bounds"] = False
    radius = _finite(movement.get("collision_radius", 0.0), "collision radius")
    checks["start_outside_expanded_collisions"] = not any(_inside_box(start, box, radius) for box in collision_boxes)

    checkpoints = movement.get("route_checkpoints", [])
    if not isinstance(checkpoints, list):
        raise ValueError("route checkpoints must be a list")
    for index, raw_point in enumerate(checkpoints):
        point = _point(raw_point, f"route checkpoint[{index}]")
        for axis, value in zip(("x", "y", "z"), point):
            pair = _pair(bounds.get(axis), f"movement {axis} bounds")
            if not pair[0] <= value <= pair[1]:
                checks["route_checkpoints_inside_bounds"] = False
        if any(_inside_box(point, box, radius) for box in collision_boxes):
            checks["route_checkpoints_outside_expanded_collisions"] = False

    return {
        "scene_dir": str(scene_dir.resolve()),
        "scene_id": manifest.get("scene_id"),
        "layout_version": layout.get("layout_version"),
        "collision_count": len(collision_boxes),
        "object_count": len(layout.get("objects", [])),
        "checks": checks,
        "status": "pass" if all(checks.values()) else "unverified",
        "interpretation": "通过只表示布局和碰撞数据静态一致；实际碰撞、穿透、失焦和视觉质量仍需浏览器路线证据。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 Luna 像素场景的布局/碰撞静态契约")
    parser.add_argument("--scene-dir", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    try:
        report = validate_layout(args.scene_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"scene_dir": str(args.scene_dir), "status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
