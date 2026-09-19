import json
from pathlib import Path

from scripts.validate_pixel_layout import validate_layout


def _write_scene(root: Path, *, start=(0.0, 1.6, 4.0), checkpoint=(0.0, 1.6, 2.0)) -> Path:
    root.mkdir()
    layout = {
        "layout_version": "test-v1",
        "objects": [{"id": "wall", "collision_box_id": "wall"}],
        "movement": {
            "start": list(start),
            "bounds": {"x": [-5.0, 5.0], "y": [1.0, 2.0], "z": [-5.0, 5.0]},
            "collision_radius": 0.3,
            "collision_boxes": [{"box_id": "wall", "bounds": {"x": [2.0, 3.0], "z": [-1.0, 1.0]}}],
            "route_checkpoints": [list(checkpoint)],
        },
    }
    (root / "layout.json").write_text(json.dumps(layout), encoding="utf-8")
    (root / "collision.json").write_text(json.dumps({"layout_version": "test-v1", "boxes": layout["movement"]["collision_boxes"]}), encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({"scene_id": "test", "layout_version": "test-v1"}), encoding="utf-8")
    return root


def test_layout_contract_passes(tmp_path: Path):
    report = validate_layout(_write_scene(tmp_path / "scene"))

    assert report["status"] == "pass"
    assert all(report["checks"].values())


def test_layout_contract_rejects_start_inside_collision(tmp_path: Path):
    report = validate_layout(_write_scene(tmp_path / "scene", start=(2.5, 1.6, 0.0)))

    assert report["status"] == "unverified"
    assert report["checks"]["start_outside_expanded_collisions"] is False
