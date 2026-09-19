from __future__ import annotations

"""Deterministic low-poly scenes for the delivery route.

The original MoGe path produces a camera-facing surface. That is useful for
visual experiments but it cannot guarantee a walkable room from one image.
This module provides the deadline route: a small parameterized environment
with real thickness, a continuous floor, visible obstacles, and a collision
description generated from the same layout as the GLB.

The source image is used as a framed panel and its average colour influences
the room materials. This is deliberately described as a coarse procedural
scene in the manifest; it is not presented as hidden-space reconstruction.
"""

import json
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image
from trimesh.visual.material import SimpleMaterial
from trimesh.visual.texture import TextureVisuals

from app.models import CollisionBox, MovementProfile, SceneTemplate


LAYOUT_VERSION = "coarse-layout-v1"


def _clamp_channel(value: float) -> int:
    return int(max(0, min(255, round(value))))


def _tint(color: tuple[int, int, int], factor: float) -> list[int]:
    return [_clamp_channel(channel * factor) for channel in color]


def _average_colour(image_path: Path) -> tuple[int, int, int]:
    try:
        with Image.open(image_path).convert("RGB") as image:
            sample = image.resize((1, 1), Image.Resampling.BILINEAR)
            return tuple(int(value) for value in sample.getpixel((0, 0)))
    except (OSError, ValueError):
        return (150, 160, 180)


def _box(
    extents: tuple[float, float, float],
    center: tuple[float, float, float],
    colour: list[int],
    name: str,
) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(center)
    rgba = np.asarray([*colour, 255], dtype=np.uint8)
    mesh.visual.vertex_colors = np.tile(rgba, (len(mesh.vertices), 1))
    mesh.metadata["layout_name"] = name
    return mesh


def _inside(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Turn an enclosure face inward so its lit side faces the visitor."""
    mesh.invert()
    return mesh


def _panel(image_path: Path, centre: tuple[float, float, float], width: float, height: float) -> trimesh.Trimesh | None:
    try:
        with Image.open(image_path).convert("RGB") as opened:
            image = opened.copy()
        image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        return None
    vertices = np.asarray([
        [-width / 2, -height / 2, 0.0],
        [width / 2, -height / 2, 0.0],
        [width / 2, height / 2, 0.0],
        [-width / 2, height / 2, 0.0],
    ], dtype=np.float64)
    vertices += np.asarray(centre, dtype=np.float64)
    faces = np.asarray([[0, 1, 2], [0, 2, 3]], dtype=np.int64)
    uv = np.asarray([[0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]], dtype=np.float64)
    material = SimpleMaterial(image=image)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.visual = TextureVisuals(uv=uv, material=material)
    mesh.metadata["layout_name"] = "source-photo-panel"
    return mesh


def _collision(box_id: str, x: tuple[float, float], z: tuple[float, float], label: str) -> CollisionBox:
    return CollisionBox(box_id=box_id, bounds={"x": list(x), "z": list(z)}, label=label)


def _add(scene: trimesh.Scene, objects: list[dict[str, object]], name: str, mesh: trimesh.Trimesh, role: str) -> None:
    scene.add_geometry(mesh, geom_name=name)
    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    objects.append({"id": name, "role": role, "bounds": bounds.tolist()})


def _add_framed_panel(
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    image_path: Path,
    z: float,
    wall_colour: tuple[int, int, int],
) -> None:
    try:
        with Image.open(image_path) as image:
            aspect = image.width / max(image.height, 1)
    except (OSError, ValueError, ZeroDivisionError):
        aspect = 1.5
    height = min(2.35, max(1.55, 4.0 / max(aspect, 0.5)))
    width = height * aspect
    width = min(width, 5.2)
    height = width / max(aspect, 0.5)
    panel = _panel(image_path, (0.0, 1.95, z), width, height)
    if panel is not None:
        _add(scene, objects, "source-photo-panel", panel, "source_panel")
    frame_colour = _tint(wall_colour, 0.42)
    frame_y = 1.95
    frame_depth = 0.12
    frame_parts = (
        ("source-frame-top", (width + 0.22, 0.12, frame_depth), (0.0, frame_y + height / 2 + 0.06, z - 0.03)),
        ("source-frame-bottom", (width + 0.22, 0.12, frame_depth), (0.0, frame_y - height / 2 - 0.06, z - 0.03)),
        ("source-frame-left", (0.12, height + 0.24, frame_depth), (-width / 2 - 0.06, frame_y, z - 0.03)),
        ("source-frame-right", (0.12, height + 0.24, frame_depth), (width / 2 + 0.06, frame_y, z - 0.03)),
    )
    for name, extents, centre in frame_parts:
        _add(scene, objects, name, _box(extents, centre, frame_colour, name), "frame")


def _room_layout(image_path: Path, gallery: bool = False) -> tuple[trimesh.Scene, MovementProfile, list[dict[str, object]], str | None]:
    average = _average_colour(image_path)
    wall = tuple(_tint(average, 1.28))
    floor_colour = tuple(_tint(average, 0.62))
    trim = tuple(_tint(average, 0.82))
    scene = trimesh.Scene()
    objects: list[dict[str, object]] = []
    collisions: list[CollisionBox] = []

    _add(scene, objects, "floor", _box((12.0, 0.20, 16.0), (0.0, -0.10, -7.5), list(floor_colour), "floor"), "floor")
    _add(scene, objects, "ceiling", _inside(_box((12.0, 0.16, 16.0), (0.0, 3.35, -7.5), list(_tint(wall, 1.05)), "ceiling")), "ceiling")
    for name, centre in (("left-wall", (-6.0, 1.62, -7.5)), ("right-wall", (6.0, 1.62, -7.5))):
        _add(scene, objects, name, _inside(_box((0.20, 3.4, 16.0), centre, list(wall), name)), "wall")
    _add(scene, objects, "back-wall", _inside(_box((12.0, 3.4, 0.20), (0.0, 1.62, -15.5), list(wall), "back-wall")), "wall")
    # Keep a centered entrance so the visitor can turn around and still see
    # a bounded room instead of looking into an unmodelled black void.
    for name, centre, width, x_bounds in (
        ("front-wall-left", (-4.2, 1.62, 0.5), 3.6, (-6.1, -2.3)),
        ("front-wall-right", (4.2, 1.62, 0.5), 3.6, (2.3, 6.1)),
    ):
        _add(scene, objects, name, _inside(_box((width, 3.4, 0.20), centre, list(wall), name)), "wall")
        collisions.append(_collision(name, x_bounds, (0.4, 0.6), "入口侧墙"))
    _add(scene, objects, "front-lintel", _inside(_box((4.6, 0.75, 0.20), (0.0, 3.05, 0.5), list(wall), "front-lintel")), "wall_detail")
    collisions.extend([
        _collision("left-wall", (-6.1, -5.9), (-15.6, 0.6), "左墙"),
        _collision("right-wall", (5.9, 6.1), (-15.6, 0.6), "右墙"),
        _collision("back-wall", (-6.1, 6.1), (-15.6, -15.4), "后墙"),
    ])

    if gallery:
        furnishings = [
            ("pedestal-left", (1.0, 1.15, 1.0), (-3.0, 0.58, -5.5), trim, (-3.5, -2.5, -6.1, -4.9), "展台"),
            ("pedestal-right", (1.0, 1.15, 1.0), (3.0, 0.58, -8.5), trim, (2.5, 3.5, -9.1, -7.9), "展台"),
            ("bench", (3.0, 0.70, 0.75), (0.0, 0.35, -11.4), list(_tint(average, 0.48)), (-1.5, 1.5, -11.8, -11.0), "长凳"),
        ]
    else:
        furnishings = [
            ("table-top", (2.6, 0.16, 1.45), (0.0, 1.00, -5.0), list(_tint(average, 0.50)), (-1.35, 1.35, -5.75, -4.25), "桌子"),
            ("sofa-body", (3.2, 0.70, 1.25), (-3.15, 0.43, -9.0), list(_tint(average, 0.42)), (-4.8, -1.5, -9.65, -8.35), "沙发"),
            ("sofa-back", (3.2, 1.35, 0.24), (-3.15, 1.05, -9.53), list(_tint(average, 0.36)), (-4.8, -1.5, -9.7, -9.4), "沙发靠背"),
            ("sideboard", (2.2, 1.0, 0.55), (3.55, 0.50, -12.0), list(_tint(average, 0.55)), (2.45, 4.65, -12.3, -11.7), "柜子"),
        ]
    for name, extents, centre, colour, bounds, label in furnishings:
        _add(scene, objects, name, _box(extents, centre, colour, name), "furniture")
        collisions.append(_collision(name, (bounds[0], bounds[1]), (bounds[2], bounds[3]), label))

    # Legs make the table read as an object with volume instead of a floating
    # slab. The table collision stays a single conservative box.
    if not gallery:
        for index, x in enumerate((-1.05, 1.05)):
            for z in (-5.48, -4.52):
                _add(scene, objects, f"table-leg-{index}-{z}", _box((0.14, 1.0, 0.14), (x, 0.48, z), list(_tint(average, 0.44)), "table-leg"), "furniture_detail")

    _add_framed_panel(scene, objects, image_path, -15.36, wall)
    movement = MovementProfile(
        kind="coarse_gallery" if gallery else "coarse_room",
        start=[0.0, 1.60, 0.0],
        bounds={"x": [-5.45, 5.45], "y": [1.20, 2.65], "z": [-15.15, 0.45]},
        walk_speed=2.4,
        fly_speed=0.0,
        allow_flight=False,
        ground_follow=True,
        ground_y=1.60,
        collision_radius=0.34,
        route_checkpoints=[[0.0, 1.60, -2.0], [2.2, 1.60, -4.0], [-2.2, 1.60, -7.0], [0.0, 1.60, -12.5]],
        collision_boxes=collisions,
    )
    return scene, movement, objects, "室内照片被放入自动粗模房间的展示框；墙、地面和家具为程序化估计。"


def _outdoor_layout(image_path: Path) -> tuple[trimesh.Scene, MovementProfile, list[dict[str, object]], str | None]:
    average = _average_colour(image_path)
    scene = trimesh.Scene()
    objects: list[dict[str, object]] = []
    collisions: list[CollisionBox] = []
    ground = list(_tint(average, 0.68))
    _add(scene, objects, "ground", _box((24.0, 0.20, 26.0), (0.0, -0.10, -12.5), ground, "ground"), "floor")
    structures = [
        ("landmark-left", (2.8, 3.4, 2.2), (-5.0, 1.7, -8.0), list(_tint(average, 0.48)), (-6.4, -3.6, -9.1, -6.9), "地标体块"),
        ("landmark-right", (3.4, 5.0, 2.4), (5.2, 2.5, -14.0), list(_tint(average, 0.56)), (3.5, 6.9, -15.2, -12.8), "地标体块"),
        ("marker", (1.2, 2.0, 1.2), (0.0, 1.0, -19.0), list(_tint(average, 0.42)), (-0.6, 0.6, -19.6, -18.4), "标记物"),
    ]
    for name, extents, centre, colour, bounds, label in structures:
        _add(scene, objects, name, _box(extents, centre, colour, name), "landmark")
        collisions.append(_collision(name, (bounds[0], bounds[1]), (bounds[2], bounds[3]), label))
    # A billboard keeps the supplied photo visible without making it a false
    # claim of a panoramic environment.
    _add_framed_panel(scene, objects, image_path, -21.0, tuple(_tint(average, 1.1)))
    movement = MovementProfile(
        kind="coarse_outdoor",
        start=[0.0, 1.60, 0.0],
        bounds={"x": [-10.8, 10.8], "y": [1.20, 8.0], "z": [-24.8, 0.8]},
        walk_speed=2.8,
        fly_speed=0.0,
        allow_flight=False,
        ground_follow=True,
        ground_y=1.60,
        collision_radius=0.34,
        route_checkpoints=[[0.0, 1.60, -5.0], [2.5, 1.60, -10.0], [-2.5, 1.60, -17.0]],
        collision_boxes=collisions,
    )
    return scene, movement, objects, "照片被用作自动粗模户外空间的远景展示面；地面和地标为程序化估计。"


def build_coarse_scene(
    image_path: Path,
    scene_path: Path,
    template: SceneTemplate,
    mock: bool,
    *,
    fallback_reason: str = "deadline_coarse_route",
) -> dict[str, object]:
    """Generate a walkable coarse GLB and its shared layout description."""

    outdoor_templates = {SceneTemplate.landscape_journey, SceneTemplate.street_descent, SceneTemplate.facade_flight}
    gallery_templates = {
        SceneTemplate.animal_diorama,
        SceneTemplate.memory_stage,
        SceneTemplate.tabletop_world,
        SceneTemplate.layered_canvas,
        SceneTemplate.generic_layers,
    }
    if template in outdoor_templates:
        scene, movement, objects, note = _outdoor_layout(image_path)
        route = "coarse_outdoor"
    else:
        scene, movement, objects, note = _room_layout(image_path, gallery=template in gallery_templates)
        route = "coarse_gallery" if template in gallery_templates else "coarse_room"
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    scene.export(scene_path, file_type="glb")
    bounds = np.asarray(scene.to_geometry().bounds, dtype=np.float64)
    if bounds.shape != (2, 3) or not np.isfinite(bounds).all():
        raise ValueError("自动粗模没有有效边界")
    collision_payload = [box.model_dump(mode="json") for box in movement.collision_boxes]
    layout_payload = {
        "layout_version": LAYOUT_VERSION,
        "route": route,
        "template": template.value,
        "estimated_scale": 1.0,
        "objects": objects,
        "movement": movement.model_dump(mode="json"),
        "source_image": image_path.name,
    }
    (scene_path.parent / "layout.json").write_text(json.dumps(layout_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (scene_path.parent / "collision.json").write_text(json.dumps({"layout_version": LAYOUT_VERSION, "boxes": collision_payload}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "coverage": None,
        "generated_region_note": note,
        "mock": mock,
        "scene_source": "procedural_coarse",
        "fallback_reason": fallback_reason,
        "layout_version": LAYOUT_VERSION,
        "estimated_scale": 1.0,
        "provider_version": "coarse-scene-v1",
        "movement": movement.model_dump(mode="json"),
        "scene_bounds": bounds.tolist(),
        "camera": {
            "position": movement.start,
            "image_size": [1280, 720],
            "world_scale": 1.0,
            "near": 0.05,
            "far": 80.0,
            "fov_x": 90.0,
            "fov_y": 68.0,
            "coordinate_frame_id": "coarse-world-v1",
        },
        "resource_files": ["layout.json", "collision.json"],
        "collision_resource": "collision.json",
    }
