import json
from pathlib import Path

from PIL import Image

from app.models import SceneTemplate
from app.services.pixel_scene import (
    BASE_VOXEL,
    PIXEL_LAYOUT_VERSION,
    PIXEL_V02_LAYOUT_VERSION,
    build_pixel_corridor_v02,
    build_pixel_indoor_sample,
    build_pixel_living_v02,
    build_pixel_nature_v03,
    build_pixel_building_v05,
    build_pixel_street_v05,
)


def test_pixel_sample_is_snapped_and_collision_layout_is_shared(tmp_path: Path):
    source = tmp_path / "source.png"
    image = Image.new("RGB", (32, 24), (220, 220, 220))
    for y in range(12, 24):
        for x in range(32):
            image.putpixel((x, y), (130, 95, 65))
    image.save(source)

    output = tmp_path / "scene"
    manifest = build_pixel_indoor_sample(source, output, "pixel-test")
    layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))
    collision = json.loads((output / "collision.json").read_text(encoding="utf-8"))

    assert manifest["template"] == SceneTemplate.indoor_walk.value
    assert manifest["style_route"] == "pixel_style_sample"
    assert manifest["layout_version"] == PIXEL_LAYOUT_VERSION
    assert manifest["pixel_spec"]["base_voxel"] == BASE_VOXEL
    assert len(layout["palette"]["base_32"]) <= 32
    assert len(layout["objects"]) >= 20
    assert next(item for item in layout["objects"] if item["id"] == "pixel-window-mullion")["voxel_grid"] == 0.0625
    assert len(collision["boxes"]) >= 6
    collision_ids = {box["box_id"] for box in collision["boxes"]}
    object_collision_ids = {
        item["collision_box_id"]
        for item in layout["objects"]
        if "collision_box_id" in item
    }
    assert collision_ids == object_collision_ids
    assert layout["movement"]["start"][2] > 4.0
    for box in collision["boxes"]:
        assert box["bounds"]["x"][0] < box["bounds"]["x"][1]
        assert box["bounds"]["z"][0] < box["bounds"]["z"][1]
    assert (output / "scene.glb").stat().st_size > 1000


def test_pixel_v02_produces_distinct_corridor_and_finer_detail(tmp_path: Path):
    source = tmp_path / "corridor.png"
    image = Image.new("RGB", (40, 24), (205, 215, 220))
    for y in range(12, 24):
        for x in range(40):
            image.putpixel((x, y), (126, 105, 86))
    image.save(source)

    corridor_dir = tmp_path / "corridor-scene"
    living_dir = tmp_path / "living-scene"
    corridor = build_pixel_corridor_v02(source, corridor_dir, "pixel-v02-i01-test")
    living = build_pixel_living_v02(source, living_dir, "pixel-v02-i02-test")
    corridor_layout = json.loads((corridor_dir / "layout.json").read_text(encoding="utf-8"))
    living_layout = json.loads((living_dir / "layout.json").read_text(encoding="utf-8"))

    assert corridor["layout_version"] == PIXEL_V02_LAYOUT_VERSION
    assert living["layout_version"] == PIXEL_V02_LAYOUT_VERSION
    assert corridor_layout["profile"] == "corridor"
    assert living_layout["profile"] == "living_room"
    assert len(corridor_layout["objects"]) >= 45
    assert len(living_layout["objects"]) >= 55
    assert 0.0625 in {item["voxel_grid"] for item in corridor_layout["objects"]}
    assert 0.0625 in {item["voxel_grid"] for item in living_layout["objects"]}
    assert corridor["movement"]["start"][2] != living["movement"]["start"][2]
    assert any(item["id"] == "pixel-v02-corridor-bench" for item in corridor_layout["objects"])
    assert any(item["id"] == "pixel-v02-rug" for item in living_layout["objects"])


def test_pixel_v03_nature_has_layered_ridges_and_walkable_path(tmp_path: Path):
    source = tmp_path / "mountain.png"
    image = Image.new("RGB", (48, 28), (170, 195, 220))
    for y in range(13, 28):
        for x in range(48):
            image.putpixel((x, y), (222, 226, 215))
    image.save(source)

    output = tmp_path / "nature-scene"
    manifest = build_pixel_nature_v03(source, output, "pixel-v03-test")
    layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))

    assert manifest["template"] == "landscape_journey"
    assert manifest["style_route"] == "pixel_style_sample_v3"
    assert manifest["layout_version"] == "pixel-natural-v3-fine-detail"
    assert layout["profile"] == "snow_mountain"
    assert len(layout["objects"]) >= 80
    assert sum(1 for item in layout["objects"] if "ridge" in item["id"]) >= 80
    assert manifest["movement"]["bounds"]["y"] == [1.625, 1.625]
    assert len(manifest["movement"]["route_checkpoints"]) == 4
    assert (output / "scene.glb").stat().st_size > 1000


def test_pixel_v05_outdoor_profiles_are_separated_and_external(tmp_path: Path):
    source = tmp_path / "outdoor.png"
    image = Image.new("RGB", (48, 30), (80, 100, 130))
    for y in range(16, 30):
        for x in range(48):
            image.putpixel((x, y), (110, 95, 80))
    image.save(source)

    street_dir = tmp_path / "street"
    building_dir = tmp_path / "building"
    street = build_pixel_street_v05(source, street_dir, "pixel-v05-s01-test")
    building = build_pixel_building_v05(source, building_dir, "pixel-v05-b01-test")
    street_layout = json.loads((street_dir / "layout.json").read_text(encoding="utf-8"))
    building_layout = json.loads((building_dir / "layout.json").read_text(encoding="utf-8"))

    assert street["template"] == "street_descent"
    assert building["template"] == "facade_flight"
    assert street_layout["profile"] == "street"
    assert building_layout["profile"] == "facade"
    assert len(street_layout["objects"]) >= 45
    assert len(building_layout["objects"]) >= 60
    assert any(item["role"] == "vehicle_proxy" for item in street_layout["objects"])
    assert any(item["role"] == "window" for item in building_layout["objects"])
    assert building["movement"]["allow_flight"] is False
