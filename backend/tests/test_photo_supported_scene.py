import json
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from app.config import Settings
from app.models import RegionConfirmation, SceneTemplate
from app.services import geometry
from app.services.photo_supported_scene import LAYOUT_VERSION, _photo_palette, build_photo_supported_scene


def _source(path: Path) -> None:
    Image.new("RGB", (320, 200), (180, 150, 120)).save(path)


def _moge_scene(path: Path) -> None:
    mesh = trimesh.creation.box((4.0, 3.0, 8.0))
    mesh.apply_translation([0.0, 0.0, -4.0])
    mesh.visual.vertex_colors = np.tile(np.asarray([80, 120, 160, 255], dtype=np.uint8), (len(mesh.vertices), 1))
    trimesh.Scene(mesh).export(path, file_type="glb")


def test_generated_material_palette_reads_photo_bands(tmp_path: Path):
    source = tmp_path / "palette.png"
    image = Image.new("RGB", (100, 100), (120, 120, 120))
    for y in range(0, 30):
        for x in range(100):
            image.putpixel((x, y), (220, 235, 250))
    for y in range(70, 100):
        for x in range(100):
            image.putpixel((x, y), (150, 105, 70))
    image.save(source)

    palette = _photo_palette(source)

    assert palette["upper"] != palette["lower"]
    assert palette["upper"][2] > palette["lower"][2]


def test_quality_route_keeps_photo_surface_and_shares_indoor_collision_layout(tmp_path: Path):
    source = tmp_path / "source.jpg"
    scene_path = tmp_path / "scene.glb"
    _source(source)
    _moge_scene(scene_path)
    result = build_photo_supported_scene(
        source,
        scene_path,
        SceneTemplate.indoor_walk,
        {"coverage": 0.81, "normalization": {"world_scale": 0.75}, "camera": {"position": [0, 0, 0]}},
        Settings(data_dir=tmp_path / "data"),
        manual_regions=[RegionConfirmation(region_id="floor", role="floor", x=0.1, y=0.7, width=0.8, height=0.2)],
    )

    assert result["scene_source"] == "photo_supported_quality"
    assert result["layout_version"] == LAYOUT_VERSION
    assert result["manual_assisted"] is True
    assert "generated-obstacle-proxy" in result["generated_regions"]
    assert len(result["movement"]["collision_boxes"]) == 4
    layout = json.loads((tmp_path / "layout.json").read_text(encoding="utf-8"))
    collision = json.loads((tmp_path / "collision.json").read_text(encoding="utf-8"))
    assert layout["photo_surface"] == "moge-camera-facing-surface"
    assert layout["material_policy"] == "generated_structure_uses_photo_band_palette_not_full_image_texture"
    assert all(abs(actual - expected) <= 2 for actual, expected in zip(layout["material_palette"]["average"], [180, 150, 120]))
    assert layout["manual_regions"][0]["role"] == "floor"
    assert len(collision["boxes"]) == len(result["movement"]["collision_boxes"])
    checkpoints = result["movement"]["route_checkpoints"]
    assert len(checkpoints) == 3
    obstacle = result["movement"]["collision_boxes"][-1]["bounds"]
    assert not (
        obstacle["x"][0] - 0.3 <= checkpoints[-1][0] <= obstacle["x"][1] + 0.3
        and obstacle["z"][0] - 0.3 <= checkpoints[-1][2] <= obstacle["z"][1] + 0.3
    )
    loaded = trimesh.load(scene_path, force="scene")
    assert len(loaded.geometry) >= 5


def test_quality_route_records_explicit_coarse_fallback_when_moge_fails(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.jpg"
    scene_path = tmp_path / "scene.glb"
    _source(source)

    def fail(*args, **kwargs):
        raise PermissionError("model checkpoint unavailable")

    monkeypatch.setattr(geometry, "run_moge", fail)
    result = geometry.generate_scene(
        source,
        scene_path,
        mock=False,
        settings=Settings(data_dir=tmp_path / "data", quality_scene_enabled=True, coarse_scene_enabled=True),
        template=SceneTemplate.indoor_walk,
        quality_route=True,
    )

    assert result["scene_source"] == "procedural_coarse"
    assert result["fallback_reason"] == "quality_route_failed:PermissionError"
    assert result["quality_route_error"] == "PermissionError"


def test_quality_route_reports_real_generation_stages(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.jpg"
    scene_path = tmp_path / "scene.glb"
    _source(source)

    def fake_run(image_path, output_path, settings, **kwargs):
        _moge_scene(output_path)
        return {
            "coverage": 0.9,
            "normalization": {"world_scale": 1.0},
            "camera": {"position": [0, 0, 0]},
        }

    monkeypatch.setattr(geometry, "run_moge", fake_run)
    events: list[tuple[str, int, str]] = []
    result = geometry.generate_scene(
        source,
        scene_path,
        mock=False,
        settings=Settings(data_dir=tmp_path / "data", quality_scene_enabled=True, coarse_scene_enabled=False),
        template=SceneTemplate.indoor_walk,
        quality_route=True,
        stage_callback=lambda stage, progress, message: events.append((stage, progress, message)),
    )

    assert result["scene_source"] == "photo_supported_quality"
    assert [event[0] for event in events] == ["depth_and_camera", "photo_supported_structure"]
    assert events[0][1] < events[1][1]
