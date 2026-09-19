from __future__ import annotations

import json
from pathlib import Path

from app.services.material_refinement import build_refined_corridor_v49


def test_v49_changes_materials_without_changing_scene_structure(tmp_path: Path) -> None:
    image = Path(__file__).parents[2] / "test-images" / "corridor" / "corridor-01.jpg"
    output = tmp_path / "i01"
    manifest = build_refined_corridor_v49(image, output)
    layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))
    collision = json.loads((output / "collision.json").read_text(encoding="utf-8"))

    assert manifest["version"] == "pixel-v49"
    assert manifest["style_route"] == "pixel_style_sample_v49"
    assert manifest["pixel_spec"]["lighting_preset"] == "indoor_pixel_detail_v5"
    assert manifest["quality_status"] == "unverified"
    assert len(layout["objects"]) == 3470
    assert len(collision["boxes"]) == 6
    assert manifest["material_adjustment_count"] > 1000
    assert layout["pixel_spec"]["material_policy"] == (
        "role_based_contrast_preserve_v48_geometry"
    )
