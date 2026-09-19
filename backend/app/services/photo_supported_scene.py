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


def _region_colour(image_path: Path, box: tuple[float, float, float, float], fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    """Read a stable colour cue from a normalized image band.

    This is deliberately a palette cue, not texture synthesis. Generated
    structure keeps its own material provenance while avoiding one global
    grey average for every wall, floor, and distant object.
    """

    try:
        with Image.open(image_path).convert("RGB") as image:
            width, height = image.size
            left, top, right, bottom = box
            crop = image.crop((
                int(max(0.0, min(1.0, left)) * width),
                int(max(0.0, min(1.0, top)) * height),
                int(max(0.0, min(1.0, right)) * width),
                int(max(0.0, min(1.0, bottom)) * height),
            ))
            if crop.width < 1 or crop.height < 1:
                return fallback
            sample = crop.resize((1, 1), Image.Resampling.BILINEAR)
            return tuple(int(value) for value in sample.getpixel((0, 0)))
    except (OSError, ValueError):
        return fallback


def _photo_palette(image_path: Path) -> dict[str, tuple[int, int, int]]:
    average = _average_colour(image_path)
    return {
        "average": average,
        "upper": _region_colour(image_path, (0.12, 0.02, 0.88, 0.28), average),
        "lower": _region_colour(image_path, (0.12, 0.68, 0.88, 0.98), average),
        "left": _region_colour(image_path, (0.02, 0.18, 0.28, 0.82), average),
        "right": _region_colour(image_path, (0.72, 0.18, 0.98, 0.82), average),
        "centre": _region_colour(image_path, (0.34, 0.30, 0.66, 0.78), average),
    }


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


def _ridge(
    width: float,
    height: float,
    base_y: float,
    center_z: float,
    thickness: float,
    colour: list[int],
    name: str,
) -> trimesh.Trimesh:
    """Create a bounded, thick distant ridge rather than a depth-axis cone."""

    profile = np.asarray(
        [(-0.50, 0.0), (-0.38, 0.42), (-0.23, 0.28), (-0.08, 0.72),
         (0.08, 0.46), (0.23, 0.82), (0.38, 0.34), (0.50, 0.0)],
        dtype=np.float64,
    )
    front = np.column_stack((profile[:, 0] * width, base_y + profile[:, 1] * height, np.full(len(profile), center_z - thickness / 2)))
    back = np.column_stack((profile[:, 0] * width, base_y + profile[:, 1] * height, np.full(len(profile), center_z + thickness / 2)))
    vertices = np.vstack((front, back))
    count = len(profile)
    faces: list[list[int]] = []
    for index in range(count - 1):
        next_index = index + 1
        faces.extend([
            [index, next_index, count + next_index],
            [index, count + next_index, count + index],
        ])
    faces.extend([[count - 1, 0, count], [count - 1, count, count + count - 1]])
    mesh = trimesh.Trimesh(vertices=vertices, faces=np.asarray(faces, dtype=np.int64), process=False)
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
    route_checkpoints = [
        [0.0, 0.0, float(max(lower[2] + depth * 0.22, -2.0))],
        [float(min(upper[0] * 0.35, 2.0)), 0.0, float(max(lower[2] + depth * 0.48, -4.0))],
        [float(max(lower[0] * 0.35, -2.0)), 0.0, float(max(lower[2] + depth * 0.72, -6.0))],
    ]
    if template is SceneTemplate.indoor_walk and collisions:
        # Keep a concrete, inspectable route for the one generated obstacle:
        # approach it on the capture axis, move to a free side, then pass it.
        # These are evidence checkpoints, not an automatic camera path.
        obstacle_bounds = collisions[-1].bounds
        obstacle_x = obstacle_bounds["x"]
        obstacle_z = obstacle_bounds["z"]
        if obstacle_x and obstacle_z:
            x_lower = float(lower[0] + x_margin + 0.15)
            x_upper = float(upper[0] - x_margin - 0.15)
            left_side = float(obstacle_x[0] - 0.30 - 0.45)
            right_side = float(obstacle_x[1] + 0.30 + 0.45)
            candidates = [side for side in (left_side, right_side) if x_lower <= side <= x_upper]
            if candidates:
                side = min(candidates, key=lambda value: abs(value))
                approach_z = float(max(lower[2] + 1.0, obstacle_z[1] + 0.85))
                pass_z = float(max(lower[2] + 1.0, obstacle_z[0] - 0.85))
                route_checkpoints = [
                    [0.0, 0.0, approach_z],
                    [side, 0.0, approach_z],
                    [side, 0.0, pass_z],
                ]
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
        route_checkpoints=route_checkpoints,
        collision_boxes=collisions,
    )


def _add_indoor_structure(
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    collisions: list[CollisionBox],
    lower: np.ndarray,
    upper: np.ndarray,
    palette: dict[str, tuple[int, int, int]],
    manual_regions: list[RegionConfirmation] | None = None,
) -> list[str]:
    width = min(max(float(upper[0] - lower[0]), 4.0), 22.0)
    depth = min(max(float(upper[2] - lower[2]), 8.0), 28.0)
    height = min(max(float(upper[1] - lower[1]), 2.6), 5.0)
    x_center = float((lower[0] + upper[0]) * 0.5)
    z_center = float((lower[2] + upper[2]) * 0.5)
    floor_y = min(float(lower[1]), 0.0) - 0.08
    generated: list[str] = []

    floor = _box((width + 0.8, 0.16, depth + 0.8), (x_center, floor_y, z_center), _colour(palette["lower"], 0.82), "generated-floor")
    _add(scene, objects, "generated-floor", floor, "generated_floor")
    generated.append("generated-floor")
    for name, center in (
        ("generated-left-wall", (float(lower[0] - 0.06), (floor_y + height) * 0.5, z_center)),
        ("generated-right-wall", (float(upper[0] + 0.06), (floor_y + height) * 0.5, z_center)),
        ("generated-back-wall", (x_center, (floor_y + height) * 0.5, float(lower[2] - 0.06))),
    ):
        extents = (0.12, height, depth + 0.9) if "left" in name or "right" in name else (width + 0.9, height, 0.12)
        wall_colour = palette["left"] if "left" in name else palette["right"] if "right" in name else palette["upper"]
        wall = _box(extents, center, _colour(wall_colour, 1.04), name)
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
        _colour(palette["centre"], 0.58),
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
    palette: dict[str, tuple[int, int, int]],
) -> list[str]:
    width = min(max(float(upper[0] - lower[0]), 12.0), 36.0)
    depth = min(max(float(upper[2] - lower[2]), 18.0), 40.0)
    floor_y = min(float(lower[1]), 0.0) - 0.10
    ground = _box((width + 10.0, 0.18, depth + 10.0), (0.0, floor_y, float((lower[2] + upper[2]) * 0.5)), _colour(palette["lower"], 0.86), "generated-terrain-ground")
    _add(scene, objects, "generated-terrain-ground", ground, "generated_ground")
    generated = ["generated-terrain-ground"]
    ridge_colour = _colour(palette["upper"], 0.72)
    ridge_height = min(max(depth * 0.16, 2.2), 4.5)
    ridge_width = max(width * 0.85, 12.0)
    # More-negative z is farther from the capture point.  Keep these ridges
    # behind the near photo surface so they read as distant context instead of
    # giant foreground cones that occlude the source image.
    for index, factor in enumerate((0.22, 0.36, 0.50)):
        ridge = _ridge(
            ridge_width * (1.0 + index * 0.10),
            ridge_height * (0.72 + index * 0.12),
            floor_y + 0.02,
            float(lower[2] + depth * factor),
            max(0.20, depth * 0.018),
            ridge_colour,
            f"generated-distant-ridge-{index}",
        )
        ridge.apply_translation([0.0, 0.0, 0.0])
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
    palette: dict[str, tuple[int, int, int]],
) -> list[str]:
    width = min(max(float(upper[0] - lower[0]), 12.0), 30.0)
    depth = min(max(float(upper[2] - lower[2]), 16.0), 34.0)
    floor_y = min(float(lower[1]), 0.0) - 0.10
    ground = _box((width + 5.0, 0.18, depth + 5.0), (0.0, floor_y, float((lower[2] + upper[2]) * 0.5)), _colour(palette["lower"], 0.78), "generated-street-ground")
    _add(scene, objects, "generated-street-ground", ground, "generated_ground")
    generated = ["generated-street-ground"]
    for index, x in enumerate((float(lower[0] - 0.5), float(upper[0] + 0.5))):
        block_colour = palette["left"] if index == 0 else palette["right"]
        block = _box((2.0, 3.2, depth * 0.34), (x, floor_y + 1.6, float(lower[2] + depth * (0.28 if index == 0 else 0.55))), _colour(block_colour, 0.68), f"generated-street-block-{index}")
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
    palette: dict[str, tuple[int, int, int]],
) -> list[str]:
    width = min(max(float(upper[0] - lower[0]), 8.0), 30.0)
    height = min(max(float(upper[1] - lower[1]), 5.0), 18.0)
    facade = _box((width + 1.0, height + 1.0, 0.22), (float((lower[0] + upper[0]) * 0.5), height * 0.5, float(lower[2] - 0.12)), _colour(palette["centre"], 0.82), "generated-facade-thickness")
    collision = _collision("generated-facade-thickness", facade, "建筑立面估计厚度")
    _add(scene, objects, "generated-facade-thickness", facade, "generated_facade", collision)
    collisions.append(collision)
    floor = _box((width + 12.0, 0.18, max(10.0, float(upper[2] - lower[2]) + 10.0)), (0.0, min(float(lower[1]), 0.0) - 0.1, float((lower[2] + upper[2]) * 0.5)), _colour(palette["lower"], 0.74), "generated-building-ground")
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
    palette = _photo_palette(image_path)
    objects: list[dict[str, object]] = []
    collisions: list[CollisionBox] = []
    if template is SceneTemplate.indoor_walk:
        generated = _add_indoor_structure(scene, objects, collisions, lower, upper, palette, manual_regions=manual_regions)
        note = "室内路线保留 MoGe 照片投色表面；墙地连接与一个可见障碍为简化结构，未声称不可见区域真实还原。"
    elif template is SceneTemplate.landscape_journey:
        generated = _add_natural_structure(scene, objects, lower, upper, palette)
        note = "自然路线保留 MoGe 照片表面；近地连续面和远景山脊为程序化补全面，远景不等同于真实地形。"
    elif template is SceneTemplate.street_descent:
        generated = _add_street_structure(scene, objects, collisions, lower, upper, palette)
        note = "街道路由保留照片表面；道路和边缘建筑为简化实体，未将照片中的人物或车辆伪装成完整模型。"
    elif template is SceneTemplate.facade_flight:
        generated = _add_building_structure(scene, objects, collisions, lower, upper, palette)
        note = "建筑路线保留照片表面、窗线和前景；立面厚度及前景地面为估计结构，不承诺进入未知室内。"
    else:
        generated = _add_natural_structure(scene, objects, lower, upper, palette)
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
        "material_policy": "generated_structure_uses_photo_band_palette_not_full_image_texture",
        "material_palette": {key: list(value) for key, value in palette.items()},
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
