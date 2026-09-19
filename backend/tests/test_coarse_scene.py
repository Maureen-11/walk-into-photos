import json
from pathlib import Path

from PIL import Image
import trimesh

from app.models import SceneTemplate
from app.services.coarse_scene import LAYOUT_VERSION, build_coarse_scene


def _photo(path: Path) -> None:
    Image.new("RGB", (640, 480), (180, 190, 205)).save(path, format="JPEG")


def test_coarse_indoor_scene_has_thick_geometry_and_shared_collisions(tmp_path: Path):
    source = tmp_path / "source.jpg"
    scene_path = tmp_path / "scene.glb"
    _photo(source)

    result = build_coarse_scene(source, scene_path, SceneTemplate.indoor_walk, mock=True)
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads((tmp_path / "layout.json").read_text(encoding="utf-8"))
    collision = json.loads((tmp_path / "collision.json").read_text(encoding="utf-8"))

    assert result["scene_source"] == "procedural_coarse"
    assert result["layout_version"] == LAYOUT_VERSION
    assert result["collision_resource"] == "collision.json"
    assert {"floor", "left-wall", "right-wall", "back-wall", "table-top", "sofa-body"} <= set(scene.geometry)
    assert len(result["movement"]["collision_boxes"]) >= 6
    assert collision["layout_version"] == layout["layout_version"] == LAYOUT_VERSION
    assert len(collision["boxes"]) == len(result["movement"]["collision_boxes"])
    bounds = scene.to_geometry().bounds
    assert (bounds[1] - bounds[0] > 2.0).all()


def test_every_delivery_route_produces_a_walkable_contract(tmp_path: Path):
    source = tmp_path / "source.jpg"
    _photo(source)
    for index, template in enumerate(SceneTemplate):
        result = build_coarse_scene(source, tmp_path / f"{index}.glb", template, mock=False)
        movement = result["movement"]
        assert result["camera"]["position"] == movement["start"]
        assert movement["collision_boxes"]
        assert movement["bounds"]["x"][0] < movement["start"][0] < movement["bounds"]["x"][1]
        assert movement["bounds"]["z"][0] < movement["start"][2] < movement["bounds"]["z"][1]
