"""Validate a recorded Luna route without claiming visual quality.

The viewer writes a route JSON and a separate WebM.  This checker only
inspects the synchronized JSON: it reports what was actually recorded and
keeps a route incomplete when the evidence does not contain sustained input,
turning, reset, or focus-loss events.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


MOVEMENT_KEYS = ("w", "a", "s", "d", "arrowup", "arrowdown", "arrowleft", "arrowright")
FOCUS_LOSS_EVENTS = {"blur", "visibilitychange"}


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _position(frame: dict[str, Any]) -> tuple[float, float, float]:
    value = frame.get("position")
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("each frame position must contain three numbers")
    return tuple(_number(item, "frame position") for item in value)  # type: ignore[return-value]


def _keys(frame: dict[str, Any]) -> set[str]:
    value = frame.get("keys", [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("each frame keys value must be a list of strings")
    return {item.lower() for item in value}


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.floor((len(ordered) - 1) * fraction))]


def _max_key_run(frames: list[dict[str, Any]], key: str) -> tuple[int, float]:
    best_count = 0
    best_duration = 0.0
    run_start: int | None = None
    for index, frame in enumerate(frames + [{"keys": [], "at_ms": frames[-1].get("at_ms", 0) if frames else 0}]):
        present = key in _keys(frame)
        if present and run_start is None:
            run_start = index
        if not present and run_start is not None:
            end_index = index - 1
            count = end_index - run_start + 1
            start_ms = _number(frames[run_start].get("at_ms", 0), "frame at_ms")
            end_ms = _number(frames[end_index].get("at_ms", start_ms), "frame at_ms")
            if count > best_count or (count == best_count and end_ms - start_ms > best_duration):
                best_count = count
                best_duration = max(0.0, end_ms - start_ms)
            run_start = None
    return best_count, best_duration


def validate_route(
    route_path: Path,
    *,
    min_duration_ms: float = 30_000.0,
    min_turn_degrees: float = 150.0,
    min_hold_ms: float = 500.0,
) -> dict[str, Any]:
    payload = json.loads(route_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("route JSON must contain an object")
    if payload.get("schema") != "luna-route-evidence/1":
        raise ValueError("unsupported route schema")
    frames = payload.get("frames")
    events = payload.get("events")
    if not isinstance(frames, list) or not frames:
        raise ValueError("route must contain a non-empty frames list")
    if not isinstance(events, list):
        raise ValueError("route must contain an events list")

    normalized_frames: list[dict[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, dict):
            raise ValueError("each route frame must be an object")
        _number(frame.get("at_ms"), "frame at_ms")
        _number(frame.get("delta_ms"), "frame delta_ms")
        _number(frame.get("yaw"), "frame yaw")
        _number(frame.get("pitch"), "frame pitch")
        _position(frame)
        _keys(frame)
        normalized_frames.append(frame)

    event_types = Counter(str(event.get("type")) for event in events if isinstance(event, dict))
    deltas = [_number(frame["delta_ms"], "frame delta_ms") for frame in normalized_frames]
    at_values = [_number(frame["at_ms"], "frame at_ms") for frame in normalized_frames]
    positions = [_position(frame) for frame in normalized_frames]
    yaws = [_number(frame["yaw"], "frame yaw") for frame in normalized_frames]
    xs = [item[0] for item in positions]
    zs = [item[2] for item in positions]
    movement_ranges = {"x": max(xs) - min(xs), "z": max(zs) - min(zs)}
    movement_span = math.hypot(movement_ranges["x"], movement_ranges["z"])
    key_runs = {
        key: {"max_frames": _max_key_run(normalized_frames, key)[0], "max_duration_ms": round(_max_key_run(normalized_frames, key)[1], 3)}
        for key in MOVEMENT_KEYS
    }
    sustained = {
        key: value for key, value in key_runs.items() if value["max_duration_ms"] >= min_hold_ms
    }
    stationary_while_moving = 0
    # The frame-to-frame stationary check below is intentionally based on the
    # current frame's movement keys; it is a candidate signal, not a proof of
    # collision without the scene layout and route video.
    for before, after, frame in zip(positions, positions[1:], normalized_frames[1:]):
        if _keys(frame).intersection(MOVEMENT_KEYS) and math.hypot(after[0] - before[0], after[2] - before[2]) < 1e-4:
            stationary_while_moving += 1

    yaw_span_radians = max(yaws) - min(yaws)
    yaw_span_degrees = math.degrees(yaw_span_radians)
    focus_loss_count = sum(event_types.get(name, 0) for name in FOCUS_LOSS_EVENTS)
    reset_count = event_types.get("reset", 0)
    checks = {
        "duration": at_values[-1] >= min_duration_ms,
        "sustained_input": bool(sustained),
        "turn": yaw_span_degrees >= min_turn_degrees,
        "reset": reset_count >= 1,
        "focus_loss": focus_loss_count >= 1,
        "movement": movement_span > 0.05,
    }
    warnings: list[str] = []
    if not checks["duration"]:
        warnings.append(f"录制时长不足 {min_duration_ms:.0f}ms")
    if not checks["sustained_input"]:
        warnings.append(f"没有检测到持续至少 {min_hold_ms:.0f}ms 的移动按键")
    if not checks["turn"]:
        warnings.append(f"最大记录转向约 {yaw_span_degrees:.1f}°，不足 {min_turn_degrees:.1f}°")
    if not checks["reset"]:
        warnings.append("没有记录 R 重置事件")
    if not checks["focus_loss"]:
        warnings.append("没有记录 blur 或 visibilitychange 事件")
    if not checks["movement"]:
        warnings.append("水平移动范围不足，不能判断路线移动")
    if stationary_while_moving:
        warnings.append("存在按移动键但位置不变的帧段；需结合碰撞布局和录像确认是否为碰撞")

    return {
        "route": str(route_path),
        "scene_id": payload.get("scene_id"),
        "scene_version": payload.get("scene_version"),
        "schema": payload["schema"],
        "status": "pass" if all(checks.values()) else "unverified",
        "checks": checks,
        "frames": len(normalized_frames),
        "duration_ms": round(at_values[-1], 3),
        "metrics": {
            "delta_ms_p50": _percentile(deltas, 0.5),
            "delta_ms_p95": _percentile(deltas, 0.95),
            "over_33_3ms": sum(value > 33.3 for value in deltas),
            "over_100ms": sum(value > 100 for value in deltas),
        },
        "event_counts": dict(event_types),
        "movement_ranges": {key: round(value, 6) for key, value in movement_ranges.items()},
        "movement_span": round(movement_span, 6),
        "yaw_span_degrees": round(yaw_span_degrees, 3),
        "key_runs": key_runs,
        "stationary_frames_while_moving": stationary_while_moving,
        "warnings": warnings,
        "interpretation": "通过只表示路线 JSON 满足记录门槛；碰撞、视觉质量和录像内容仍需人工结合场景检查。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 Luna 连续路线 JSON 的记录完整性")
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--min-duration-ms", type=float, default=30_000.0)
    parser.add_argument("--min-turn-degrees", type=float, default=150.0)
    parser.add_argument("--min-hold-ms", type=float, default=500.0)
    parser.add_argument("--strict", action="store_true", help="不满足完整路线门槛时返回退出码 1")
    args = parser.parse_args()
    report = validate_route(
        args.route,
        min_duration_ms=args.min_duration_ms,
        min_turn_degrees=args.min_turn_degrees,
        min_hold_ms=args.min_hold_ms,
    )
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
