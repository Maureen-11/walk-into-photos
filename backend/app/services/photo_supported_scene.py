from __future__ import annotations

"""Photo-supported structure around the original MoGe surface.

MoGe supplies the most valuable part of a single-image reconstruction: a
camera-facing, photo-coloured surface with a camera contract.  This module
adds only the structural pieces needed for a bounded walk (floor, closure
planes and a few visible proxies).  It never replaces the source surface with
a grey room and it writes the same layout information used for collisions.
"""

import json
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from app.config import Settings
from app.models import CollisionBox, MovementProfile, RegionConfirmation, SceneTemplate


LAYOUT_VERSION = "photo-structure-v1"


def _average_colour(image_path: Path) -> tuple[int, int, int]:
    try:
        with Image.open(image_path).convert("RGB") as image:
            sample = image.resize((1, 1), Image.Resampling.BILINEAR)
            return tuple(int(value) for value in sample.getpixel((0, 0)))
    except (OSError, ValueError):
        return (150, 160, 180)


def _colour(base: tuple[int, int, int], factor: float) -> list[int]:
    return [int(max(0, min(255, round(channel * factor)))) for channel in base]


def _box(
    extents: tuple[float, float, float],
    center: tuple[float, float, float],
    colour: list[int],
    name: str,
) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(center)
    mesh.visual.vertex_colors = np.tile(np.asarray([*colour, 255], dtype=np.uint8), (len(mesh.vertices), 1))
    mesh.metadata["layout_name"] = name
    return mesh


def _collision(name: str, mesh: trimesh.Trimesh, label: str) -> CollisionBox:
    bounds = np.asarray(mesh.bounds, dtype=np.float64)
    return CollisionBox(
        box_id=name,
        bounds={"x": [float(bounds[0, 0]), float(bounds[1, 0])], "z": [float(bounds[0, 2]), float(bounds[1, 2])]},
        label=label,
    )


def _add(
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    name: str,
    mesh: trimesh.Trimesh,
    role: str,
    collision: CollisionBox | None = None,
) -> None:
    scene.add_geometry(mesh, geom_name=name)
    objects.append({"id": name, "role": role, "bounds": np.asarray(mesh.bounds, dtype=float).tolist()})
    if collision is not None:
        objects[-1]["collision_box_id"] = collision.box_id


def _valid_bounds(scene: trimesh.Scene) -> tuple[np.ndarray, np.ndarray]:
    bounds = np.asarray(scene.bounds, dtype=np.float64)
    if bounds.shape != (2, 3) or not np.isfinite(bounds).all():
        raise ValueError("MoGe 场景没有有效边界")
    lower, upper = bounds
    if np.any(upper <= lower):
        raise ValueError("MoGe 场景边界退化")
    return lower, upper


def _movement(
    template: SceneTemplate,
    lower: np.ndarray,
    upper: np.ndarray,
    collisions: list[CollisionBox],
) -> MovementProfile:
    width = max(float(upper[0] - lower[0]), 3.0)
    depth = max(float(upper[2] - lower[2]), 6.0)
    x_margin = min(max(0.30, width * 0.04), 1.0)
    z_margin = min(max(0.30, depth * 0.025), 1.0)
    kind = {
        SceneTemplate.indoor_walk: "photo_indoor_walk",
        SceneTemplate.landscape_journey: "photo_natural_walk",
        SceneTemplate.street_descent: "photo_street_walk",
        SceneTemplate.facade_flight: "photo_building_walk",
    }.get(template, "photo_supported_walk")
    outdoor = template in {SceneTemplate.landscape_journey, SceneTemplate.street_descent}
    return MovementProfile(
        kind=kind,
        start=[0.0, 0.0, 0.0],
        bounds={
            "x": [float(lower[0] - x_margin), float(upper[0] + x_margin)],
            "y": [0.0, 0.0],
            "z": [float(lower[2] - z_margin), float(max(upper[2] + z_margin, 0.25))],
        },
        walk_speed=2.0 if not outdoor else 2.4,
        fly_speed=0.0,
        allow_flight=False,
        ground_follow=False,
        ground_y=0.0,
        collision_radius=0.30,
        route_checkpoints=[
            [0.0, 0.0, float(max(lower[2] + depth * 0.22, -2.0))],
            [float(min(upper[0] * 0.35, 2.0)), 0.0, float(max(lower[2] + depth * 0.48, -4.0))],
            [float(max(lower[0] * 0.35, -2.0)), 0.0, float(max(lower[2] + depth * 0.72, -6.0))],
        ],
        collision_boxes=collisions,
    )


def _add_indoor_structure(
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    collisions: list[CollisionBox],
    lower: np.ndarray,
    upper: np.ndarray,
    average: tuple[int, int, int],
    manual_regions: list[RegionConfirmation] | None = None,
) -> list[str]:
    width = min(max(float(upper[0] - lower[0]), 4.0), 22.0)
    depth = min(max(float(upper[2] - lower[2]), 8.0), 28.0)
    height = min(max(float(upper[1] - lower[1]), 2.6), 5.0)
    x_center = float((lower[0] + upper[0]) * 0.5)
    z_center = float((lower[2] + upper[2]) * 0.5)
    floor_y = min(float(lower[1]), 0.0) - 0.08
    generated: list[str] = []

    floor = _box((width + 0.8, 0.16, depth + 0.8), (x_center, floor_y, z_center), _colour(average, 0.72), "generated-floor")
    _add(scene, objects, "generated-floor", floor, "generated_floor")
    generated.append("generated-floor")
    for name, center in (
        ("generated-left-wall", (float(lower[0] - 0.06), (floor_y + height) * 0.5, z_center)),
        ("generated-right-wall", (float(upper[0] + 0.06), (floor_y + height) * 0.5, z_center)),
        ("generated-back-wall", (x_center, (floor_y + height) * 0.5, float(lower[2] - 0.06))),
    ):
        extents = (0.12, height, depth + 0.9) if "left" in name or "right" in name else (width + 0.9, height, 0.12)
        wall = _box(extents, center, _colour(average, 1.08), name)
        collision = _collision(name, wall, "照片支持结构边界")
        _add(scene, objects, name, wall, "generated_wall", collision)
        collisions.append(collision)
        generated.append(name)

    # One solid, clearly visible proxy provides a real obstacle for the route
    # test. Its location is deliberately away from the capture origin.
    obstacle_width = min(max(width * 0.24, 0.9), 3.0)
    obstacle_depth = min(max(depth * 0.10, 0.75), 1.6)
    obstacle_z = float(lower[2] + depth * 0.42)
    if obstacle_z > -1.0:
        obstacle_z = -1.8
    obstacle_x = x_center
    obstacle_regions = [region for region in (manual_regions or []) if region.role == "obstacle"]
    if obstacle_regions:
        confirmed = obstacle_regions[-1]
        obstacle_x = float(lower[0] + (confirmed.x + confirmed.width * 0.5) * (upper[0] - lower[0]))
    obstacle = _box(
        (obstacle_width, 0.86, obstacle_depth),
        (obstacle_x, floor_y + 0.43, obstacle_z),
        _colour(average, 0.48),
        "generated-obstacle-proxy",
    )
    obstacle_collision = _collision("generated-obstacle-proxy", obstacle, "照片中主要家具的简化障碍代理")
    _add(scene, objects, "generated-obstacle-proxy", obstacle, "generated_obstacle", obstacle_collision)
    collisions.append(obstacle_collision)
    generated.append("generated-obstacle-proxy")
    return generated


def _add_natural_structure(
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    lower: np.ndarray,
    upper: np.ndarray,
    average: tuple[int, int, int],
) -> list[str]:
    width = min(max(float(upper[0] - lower[0]), 12.0), 36.0)
    depth = min(max(float(upper[2] - lower[2]), 18.0), 40.0)
    floor_y = min(float(lower[1]), 0.0) - 0.10
    ground = _box((width + 10.0, 0.18, depth + 10.0), (0.0, floor_y, float((lower[2] + upper[2]) * 0.5)), _colour(average, 0.78), "generated-terrain-ground")
    _add(scene, objects, "generated-terrain-ground", ground, "generated_ground")
    generated = ["generated-terrain-ground"]
    ridge_colour = _colour(average, 0.56)
    for index, factor in enumerate((0.30, 0.48, 0.66)):
        ridge = trimesh.creation.cone(radius=max(2.5, width * 0.13), height=max(2.0, depth * 0.20), sections=8)
        ridge.apply_translation([(-width * 0.30) + index * width * 0.30, floor_y + depth * 0.10, float(lower[2] + depth * factor)])
        ridge.visual.vertex_colors = np.tile(np.asarray([*ridge_colour, 255], dtype=np.uint8), (len(ridge.vertices), 1))
        name = f"generated-distant-ridge-{index}"
        _add(scene, objects, name, ridge, "generated_distant_context")
        generated.append(name)
    return generated


def _add_street_structure(
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    collisions: list[CollisionBox],
    lower: np.ndarray,
    upper: np.ndarray,
    average: tuple[int, int, int],
) -> list[str]:
    width = min(max(float(upper[0] - lower[0]), 12.0), 30.0)
    depth = min(max(float(upper[2] - lower[2]), 16.0), 34.0)
    floor_y = min(float(lower[1]), 0.0) - 0.10
    ground = _box((width + 5.0, 0.18, depth + 5.0), (0.0, floor_y, float((lower[2] + upper[2]) * 0.5)), _colour(average, 0.66), "generated-street-ground")
    _add(scene, objects, "generated-street-ground", ground, "generated_ground")
    generated = ["generated-street-ground"]
    for index, x in enumerate((float(lower[0] - 0.5), float(upper[0] + 0.5))):
        block = _box((2.0, 3.2, depth * 0.34), (x, floor_y + 1.6, float(lower[2] + depth * (0.28 if index == 0 else 0.55))), _colour(average, 0.52), f"generated-street-block-{index}")
        collision = _collision(f"generated-street-block-{index}", block, "街道边缘简化建筑体块")
        _add(scene, objects, f"generated-street-block-{index}", block, "generated_building", collision)
        collisions.append(collision)
        generated.append(f"generated-street-block-{index}")
    return generated


def _add_building_structure(
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    collisions: list[CollisionBox],
    lower: np.ndarray,
    upper: np.ndarray,
    average: tuple[int, int, int],
) -> list[str]:
    width = min(max(float(upper[0] - lower[0]), 8.0), 30.0)
    height = min(max(float(upper[1] - lower[1]), 5.0), 18.0)
    facade = _box((width + 1.0, height + 1.0, 0.22), (float((lower[0] + upper[0]) * 0.5), height * 0.5, float(lower[2] - 0.12)), _colour(average, 0.72), "generated-facade-thickness")
    collision = _collision("generated-facade-thickness", facade, "建筑立面估计厚度")
    _add(scene, objects, "generated-facade-thickness", facade, "generated_facade", collision)
    collisions.append(collision)
    floor = _box((width + 12.0, 0.18, max(10.0, float(upper[2] - lower[2]) + 10.0)), (0.0, min(float(lower[1]), 0.0) - 0.1, float((lower[2] + upper[2]) * 0.5)), _colour(average, 0.62), "generated-building-ground")
    _add(scene, objects, "generated-building-ground", floor, "generated_ground")
    return ["generated-facade-thickness", "generated-building-ground"]


def build_photo_supported_scene(
    image_path: Path,
    scene_path: Path,
    template: SceneTemplate,
    moge_result: dict[str, object],
    settings: Settings,
    manual_regions: list[RegionConfirmation] | None = None,
) -> dict[str, object]:
    """Keep MoGe's photo surface and add bounded, category-aware structure."""

    scene = trimesh.load(scene_path, force="scene")
    lower, upper = _valid_bounds(scene)
    average = _average_colour(image_path)
    objects: list[dict[str, object]] = []
    collisions: list[CollisionBox] = []
    if template is SceneTemplate.indoor_walk:
        generated = _add_indoor_structure(scene, objects, collisions, lower, upper, average, manual_regions=manual_regions)
        note = "室内路线保留 MoGe 照片投色表面；墙地连接与一个可见障碍为简化结构，未声称不可见区域真实还原。"
    elif template is SceneTemplate.landscape_journey:
        generated = _add_natural_structure(scene, objects, lower, upper, average)
        note = "自然路线保留 MoGe 照片表面；近地连续面和远景山脊为程序化补全面，远景不等同于真实地形。"
    elif template is SceneTemplate.street_descent:
        generated = _add_street_structure(scene, objects, collisions, lower, upper, average)
        note = "街道路由保留照片表面；道路和边缘建筑为简化实体，未将照片中的人物或车辆伪装成完整模型。"
    elif template is SceneTemplate.facade_flight:
        generated = _add_building_structure(scene, objects, collisions, lower, upper, average)
        note = "建筑路线保留照片表面、窗线和前景；立面厚度及前景地面为估计结构，不承诺进入未知室内。"
    else:
        generated = _add_natural_structure(scene, objects, lower, upper, average)
        note = "照片表面保留为主要可见内容；未识别空间使用有限程序化补全面并明确标注。"

    scene.export(scene_path, file_type="glb")
    movement = _movement(template, lower, upper, collisions)
    normalized_regions = [region.model_dump(mode="json") for region in (manual_regions or [])]
    layout_payload = {
        "layout_version": LAYOUT_VERSION,
        "route": "photo_supported",
        "template": template.value,
        "estimated_scale": float(moge_result.get("normalization", {}).get("world_scale", 1.0)),
        "photo_surface": "moge-camera-facing-surface",
        "objects": objects,
        "generated_regions": generated,
        "manual_regions": normalized_regions,
        "movement": movement.model_dump(mode="json"),
        "source_image": image_path.name,
    }
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    (scene_path.parent / "layout.json").write_text(json.dumps(layout_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (scene_path.parent / "collision.json").write_text(
        json.dumps({"layout_version": LAYOUT_VERSION, "boxes": [box.model_dump(mode="json") for box in collisions]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if manual_regions:
        note += " 本次使用了用户提供的区域确认，已写入布局证据。"
    return {
        **moge_result,
        "generated_region_note": note,
        "mock": False,
        "scene_source": "photo_supported_quality",
        "fallback_reason": None,
        "layout_version": LAYOUT_VERSION,
        "estimated_scale": float(moge_result.get("normalization", {}).get("world_scale", 1.0)),
        "provider_version": f"moge-{settings.moge_version}:{settings.moge_pretrained}+photo-structure-v1",
        "movement": movement.model_dump(mode="json"),
        "scene_bounds": np.asarray(scene.bounds, dtype=float).tolist(),
        "resource_files": ["layout.json", "collision.json"],
        "collision_resource": "collision.json",
        "photo_supported_regions": ["moge_camera_surface"],
        "generated_regions": generated,
        "manual_assisted": bool(manual_regions),
    }
