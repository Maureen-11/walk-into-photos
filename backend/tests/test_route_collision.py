import json

from scripts.validate_route_collision import validate_route_collision


def _write_inputs(tmp_path, *, contact: bool):
    root = tmp_path / ("contact" if contact else "bound")
    root.mkdir()
    point_z = 0.9 if contact else 5.0
    route = {
        "schema": "luna-route-evidence/1",
        "scene_id": "test",
        "scene_version": "v1",
        "frames": [
            {"at_ms": 0, "position": [0, 1.6, point_z], "keys": []},
            {"at_ms": 100, "position": [0, 1.6, point_z], "keys": ["w"]},
        ],
        "events": [],
    }
    layout = {
        "movement": {
            "collision_radius": 0.3,
            "bounds": {"x": [-5, 5], "y": [1.6, 1.6], "z": [-5, 5]},
            "collision_boxes": [{"box_id": "front", "bounds": {"x": [-1, 1], "z": [1.2, 1.5]}}],
        }
    }
    route_path = root / "route.json"
    layout_path = root / "layout.json"
    route_path.write_text(json.dumps(route), encoding="utf-8")
    layout_path.write_text(json.dumps(layout), encoding="utf-8")
    return route_path, layout_path


def test_stationary_route_frame_matches_collision_edge(tmp_path):
    route, layout = _write_inputs(tmp_path, contact=True)
    report = validate_route_collision(route, layout)

    assert report["status"] == "pass"
    assert report["collision_contact_frames"] == 1
    assert report["outer_bound_only_frames"] == 0


def test_outer_bound_stop_is_not_called_collision(tmp_path):
    route, layout = _write_inputs(tmp_path, contact=False)
    report = validate_route_collision(route, layout)

    assert report["status"] == "unverified"
    assert report["collision_contact_frames"] == 0
    assert report["outer_bound_only_frames"] == 1
