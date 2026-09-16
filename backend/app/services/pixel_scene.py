from __future__ import annotations

"""Small, isolated pixel-style scene route.

This is deliberately a sample generator, not a replacement for the current
photo-supported quality route.  It uses the input photo for stable palette
cues and a documented, parameterized indoor layout.  The generated blocks and
their collision boxes are derived from the same object table so the sample is
useful for testing the style, movement and offline delivery contract without
claiming single-image geometry recovery.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

from app.models import CameraSpec, CollisionBox, MovementProfile, SceneEngine, SceneManifest, SceneTemplate


PIXEL_LAYOUT_VERSION = "pixel-indoor-sample-v1"
BASE_VOXEL = 0.125
DETAIL_VOXEL = 0.0625
CHUNK_SIZE = 16
CHARACTER_RADIUS = 0.30


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _snap(value: float, grid: float = BASE_VOXEL) -> float:
    return round(round(value / grid) * grid, 6)


def _clamp_colour(values: tuple[int, int, int] | list[int]) -> list[int]:
    return [int(max(0, min(255, round(value)))) for value in values[:3]]


def _shade(colour: list[int], factor: float) -> list[int]:
    return _clamp_colour([channel * factor for channel in colour])


def _mix(first: list[int], second: list[int], amount: float) -> list[int]:
    return _clamp_colour([
        first[index] * (1.0 - amount) + second[index] * amount
        for index in range(3)
    ])


def _region_colour(image: Image.Image, box: tuple[float, float, float, float]) -> list[int]:
    width, height = image.size
    left, top, right, bottom = box
    crop = image.crop((
        int(max(0.0, min(1.0, left)) * width),
        int(max(0.0, min(1.0, top)) * height),
        int(max(0.0, min(1.0, right)) * width),
        int(max(0.0, min(1.0, bottom)) * height),
    ))
    if crop.width < 1 or crop.height < 1:
        return [150, 160, 180]
    sample = crop.resize((1, 1), Image.Resampling.BILINEAR)
    return _clamp_colour(sample.getpixel((0, 0)))


def _palette(image_path: Path) -> dict[str, object]:
    """Derive a bounded palette without turning the photo into a wall texture."""

    with Image.open(image_path).convert("RGB") as source:
        image = source.copy()
        quantized = image.resize((96, 96), Image.Resampling.BILINEAR).quantize(
            colors=32,
            method=Image.Quantize.MEDIANCUT,
        )
        raw = quantized.getpalette() or []
        colours: list[list[int]] = []
        for index in range(32):
            start = index * 3
            if start + 2 >= len(raw):
                break
            colour = _clamp_colour(raw[start:start + 3])
            if colour not in colours:
                colours.append(colour)
        average = _region_colour(image, (0.05, 0.05, 0.95, 0.95))
        upper = _region_colour(image, (0.10, 0.02, 0.90, 0.30))
        lower = _region_colour(image, (0.10, 0.68, 0.90, 0.98))
        centre = _region_colour(image, (0.30, 0.30, 0.70, 0.78))
        left = _region_colour(image, (0.02, 0.20, 0.30, 0.82))
        right = _region_colour(image, (0.70, 0.20, 0.98, 0.82))

    neutral = [235, 230, 218]
    dark = [38, 39, 46]
    warm = [224, 156, 92]
    green = [82, 132, 82]
    return {
        "base_32": colours[:32],
        "photo_bands": {
            "average": average,
            "upper": upper,
            "lower": lower,
            "centre": centre,
            "left": left,
            "right": right,
        },
        "roles": {
            "wall": _mix(upper, neutral, 0.35),
            "floor": _mix(lower, [128, 112, 98], 0.42),
            "trim": _mix(upper, dark, 0.52),
            "sofa": _mix(centre, [170, 145, 120], 0.26),
            "wood": _mix(lower, [112, 66, 35], 0.45),
            "metal": _mix(right, [74, 83, 96], 0.45),
            "window": _mix(upper, [164, 207, 224], 0.58),
            "plant": green,
            "lamp": warm,
            "dark": dark,
        },
    }


def _box_mesh(
    extents: tuple[float, float, float],
    center: tuple[float, float, float],
    colour: list[int],
    name: str,
    grid: float = BASE_VOXEL,
) -> trimesh.Trimesh:
    snapped_extents = tuple(max(grid, _snap(value, grid)) for value in extents)
    snapped_center = tuple(_snap(value, grid) for value in center)
    mesh = trimesh.creation.box(extents=snapped_extents)
    mesh.apply_translation(snapped_center)
    mesh.visual.vertex_colors = np.tile(np.asarray([*colour, 255], dtype=np.uint8), (len(mesh.vertices), 1))
    # Vertex colours alone are not consistently promoted to a visible
    # material by every GLB viewer.  Keep them for inspection and also write a
    # concrete PBR base colour so the offline viewer preserves the palette.
    mesh.visual.material = trimesh.visual.material.PBRMaterial(
        baseColorFactor=[*colour, 255],
        metallicFactor=0.0,
        roughnessFactor=0.82,
    )
    mesh.metadata["layout_name"] = name
    mesh.metadata["voxel_grid"] = BASE_VOXEL
    return mesh


def _collision(box_id: str, mesh: trimesh.Trimesh, label: str) -> CollisionBox:
    bounds = np.asarray(mesh.bounds, dtype=float)
    return CollisionBox(
        box_id=box_id,
        bounds={
            "x": [float(bounds[0, 0]), float(bounds[1, 0])],
            "z": [float(bounds[0, 2]), float(bounds[1, 2])],
        },
        label=label,
    )


def _add_part(
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    collisions: list[CollisionBox],
    name: str,
    extents: tuple[float, float, float],
    center: tuple[float, float, float],
    colour: list[int],
    role: str,
    source: str,
    collision_label: str | None = None,
    grid: float = BASE_VOXEL,
) -> trimesh.Trimesh:
    # All final dimensions are quantized to the route grid.  Detail parts can
    # request the finer grid but remain ordinary merged boxes in the GLB.
    snapped_extents = tuple(max(grid, round(value / grid) * grid) for value in extents)
    snapped_center = tuple(round(value / grid) * grid for value in center)
    mesh = _box_mesh(snapped_extents, snapped_center, colour, name, grid=grid)
    scene.add_geometry(mesh, geom_name=name)
    bounds = np.asarray(mesh.bounds, dtype=float)
    entry: dict[str, object] = {
        "id": name,
        "role": role,
        "source": source,
        "voxel_grid": grid,
        "bounds": bounds.tolist(),
    }
    if collision_label is not None:
        collision = _collision(name, mesh, collision_label)
        collisions.append(collision)
        entry["collision_box_id"] = collision.box_id
    objects.append(entry)
    return mesh


def _movement(collisions: list[CollisionBox]) -> MovementProfile:
    return MovementProfile(
        kind="pixel_indoor_walk_sample",
        start=[0.0, 1.625, 4.75],
        bounds={"x": [-4.45, 4.45], "y": [1.625, 1.625], "z": [-6.15, 5.10]},
        walk_speed=2.0,
        fly_speed=0.0,
        allow_flight=False,
        ground_follow=False,
        ground_y=1.625,
        collision_radius=CHARACTER_RADIUS,
        route_checkpoints=[
            [0.0, 1.625, 2.0],
            [3.0, 1.625, 2.0],
            [3.0, 1.625, -3.5],
            [0.0, 1.625, -3.5],
            [0.0, 1.625, -5.5],
        ],
        collision_boxes=collisions,
    )


def build_pixel_indoor_sample(image_path: Path, output_dir: Path, scene_id: str = "pixel-v01-i02") -> dict[str, object]:
    """Build the isolated I02 pixel sample and return its manifest payload."""

    image_path = image_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    palette = _palette(image_path)
    roles = palette["roles"]
    assert isinstance(roles, dict)

    scene = trimesh.Scene()
    objects: list[dict[str, object]] = []
    collisions: list[CollisionBox] = []

    wall = roles["wall"]
    floor = roles["floor"]
    trim = roles["trim"]
    sofa = roles["sofa"]
    wood = roles["wood"]
    metal = roles["metal"]
    window = roles["window"]
    plant = roles["plant"]
    lamp = roles["lamp"]
    dark = roles["dark"]
    for value in (wall, floor, trim, sofa, wood, metal, window, plant, lamp, dark):
        if not isinstance(value, list):
            raise ValueError("pixel palette role is not a colour list")

    # Room shell.  The front remains open for the camera, while the three
    # thick boundaries make the sample an actual walkable room.
    _add_part(scene, objects, collisions, "pixel-floor", (9.75, 0.25, 12.25), (0.0, 0.0, -0.55), floor, "ground", "photo_palette_lower")
    _add_part(scene, objects, collisions, "pixel-left-wall", (0.25, 3.75, 12.25), (-4.875, 1.875, -0.55), wall, "wall", "photo_inferred_room_boundary", "左侧墙体")
    _add_part(scene, objects, collisions, "pixel-right-wall", (0.25, 3.75, 12.25), (4.875, 1.875, -0.55), _shade(wall, 0.92), "wall", "photo_inferred_room_boundary", "右侧墙体")
    _add_part(scene, objects, collisions, "pixel-back-wall", (9.75, 3.75, 0.25), (0.0, 1.875, -6.675), _shade(wall, 0.96), "wall", "photo_inferred_room_boundary", "后侧墙体")
    _add_part(scene, objects, [], "pixel-ceiling", (9.75, 0.25, 12.25), (0.0, 3.875, -0.55), _mix(wall, [245, 232, 208], 0.22), "ceiling", "photo_inferred_room_boundary")
    _add_part(scene, objects, [], "pixel-ceiling-beam-left", (0.25, 0.25, 12.25), (-3.65, 3.70, -0.55), trim, "ceiling_detail", "procedural_completion")
    _add_part(scene, objects, [], "pixel-ceiling-beam-right", (0.25, 0.25, 12.25), (3.65, 3.70, -0.55), trim, "ceiling_detail", "procedural_completion")

    # The capture side has a doorway-sized opening rather than an entirely
    # missing wall.  This keeps the 180-degree inspection inside the room and
    # makes the front boundary part of the same visible/collision contract.
    _add_part(scene, objects, collisions, "pixel-front-wall-left", (1.10, 3.75, 0.25), (-4.30, 1.875, 5.675), _shade(wall, 0.96), "wall", "procedural_completion", "前侧墙体")
    _add_part(scene, objects, collisions, "pixel-front-wall-right", (6.95, 3.75, 0.25), (1.45, 1.875, 5.675), _shade(wall, 0.96), "wall", "procedural_completion", "前侧墙体")
    _add_part(scene, objects, [], "pixel-front-wall-top", (1.95, 1.25, 0.25), (-2.75, 3.15, 5.675), _shade(wall, 0.96), "wall_detail", "procedural_completion")

    # A block-built window and door preserve the room opening vocabulary
    # without claiming that the wall segmentation came from a model.
    _add_part(scene, objects, [], "pixel-window-glow", (3.00, 2.10, 0.08), (1.75, 2.55, -6.50), window, "window_surface", "photo_band_upper")
    for name, center, extents in (
        ("pixel-window-top", (1.75, 3.70, -6.53), (3.30, 0.18, 0.18)),
        ("pixel-window-bottom", (1.75, 1.42, -6.53), (3.30, 0.18, 0.18)),
        ("pixel-window-left", (0.08, 2.56, -6.53), (0.18, 2.45, 0.18)),
        ("pixel-window-right", (3.42, 2.56, -6.53), (0.18, 2.45, 0.18)),
        ("pixel-window-mullion", (1.75, 2.56, -6.54), (0.16, 2.20, 0.20)),
    ):
        _add_part(scene, objects, [], name, extents, center, trim, "window_frame", "procedural_completion", grid=DETAIL_VOXEL)

    _add_part(scene, objects, [], "pixel-door", (1.25, 2.55, 0.10), (-3.45, 1.40, 4.76), _mix(wood, dark, 0.20), "door_surface", "photo_inferred_opening")
    for name, center, extents in (
        ("pixel-door-left", (-4.12, 1.40, 4.70), (0.16, 2.85, 0.20)),
        ("pixel-door-right", (-2.78, 1.40, 4.70), (0.16, 2.85, 0.20)),
        ("pixel-door-top", (-3.45, 2.82, 4.70), (1.50, 0.16, 0.20)),
    ):
        _add_part(scene, objects, [], name, extents, center, trim, "door_frame", "procedural_completion", grid=DETAIL_VOXEL)

    # Sofa: a few snapped blocks read as a low-detail upholstered object and
    # share one collision envelope with the visible pieces.
    sofa_parts = [
        ("pixel-sofa-base", (3.40, 0.55, 1.45), (-1.95, 0.42, -2.10), sofa),
        ("pixel-sofa-back", (3.40, 1.20, 0.35), (-1.95, 1.15, -2.65), _shade(sofa, 0.88)),
        ("pixel-sofa-arm-left", (0.35, 1.05, 1.45), (-3.55, 0.92, -2.10), _shade(sofa, 0.90)),
        ("pixel-sofa-arm-right", (0.35, 1.05, 1.45), (-0.35, 0.92, -2.10), _shade(sofa, 0.90)),
        ("pixel-sofa-cushion-left", (1.45, 0.25, 1.05), (-2.75, 0.82, -2.02), _mix(sofa, wall, 0.16)),
        ("pixel-sofa-cushion-right", (1.45, 0.25, 1.05), (-1.15, 0.82, -2.02), _mix(sofa, wall, 0.16)),
    ]
    for name, extents, center, colour in sofa_parts:
        _add_part(scene, objects, collisions, name, extents, center, colour, "furniture", "photo_inferred_furniture", "沙发简化体积" if name == "pixel-sofa-base" else None)

    _add_part(scene, objects, collisions, "pixel-coffee-table-top", (1.75, 0.25, 1.15), (1.25, 0.82, 0.55), wood, "furniture", "photo_inferred_furniture", "茶几简化体积")
    for index, x in enumerate((0.58, 1.92)):
        _add_part(scene, objects, [], f"pixel-coffee-table-leg-{index}", (0.16, 0.75, 0.16), (x, 0.40, 0.55), _shade(wood, 0.78), "furniture_detail", "procedural_completion", grid=DETAIL_VOXEL)

    # Console/TV and plant create two scale anchors without overfitting every
    # photograph.  They remain deliberately blocky and are labelled as
    # inferred or completion in layout.json.
    _add_part(scene, objects, collisions, "pixel-console", (1.65, 0.65, 0.45), (3.25, 0.55, -4.55), wood, "furniture", "photo_inferred_furniture", "电视柜简化体积")
    _add_part(scene, objects, [], "pixel-screen", (1.35, 1.00, 0.12), (3.25, 1.45, -4.53), dark, "display", "photo_inferred_object", grid=DETAIL_VOXEL)
    _add_part(scene, objects, [], "pixel-plant-pot", (0.70, 0.55, 0.70), (-3.55, 0.48, 0.45), wood, "decor", "procedural_completion")
    _add_part(scene, objects, [], "pixel-plant-stem", (0.18, 1.35, 0.18), (-3.55, 1.42, 0.45), plant, "decor", "procedural_completion", grid=DETAIL_VOXEL)
    for index, (x, y, z) in enumerate(((-3.92, 2.00, 0.45), (-3.25, 1.95, 0.45), (-3.55, 2.25, 0.45), (-3.55, 1.86, 0.82))):
        _add_part(scene, objects, [], f"pixel-plant-leaf-{index}", (0.48, 0.28, 0.48), (x, y, z), _mix(plant, wall, 0.12), "decor_detail", "procedural_completion", grid=DETAIL_VOXEL)
    _add_part(scene, objects, [], "pixel-lamp-glow", (0.42, 0.75, 0.42), (3.55, 2.55, 1.40), lamp, "warm_light_accent", "photo_palette_centre", grid=DETAIL_VOXEL)

    movement = _movement(collisions)
    scene_path = output_dir / "scene.glb"
    scene.export(scene_path, file_type="glb")
    layout_payload = {
        "layout_version": PIXEL_LAYOUT_VERSION,
        "route": "pixel_style_sample",
        "template": SceneTemplate.indoor_walk.value,
        "source_image": image_path.name,
        "source_sha256": _sha256(image_path),
        "style_route": "pixel_style_sample",
        "layout_authoring": "developer_sample_layout_no_user_region_confirmation",
        "pixel_spec": {
            "base_voxel": BASE_VOXEL,
            "detail_voxel": DETAIL_VOXEL,
            "distant_voxel": [0.5, 1.0],
            "chunk_size": [CHUNK_SIZE, CHUNK_SIZE, CHUNK_SIZE],
            "wall_thickness_voxels": 2,
            "character_radius": CHARACTER_RADIUS,
            "channel_width": 0.85,
            "mesh_policy": "snapped_block_parts_no_internal_voxel_faces_in_part_meshes",
            "texture_policy": "nearest_neighbour_pixel_material_cues_no_full_photo_projection",
            "palette_limit": 32,
        },
        "palette": palette,
        "objects": objects,
        "movement": movement.model_dump(mode="json"),
        "photo_supported_regions": ["palette_cues", "window_and_opening_vocabulary"],
        "generated_regions": ["room_shell", "furniture_blocks", "collision_envelope", "pixel_materials"],
    }
    (output_dir / "layout.json").write_text(json.dumps(layout_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "collision.json").write_text(
        json.dumps({"layout_version": PIXEL_LAYOUT_VERSION, "boxes": [box.model_dump(mode="json") for box in collisions]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    camera = CameraSpec(
        position=movement.start,
        image_size=[1024, 1536],
        world_scale=1.0,
        near=0.01,
        far=100.0,
        fov_y=58.0,
        coordinate_frame_id="pixel-sample-world-v1",
    )
    manifest = SceneManifest(
        scene_id=scene_id,
        scene_url=f"/api/scenes/{scene_id}/scene.glb",
        download_url=f"/api/scenes/{scene_id}/scene.glb",
        export_url=f"/api/scenes/{scene_id}/export",
        version="pixel-v01",
        template=SceneTemplate.indoor_walk,
        engine=SceneEngine.space,
        movement=movement,
        camera=camera,
        generated_region_note=(
            "像素风样板：I02 的照片色彩和开口关系用于参数提示；房间、家具和背面是手工参数化的风格化实体，"
            "不是单图真实几何复原。该样板尚未获得客户风格确认，也未替换写实默认路线。"
        ),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        mock=False,
        coverage=None,
        quality_status="unverified",
        quality_metrics={
            "machine_status": "candidate",
            "visual_status": "not_run",
            "style_acceptance": "waiting_client_review",
            "collision_status": "layout_checked",
        },
        input_sha256=_sha256(image_path),
        provider_version="pixel-voxel-v1",
        coordinate_frame_id=camera.coordinate_frame_id,
        resource_manifest=["scene.glb", "layout.json", "collision.json"],
        collision_resource="collision.json",
        acceptance_evidence=[],
        generation_source="pixel_style_sample",
        fallback_reason=None,
        layout_version=PIXEL_LAYOUT_VERSION,
        estimated_scale=1.0,
        quality_route=False,
        manual_assisted=False,
        photo_supported_regions=["palette_cues", "window_and_opening_vocabulary"],
        generated_regions=["room_shell", "furniture_blocks", "collision_envelope", "pixel_materials"],
        style_route="pixel_style_sample",
        pixel_spec=layout_payload["pixel_spec"],
    )
    (output_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V01\n\n"
        "这是 I02 室内照片的隔离风格候选，不是默认生成路线，也不代表真实空间复原。\n"
        "几何、材质、碰撞来自同一份 layout.json；像素规格和照片支持/程序化区域见 manifest.json。\n"
        "客户尚未确认风格，视觉状态保持 unverified。\n",
        encoding="utf-8",
    )
    return manifest.model_dump(mode="json")


PIXEL_V02_LAYOUT_VERSION = "pixel-indoor-v2-fine-detail"


def _image_size(image_path: Path) -> list[int]:
    with Image.open(image_path) as image:
        return [int(image.width), int(image.height)]


def _v02_spec() -> dict[str, object]:
    return {
        "base_voxel": BASE_VOXEL,
        "detail_voxel": DETAIL_VOXEL,
        "distant_voxel": [0.5, 1.0],
        "chunk_size": [CHUNK_SIZE, CHUNK_SIZE, CHUNK_SIZE],
        "wall_thickness_voxels": 2,
        "character_radius": CHARACTER_RADIUS,
        "channel_width": 0.85,
        "mesh_policy": "snapped_block_parts_with_fine_detail_layers",
        "texture_policy": "nearest_neighbour_pixel_material_cues_no_full_photo_projection",
        "palette_limit": 32,
        "detail_pass": "v02-fine-blocks-and-surface-breaks",
    }


def _finalize_v02(
    image_path: Path,
    output_dir: Path,
    scene_id: str,
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    collisions: list[CollisionBox],
    movement: MovementProfile,
    palette: dict[str, object],
    profile: str,
    note: str,
    photo_supported_regions: list[str],
    generated_regions: list[str],
    template: SceneTemplate = SceneTemplate.indoor_walk,
    engine: SceneEngine = SceneEngine.space,
    route_name: str = "pixel_style_sample_v2",
    layout_version: str = PIXEL_V02_LAYOUT_VERSION,
    version: str = "pixel-v02",
    provider_version: str = "pixel-voxel-v2",
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_path = output_dir / "scene.glb"
    scene.export(scene_path, file_type="glb")
    pixel_spec = _v02_spec()
    layout_payload = {
        "layout_version": layout_version,
        "route": route_name,
        "template": template.value,
        "profile": profile,
        "source_image": image_path.name,
        "source_sha256": _sha256(image_path),
        "style_route": route_name,
        "layout_authoring": "developer_sample_layout_no_user_region_confirmation",
        "pixel_spec": pixel_spec,
        "palette": palette,
        "objects": objects,
        "movement": movement.model_dump(mode="json"),
        "photo_supported_regions": photo_supported_regions,
        "generated_regions": generated_regions,
    }
    (output_dir / "layout.json").write_text(json.dumps(layout_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "collision.json").write_text(
        json.dumps({"layout_version": layout_version, "boxes": [box.model_dump(mode="json") for box in collisions]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    camera = CameraSpec(
        position=movement.start,
        image_size=_image_size(image_path),
        world_scale=1.0,
        near=0.01,
        far=100.0,
        fov_y=58.0,
        coordinate_frame_id="pixel-sample-world-v1",
    )
    manifest = SceneManifest(
        scene_id=scene_id,
        scene_url=f"/api/scenes/{scene_id}/scene.glb",
        download_url=f"/api/scenes/{scene_id}/scene.glb",
        export_url=f"/api/scenes/{scene_id}/export",
        version=version,
        template=template,
        engine=engine,
        movement=movement,
        camera=camera,
        generated_region_note=note,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        mock=False,
        coverage=None,
        quality_status="unverified",
        quality_metrics={
            "machine_status": "candidate",
            "visual_status": "not_run",
            "style_acceptance": "waiting_client_review",
            "collision_status": "layout_checked",
            "detail_pass": "fine_block_layers",
        },
        input_sha256=_sha256(image_path),
        provider_version=provider_version,
        coordinate_frame_id=camera.coordinate_frame_id,
        resource_manifest=["scene.glb", "layout.json", "collision.json"],
        collision_resource="collision.json",
        acceptance_evidence=[],
        generation_source=route_name,
        fallback_reason=None,
        layout_version=layout_version,
        estimated_scale=1.0,
        quality_route=False,
        manual_assisted=False,
        photo_supported_regions=photo_supported_regions,
        generated_regions=generated_regions,
        style_route=route_name,
        pixel_spec=pixel_spec,
    )
    (output_dir / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        f"Luna 像素风样板 {version}\n\n"
        f"样片：{profile}；这是隔离的细体素候选，不是默认生成路线，也不代表真实空间复原。\n"
        "V02 增加了细节栅格层、材质分层和样片差异化布局；客户尚未确认风格，视觉状态保持 unverified。\n",
        encoding="utf-8",
    )
    return manifest.model_dump(mode="json")


def build_pixel_living_v02(image_path: Path, output_dir: Path, scene_id: str = "pixel-v02-i02") -> dict[str, object]:
    """Refine the V01 living-room sample with smaller visible detail layers."""

    build_pixel_indoor_sample(image_path, output_dir, scene_id)
    scene = trimesh.load(output_dir / "scene.glb", force="scene")
    layout = json.loads((output_dir / "layout.json").read_text(encoding="utf-8"))
    objects = list(layout["objects"])
    collisions = [CollisionBox.model_validate(item) for item in layout["movement"]["collision_boxes"]]
    palette = layout["palette"]
    roles = palette["roles"]
    wall = roles["wall"]
    floor = roles["floor"]
    trim = roles["trim"]
    sofa = roles["sofa"]
    wood = roles["wood"]
    metal = roles["metal"]
    centre = roles["dark"]

    # The V01 silhouette remains, but the visible surfaces are split into
    # smaller snapped layers so the result reads as fine voxel work rather
    # than a few oversized boxes.
    _add_part(scene, objects, collisions, "pixel-v02-rug", (4.50, 0.08, 2.70), (0.0, 0.18, 0.30), _mix(sofa, floor, 0.24), "floor_detail", "photo_inferred_floor_region", grid=DETAIL_VOXEL)
    for index, (extents, center_pos) in enumerate((
        ((4.50, 0.035, 0.08), (0.0, 0.235, -1.02)),
        ((4.50, 0.035, 0.08), (0.0, 0.235, 1.62)),
        ((0.08, 0.035, 2.70), (-2.21, 0.235, 0.30)),
        ((0.08, 0.035, 2.70), (2.21, 0.235, 0.30)),
    )):
        _add_part(scene, objects, collisions, f"pixel-v02-rug-border-{index}", extents, center_pos, trim, "floor_detail", "procedural_completion", grid=DETAIL_VOXEL)
    for index, z in enumerate((-5.85, -4.70, -3.55, -2.40, -1.25, -0.10, 1.05, 2.20, 3.35, 4.50)):
        _add_part(scene, objects, collisions, f"pixel-v02-floor-seam-{index}", (9.10, 0.035, 0.035), (0.0, 0.145, z), _shade(floor, 0.78), "floor_detail", "procedural_completion", grid=DETAIL_VOXEL)

    # Sofa seams, buttons and table inlay add readable object structure while
    # preserving the deliberately low-detail silhouette.
    for index, x in enumerate((-2.75, -1.15)):
        _add_part(scene, objects, collisions, f"pixel-v02-sofa-seam-{index}", (0.04, 0.30, 0.92), (x, 0.84, -2.56), trim, "furniture_detail", "procedural_completion", grid=DETAIL_VOXEL)
        _add_part(scene, objects, collisions, f"pixel-v02-sofa-button-{index}", (0.12, 0.12, 0.12), (x, 1.25, -2.82), trim, "furniture_detail", "procedural_completion", grid=DETAIL_VOXEL)
    _add_part(scene, objects, collisions, "pixel-v02-table-inlay", (1.30, 0.045, 0.72), (1.25, 0.965, 0.55), _mix(wood, metal, 0.18), "furniture_detail", "procedural_completion", grid=DETAIL_VOXEL)
    _add_part(scene, objects, collisions, "pixel-v02-table-edge-front", (1.82, 0.12, 0.08), (1.25, 0.92, 1.10), _shade(wood, 0.78), "furniture_detail", "procedural_completion", grid=DETAIL_VOXEL)

    # Back wall art and baseboards break up the large flat surfaces.
    _add_part(scene, objects, collisions, "pixel-v02-wall-art", (1.35, 1.02, 0.07), (-2.25, 2.35, -6.50), _mix(sofa, wall, 0.35), "wall_detail", "photo_inferred_wall_object", grid=DETAIL_VOXEL)
    for index, (extents, centre_pos) in enumerate((
        ((1.52, 0.08, 0.08), (-2.25, 2.90, -6.54)),
        ((1.52, 0.08, 0.08), (-2.25, 1.80, -6.54)),
        ((0.08, 1.18, 0.08), (-2.95, 2.35, -6.54)),
        ((0.08, 1.18, 0.08), (-1.55, 2.35, -6.54)),
    )):
        _add_part(scene, objects, collisions, f"pixel-v02-wall-art-frame-{index}", extents, centre_pos, trim, "wall_detail", "procedural_completion", grid=DETAIL_VOXEL)
    _add_part(scene, objects, collisions, "pixel-v02-back-baseboard", (9.15, 0.22, 0.10), (0.0, 0.30, -6.48), trim, "wall_detail", "procedural_completion", grid=DETAIL_VOXEL)
    _add_part(scene, objects, collisions, "pixel-v02-left-baseboard", (0.10, 0.22, 11.90), (-4.70, 0.30, -0.55), trim, "wall_detail", "procedural_completion", grid=DETAIL_VOXEL)
    _add_part(scene, objects, collisions, "pixel-v02-right-baseboard", (0.10, 0.22, 11.90), (4.70, 0.30, -0.55), trim, "wall_detail", "procedural_completion", grid=DETAIL_VOXEL)

    movement = _movement(collisions)
    return _finalize_v02(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "living_room",
        "像素风 V02 客厅候选：保留 I02 的照片色彩和窗墙关系，使用更细的家具、地面、墙面和装饰层。仍是参数化风格化实体，不是单图真实几何复原。",
        ["palette_cues", "window_and_opening_vocabulary", "furniture_colour_relationships"],
        ["room_shell", "fine_floor_layers", "fine_furniture_layers", "wall_detail", "collision_envelope"],
    )


def build_pixel_corridor_v02(image_path: Path, output_dir: Path, scene_id: str = "pixel-v02-i01") -> dict[str, object]:
    """Build a distinct fine-detail corridor candidate for I01."""

    image_path = image_path.resolve()
    output_dir = output_dir.resolve()
    palette = _palette(image_path)
    roles = palette["roles"]
    wall, floor, trim = roles["wall"], roles["floor"], roles["trim"]
    wood, window, lamp, dark = roles["wood"], roles["window"], roles["lamp"], roles["dark"]
    scene = trimesh.Scene()
    objects: list[dict[str, object]] = []
    collisions: list[CollisionBox] = []

    _add_part(scene, objects, collisions, "pixel-v02-corridor-floor", (5.00, 0.25, 16.00), (0.0, 0.0, -1.50), floor, "ground", "photo_palette_lower")
    _add_part(scene, objects, collisions, "pixel-v02-corridor-left-wall", (0.25, 3.75, 16.00), (-2.50, 1.875, -1.50), wall, "wall", "photo_inferred_corridor_boundary", "走廊左侧墙体")
    _add_part(scene, objects, collisions, "pixel-v02-corridor-right-wall", (0.25, 3.75, 16.00), (2.50, 1.875, -1.50), _shade(wall, 0.92), "wall", "photo_inferred_corridor_boundary", "走廊右侧墙体")
    _add_part(scene, objects, collisions, "pixel-v02-corridor-back-wall", (5.00, 3.75, 0.25), (0.0, 1.875, -9.50), _shade(wall, 0.96), "wall", "photo_inferred_corridor_boundary", "走廊尽端墙体")
    _add_part(scene, objects, [], "pixel-v02-corridor-ceiling", (5.00, 0.25, 16.00), (0.0, 3.875, -1.50), _mix(wall, [245, 232, 208], 0.22), "ceiling", "photo_inferred_corridor_boundary")
    _add_part(scene, objects, collisions, "pixel-v02-corridor-front-left", (1.10, 3.75, 0.25), (-1.95, 1.875, 6.50), wall, "wall", "procedural_completion", "走廊前侧墙体")
    _add_part(scene, objects, collisions, "pixel-v02-corridor-front-right", (2.80, 3.75, 0.25), (1.10, 1.875, 6.50), wall, "wall", "procedural_completion", "走廊前侧墙体")
    _add_part(scene, objects, [], "pixel-v02-corridor-front-top", (1.10, 1.25, 0.25), (-0.55, 3.15, 6.50), wall, "wall_detail", "procedural_completion")

    for index, z in enumerate((3.5, 0.0, -3.5, -7.0)):
        for side, x in (("left", -2.34), ("right", 2.34)):
            _add_part(scene, objects, [], f"pixel-v02-corridor-{side}-door-{index}", (0.08, 2.55, 0.90), (x, 1.42, z), _mix(wood, dark, 0.18), "door_surface", "photo_inferred_opening", grid=DETAIL_VOXEL)
            for frame_index, (extents, centre_pos) in enumerate((
                ((0.10, 0.10, 1.10), (x, 2.75, z)),
                ((0.10, 2.75, 0.10), (x, 1.42, z - 0.58)),
                ((0.10, 2.75, 0.10), (x, 1.42, z + 0.58)),
            )):
                _add_part(scene, objects, [], f"pixel-v02-corridor-{side}-door-{index}-frame-{frame_index}", extents, centre_pos, trim, "door_detail", "procedural_completion", grid=DETAIL_VOXEL)

    _add_part(scene, objects, [], "pixel-v02-corridor-end-window", (1.75, 1.65, 0.08), (0.0, 2.50, -9.34), window, "window_surface", "photo_band_upper")
    for index, (extents, centre_pos) in enumerate((
        ((1.95, 0.08, 0.08), (0.0, 3.38, -9.38)),
        ((1.95, 0.08, 0.08), (0.0, 1.62, -9.38)),
        ((0.08, 1.85, 0.08), (-0.95, 2.50, -9.38)),
        ((0.08, 1.85, 0.08), (0.95, 2.50, -9.38)),
        ((0.08, 1.85, 0.08), (0.0, 2.50, -9.38)),
    )):
        _add_part(scene, objects, [], f"pixel-v02-corridor-window-frame-{index}", extents, centre_pos, trim, "window_detail", "procedural_completion", grid=DETAIL_VOXEL)

    # Low bench is a visible, bypassable obstacle for the indoor route.
    _add_part(scene, objects, collisions, "pixel-v02-corridor-bench", (1.35, 0.70, 0.55), (0.0, 0.48, -1.0), wood, "furniture", "photo_inferred_furniture", "走廊长凳简化体积")
    for index, z in enumerate((5.2, 3.9, 2.6, 1.3, 0.0, -1.3, -2.6, -3.9, -5.2, -6.5, -7.8, -9.0)):
        _add_part(scene, objects, collisions, f"pixel-v02-corridor-floor-seam-{index}", (4.35, 0.035, 0.035), (0.0, 0.145, z), _shade(floor, 0.78), "floor_detail", "procedural_completion", grid=DETAIL_VOXEL)
    for index, z in enumerate((4.3, 2.2, 0.1, -2.0, -4.2, -6.4, -8.5)):
        _add_part(scene, objects, [], f"pixel-v02-corridor-light-{index}", (0.35, 0.18, 0.35), (0.0, 3.65, z), lamp, "warm_light_accent", "photo_palette_centre", grid=DETAIL_VOXEL)
    _add_part(scene, objects, [], "pixel-v02-corridor-left-baseboard", (0.10, 0.22, 15.60), (-2.34, 0.30, -1.50), trim, "wall_detail", "procedural_completion", grid=DETAIL_VOXEL)
    _add_part(scene, objects, [], "pixel-v02-corridor-right-baseboard", (0.10, 0.22, 15.60), (2.34, 0.30, -1.50), trim, "wall_detail", "procedural_completion", grid=DETAIL_VOXEL)

    movement = MovementProfile(
        kind="pixel_indoor_corridor_walk_sample",
        start=[0.0, 1.625, 5.75],
        bounds={"x": [-2.10, 2.10], "y": [1.625, 1.625], "z": [-9.05, 6.10]},
        walk_speed=2.0,
        fly_speed=0.0,
        allow_flight=False,
        ground_follow=False,
        ground_y=1.625,
        collision_radius=CHARACTER_RADIUS,
        route_checkpoints=[[0.0, 1.625, 3.0], [1.55, 1.625, 3.0], [1.55, 1.625, -3.0], [0.0, 1.625, -7.8]],
        collision_boxes=collisions,
    )
    return _finalize_v02(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "corridor",
        "像素风 V02 走廊候选：I01 的明亮窗边走廊使用独立的长向空间、门框、尽端窗和可绕行长凳，不套用客厅布局；仍是参数化风格化实体，不是单图真实几何复原。",
        ["palette_cues", "corridor_direction", "window_and_opening_vocabulary"],
        ["corridor_shell", "door_frames", "window_frames", "fine_floor_layers", "bypassable_bench", "collision_envelope"],
    )


PIXEL_V03_LAYOUT_VERSION = "pixel-natural-v3-fine-detail"


def build_pixel_nature_v03(image_path: Path, output_dir: Path, scene_id: str = "pixel-v03-n01") -> dict[str, object]:
    """Build a walkable, layered pixel mountain sample for N01."""

    image_path = image_path.resolve()
    output_dir = output_dir.resolve()
    palette = _palette(image_path)
    roles = palette["roles"]
    floor, wall, trim = roles["floor"], roles["wall"], roles["trim"]
    window, plant, dark = roles["window"], roles["plant"], roles["dark"]
    scene = trimesh.Scene()
    objects: list[dict[str, object]] = []
    collisions: list[CollisionBox] = []

    # A continuous flat walk surface is kept separate from the visual stepped
    # terrain, so a single-image height guess cannot create invisible holes.
    _add_part(scene, objects, collisions, "pixel-v03-nature-ground", (24.00, 0.25, 27.00), (0.0, 0.0, -4.50), floor, "ground", "photo_palette_lower")
    _add_part(scene, objects, [], "pixel-v03-nature-path", (3.20, 0.08, 23.00), (0.0, 0.18, -4.50), _mix(floor, window, 0.10), "walk_surface", "photo_inferred_near_ground")
    for index, z in enumerate((7.0, 5.5, 4.0, 2.5, 1.0, -0.5, -2.0, -3.5, -5.0, -6.5, -8.0, -9.5, -11.0, -12.5, -14.0, -15.5, -17.0)):
        _add_part(scene, objects, [], f"pixel-v03-path-edge-left-{index}", (0.08, 0.06, 0.72), (-1.66, 0.23, z), _shade(window, 0.78), "path_detail", "procedural_completion", grid=DETAIL_VOXEL)
        _add_part(scene, objects, [], f"pixel-v03-path-edge-right-{index}", (0.08, 0.06, 0.72), (1.66, 0.23, z), _shade(window, 0.78), "path_detail", "procedural_completion", grid=DETAIL_VOXEL)

    def add_ridge(prefix: str, center_z: float, thickness: float, height_scale: float, colour: list[int], cap_colour: list[int]) -> None:
        profile = (0.52, 0.78, 0.63, 1.00, 0.72, 0.88, 0.58, 0.76, 0.45, 0.68, 0.50, 0.64, 0.42, 0.58, 0.38)
        x_start = -10.50
        for index, factor in enumerate(profile):
            x = x_start + index * 1.50
            height = max(1.0, round(5.2 * height_scale * factor / BASE_VOXEL) * BASE_VOXEL)
            block = _add_part(
                scene, objects, collisions, f"{prefix}-block-{index}", (1.58, height, thickness), (x, height * 0.5, center_z),
                _mix(colour, wall, 0.08), "distant_ridge", "photo_inferred_horizon",
            )
            cap_height = max(0.125, round(min(0.50, height * 0.16) / DETAIL_VOXEL) * DETAIL_VOXEL)
            _add_part(
                scene, objects, collisions, f"{prefix}-snow-cap-{index}", (1.38, cap_height, thickness + 0.06),
                (x, height + cap_height * 0.5, center_z - 0.03), cap_colour, "distant_ridge_detail", "photo_palette_upper", grid=DETAIL_VOXEL,
            )

    # The negative-z direction is farther away from the capture point. Three
    # separated ridges preserve depth order instead of stretching one ridge
    # through the foreground.
    add_ridge("pixel-v03-near-ridge", -10.0, 0.90, 1.00, _mix(floor, dark, 0.18), _mix(window, [245, 245, 238], 0.48))
    add_ridge("pixel-v03-mid-ridge", -14.0, 0.70, 0.82, _mix(wall, dark, 0.32), _mix(window, [245, 245, 238], 0.62))
    add_ridge("pixel-v03-far-ridge", -18.0, 0.55, 0.64, _mix(wall, dark, 0.48), _mix(window, [245, 245, 238], 0.74))

    # A few large, visible rocks give the route an obstacle to bypass. They
    # stay beside the central path and therefore do not fake a mountain route.
    rock_specs = (
        ("left", (-3.0, 0.70, -2.0), (1.25, 1.40, 1.40)),
        ("right", (3.15, 0.55, -5.2), (1.10, 1.10, 1.20)),
        ("left-far", (-3.45, 0.50, -8.0), (1.40, 1.00, 1.10)),
    )
    for label, center_pos, extents in rock_specs:
        _add_part(scene, objects, collisions, f"pixel-v03-rock-{label}", extents, center_pos, _mix(dark, floor, 0.28), "near_obstacle", "photo_inferred_rock", "自然障碍简化体积")
    for index, (x, z) in enumerate(((-5.6, -1.0), (5.2, -3.0), (-6.5, -6.0), (6.2, -9.0))):
        _add_part(scene, objects, [], f"pixel-v03-snow-patch-{index}", (1.60, 0.08, 0.95), (x, 0.20, z), _mix(window, floor, 0.15), "near_ground_detail", "photo_palette_upper", grid=DETAIL_VOXEL)
    for index, z in enumerate((5.8, 1.8, -2.2, -6.2, -10.2, -14.2)):
        _add_part(scene, objects, [], f"pixel-v03-path-marker-{index}", (0.22, 0.28, 0.22), (0.0, 0.36, z), plant, "route_detail", "procedural_completion", grid=DETAIL_VOXEL)

    movement = MovementProfile(
        kind="pixel_natural_walk_sample",
        start=[0.0, 1.625, 7.25],
        bounds={"x": [-10.80, 10.80], "y": [1.625, 1.625], "z": [-17.25, 7.75]},
        walk_speed=2.4,
        fly_speed=0.0,
        allow_flight=False,
        ground_follow=False,
        ground_y=1.625,
        collision_radius=CHARACTER_RADIUS,
        route_checkpoints=[[0.0, 1.625, 4.0], [2.4, 1.625, 1.2], [2.4, 1.625, -6.8], [0.0, 1.625, -12.5]],
        collision_boxes=collisions,
    )
    return _finalize_v02(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "snow_mountain",
        "像素风 V03 自然候选：N01 的雪色、近地与远山关系用于调色和分层；连续行走面、三层块状山脊与近景岩石为参数化估计，不等同于真实地形复原。",
        ["palette_cues", "near_ground_colour", "horizon_depth_order"],
        ["continuous_walk_surface", "near_ground_detail", "three_ridge_layers", "near_obstacle_rocks", "collision_envelope"],
        template=SceneTemplate.landscape_journey,
        engine=SceneEngine.terrain,
        route_name="pixel_style_sample_v3",
        layout_version=PIXEL_V03_LAYOUT_VERSION,
        version="pixel-v03",
        provider_version="pixel-voxel-v3",
    )


PIXEL_V05_STREET_LAYOUT_VERSION = "pixel-street-v5-fine-detail"
PIXEL_V05_BUILDING_LAYOUT_VERSION = "pixel-building-v5-fine-detail"


def build_pixel_street_v05(image_path: Path, output_dir: Path, scene_id: str = "pixel-v05-s01") -> dict[str, object]:
    """Build an external, walkable street candidate with separated proxies."""

    image_path = image_path.resolve()
    output_dir = output_dir.resolve()
    palette = _palette(image_path)
    roles = palette["roles"]
    floor, wall, wood = roles["floor"], roles["wall"], roles["wood"]
    metal, plant, window, dark = roles["metal"], roles["plant"], roles["window"], roles["dark"]
    scene = trimesh.Scene()
    objects: list[dict[str, object]] = []
    collisions: list[CollisionBox] = []

    _add_part(scene, objects, collisions, "pixel-v05-street-road", (12.00, 0.25, 24.00), (0.0, 0.0, -3.0), floor, "road", "photo_inferred_road_surface")
    _add_part(scene, objects, [], "pixel-v05-street-sidewalk-left", (2.10, 0.32, 24.00), (-7.05, 0.16, -3.0), _mix(floor, wall, 0.22), "sidewalk", "photo_inferred_sidewalk")
    _add_part(scene, objects, [], "pixel-v05-street-sidewalk-right", (2.10, 0.32, 24.00), (7.05, 0.16, -3.0), _mix(floor, wall, 0.16), "sidewalk", "photo_inferred_sidewalk")
    for index, z in enumerate((7.0, 4.5, 2.0, -0.5, -3.0, -5.5, -8.0, -10.5, -13.0)):
        _add_part(scene, objects, [], f"pixel-v05-street-lane-mark-{index}", (0.18, 0.04, 1.15), (0.0, 0.17, z), _mix(window, floor, 0.18), "road_detail", "photo_palette_upper", grid=DETAIL_VOXEL)

    # Building masses stay on the sides; the route remains an outdoor street
    # observation and does not promise entry into their unseen interiors.
    for side, x, colour in (("left", -6.0, _mix(wall, dark, 0.20)), ("right", 6.0, _mix(wall, dark, 0.30))):
        for index, z in enumerate((3.6, -2.0, -7.6)):
            _add_part(scene, objects, collisions, f"pixel-v05-street-{side}-building-{index}", (1.65, 4.40 + index * 0.45, 4.20), (x, 2.20 + index * 0.225, z), colour, "building_mass", "photo_inferred_background_building", "街道边缘建筑体块")
            for window_index, y in enumerate((1.55, 2.65, 3.75)):
                _add_part(scene, objects, [], f"pixel-v05-street-{side}-window-{index}-{window_index}", (0.08, 0.52, 0.72), (x - (0.86 if side == "left" else -0.86), y, z), window, "building_detail", "photo_inferred_window_line", grid=DETAIL_VOXEL)

    # Cars and trees are intentionally separate simplified entities so they
    # cannot become a single ribbon across road, people and background.
    for index, (x, z, colour) in enumerate(((-2.55, 1.2, wood), (2.65, -4.0, metal))):
        _add_part(scene, objects, collisions, f"pixel-v05-street-car-{index}", (1.45, 0.62, 2.60), (x, 0.48, z), colour, "vehicle_proxy", "photo_inferred_vehicle", "车辆简化体积")
        _add_part(scene, objects, [], f"pixel-v05-street-car-window-{index}", (1.10, 0.32, 0.72), (x, 0.88, z - 0.10), dark, "vehicle_detail", "procedural_completion", grid=DETAIL_VOXEL)
        for wheel_index, wheel_x in enumerate((x - 0.58, x + 0.58)):
            _add_part(scene, objects, [], f"pixel-v05-street-car-wheel-{index}-{wheel_index}", (0.16, 0.28, 0.34), (wheel_x, 0.25, z), dark, "vehicle_detail", "procedural_completion", grid=DETAIL_VOXEL)
    for index, (x, z) in enumerate(((-4.35, 4.2), (4.25, -8.2), (-4.50, -11.0))):
        _add_part(scene, objects, [], f"pixel-v05-street-tree-trunk-{index}", (0.22, 1.45, 0.22), (x, 0.82, z), wood, "tree_proxy", "photo_inferred_tree", grid=DETAIL_VOXEL)
        _add_part(scene, objects, collisions, f"pixel-v05-street-tree-crown-{index}", (1.35, 1.25, 1.35), (x, 1.95, z), plant, "tree_proxy", "photo_inferred_tree", "树木简化体积")
    for index, (x, z) in enumerate(((-1.0, -7.2), (1.1, -10.4))):
        _add_part(scene, objects, [], f"pixel-v05-street-person-{index}", (0.30, 1.45, 0.30), (x, 0.82, z), _mix(wood, dark, 0.35), "person_proxy", "photo_inferred_person", grid=DETAIL_VOXEL)
        _add_part(scene, objects, [], f"pixel-v05-street-person-head-{index}", (0.38, 0.38, 0.38), (x, 1.72, z), _mix(wood, wall, 0.20), "person_detail", "photo_inferred_person", grid=DETAIL_VOXEL)

    movement = MovementProfile(
        kind="pixel_street_walk_sample",
        start=[0.0, 1.625, 8.0],
        bounds={"x": [-5.25, 5.25], "y": [1.625, 1.625], "z": [-14.25, 8.50]},
        walk_speed=2.4,
        fly_speed=0.0,
        allow_flight=False,
        ground_follow=False,
        ground_y=1.625,
        collision_radius=CHARACTER_RADIUS,
        route_checkpoints=[[0.0, 1.625, 5.0], [3.8, 1.625, 5.0], [3.8, 1.625, -5.8], [0.0, 1.625, -11.5]],
        collision_boxes=collisions,
    )
    return _finalize_v02(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "street",
        "像素风 V05 街道候选：S01 的道路方向、建筑边缘、人车树分离和接地关系用于布局提示；主要对象是可见的简化代理，未声称完整主体重建。",
        ["palette_cues", "road_direction", "foreground_object_separation"],
        ["continuous_road", "sidewalks", "building_masses", "vehicle_proxies", "person_proxies", "tree_proxies", "collision_envelope"],
        template=SceneTemplate.street_descent,
        engine=SceneEngine.street,
        route_name="pixel_style_sample_v5",
        layout_version=PIXEL_V05_STREET_LAYOUT_VERSION,
        version="pixel-v05-street",
        provider_version="pixel-voxel-v5",
    )


def build_pixel_building_v05(image_path: Path, output_dir: Path, scene_id: str = "pixel-v05-b01") -> dict[str, object]:
    """Build a facade-only pixel candidate for external building viewing."""

    image_path = image_path.resolve()
    output_dir = output_dir.resolve()
    palette = _palette(image_path)
    roles = palette["roles"]
    floor, wall, trim = roles["floor"], roles["wall"], roles["trim"]
    window, wood, lamp, dark = roles["window"], roles["wood"], roles["lamp"], roles["dark"]
    scene = trimesh.Scene()
    objects: list[dict[str, object]] = []
    collisions: list[CollisionBox] = []

    _add_part(scene, objects, [], "pixel-v05-building-ground", (22.00, 0.25, 24.00), (0.0, 0.0, 0.0), floor, "ground", "photo_inferred_foreground")
    facade = _add_part(scene, objects, collisions, "pixel-v05-building-facade", (15.00, 10.50, 0.45), (0.0, 5.25, -5.50), _mix(wall, dark, 0.18), "facade", "photo_inferred_building_mass", "建筑立面外部边界")
    _add_part(scene, objects, [], "pixel-v05-building-entry-plinth", (3.25, 0.35, 1.15), (0.0, 0.18, -4.78), trim, "facade_detail", "photo_inferred_foreground", grid=DETAIL_VOXEL)
    for row in range(4):
        y = 1.75 + row * 2.05
        for column in range(5):
            x = -5.30 + column * 2.65
            _add_part(scene, objects, [], f"pixel-v05-building-window-{row}-{column}", (1.18, 1.20, 0.10), (x, y, -5.22), window if row < 2 else _mix(window, dark, 0.28), "window", "photo_inferred_window_grid", grid=DETAIL_VOXEL)
            _add_part(scene, objects, [], f"pixel-v05-building-window-frame-h-{row}-{column}", (1.38, 0.08, 0.14), (x, y + 0.66, -5.16), trim, "window_detail", "procedural_completion", grid=DETAIL_VOXEL)
            _add_part(scene, objects, [], f"pixel-v05-building-window-frame-v-{row}-{column}", (0.08, 1.38, 0.14), (x, y, -5.16), trim, "window_detail", "procedural_completion", grid=DETAIL_VOXEL)
    _add_part(scene, objects, [], "pixel-v05-building-entry", (2.25, 2.90, 0.12), (0.0, 1.45, -5.18), _mix(wood, dark, 0.28), "entry_detail", "photo_inferred_opening", grid=DETAIL_VOXEL)
    for index, x in enumerate((-7.15, 7.15)):
        _add_part(scene, objects, [], f"pixel-v05-building-side-pillar-{index}", (0.28, 10.90, 0.62), (x, 5.45, -5.28), trim, "facade_detail", "procedural_completion", grid=DETAIL_VOXEL)
    for index, (x, y, z) in enumerate(((-8.0, 5.5, -1.6), (8.0, 4.0, -2.8), (-6.8, 1.0, -8.8))):
        _add_part(scene, objects, [], f"pixel-v05-building-wire-{index}", (0.05, 0.05, 12.00), (x, y, z), dark, "foreground_line", "photo_inferred_foreground_line", grid=DETAIL_VOXEL)
    for index, x in enumerate((-4.5, 4.5)):
        _add_part(scene, objects, [], f"pixel-v05-building-lamp-{index}", (0.32, 0.55, 0.20), (x, 3.0, -4.95), lamp, "warm_light_accent", "photo_palette_centre", grid=DETAIL_VOXEL)

    movement = MovementProfile(
        kind="pixel_building_external_walk_sample",
        start=[0.0, 1.625, 13.0],
        bounds={"x": [-10.0, 10.0], "y": [1.625, 1.625], "z": [-13.0, 13.75]},
        walk_speed=2.0,
        fly_speed=0.0,
        allow_flight=False,
        ground_follow=False,
        ground_y=1.625,
        collision_radius=CHARACTER_RADIUS,
        route_checkpoints=[[0.0, 1.625, 8.0], [5.0, 1.625, 8.0], [5.0, 1.625, 0.0], [0.0, 1.625, 0.0]],
        collision_boxes=collisions,
    )
    return _finalize_v02(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "facade",
        "像素风 V05 建筑候选：B01 的楼体轮廓、窗格、夜色/日色关系和前景线条用于外部观察；立面有厚度，但不承诺进入未知室内。",
        ["palette_cues", "facade_outline", "window_line_and_foreground_lines"],
        ["facade_thickness", "window_grid", "entry_plinth", "foreground_lines", "external_collision_boundary"],
        template=SceneTemplate.facade_flight,
        engine=SceneEngine.facade,
        route_name="pixel_style_sample_v5",
        layout_version=PIXEL_V05_BUILDING_LAYOUT_VERSION,
        version="pixel-v05-building",
        provider_version="pixel-voxel-v5",
    )
