from __future__ import annotations

import json
from pathlib import Path

from app.services.detail_refinement import build_refined_corridor_v48


def test_v48_corridor_preserves_v47_and_adds_detail_layers(tmp_path: Path) -> None:
    image = Path(__file__).parents[2] / "test-images" / "corridor" / "corridor-01.jpg"
    output = tmp_path / "i01"
    manifest = build_refined_corridor_v48(image, output)

    layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))
    collision = json.loads((output / "collision.json").read_text(encoding="utf-8"))

    assert manifest["version"] == "pixel-v48"
    assert manifest["style_route"] == "pixel_style_sample_v48"
    assert manifest["quality_status"] == "unverified"
    assert len(layout["objects"]) > 3418
    assert len(collision["boxes"]) == 6
    assert layout["pixel_spec"]["refinement_policy"] == (
        "additive_depth_layers_preserve_v47_objects_and_collisions"
    )
    detail_ids = set(manifest["detail_object_ids"])
    assert "pixel-q05-r48-i01-left-window-0-recess" in detail_ids
    assert "pixel-q05-r48-i01-right-door-0-recessed-panel" in detail_ids
    assert all(obj.get("source") != "full_photo_projection" for obj in layout["objects"])

    movement = layout["movement"]
    bounds = movement["bounds"]
    checkpoints = [movement["start"], *movement["route_checkpoints"]]
    assert all(
        bounds["x"][0] <= point[0] <= bounds["x"][1]
        and bounds["z"][0] <= point[2] <= bounds["z"][1]
        and point[1] == bounds["y"][0]
        for point in checkpoints
    )
    bench = next(box for box in movement["collision_boxes"] if box["box_id"].endswith("bench"))
    assert all(
        not (
            bench["bounds"]["x"][0] <= point[0] <= bench["bounds"]["x"][1]
            and bench["bounds"]["z"][0] <= point[2] <= bench["bounds"]["z"][1]
        )
        for point in checkpoints
    )
