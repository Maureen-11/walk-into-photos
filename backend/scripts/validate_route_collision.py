"""Correlate a route's stationary movement frames with layout collision boxes.

The route recorder can detect a key held while the position stops, but that
signal alone could also be caused by the outer movement bounds.  This checker
joins the route JSON with layout.json and reports which explanation matches.
It does not claim visual quality or replace a human inspection of the video.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

MOVEMENT_KEYS = {"w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright"}


def _point(value: Any) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("position must contain three numbers")
    numbers = tuple(float(item) for item in value)
    if not all(math.isfinite(item) for item in numbers):
        raise ValueError("position must be finite")
    return numbers  # type: ignore[return-value]


def _inside_or_contact(point: tuple[float, float, float], box: dict[str, Any], radius: float, step_tolerance: float = 0.13) -> bool:
    bounds = box.get("bounds", {})
    x_bounds = bounds.get("x")
    z_bounds = bounds.get("z")
    if not isinstance(x_bounds, list) or not isinstance(z_bounds, list) or len(x_bounds) != 2 or len(z_bounds) != 2:
        return False
    expanded_x = (float(x_bounds[0]) - radius, float(x_bounds[1]) + radius)
    expanded_z = (float(z_bounds[0]) - radius, float(z_bounds[1]) + radius)
    x_inside = expanded_x[0] <= point[0] <= expanded_x[1]
    z_inside = expanded_z[0] <= point[2] <= expanded_z[1]
    # The viewer stops on the last safe sub-step.  A contact point can
    # therefore be just outside the expanded box by at most one movement
    # sub-step rather than numerically inside it.
    x_near = min(abs(point[0] - expanded_x[0]), abs(point[0] - expanded_x[1])) <= step_tolerance
    z_near = min(abs(point[2] - expanded_z[0]), abs(point[2] - expanded_z[1])) <= step_tolerance
    return (x_inside and z_inside) or (x_inside and z_near) or (z_inside and x_near)


def _on_outer_bound(point: tuple[float, float, float], bounds: dict[str, Any], epsilon: float = 0.01) -> bool:
    # Horizontal route evidence keeps y fixed at the ground plane by design;
    # do not classify that intentional ground clamp as an outer-bound stop.
    for axis, value in (("x", point[0]), ("z", point[2])):
        pair = bounds.get(axis)
        if isinstance(pair, list) and len(pair) == 2 and min(abs(value - float(pair[0])), abs(value - float(pair[1]))) <= epsilon:
            return True
    return False


def validate_route_collision(route_path: Path, layout_path: Path) -> dict[str, Any]:
    route = json.loads(route_path.read_text(encoding="utf-8"))
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    frames = route.get("frames")
    movement = layout.get("movement")
    if not isinstance(frames, list) or not frames:
        raise ValueError("route frames are missing")
    if not isinstance(movement, dict):
        raise ValueError("layout movement is missing")
    boxes = movement.get("collision_boxes", [])
    bounds = movement.get("bounds", {})
    radius = float(movement.get("collision_radius", 0.0))
    stationary: list[dict[str, Any]] = []
    for index in range(1, len(frames)):
        before = _point(frames[index - 1].get("position"))
        after = _point(frames[index].get("position"))
        keys = set(frames[index].get("keys", []))
        distance = math.hypot(after[0] - before[0], after[2] - before[2])
        if keys.intersection(MOVEMENT_KEYS) and distance < 1e-4:
            matching = [str(box.get("box_id")) for box in boxes if isinstance(box, dict) and _inside_or_contact(after, box, radius)]
            stationary.append({
                "frame_index": index,
                "at_ms": float(frames[index].get("at_ms", 0.0)),
                "position": list(after),
                "keys": sorted(keys.intersection(MOVEMENT_KEYS)),
                "collision_boxes": matching,
                "on_outer_bound": _on_outer_bound(after, bounds),
            })
    collision_frames = [item for item in stationary if item["collision_boxes"]]
    bound_frames = [item for item in stationary if item["on_outer_bound"] and not item["collision_boxes"]]
    unknown_frames = [item for item in stationary if not item["collision_boxes"] and not item["on_outer_bound"]]
    checks = {
        "stationary_movement_observed": bool(stationary),
        "collision_contact_observed": bool(collision_frames),
        "not_outer_bound_only": bool(collision_frames) and not bound_frames,
    }
    return {
        "route": str(route_path.resolve()),
        "layout": str(layout_path.resolve()),
        "scene_id": route.get("scene_id"),
        "scene_version": route.get("scene_version"),
        "collision_radius": radius,
        "stationary_frames": len(stationary),
        "collision_contact_frames": len(collision_frames),
        "outer_bound_only_frames": len(bound_frames),
        "unclassified_frames": len(unknown_frames),
        "sample_collision_contact": collision_frames[:3] + collision_frames[-3:] if len(collision_frames) > 6 else collision_frames,
        "checks": checks,
        "status": "pass" if all(checks.values()) else "unverified",
        "interpretation": "通过表示轨迹静止段与布局碰撞盒相符且不是外边界单独造成；仍需结合录像检查是否有穿透。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="核对路线静止段是否由布局碰撞盒而非外边界造成")
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--layout", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    try:
        report = validate_route_collision(args.route, args.layout)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
