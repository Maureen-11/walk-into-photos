import json
from pathlib import Path

from PIL import Image

from app.models import SceneTemplate
from app.services.pixel_scene import (
    BASE_VOXEL,
    FURNITURE_VOXEL,
    MICRO_VOXEL,
    PIXEL_ASSET_LIBRARY_VERSION,
    PIXEL_LAYOUT_VERSION,
    PIXEL_V02_LAYOUT_VERSION,
    build_pixel_corridor_v02,
    build_pixel_indoor_sample,
    build_pixel_living_v02,
    build_pixel_nature_v03,
    build_pixel_building_v05,
    build_pixel_street_v05,
    PIXEL_V06_LAYOUT_VERSION,
    build_pixel_corridor_v06,
    build_pixel_living_v06,
    PIXEL_V36_LAYOUT_VERSIONS,
    build_pixel_corridor_v36,
    build_pixel_living_v36,
    PIXEL_V37_LAYOUT_VERSION,
    build_pixel_living_v37,
    PIXEL_V38_LAYOUT_VERSION,
    build_pixel_living_v38,
    PIXEL_V39_LAYOUT_VERSION,
    build_pixel_corridor_v39,
    PIXEL_V40_LAYOUT_VERSION,
    build_pixel_nature_v40,
    PIXEL_V41_LAYOUT_VERSION,
    build_pixel_street_v41,
    PIXEL_V42_LAYOUT_VERSION,
    build_pixel_building_v42,
    PIXEL_V43_LAYOUT_VERSION,
    build_pixel_nature_v43,
    PIXEL_V44_LAYOUT_VERSION,
    build_pixel_building_v44,
    PIXEL_V45_LAYOUT_VERSION,
    build_pixel_nature_v45,
    PIXEL_V46_LAYOUT_VERSIONS,
    build_pixel_corridor_v46,
    build_pixel_living_v46,
    build_pixel_nature_v46,
    build_pixel_street_v46,
    build_pixel_building_v46,
    PIXEL_V47_LAYOUT_VERSIONS,
    build_pixel_corridor_v47,
    build_pixel_living_v47,
    build_pixel_nature_v47,
    build_pixel_street_v47,
    build_pixel_building_v47,
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


def test_pixel_v06_adds_readable_layers_without_changing_indoor_collision_contract(tmp_path: Path):
    source = tmp_path / "indoor.png"
    image = Image.new("RGB", (48, 32), (205, 210, 212))
    for y in range(16, 32):
        for x in range(48):
            image.putpixel((x, y), (132, 108, 92))
    image.save(source)

    v02_dir = tmp_path / "v02"
    v06_dir = tmp_path / "v06"
    v02 = build_pixel_living_v02(source, v02_dir, "pixel-v02-compare")
    v06 = build_pixel_living_v06(source, v06_dir, "pixel-v06-compare")
    v02_layout = json.loads((v02_dir / "layout.json").read_text(encoding="utf-8"))
    v06_layout = json.loads((v06_dir / "layout.json").read_text(encoding="utf-8"))

    assert v06["layout_version"] == PIXEL_V06_LAYOUT_VERSION
    assert v06["style_route"] == "pixel_style_sample_v6"
    assert len(v06_layout["objects"]) > len(v02_layout["objects"])
    assert len(v06["movement"]["collision_boxes"]) == len(v02["movement"]["collision_boxes"])
    assert v06["pixel_spec"]["asset_library_version"] == PIXEL_ASSET_LIBRARY_VERSION
    assert v06["pixel_spec"]["furniture_voxel"] == FURNITURE_VOXEL
    assert v06["pixel_spec"]["micro_voxel"] == MICRO_VOXEL
    assert v06["pixel_spec"]["photo_key_colour_budget"] == 16
    assert any(item["id"] == "pixel-v06-front-wall-panel" for item in v06_layout["objects"])
    assert any(item["id"] == "pixel-v06-front-wall-eye-panel" for item in v06_layout["objects"])
    assert any(item["id"] == "pixel-v06-screen-bezel" for item in v06_layout["objects"])
    assert 0.0625 in {item["voxel_grid"] for item in v06_layout["objects"]}
    assert FURNITURE_VOXEL in {item["voxel_grid"] for item in v06_layout["objects"]}
    assert MICRO_VOXEL in {item["voxel_grid"] for item in v06_layout["objects"]}


def test_pixel_v06_corridor_adds_door_and_portal_detail(tmp_path: Path):
    source = tmp_path / "corridor.png"
    Image.new("RGB", (40, 24), (188, 198, 202)).save(source)
    output = tmp_path / "corridor-v06"
    manifest = build_pixel_corridor_v06(source, output, "pixel-v06-corridor")
    layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))

    ids = {item["id"] for item in layout["objects"]}
    assert manifest["layout_version"] == PIXEL_V06_LAYOUT_VERSION
    assert "pixel-v06-left-door-0-handle" in ids
    assert "pixel-v06-corridor-front-sign" in ids
    assert "pixel-v06-corridor-front-eye-panel" in ids
    assert len(manifest["movement"]["collision_boxes"]) == 6
    grids = {item["voxel_grid"] for item in layout["objects"]}
    assert FURNITURE_VOXEL in grids
    assert MICRO_VOXEL in grids


def test_pixel_q02_i01_uses_photo_specific_window_side_layout(tmp_path: Path):
    source = tmp_path / "i01.png"
    Image.new("RGB", (40, 24), (188, 198, 202)).save(source)
    output = tmp_path / "i01-q02"

    manifest = build_pixel_corridor_v06(
        source,
        output,
        "pixel-q02-i01-test",
        layout_variant="i01",
    )
    layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))
    ids = {item["id"] for item in layout["objects"]}

    assert manifest["style_route"] == "pixel_style_sample_v6"
    assert layout["layout_authoring"] == "q00_visual_index:i01"
    assert "pixel-v02-corridor-left-window-0" in ids
    assert "pixel-v02-corridor-left-door-0" not in ids
    assert "pixel-q02-i01-window-light-0-0" in ids


def test_pixel_v36_indoor_surface_pass_keeps_collision_contract(tmp_path: Path):
    source = tmp_path / "indoor.png"
    Image.new("RGB", (48, 32), (205, 210, 212)).save(source)

    corridor_dir = tmp_path / "corridor-v36"
    living_dir = tmp_path / "living-v36"
    corridor = build_pixel_corridor_v36(source, corridor_dir, "pixel-v36-i01-test")
    living = build_pixel_living_v36(source, living_dir, "pixel-v36-i02-test")
    corridor_layout = json.loads((corridor_dir / "layout.json").read_text(encoding="utf-8"))
    living_layout = json.loads((living_dir / "layout.json").read_text(encoding="utf-8"))

    assert corridor["style_route"] == "pixel_style_sample_v36"
    assert living["style_route"] == "pixel_style_sample_v36"
    assert corridor["layout_version"] == PIXEL_V36_LAYOUT_VERSIONS["corridor"]
    assert living["layout_version"] == PIXEL_V36_LAYOUT_VERSIONS["living_room"]
    assert len(corridor["movement"]["collision_boxes"]) == 6
    assert len(living["movement"]["collision_boxes"]) == 8
    assert len(corridor_layout["objects"]) > 2200
    assert len(living_layout["objects"]) > 2200
    assert any(item["role"] == "window_reflection_pixel" for item in corridor_layout["objects"])
    assert any(item["role"] == "upholstery_seam_detail" for item in living_layout["objects"])


def test_pixel_v37_living_composition_adds_anchor_group_without_new_collision(tmp_path: Path):
    source = tmp_path / "living.png"
    Image.new("RGB", (48, 32), (235, 236, 232)).save(source)
    output = tmp_path / "living-v37"

    manifest = build_pixel_living_v37(source, output, "pixel-v37-i02-test")
    layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))
    ids = {item["id"] for item in layout["objects"]}

    assert manifest["style_route"] == "pixel_style_sample_v37"
    assert manifest["layout_version"] == PIXEL_V37_LAYOUT_VERSION
    assert len(manifest["movement"]["collision_boxes"]) == 8
    assert "pixel-q05-r37-i02-sectional-front-base" in ids
    assert any(item.startswith("pixel-q05-r37-i02-rug-centre-weave") for item in ids)
    assert "pixel-q05-r37-i02-tv-wall-lower-edge" in ids


def test_pixel_v38_adds_pixel_material_hierarchy_without_changing_collision(tmp_path: Path):
    source = tmp_path / "living.png"
    Image.new("RGB", (48, 32), (235, 236, 232)).save(source)
    output = tmp_path / "living-v38"

    manifest = build_pixel_living_v38(source, output, "pixel-v38-i02-test")
    layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))
    roles = {item["role"] for item in layout["objects"]}

    assert manifest["style_route"] == "pixel_style_sample_v38"
    assert manifest["layout_version"] == PIXEL_V38_LAYOUT_VERSION
    assert manifest["pixel_spec"]["lighting_preset"] == "indoor_pixel_detail_v4"
    assert len(manifest["movement"]["collision_boxes"]) == 8
    assert "upholstery_pixel_surface" in roles
    assert "rug_pixel_surface" in roles
    assert "display_light_detail" in roles


def test_pixel_v39_corridor_adds_fine_surface_hierarchy_without_new_collision(tmp_path: Path):
    source = tmp_path / "corridor.png"
    Image.new("RGB", (48, 32), (205, 210, 212)).save(source)
    output = tmp_path / "corridor-v39"

    manifest = build_pixel_corridor_v39(source, output, "pixel-v39-i01-test")
    layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))
    roles = {item["role"] for item in layout["objects"]}

    assert manifest["style_route"] == "pixel_style_sample_v39"
    assert manifest["layout_version"] == PIXEL_V39_LAYOUT_VERSION
    assert manifest["pixel_spec"]["lighting_preset"] == "indoor_pixel_detail_v4"
    assert len(manifest["movement"]["collision_boxes"]) == 6
    assert "window_pixel_surface" in roles
    assert "door_pixel_surface" in roles
    assert "ceiling_light_detail" in roles


def test_pixel_v40_nature_adds_ordered_snow_and_fence_layers_without_new_collision(tmp_path: Path):
    source = tmp_path / "nature.png"
    Image.new("RGB", (48, 32), (184, 205, 226)).save(source)
    output = tmp_path / "nature-v40"

    manifest = build_pixel_nature_v40(source, output, "pixel-v40-n01-test")
    layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))
    roles = {item["role"] for item in layout["objects"]}

    assert manifest["style_route"] == "pixel_style_sample_v40"
    assert manifest["layout_version"] == PIXEL_V40_LAYOUT_VERSION
    assert manifest["pixel_spec"]["lighting_preset"] == "outdoor_cool_daylight_v2"
    assert len(manifest["movement"]["collision_boxes"]) == 3
    assert "mountain_pixel_facet" in roles
    assert "snow_track_detail" in roles
    assert "foreground_fence_detail" in roles


def test_pixel_v41_street_adds_surface_and_vehicle_layers_without_new_collision(tmp_path: Path):
    source = tmp_path / "street.png"
    Image.new("RGB", (48, 32), (184, 205, 226)).save(source)
    output = tmp_path / "street-v41"

    manifest = build_pixel_street_v41(source, output, "pixel-v41-s01-test")
    layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))
    roles = {item["role"] for item in layout["objects"]}

    assert manifest["style_route"] == "pixel_style_sample_v41"
    assert manifest["layout_version"] == PIXEL_V41_LAYOUT_VERSION
    assert manifest["pixel_spec"]["lighting_preset"] == "street_soft_daylight_v3"
    assert len(manifest["movement"]["collision_boxes"]) == 11
    assert "road_surface_contour" in roles
    assert "vehicle_pixel_surface" in roles
    assert "building_window_pixel_surface" in roles


def test_pixel_v42_building_adds_facade_light_layers_without_new_collision(tmp_path: Path):
    source = tmp_path / "building.png"
    Image.new("RGB", (48, 32), (18, 26, 54)).save(source)
    output = tmp_path / "building-v42"

    manifest = build_pixel_building_v42(source, output, "pixel-v42-b01-test")
    layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))
    roles = {item["role"] for item in layout["objects"]}

    assert manifest["style_route"] == "pixel_style_sample_v42"
    assert manifest["layout_version"] == PIXEL_V42_LAYOUT_VERSION
    assert manifest["pixel_spec"]["lighting_preset"] == "facade_blue_hour_v3"
    assert len(manifest["movement"]["collision_boxes"]) == 1
    assert "facade_contour" in roles
    assert "facade_window_pixel_surface" in roles
    assert "balcony_light_detail" in roles


def test_pixel_v43_nature_rebalances_fence_and_keeps_collision_contract(tmp_path: Path):
    source = tmp_path / "nature.png"
    Image.new("RGB", (48, 32), (184, 205, 226)).save(source)
    output = tmp_path / "nature-v43"

    manifest = build_pixel_nature_v43(source, output, "pixel-v43-n01-test")
    layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))
    ids = {item["id"] for item in layout["objects"]}
    roles = {item["role"] for item in layout["objects"]}

    assert manifest["style_route"] == "pixel_style_sample_v43"
    assert manifest["layout_version"] == PIXEL_V43_LAYOUT_VERSION
    assert len(manifest["movement"]["collision_boxes"]) == 3
    assert "pixel-q05-r22-n01-fence-rail-1" not in ids
    assert "pixel-q05-r22-n01-fence-rail-2" not in ids
    assert "mountain_ridge_contour" in roles
    assert "snow_surface_detail" in roles


def test_pixel_v44_building_switches_only_to_brighter_blue_hour_preset(tmp_path: Path):
    source = tmp_path / "building.png"
    Image.new("RGB", (48, 32), (18, 26, 54)).save(source)
    output = tmp_path / "building-v44"

    manifest = build_pixel_building_v44(source, output, "pixel-v44-b01-test")

    assert manifest["style_route"] == "pixel_style_sample_v44"
    assert manifest["layout_version"] == PIXEL_V44_LAYOUT_VERSION
    assert manifest["pixel_spec"]["lighting_preset"] == "facade_blue_hour_v4"
    assert len(manifest["movement"]["collision_boxes"]) == 1


def test_pixel_v45_nature_adds_bounded_lateral_terrain_without_collision_change(tmp_path: Path):
    source = tmp_path / "nature.png"
    Image.new("RGB", (48, 32), (184, 205, 226)).save(source)
    output = tmp_path / "nature-v45"

    manifest = build_pixel_nature_v45(source, output, "pixel-v45-n01-test")
    layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))
    roles = {item["role"] for item in layout["objects"]}

    assert manifest["style_route"] == "pixel_style_sample_v45"
    assert manifest["layout_version"] == PIXEL_V45_LAYOUT_VERSION
    assert len(manifest["movement"]["collision_boxes"]) == 3
    assert "lateral_terrain_mass" in roles
    assert "lateral_ridge_mass" in roles


def test_pixel_v46_micro_surface_pass_covers_five_profiles_without_new_collision(tmp_path: Path):
    source = tmp_path / "source.png"
    Image.new("RGB", (48, 32), (190, 200, 210)).save(source)
    cases = (
        ("corridor", build_pixel_corridor_v46, 6, "window_micro_surface"),
        ("living", build_pixel_living_v46, 8, "upholstery_micro_surface"),
        ("nature", build_pixel_nature_v46, 3, "lateral_terrain_micro_surface"),
        ("street", build_pixel_street_v46, 11, "vehicle_micro_surface"),
        ("building", build_pixel_building_v46, 1, "facade_window_micro_surface"),
    )
    for profile, builder, collision_count, expected_role in cases:
        output = tmp_path / profile
        manifest = builder(source, output, f"pixel-v46-{profile}-test")
        layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))
        roles = {item["role"] for item in layout["objects"]}
        assert manifest["style_route"] == "pixel_style_sample_v46"
        assert manifest["layout_version"] == PIXEL_V46_LAYOUT_VERSIONS["living" if profile == "living" else profile]
        assert len(manifest["movement"]["collision_boxes"]) == collision_count
        assert expected_role in roles


def test_pixel_v47_semantic_surface_hierarchy_keeps_five_collision_contracts(tmp_path: Path):
    source = tmp_path / "source-v47.png"
    Image.new("RGB", (48, 32), (190, 200, 210)).save(source)
    cases = (
        ("corridor", build_pixel_corridor_v47, 6),
        ("living", build_pixel_living_v47, 8),
        ("nature", build_pixel_nature_v47, 3),
        ("street", build_pixel_street_v47, 11),
        ("building", build_pixel_building_v47, 1),
    )
    for profile, builder, collision_count in cases:
        output = tmp_path / f"v47-{profile}"
        manifest = builder(source, output, f"pixel-v47-{profile}-test")
        layout = json.loads((output / "layout.json").read_text(encoding="utf-8"))
        collision = json.loads((output / "collision.json").read_text(encoding="utf-8"))
        roles = {item["role"] for item in layout["objects"]}
        assert manifest["style_route"] == "pixel_style_sample_v47"
        assert manifest["layout_version"] == PIXEL_V47_LAYOUT_VERSIONS[profile]
        assert len(manifest["movement"]["collision_boxes"]) == collision_count
        assert layout["movement"]["collision_boxes"] == collision["boxes"]
        assert manifest["quality_status"] == "unverified"
        assert manifest["detail_object_ids"]
        assert any(role.endswith("structure") or role.endswith("surface") for role in roles)
