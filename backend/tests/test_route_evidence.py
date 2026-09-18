import json
from pathlib import Path

from scripts.validate_route_evidence import validate_route


def _write_route(path: Path, *, sustained: bool = True, complete: bool = True) -> Path:
    frames = []
    for index in range(80):
        keys = ["w"] if sustained and 10 <= index < 50 else []
        frames.append({
            "at_ms": index * 1000 / 10,
            "delta_ms": 100,
            "position": [index * 0.01 if keys else 0.4, 1.6, 4.7],
            "yaw": 0 if index < 30 else -3.2,
            "pitch": 0,
            "keys": keys,
        })
    events = [{"type": "keydown", "key": "w"}, {"type": "keyup", "key": "w"}]
    if complete:
        events += [{"type": "reset", "key": "r"}, {"type": "blur"}]
    path.write_text(json.dumps({"schema": "luna-route-evidence/1", "scene_id": "test", "scene_version": "v1", "frames": frames, "events": events}), encoding="utf-8")
    return path


def test_complete_route_passes_recording_gate(tmp_path: Path):
    report = validate_route(_write_route(tmp_path / "route.json"), min_duration_ms=7_000)

    assert report["status"] == "pass"
    assert report["checks"] == {"duration": True, "sustained_input": True, "turn": True, "reset": True, "focus_loss": True, "movement": True}
    assert report["key_runs"]["w"]["max_duration_ms"] >= 500


def test_discrete_route_remains_unverified(tmp_path: Path):
    report = validate_route(_write_route(tmp_path / "route.json", sustained=False, complete=False))

    assert report["status"] == "unverified"
    assert report["checks"]["sustained_input"] is False
    assert report["checks"]["reset"] is False
    assert report["checks"]["focus_loss"] is False


def test_invalid_schema_is_rejected(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema": "wrong", "frames": []}), encoding="utf-8")

    try:
        validate_route(path)
    except ValueError as exc:
        assert "unsupported route schema" in str(exc)
    else:
        raise AssertionError("invalid route schema should be rejected")
