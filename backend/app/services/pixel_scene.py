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
FURNITURE_VOXEL = 0.03125
MICRO_VOXEL = 0.015625
CHUNK_SIZE = 16
CHARACTER_RADIUS = 0.30

# Q01 is a shared authoring contract, not a claim that every scene is already
# photo-reconstructed.  Builders may use coarser grids for large silhouettes,
# while readable asset layers opt into the two finer grids below.
PIXEL_ASSET_LIBRARY_VERSION = "pixel-assets-q01-r1"
PIXEL_ASSET_LIBRARY = {
    "upholstery": ["silhouette", "cushion", "piping", "seam", "button"],
    "wood_furniture": ["silhouette", "edge", "apron", "inlay", "handle"],
    "opening": ["wall_thickness", "frame", "panel", "mullion", "handle"],
    "vegetation": ["trunk", "branch", "leaf_cluster", "highlight"],
    "street": ["road", "curb", "lane_mark", "vehicle", "person_tree_proxy"],
    "facade": ["mass", "window", "frame", "balcony", "foreground_line"],
    "surface_rules": [
        "directional_material_breaks",
        "limited_shade_steps",
        "no_uniform_random_noise",
        "no_full_photo_projection",
    ],
}


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

    # A bounded accent is selected from the source quantization rather than
    # introducing a fixed neon colour.  It is used sparingly for readable
    # windows, signs and foliage highlights so the scene does not collapse to
    # the low-contrast grey that the first voxel samples exhibited.
    accent = max(
        colours,
        key=lambda colour: (max(colour) - min(colour), max(colour)),
        default=[96, 156, 204],
    )

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
            "accent": accent,
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
    mesh.metadata["voxel_grid"] = grid
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


def _q01_spec(detail_pass: str) -> dict[str, object]:
    return {
        "base_voxel": BASE_VOXEL,
        "detail_voxel": DETAIL_VOXEL,
        "furniture_voxel": FURNITURE_VOXEL,
        "micro_voxel": MICRO_VOXEL,
        "distant_voxel": [0.25, 1.0],
        "chunk_size": [CHUNK_SIZE, CHUNK_SIZE, CHUNK_SIZE],
        "wall_thickness_voxels": 2,
        "character_radius": CHARACTER_RADIUS,
        "channel_width": 0.85,
        "asset_library_version": PIXEL_ASSET_LIBRARY_VERSION,
        "asset_library": PIXEL_ASSET_LIBRARY,
        "mesh_policy": "sparse_voxel_parts_internal_faces_removed_per_asset_same_material_merged",
        "texture_policy": "nearest_neighbour_pixel_material_cues_no_full_photo_projection",
        "palette_limit": 32,
        "photo_key_colour_budget": 16,
        "material_shade_steps": [4, 6],
        "mipmap_policy": "enabled_for_distance_stability_nearest_for_pixel_material_sampling",
        "detail_pass": detail_pass,
    }


def _v02_spec() -> dict[str, object]:
    return _q01_spec("v02-fine-blocks-and-surface-breaks")


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
    pixel_spec: dict[str, object] | None = None,
    layout_basis: str = "developer_sample_layout_no_user_region_confirmation",
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_path = output_dir / "scene.glb"
    scene.export(scene_path, file_type="glb")
    pixel_spec = pixel_spec or _v02_spec()
    layout_payload = {
        "layout_version": layout_version,
        "route": route_name,
        "template": template.value,
        "profile": profile,
        "source_image": image_path.name,
        "source_sha256": _sha256(image_path),
        "style_route": route_name,
        "layout_authoring": layout_basis,
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


def build_pixel_corridor_v02(
    image_path: Path,
    output_dir: Path,
    scene_id: str = "pixel-v02-i01",
    layout_variant: str = "generic",
) -> dict[str, object]:
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
            # Q00 identified I01 as a bright window-side corridor: its left
            # side is not another row of doors.  Keep the generic builder for
            # old tests and samples, while the Q02 I01 variant records this
            # photo-specific layout decision explicitly.
            if layout_variant == "i01" and side == "left":
                _add_part(scene, objects, [], f"pixel-v02-corridor-{side}-window-{index}", (0.08, 2.55, 0.90), (x, 1.42, z), window, "window_surface", "photo_inferred_opening", grid=DETAIL_VOXEL)
                for frame_index, (extents, centre_pos) in enumerate((
                    ((0.10, 0.10, 1.10), (x, 2.75, z)),
                    ((0.10, 2.75, 0.10), (x, 1.42, z - 0.58)),
                    ((0.10, 2.75, 0.10), (x, 1.42, z + 0.58)),
                    ((0.08, 2.30, 0.08), (x - 0.02, 1.42, z)),
                )):
                    _add_part(scene, objects, [], f"pixel-v02-corridor-{side}-window-{index}-frame-{frame_index}", extents, centre_pos, trim, "window_detail", "photo_inferred_opening", grid=FURNITURE_VOXEL)
                continue
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


PIXEL_V06_LAYOUT_VERSION = "pixel-indoor-v6-readable-detail"


def _v06_spec() -> dict[str, object]:
    spec = _q01_spec("v06-readable-layered-details")
    spec.update({
        "detail_grid_policy": "0.0625 general detail, 0.03125 asset layers, 0.015625 micro accents",
        "back_view_policy": "front_boundary_and_opening_details_added_without_new_collision_envelopes",
    })
    return spec


def _load_v02_for_refinement(
    image_path: Path,
    output_dir: Path,
    scene_id: str,
    builder,
) -> tuple[trimesh.Scene, list[dict[str, object]], list[CollisionBox], dict[str, object], dict[str, object]]:
    """Build an existing indoor candidate, then refine only its visible layers."""

    builder(image_path, output_dir, scene_id)
    scene = trimesh.load(output_dir / "scene.glb", force="scene")
    layout = json.loads((output_dir / "layout.json").read_text(encoding="utf-8"))
    objects = list(layout["objects"])
    collisions = [CollisionBox.model_validate(item) for item in layout["movement"]["collision_boxes"]]
    palette = layout["palette"]
    roles = palette["roles"]
    return scene, objects, collisions, palette, roles


def build_pixel_living_v06(image_path: Path, output_dir: Path, scene_id: str = "pixel-v06-i02") -> dict[str, object]:
    """Refine the V02 living room with readable layers and a structured back view."""

    scene, objects, collisions, palette, roles = _load_v02_for_refinement(
        image_path, output_dir, scene_id, build_pixel_living_v02
    )
    wall, trim = roles["wall"], roles["trim"]
    sofa, wood = roles["sofa"], roles["wood"]
    metal, window, plant, lamp, accent = roles["metal"], roles["window"], roles["plant"], roles["lamp"], roles["accent"]
    dark = roles["dark"]

    # Add small, non-colliding layers to existing silhouettes.  The collision
    # envelopes remain exactly those from V02 so visual refinement cannot make
    # the walkable contract unsafe.
    for index, (x, z) in enumerate(((-3.20, -2.02), (-2.30, -2.02), (-1.60, -2.02), (-0.70, -2.02))):
        _add_part(scene, objects, [], f"pixel-v06-sofa-cushion-piping-{index}", (0.62, 0.06, 0.06), (x, 0.98, z), trim, "furniture_detail", "procedural_completion", grid=MICRO_VOXEL)
    for index, x in enumerate((-3.18, -2.35, -1.52, -0.69)):
        _add_part(scene, objects, [], f"pixel-v06-sofa-back-seam-{index}", (0.06, 0.72, 0.06), (x, 1.34, -2.82), _shade(sofa, 0.72), "furniture_detail", "procedural_completion", grid=FURNITURE_VOXEL)

    for index, x in enumerate((0.72, 1.25, 1.78)):
        _add_part(scene, objects, [], f"pixel-v06-table-inlay-{index}", (0.06, 0.06, 0.82), (x, 0.99, 0.55), metal, "furniture_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    _add_part(scene, objects, [], "pixel-v06-table-front-apron", (1.70, 0.16, 0.06), (1.25, 0.70, 1.11), _shade(wood, 0.72), "furniture_detail", "procedural_completion", grid=FURNITURE_VOXEL)

    # The reverse-facing wall now has a readable panel and a low wainscot, so
    # turning around does not leave a featureless plane or falsely imply a
    # reconstructed doorway.
    _add_part(scene, objects, [], "pixel-v06-front-wall-wainscot", (6.40, 0.42, 0.06), (1.45, 0.64, 5.52), _shade(trim, 0.88), "wall_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    _add_part(scene, objects, [], "pixel-v06-front-wall-panel", (1.55, 1.22, 0.06), (1.15, 2.25, 5.52), _mix(wall, sofa, 0.22), "wall_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    for index, (centre, extents) in enumerate((
        ((1.15, 2.90, 5.48), (1.72, 0.08, 0.08)),
        ((1.15, 1.60, 5.48), (1.72, 0.08, 0.08)),
        ((0.32, 2.25, 5.48), (0.08, 1.38, 0.08)),
        ((1.98, 2.25, 5.48), (0.08, 1.38, 0.08)),
    )):
        _add_part(scene, objects, [], f"pixel-v06-front-wall-panel-frame-{index}", extents, centre, trim, "wall_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    _add_part(scene, objects, [], "pixel-v06-front-wall-light-left", (0.18, 0.34, 0.08), (-0.70, 2.20, 5.50), window, "wall_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    _add_part(scene, objects, [], "pixel-v06-front-wall-light-right", (0.18, 0.34, 0.08), (3.30, 2.20, 5.50), window, "wall_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    # The first refinement put this panel above the close back-view frustum:
    # from the sample start the reverse wall is less than one unit away, so
    # eye-level details are required to remain readable after a 180 degree
    # turn.  Keep the high composition, but add a second, lower marker that
    # is intentionally inside that frustum.
    _add_part(scene, objects, [], "pixel-v06-front-wall-eye-panel", (0.82, 0.56, 0.06), (0.25, 1.68, 5.48), _mix(sofa, trim, 0.38), "wall_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    for index, (centre, extents) in enumerate((
        ((0.25, 1.99, 5.44), (0.98, 0.08, 0.08)),
        ((0.25, 1.37, 5.44), (0.98, 0.08, 0.08)),
        ((-0.24, 1.68, 5.44), (0.08, 0.70, 0.08)),
        ((0.74, 1.68, 5.44), (0.08, 0.70, 0.08)),
    )):
        _add_part(scene, objects, [], f"pixel-v06-front-wall-eye-panel-frame-{index}", extents, centre, trim, "wall_detail", "procedural_completion", grid=FURNITURE_VOXEL)

    _add_part(scene, objects, [], "pixel-v06-screen-bezel", (1.50, 1.12, 0.06), (3.25, 1.45, -4.44), trim, "display_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    for index, y in enumerate((0.43, 0.66)):
        _add_part(scene, objects, [], f"pixel-v06-console-drawer-{index}", (0.58, 0.06, 0.26), (3.25, y, -4.31), metal, "furniture_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    for index, (x, y, z) in enumerate(((-4.00, 2.18, 0.45), (-3.10, 2.12, 0.45), (-3.72, 2.46, 0.45))):
        _add_part(scene, objects, [], f"pixel-v06-plant-leaf-{index}", (0.34, 0.18, 0.34), (x, y, z), _mix(plant, wall, 0.10), "decor_detail", "procedural_completion", grid=FURNITURE_VOXEL)

    # Q02 asset pass: turn the large silhouettes into authored, readable
    # pieces.  These layers are deliberately sparse and named by the asset
    # part they explain; they are not random voxel noise and do not add new
    # collision envelopes.
    for index, (x, z) in enumerate(((-2.75, -2.02), (-1.15, -2.02))):
        _add_part(scene, objects, [], f"pixel-q02-sofa-cushion-shadow-{index}", (1.22, 0.055, 0.06), (x, 0.96, z - 0.43), _shade(sofa, 0.72), "upholstery_detail", "photo_inferred_furniture", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-q02-sofa-cushion-highlight-{index}", (0.86, 0.045, 0.045), (x, 0.99, z + 0.28), _mix(sofa, wall, 0.25), "upholstery_detail", "photo_inferred_furniture", grid=MICRO_VOXEL)
    for index, (x, z) in enumerate(((0.62, 0.55), (1.88, 0.55))):
        _add_part(scene, objects, [], f"pixel-q02-table-leg-back-{index}", (0.14, 0.72, 0.14), (x, 0.40, z - 0.74), _shade(wood, 0.68), "wood_furniture_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    _add_part(scene, objects, [], "pixel-q02-table-lower-shelf", (1.30, 0.08, 0.60), (1.25, 0.48, 0.55), _shade(wood, 0.82), "wood_furniture_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    for index, x in enumerate((2.62, 3.25, 3.88)):
        _add_part(scene, objects, [], f"pixel-q02-console-slat-{index}", (0.06, 0.42, 0.05), (x, 0.55, -4.30), _shade(wood, 0.72), "wood_furniture_detail", "procedural_completion", grid=MICRO_VOXEL)
    for index, (x, y) in enumerate(((2.88, 1.22), (3.20, 1.42), (3.52, 1.22), (3.20, 1.62))):
        _add_part(scene, objects, [], f"pixel-q02-screen-pixel-{index}", (0.16, 0.10, 0.025), (x, y, -4.37), _mix(window, metal, 0.18), "display_detail", "photo_inferred_object", grid=MICRO_VOXEL)
    for index, x in enumerate((0.42, 3.05)):
        _add_part(scene, objects, [], f"pixel-q02-window-curtain-{index}", (0.32, 2.45, 0.08), (x, 2.45, -6.42), _mix(trim, wall, 0.30), "opening_detail", "photo_inferred_opening", grid=FURNITURE_VOXEL)
        for pleat in range(3):
            _add_part(scene, objects, [], f"pixel-q02-window-curtain-{index}-pleat-{pleat}", (0.045, 2.18, 0.045), (x + (pleat - 1) * 0.08, 2.45, -6.36), _shade(trim, 0.86), "opening_detail", "procedural_completion", grid=MICRO_VOXEL)
    for index, (x, width, height) in enumerate(((-3.25, 1.18, 1.30), (1.00, 1.05, 0.92), (3.65, 0.78, 1.18))):
        _add_part(scene, objects, [], f"pixel-q03-living-wall-art-{index}", (width, height, 0.045), (x, 1.75 + index * 0.18, 5.48), _mix(accent, wall, 0.32), "wall_art", "photo_inferred_wall_object", grid=FURNITURE_VOXEL)
        for frame_index, (extents, centre) in enumerate((
            ((width + 0.14, 0.045, 0.045), (x, 1.75 + index * 0.18 + height * 0.5 + 0.06, 5.44)),
            ((width + 0.14, 0.045, 0.045), (x, 1.75 + index * 0.18 - height * 0.5 - 0.06, 5.44)),
            ((0.045, height + 0.14, 0.045), (x - width * 0.5 - 0.06, 1.75 + index * 0.18, 5.44)),
            ((0.045, height + 0.14, 0.045), (x + width * 0.5 + 0.06, 1.75 + index * 0.18, 5.44)),
        )):
            _add_part(scene, objects, [], f"pixel-q03-living-wall-art-{index}-frame-{frame_index}", extents, centre, trim, "wall_art_detail", "procedural_completion", grid=MICRO_VOXEL)
        for tile in range(3):
            _add_part(scene, objects, [], f"pixel-q03-living-wall-art-{index}-tile-{tile}", (0.14, 0.12, 0.025), (x - width * 0.25 + tile * width * 0.25, 1.75 + index * 0.18, 5.41), _mix(accent, lamp, tile * 0.12), "wall_art_detail", "procedural_completion", grid=MICRO_VOXEL)
    # A shallow skyline behind the back window preserves the I02 window/city
    # cue while remaining a separate, non-colliding background layer.
    for index, (x, width, height) in enumerate(((-0.10, 0.42, 0.62), (0.42, 0.34, 0.98), (0.90, 0.52, 0.48), (1.52, 0.38, 1.22), (2.05, 0.62, 0.72), (2.72, 0.34, 1.05))):
        _add_part(scene, objects, [], f"pixel-q03-living-window-city-{index}", (width, height, 0.035), (x, 1.42 + height * 0.5, -6.39), _mix(accent if index % 2 else dark, window, 0.25), "window_background", "photo_palette_upper", grid=FURNITURE_VOXEL)

    # Q03 visual pass: I02's white L-sofa and window are the two strongest
    # recognition anchors.  Turn each cushion into a small, authored pixel
    # asset and add a sparse skyline window pattern.  These are visible surface
    # layers only; the V02 collision envelopes remain unchanged.
    sofa_light = _mix(sofa, [236, 236, 228], 0.48)
    sofa_shadow = _shade(sofa, 0.62)
    for index, x in enumerate((-2.75, -1.15)):
        _add_part(scene, objects, [], f"pixel-q03-living-sofa-cushion-face-{index}", (1.22, 0.045, 0.78), (x, 0.98, -2.02), sofa_light, "upholstery_surface", "photo_inferred_furniture", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-living-sofa-cushion-shadow-{index}", (1.06, 0.035, 0.08), (x, 0.94, -2.40), sofa_shadow, "upholstery_detail", "photo_inferred_furniture", grid=MICRO_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-living-sofa-cushion-top-{index}", (0.82, 0.035, 0.06), (x - 0.12, 1.02, -1.72), _mix(sofa_light, window, 0.18), "upholstery_detail", "photo_inferred_furniture", grid=MICRO_VOXEL)
    # The photographed coffee table reads as a separate object because of its
    # top contents, edge band and legs, rather than one uninterrupted slab.
    _add_part(scene, objects, [], "pixel-q03-living-table-runner", (1.18, 0.035, 0.12), (1.25, 1.00, 0.55), _mix(wood, sofa_light, 0.22), "wood_furniture_detail", "photo_inferred_furniture", grid=MICRO_VOXEL)
    _add_part(scene, objects, [], "pixel-q03-living-table-book", (0.42, 0.05, 0.28), (0.88, 1.06, 0.48), accent, "tabletop_object", "procedural_completion", grid=FURNITURE_VOXEL)
    _add_part(scene, objects, [], "pixel-q03-living-table-mug", (0.14, 0.13, 0.14), (1.70, 1.10, 0.72), lamp, "tabletop_object", "procedural_completion", grid=MICRO_VOXEL)
    for building_index, (x, width, height) in enumerate(((-0.10, 0.42, 0.62), (0.42, 0.34, 0.98), (0.90, 0.52, 0.48), (1.52, 0.38, 1.22), (2.05, 0.62, 0.72), (2.72, 0.34, 1.05))):
        for window_index, y in enumerate((1.58 + height * 0.28, 1.58 + height * 0.64)):
            _add_part(scene, objects, [], f"pixel-q03-living-window-city-{building_index}-light-{window_index}", (min(0.16, width * 0.42), 0.07, 0.025), (x - width * 0.15, y, -6.36), _mix(window, accent if window_index == 1 else lamp, 0.20), "window_background_detail", "photo_palette_upper", grid=MICRO_VOXEL)
    # I02's tall plant is not a single green cube: a stem, branching leaf
    # clusters and two green shades give it a readable silhouette at a glance.
    leaf_colours = (plant, _mix(plant, window, 0.18), _shade(plant, 0.76))
    for index, (x, y, z, width, depth) in enumerate((
        (-4.02, 1.92, 0.45, 0.48, 0.30), (-3.70, 2.18, 0.45, 0.42, 0.26),
        (-3.30, 2.02, 0.45, 0.50, 0.30), (-3.10, 2.34, 0.45, 0.36, 0.24),
        (-3.82, 2.52, 0.45, 0.38, 0.24), (-3.48, 2.72, 0.45, 0.34, 0.22),
        (-3.08, 2.58, 0.45, 0.42, 0.24), (-3.95, 2.88, 0.45, 0.30, 0.20),
    )):
        _add_part(scene, objects, [], f"pixel-q03-living-plant-leaf-{index}", (width, 0.20, depth), (x, y, z), leaf_colours[index % len(leaf_colours)], "vegetation_detail", "photo_inferred_vegetation", grid=FURNITURE_VOXEL)

    movement = _movement(collisions)
    return _finalize_v02(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "living_room",
        "像素风 V06 客厅精修候选：在 V02 的客厅轮廓、窗墙关系和碰撞基础上增加可读家具层、前侧墙面构图和小尺度材质分层；仍是参数化风格化实体，不是单图真实几何复原。",
        ["palette_cues", "window_and_opening_vocabulary", "furniture_colour_relationships"],
        ["room_shell", "fine_floor_layers", "fine_furniture_layers", "structured_back_view", "collision_envelope"],
        route_name="pixel_style_sample_v6",
        layout_version=PIXEL_V06_LAYOUT_VERSION,
        version="pixel-v06",
        provider_version="pixel-voxel-v6",
        pixel_spec=_v06_spec(),
        layout_basis="q00_visual_index:i02",
    )


def build_pixel_corridor_v06(
    image_path: Path,
    output_dir: Path,
    scene_id: str = "pixel-v06-i01",
    layout_variant: str = "generic",
) -> dict[str, object]:
    """Refine the V02 corridor with small door, portal and floor accents."""

    scene, objects, collisions, palette, roles = _load_v02_for_refinement(
        image_path,
        output_dir,
        scene_id,
        lambda source, target, identifier: build_pixel_corridor_v02(
            source, target, identifier, layout_variant=layout_variant
        ),
    )
    wall, trim = roles["wall"], roles["trim"]
    wood, window, lamp, dark, metal = roles["wood"], roles["window"], roles["lamp"], roles["dark"], roles["metal"]
    accent = roles["accent"]

    for index, (side, x) in enumerate((("left", -2.25), ("right", 2.25))):
        for door_index, z in enumerate((3.5, 0.0, -3.5, -7.0)):
            if layout_variant == "i01" and side == "left":
                _add_part(scene, objects, [], f"pixel-v06-left-window-sill-{door_index}", (0.82, 0.06, 0.12), (x - 0.02, 0.20, z), trim, "window_detail", "photo_inferred_opening", grid=FURNITURE_VOXEL)
                _add_part(scene, objects, [], f"pixel-v06-left-window-mullion-{door_index}", (0.06, 1.90, 0.06), (x - 0.02, 1.42, z), _shade(trim, 0.86), "window_detail", "photo_inferred_opening", grid=MICRO_VOXEL)
                continue
            _add_part(scene, objects, [], f"pixel-v06-{side}-door-{door_index}-handle", (0.10, 0.10, 0.10), (x, 1.45, z), metal, "door_detail", "procedural_completion", grid=MICRO_VOXEL)
            _add_part(scene, objects, [], f"pixel-v06-{side}-door-{door_index}-panel", (0.05, 1.60, 0.48), (x, 1.42, z), _mix(wood, wall, 0.18), "door_detail", "procedural_completion", grid=FURNITURE_VOXEL)

    # Add a visible front portal/threshold and small ceiling fixtures.  These
    # are render-only details; the existing six collision boxes are retained.
    _add_part(scene, objects, [], "pixel-v06-corridor-front-threshold", (1.35, 0.08, 0.18), (0.0, 0.20, 6.26), trim, "opening_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    _add_part(scene, objects, [], "pixel-v06-corridor-front-sign", (0.52, 0.30, 0.06), (0.65, 2.45, 6.34), window, "opening_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    _add_part(scene, objects, [], "pixel-v06-corridor-front-center-sign", (0.46, 0.28, 0.06), (0.18, 1.68, 6.34), lamp, "opening_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    _add_part(scene, objects, [], "pixel-v06-corridor-front-eye-panel", (0.88, 0.54, 0.06), (0.0, 1.68, 6.34), _mix(window, trim, 0.35), "opening_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    for index, (centre, extents) in enumerate((
        ((0.0, 1.99, 6.30), (1.04, 0.08, 0.08)),
        ((0.0, 1.37, 6.30), (1.04, 0.08, 0.08)),
        ((-0.52, 1.68, 6.30), (0.08, 0.70, 0.08)),
        ((0.52, 1.68, 6.30), (0.08, 0.70, 0.08)),
    )):
        _add_part(scene, objects, [], f"pixel-v06-corridor-front-eye-panel-frame-{index}", extents, centre, trim, "opening_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    for index, z in enumerate((4.3, 2.2, 0.1, -2.0, -4.2, -6.4, -8.5)):
        _add_part(scene, objects, [], f"pixel-v06-corridor-light-cross-{index}", (0.58, 0.06, 0.06), (0.0, 3.54, z), lamp, "warm_light_accent", "photo_palette_centre", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-v06-corridor-light-cap-{index}", (0.10, 0.10, 0.10), (0.0, 3.78, z), dark, "warm_light_accent", "procedural_completion", grid=MICRO_VOXEL)
    for index, z in enumerate((4.7, 1.8, -1.1, -4.0, -6.9)):
        _add_part(scene, objects, [], f"pixel-v06-corridor-wall-panel-left-{index}", (0.06, 0.72, 0.42), (-2.28, 1.95, z), _mix(wall, trim, 0.12), "wall_detail", "procedural_completion", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-v06-corridor-wall-panel-right-{index}", (0.06, 0.72, 0.42), (2.28, 1.95, z), _mix(wall, trim, 0.18), "wall_detail", "procedural_completion", grid=FURNITURE_VOXEL)

    # Q02 corridor surface pass: window-side colour blocks and door inset
    # lines make the I01 layout read as a bright window/door corridor rather
    # than a symmetrical row of featureless boxes.
    for index, z in enumerate((3.5, 0.0, -3.5, -7.0)):
        if layout_variant == "i01":
            for band, y in enumerate((1.05, 1.55, 2.05)):
                _add_part(scene, objects, [], f"pixel-q02-i01-window-light-{index}-{band}", (0.035, 0.18, 0.30), (-2.27, y, z), _mix(window, lamp, 0.08 + band * 0.04), "window_detail", "photo_palette_upper", grid=MICRO_VOXEL)
        for band, y in enumerate((0.85, 1.45, 2.05)):
            _add_part(scene, objects, [], f"pixel-q02-corridor-door-inset-{index}-{band}", (0.035, 0.18, 0.28), (2.27, y, z), _mix(wood, trim, 0.22), "door_detail", "procedural_completion", grid=MICRO_VOXEL)
    for index, x in enumerate((-1.22, 0.82)):
        _add_part(scene, objects, [], f"pixel-q03-corridor-end-art-{index}", (0.74, 0.88, 0.04), (x, 2.20, 6.31), _mix(accent, window, 0.32), "wall_art", "procedural_completion", grid=FURNITURE_VOXEL)
        for frame_index, (extents, centre) in enumerate((
            ((0.88, 0.04, 0.04), (x, 2.68, 6.27)),
            ((0.88, 0.04, 0.04), (x, 1.72, 6.27)),
            ((0.04, 1.00, 0.04), (x - 0.48, 2.20, 6.27)),
            ((0.04, 1.00, 0.04), (x + 0.48, 2.20, 6.27)),
        )):
            _add_part(scene, objects, [], f"pixel-q03-corridor-end-art-{index}-frame-{frame_index}", extents, centre, trim, "wall_art_detail", "procedural_completion", grid=MICRO_VOXEL)

    # Q03 visual pass: I01 is a bright window-side corridor.  Add a small
    # pane grid and a shallow city silhouette behind each opening so the
    # window side reads as an opening with depth, not a flat blue rectangle.
    for index, z in enumerate((3.5, 0.0, -3.5, -7.0)):
        for pane_index, y in enumerate((1.10, 1.62, 2.14)):
            pane_colour = _mix(window, accent if pane_index == 1 else lamp, 0.12 + pane_index * 0.08)
            _add_part(scene, objects, [], f"pixel-q03-i01-window-pane-{index}-{pane_index}", (0.035, 0.38, 0.42), (-2.22, y, z), pane_colour, "window_surface_detail", "photo_inferred_opening", grid=FURNITURE_VOXEL)
        for city_index, (x_offset, y, height, width) in enumerate(((-0.20, 0.86, 0.54, 0.28), (0.12, 1.00, 0.78, 0.24), (0.34, 0.80, 0.40, 0.20))):
            _add_part(scene, objects, [], f"pixel-q03-i01-window-city-{index}-{city_index}", (0.025, height, width), (-2.41, y + height * 0.5, z + x_offset), _mix(dark, accent, 0.20), "window_background_detail", "photo_palette_upper", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-i01-window-sill-{index}", (0.14, 0.08, 0.98), (-2.18, 0.22, z), trim, "window_detail", "procedural_completion", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-i01-window-top-light-{index}", (0.04, 0.10, 0.82), (-2.18, 2.76, z), _mix(window, lamp, 0.16), "window_detail", "photo_palette_upper", grid=MICRO_VOXEL)
        for band, y in enumerate((0.94, 1.48, 2.02)):
            _add_part(scene, objects, [], f"pixel-q03-corridor-door-panel-{index}-{band}", (0.035, 0.07, 0.56), (2.20, y, z), _mix(wood, trim, 0.18 + band * 0.06), "door_detail", "procedural_completion", grid=FURNITURE_VOXEL)

    # The end opening receives the same three-layer treatment at a smaller
    # scale: distant building blocks, lit windows and a sill/edge highlight.
    for index, (x, width, height) in enumerate(((-0.66, 0.26, 0.46), (-0.30, 0.34, 0.72), (0.10, 0.28, 0.54), (0.46, 0.38, 0.86))):
        _add_part(scene, objects, [], f"pixel-q03-corridor-end-city-{index}", (width, height, 0.025), (x, 1.52 + height * 0.5, -9.25), _mix(dark, window, 0.28), "window_background_detail", "photo_palette_upper", grid=FURNITURE_VOXEL)
        for light_index, y in enumerate((1.68 + height * 0.25, 1.68 + height * 0.58)):
            _add_part(scene, objects, [], f"pixel-q03-corridor-end-city-{index}-light-{light_index}", (min(0.12, width * 0.42), 0.07, 0.03), (x, y, -9.21), _mix(window, lamp, 0.16), "window_background_detail", "photo_palette_upper", grid=MICRO_VOXEL)

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
        "像素风 V06 走廊精修候选：保留 V02 的长向空间和可绕行长凳，增加门把手、门板、入口阈值、灯具层和墙面小尺度分割；仍是参数化风格化实体，不是单图真实几何复原。",
        ["palette_cues", "corridor_direction", "window_and_opening_vocabulary"],
        ["corridor_shell", "door_frames", "readable_door_layers", "window_frames", "fine_floor_layers", "bypassable_bench", "collision_envelope"],
        route_name="pixel_style_sample_v6",
        layout_version=PIXEL_V06_LAYOUT_VERSION,
        version="pixel-v06",
        provider_version="pixel-voxel-v6",
        pixel_spec=_v06_spec(),
        layout_basis=f"q00_visual_index:{layout_variant}",
    )


PIXEL_V03_LAYOUT_VERSION = "pixel-natural-v3-fine-detail"


def build_pixel_nature_v03(image_path: Path, output_dir: Path, scene_id: str = "pixel-v03-n01") -> dict[str, object]:
    """Build a walkable, layered pixel mountain sample for N01."""

    image_path = image_path.resolve()
    output_dir = output_dir.resolve()
    palette = _palette(image_path)
    roles = palette["roles"]
    floor, wall, trim = roles["floor"], roles["wall"], roles["trim"]
    window, plant, dark, accent = roles["window"], roles["plant"], roles["dark"], roles["accent"]
    scene = trimesh.Scene()
    objects: list[dict[str, object]] = []
    collisions: list[CollisionBox] = []

    # A continuous flat walk surface is kept separate from the visual stepped
    # terrain, so a single-image height guess cannot create invisible holes.
    _add_part(scene, objects, collisions, "pixel-v03-nature-ground", (24.00, 0.25, 27.00), (0.0, 0.0, -4.50), floor, "ground", "photo_palette_lower")
    _add_part(scene, objects, [], "pixel-v03-nature-path", (3.20, 0.08, 23.00), (0.0, 0.18, -4.50), _mix(floor, window, 0.10), "walk_surface", "photo_inferred_near_ground")
    _add_part(scene, objects, [], "pixel-q02-nature-sky-layer", (80.00, 40.00, 0.18), (0.0, 12.0, -24.0), _mix(window, wall, 0.18), "far_background", "photo_inferred_sky_region")
    for index, z in enumerate((7.0, 5.5, 4.0, 2.5, 1.0, -0.5, -2.0, -3.5, -5.0, -6.5, -8.0, -9.5, -11.0, -12.5, -14.0, -15.5, -17.0)):
        _add_part(scene, objects, [], f"pixel-v03-path-edge-left-{index}", (0.08, 0.06, 0.72), (-1.66, 0.23, z), _shade(window, 0.78), "path_detail", "procedural_completion", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-v03-path-edge-right-{index}", (0.08, 0.06, 0.72), (1.66, 0.23, z), _shade(window, 0.78), "path_detail", "procedural_completion", grid=FURNITURE_VOXEL)

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
            cap_height = max(0.125, round(min(0.50, height * 0.16) / FURNITURE_VOXEL) * FURNITURE_VOXEL)
            _add_part(
                scene, objects, collisions, f"{prefix}-snow-cap-{index}", (1.38, cap_height, thickness + 0.06),
                (x, height + cap_height * 0.5, center_z - 0.03), cap_colour, "distant_ridge_detail", "photo_palette_upper", grid=FURNITURE_VOXEL,
            )
            # Break the large ridge face into a few intentional snow/shadow
            # facets.  The facets are render-only and stay on the same front
            # plane, so they add readable mountain planes without turning a
            # distant ridge into a stack of collision walls.
            front_z = center_z + thickness * 0.5 + 0.02
            for facet_index, (offset, level, width_factor, height_factor) in enumerate((
                (-0.34, 0.42, 0.38, 0.18), (0.16, 0.64, 0.30, 0.14), (0.34, 0.28, 0.22, 0.12),
            )):
                facet_width = max(FURNITURE_VOXEL, round(1.58 * width_factor / FURNITURE_VOXEL) * FURNITURE_VOXEL)
                facet_height = max(FURNITURE_VOXEL, round(max(0.12, height * height_factor) / FURNITURE_VOXEL) * FURNITURE_VOXEL)
                facet_y = max(facet_height * 0.5 + 0.06, min(height - facet_height * 0.5 - 0.06, height * level))
                _add_part(
                    scene, objects, [], f"{prefix}-facet-{index}-{facet_index}",
                    (facet_width, facet_height, 0.035), (x + offset, facet_y, front_z),
                    _mix(colour, cap_colour, 0.30 + facet_index * 0.12), "distant_ridge_detail", "photo_palette_upper", grid=FURNITURE_VOXEL,
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
        _add_part(scene, objects, [], f"pixel-v03-snow-patch-{index}", (1.60, 0.08, 0.95), (x, 0.20, z), _mix(window, floor, 0.15), "near_ground_detail", "photo_palette_upper", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-q02-snow-patch-highlight-{index}", (0.72, 0.045, 0.12), (x - 0.20, 0.27, z - 0.18), _mix(window, [245, 245, 238], 0.48), "near_ground_detail", "photo_palette_upper", grid=MICRO_VOXEL)
    for index, (x, z) in enumerate(((-4.1, -6.8), (-2.8, -7.7), (2.9, -8.2), (4.2, -6.5))):
        _add_part(scene, objects, [], f"pixel-q03-nature-snow-rock-{index}", (0.72, 0.24, 0.58), (x, 0.30, z), _mix(accent, window, 0.56), "near_obstacle_detail", "photo_inferred_rock", grid=FURNITURE_VOXEL)
    for index, z in enumerate((5.8, 1.8, -2.2, -6.2, -10.2, -14.2)):
        _add_part(scene, objects, [], f"pixel-v03-path-marker-{index}", (0.22, 0.28, 0.22), (0.0, 0.36, z), plant, "route_detail", "procedural_completion", grid=MICRO_VOXEL)

    # N01 has a visible foreground fence.  Preserve it as a shallow, detailed
    # observation-layer asset, without adding collision to the central route.
    fence = _mix(dark, window, 0.24)
    for rail_index, y in enumerate((0.92, 1.42, 1.84)):
        _add_part(scene, objects, [], f"pixel-q03-nature-fence-rail-{rail_index}", (9.60, 0.09, 0.10), (0.0, y, 6.02), fence, "foreground_fence", "photo_inferred_foreground_fence", grid=FURNITURE_VOXEL)
    for index, x in enumerate((-4.50, -3.00, -1.50, 0.0, 1.50, 3.00, 4.50)):
        _add_part(scene, objects, [], f"pixel-q03-nature-fence-post-{index}", (0.10, 1.30, 0.12), (x, 1.22, 6.02), _shade(fence, 0.82), "foreground_fence", "photo_inferred_foreground_fence", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-nature-fence-post-cap-{index}", (0.16, 0.08, 0.16), (x, 1.90, 6.02), _mix(fence, window, 0.18), "foreground_fence_detail", "photo_inferred_foreground_fence", grid=MICRO_VOXEL)
    # Low snow/stone clumps at the route edges give the near ground a scale
    # cue while leaving the documented path width untouched.
    for index, (x, z, colour) in enumerate(((-2.45, 3.20, _mix(window, floor, 0.18)), (2.55, 2.20, _mix(window, floor, 0.28)), (-2.85, -1.20, _mix(accent, floor, 0.42)), (2.80, -3.40, _mix(window, floor, 0.12)))):
        _add_part(scene, objects, [], f"pixel-q03-nature-near-clump-{index}", (0.76, 0.22, 0.52), (x, 0.28, z), colour, "near_ground_detail", "photo_inferred_near_ground", grid=FURNITURE_VOXEL)

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
        layout_basis="q00_visual_index:n01",
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
    metal, plant, window, lamp, dark, accent = roles["metal"], roles["plant"], roles["window"], roles["lamp"], roles["dark"], roles["accent"]
    scene = trimesh.Scene()
    objects: list[dict[str, object]] = []
    collisions: list[CollisionBox] = []

    _add_part(scene, objects, collisions, "pixel-v05-street-road", (12.00, 0.25, 24.00), (0.0, 0.0, -3.0), floor, "road", "photo_inferred_road_surface")
    _add_part(scene, objects, [], "pixel-v05-street-sidewalk-left", (2.10, 0.32, 24.00), (-7.05, 0.16, -3.0), _mix(floor, wall, 0.22), "sidewalk", "photo_inferred_sidewalk")
    _add_part(scene, objects, [], "pixel-v05-street-sidewalk-right", (2.10, 0.32, 24.00), (7.05, 0.16, -3.0), _mix(floor, wall, 0.16), "sidewalk", "photo_inferred_sidewalk")
    for index, z in enumerate((7.0, 4.5, 2.0, -0.5, -3.0, -5.5, -8.0, -10.5, -13.0)):
        _add_part(scene, objects, [], f"pixel-v05-street-lane-mark-{index}", (0.18, 0.04, 1.15), (0.0, 0.17, z), _mix(window, floor, 0.18), "road_detail", "photo_palette_upper", grid=FURNITURE_VOXEL)

    # Building masses stay on the sides; the route remains an outdoor street
    # observation and does not promise entry into their unseen interiors.
    for side, x, colour in (("left", -6.0, _mix(wall, dark, 0.20)), ("right", 6.0, _mix(wall, dark, 0.30))):
        for index, z in enumerate((3.6, -2.0, -7.6)):
            _add_part(scene, objects, collisions, f"pixel-v05-street-{side}-building-{index}", (1.65, 4.40 + index * 0.45, 4.20), (x, 2.20 + index * 0.225, z), colour, "building_mass", "photo_inferred_background_building", "街道边缘建筑体块")
            for window_index, y in enumerate((1.55, 2.65, 3.75)):
                _add_part(scene, objects, [], f"pixel-v05-street-{side}-window-{index}-{window_index}", (0.08, 0.52, 0.72), (x - (0.86 if side == "left" else -0.86), y, z), window, "building_detail", "photo_inferred_window_line", grid=FURNITURE_VOXEL)

    # Cars and trees are intentionally separate simplified entities so they
    # cannot become a single ribbon across road, people and background.
    for index, (x, z, colour) in enumerate(((-2.55, 1.2, wood), (2.65, -4.0, metal))):
        _add_part(scene, objects, collisions, f"pixel-v05-street-car-{index}", (1.45, 0.62, 2.60), (x, 0.48, z), colour, "vehicle_proxy", "photo_inferred_vehicle", "车辆简化体积")
        _add_part(scene, objects, [], f"pixel-v05-street-car-window-{index}", (1.10, 0.32, 0.72), (x, 0.88, z - 0.10), dark, "vehicle_detail", "procedural_completion", grid=FURNITURE_VOXEL)
        for wheel_index, wheel_x in enumerate((x - 0.58, x + 0.58)):
            _add_part(scene, objects, [], f"pixel-v05-street-car-wheel-{index}-{wheel_index}", (0.16, 0.28, 0.34), (wheel_x, 0.25, z), dark, "vehicle_detail", "procedural_completion", grid=MICRO_VOXEL)
    for index, (x, z) in enumerate(((-4.35, 4.2), (4.25, -8.2), (-4.50, -11.0))):
        _add_part(scene, objects, [], f"pixel-v05-street-tree-trunk-{index}", (0.22, 1.45, 0.22), (x, 0.82, z), wood, "tree_proxy", "photo_inferred_tree", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, collisions, f"pixel-v05-street-tree-crown-{index}", (1.35, 1.25, 1.35), (x, 1.95, z), plant, "tree_proxy", "photo_inferred_tree", "树木简化体积")
        for leaf_index, (dx, dy, dz) in enumerate(((-0.48, 0.10, 0.0), (0.0, 0.32, 0.0), (0.48, 0.12, 0.0), (0.0, 0.12, 0.42))):
            _add_part(scene, objects, [], f"pixel-q02-street-tree-leaf-{index}-{leaf_index}", (0.48, 0.30, 0.48), (x + dx, 1.95 + dy, z + dz), _mix(plant, wall, 0.08 + leaf_index * 0.03), "tree_detail", "photo_inferred_tree", grid=FURNITURE_VOXEL)
    for index, (x, z) in enumerate(((-1.0, -7.2), (1.1, -10.4))):
        _add_part(scene, objects, [], f"pixel-v05-street-person-{index}", (0.30, 1.45, 0.30), (x, 0.82, z), _mix(wood, dark, 0.35), "person_proxy", "photo_inferred_person", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-v05-street-person-head-{index}", (0.38, 0.38, 0.38), (x, 1.72, z), _mix(wood, wall, 0.20), "person_detail", "photo_inferred_person", grid=MICRO_VOXEL)

    # S01 is a top-down street image, so its strongest readable cues are the
    # road paint and foreground separation.  Keep those cues as shallow,
    # non-colliding surface layers instead of pretending the capture view is
    # already a first-person reconstruction.
    for index, z in enumerate((6.2, 5.0, 3.8)):
        _add_part(scene, objects, [], f"pixel-q02-street-crosswalk-{index}", (4.80, 0.045, 0.34), (0.0, 0.17, z), _mix(window, floor, 0.06), "road_marking", "photo_inferred_road_marking", grid=FURNITURE_VOXEL)
    _add_part(scene, objects, [], "pixel-q02-street-bike-lane", (1.25, 0.05, 8.20), (-3.20, 0.17, -2.2), _mix(wood, lamp, 0.32), "road_marking", "photo_inferred_road_marking", grid=FURNITURE_VOXEL)

    # Q03 visual pass: S01's strongest cues are the red bike lane, repeated
    # crosswalk bars and the separation of small foreground objects.  Add
    # shallow lane arrows, curbs, bicycle silhouettes and pane lights; these
    # remain non-colliding surface/details and do not change the route.
    curb = _mix(roles["trim"], floor, 0.22)
    for side, x in (("left", -5.86), ("right", 5.86)):
        _add_part(scene, objects, [], f"pixel-q03-street-curb-{side}", (0.18, 0.18, 23.40), (x, 0.25, -3.0), curb, "curb_detail", "photo_inferred_sidewalk", grid=FURNITURE_VOXEL)
        for index, z in enumerate((6.8, 2.8, -1.2, -5.2, -9.2)):
            _add_part(scene, objects, [], f"pixel-q03-street-curb-mark-{side}-{index}", (0.22, 0.05, 0.42), (x, 0.38, z), _mix(curb, window, 0.24), "curb_detail", "procedural_completion", grid=MICRO_VOXEL)
    lane_colour = _mix(accent, lamp, 0.24)
    for index, z in enumerate((-0.2, -1.2, -2.2, -3.2, -4.2)):
        _add_part(scene, objects, [], f"pixel-q03-street-bike-lane-dash-{index}", (0.32, 0.055, 0.62), (-3.20, 0.22, z), lane_colour, "road_marking_detail", "photo_inferred_road_marking", grid=FURNITURE_VOXEL)
    _add_part(scene, objects, [], "pixel-q03-street-bike-lane-arrow-stem", (0.10, 0.06, 0.78), (-3.20, 0.23, -5.30), lane_colour, "road_marking_detail", "photo_inferred_road_marking", grid=MICRO_VOXEL)
    _add_part(scene, objects, [], "pixel-q03-street-bike-lane-arrow-left", (0.42, 0.06, 0.10), (-3.38, 0.23, -5.02), lane_colour, "road_marking_detail", "photo_inferred_road_marking", grid=MICRO_VOXEL)
    _add_part(scene, objects, [], "pixel-q03-street-bike-lane-arrow-right", (0.42, 0.06, 0.10), (-3.02, 0.23, -5.02), lane_colour, "road_marking_detail", "photo_inferred_road_marking", grid=MICRO_VOXEL)
    for index, (x, z) in enumerate(((-1.0, -7.2), (1.1, -10.4))):
        bicycle = _mix(accent, lamp, 0.18)
        _add_part(scene, objects, [], f"pixel-q03-street-bike-wheel-front-{index}", (0.08, 0.42, 0.42), (x + 0.20, 0.42, z), bicycle, "bicycle_detail", "photo_inferred_bicycle", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-street-bike-wheel-back-{index}", (0.08, 0.42, 0.42), (x - 0.20, 0.42, z), bicycle, "bicycle_detail", "photo_inferred_bicycle", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-street-bike-frame-{index}", (0.42, 0.08, 0.08), (x, 0.72, z), bicycle, "bicycle_detail", "photo_inferred_bicycle", grid=MICRO_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-street-bike-handle-{index}", (0.08, 0.18, 0.08), (x + 0.23, 0.88, z), bicycle, "bicycle_detail", "photo_inferred_bicycle", grid=MICRO_VOXEL)
    for building_index, (x, z) in enumerate(((-6.82, 3.6), (-6.82, -2.0), (-6.82, -7.6), (6.82, 3.6), (6.82, -2.0), (6.82, -7.6))):
        for window_index, y in enumerate((1.48, 2.48, 3.48)):
            _add_part(scene, objects, [], f"pixel-q03-street-building-light-{building_index}-{window_index}", (0.035, 0.14, 0.28), (x, y, z), _mix(window, accent, 0.20 + window_index * 0.08), "building_detail", "photo_palette_upper", grid=MICRO_VOXEL)

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
        layout_basis="q00_visual_index:s01",
    )


def build_pixel_building_v05(image_path: Path, output_dir: Path, scene_id: str = "pixel-v05-b01") -> dict[str, object]:
    """Build a facade-only pixel candidate for external building viewing."""

    image_path = image_path.resolve()
    output_dir = output_dir.resolve()
    palette = _palette(image_path)
    roles = palette["roles"]
    floor, wall, trim = roles["floor"], roles["wall"], roles["trim"]
    window, wood, lamp, plant, accent, dark, metal = roles["window"], roles["wood"], roles["lamp"], roles["plant"], roles["accent"], roles["dark"], roles["metal"]
    scene = trimesh.Scene()
    objects: list[dict[str, object]] = []
    collisions: list[CollisionBox] = []

    _add_part(scene, objects, [], "pixel-v05-building-ground", (22.00, 0.25, 24.00), (0.0, 0.0, 0.0), floor, "ground", "photo_inferred_foreground")
    facade = _add_part(scene, objects, collisions, "pixel-v05-building-facade", (15.00, 10.50, 0.45), (0.0, 5.25, -5.50), _mix(wall, dark, 0.18), "facade", "photo_inferred_building_mass", "建筑立面外部边界")
    _add_part(scene, objects, [], "pixel-v05-building-entry-plinth", (3.25, 0.35, 1.15), (0.0, 0.18, -4.78), trim, "facade_detail", "photo_inferred_foreground", grid=FURNITURE_VOXEL)
    for row in range(4):
        y = 1.75 + row * 2.05
        for column in range(5):
            x = -5.30 + column * 2.65
            lit_window = _mix(window, accent, 0.34 if (row + column) % 3 == 0 else 0.08)
            _add_part(scene, objects, [], f"pixel-v05-building-window-{row}-{column}", (1.18, 1.20, 0.10), (x, y, -5.22), lit_window if row < 2 else _mix(lit_window, dark, 0.28), "window", "photo_inferred_window_grid", grid=FURNITURE_VOXEL)
            _add_part(scene, objects, [], f"pixel-v05-building-window-frame-h-{row}-{column}", (1.38, 0.08, 0.14), (x, y + 0.66, -5.16), trim, "window_detail", "procedural_completion", grid=FURNITURE_VOXEL)
            _add_part(scene, objects, [], f"pixel-v05-building-window-frame-v-{row}-{column}", (0.08, 1.38, 0.14), (x, y, -5.16), trim, "window_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    _add_part(scene, objects, [], "pixel-v05-building-entry", (2.25, 2.90, 0.12), (0.0, 1.45, -5.18), _mix(wood, dark, 0.28), "entry_detail", "photo_inferred_opening", grid=FURNITURE_VOXEL)
    for index, x in enumerate((-7.15, 7.15)):
        _add_part(scene, objects, [], f"pixel-v05-building-side-pillar-{index}", (0.28, 10.90, 0.62), (x, 5.45, -5.28), trim, "facade_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    for index, (x, y, z) in enumerate(((-8.0, 5.5, -1.6), (8.0, 4.0, -2.8), (-6.8, 1.0, -8.8))):
        _add_part(scene, objects, [], f"pixel-v05-building-wire-{index}", (0.05, 0.05, 12.00), (x, y, z), dark, "foreground_line", "photo_inferred_foreground_line", grid=MICRO_VOXEL)
    for index, x in enumerate((-4.5, 4.5)):
        _add_part(scene, objects, [], f"pixel-v05-building-lamp-{index}", (0.32, 0.55, 0.20), (x, 3.0, -4.95), lamp, "warm_light_accent", "photo_palette_centre", grid=FURNITURE_VOXEL)

    # B01's visible facade is more than a regular window grid: balconies,
    # a foreground pole and nearby leaf clusters provide the depth layers
    # visible in the source photo while remaining external-only geometry.
    for index, (x, y) in enumerate(((-2.65, 3.78), (2.65, 5.83), (-2.65, 7.88), (2.65, 9.93))):
        _add_part(scene, objects, [], f"pixel-q02-building-balcony-{index}", (2.10, 0.12, 0.42), (x, y, -5.00), _mix(trim, dark, 0.18), "balcony_detail", "photo_inferred_facade_layer", grid=FURNITURE_VOXEL)
        for rail in range(4):
            _add_part(scene, objects, [], f"pixel-q02-building-balcony-rail-{index}-{rail}", (0.05, 0.42, 0.05), (x - 0.72 + rail * 0.48, y + 0.22, -4.76), trim, "balcony_detail", "procedural_completion", grid=MICRO_VOXEL)
    _add_part(scene, objects, [], "pixel-q02-building-foreground-pole", (0.22, 11.00, 0.22), (-4.55, 5.50, -1.40), dark, "foreground_pole", "photo_inferred_foreground", grid=FURNITURE_VOXEL)
    for index, (x, y, z) in enumerate(((-4.20, 7.50, -1.25), (-4.00, 5.35, -1.15), (4.20, 8.20, -1.45), (4.00, 4.10, -1.35))):
        _add_part(scene, objects, [], f"pixel-q02-building-wire-node-{index}", (0.12, 0.12, 0.12), (x, y, z), lamp, "foreground_line_detail", "photo_inferred_foreground_line", grid=MICRO_VOXEL)
    for index, (x, y, z) in enumerate(((-7.20, 1.55, -1.0), (7.15, 2.25, -1.0), (7.35, 1.95, -0.45), (-7.45, 1.80, -0.40))):
        _add_part(scene, objects, [], f"pixel-q02-building-leaf-cluster-{index}", (0.70, 0.48, 0.52), (x, y, z), plant, "foreground_vegetation", "photo_inferred_foreground", grid=FURNITURE_VOXEL)

    # Q03 visual pass: preserve the night-facade reading with regular masonry
    # courses, window interiors and a few service units.  The thin accents
    # stay on the facade plane and do not alter the external collision box.
    course_colour = _mix(trim, wall, 0.18)
    for index, y in enumerate((0.86, 2.78, 4.82, 6.86, 8.90)):
        _add_part(scene, objects, [], f"pixel-q03-building-facade-course-{index}", (13.60, 0.055, 0.06), (0.0, y, -5.08), course_colour, "facade_surface_detail", "photo_inferred_building_mass", grid=FURNITURE_VOXEL)
    for row in range(4):
        y = 1.75 + row * 2.05
        for column in range(5):
            x = -5.30 + column * 2.65
            pane_colour = _mix(window, accent if (row + column) % 2 else lamp, 0.18 + (row % 2) * 0.08)
            _add_part(scene, objects, [], f"pixel-q03-building-window-pane-{row}-{column}", (0.78, 0.72, 0.035), (x, y, -5.10), pane_colour, "window_surface_detail", "photo_palette_upper", grid=FURNITURE_VOXEL)
            _add_part(scene, objects, [], f"pixel-q03-building-window-pane-cross-{row}-{column}", (0.06, 0.70, 0.025), (x, y, -5.07), trim, "window_detail", "procedural_completion", grid=MICRO_VOXEL)
            if (row + column) % 3 == 0:
                _add_part(scene, objects, [], f"pixel-q03-building-window-service-unit-{row}-{column}", (0.46, 0.18, 0.18), (x, y - 0.72, -4.98), _mix(metal, dark, 0.20), "facade_service_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    for index, x in enumerate((-5.30, 0.0, 5.30)):
        _add_part(scene, objects, [], f"pixel-q03-building-roof-light-{index}", (0.16, 0.22, 0.12), (x, 10.58, -4.98), lamp, "warm_light_accent", "photo_palette_centre", grid=MICRO_VOXEL)

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
        layout_basis="q00_visual_index:b01",
    )


# Q03 r3 keeps the existing walkable layouts and adds a second authored detail
# pass.  The pass is deliberately isolated from the default generators: it
# increases readable information on the visible surfaces without adding
# collision envelopes or changing the user's established movement contract.
PIXEL_V07_LAYOUT_VERSION = "pixel-v07-authored-detail-pass-2"


def _load_candidate_for_detail(image_path: Path, output_dir: Path, scene_id: str, builder) -> tuple[
    trimesh.Scene, list[dict[str, object]], list[CollisionBox], dict[str, object], MovementProfile
]:
    builder(image_path, output_dir, scene_id)
    scene = trimesh.load(output_dir / "scene.glb", force="scene")
    layout = json.loads((output_dir / "layout.json").read_text(encoding="utf-8"))
    objects = list(layout["objects"])
    collisions = [CollisionBox.model_validate(item) for item in layout["movement"]["collision_boxes"]]
    return scene, objects, collisions, layout["palette"], MovementProfile.model_validate(layout["movement"])


def _v07_spec() -> dict[str, object]:
    spec = _v06_spec()
    spec.update({
        "detail_pass": "v07-authored-pixel-asset-pass-2",
        "detail_grid_policy": "0.125 structural voxel, 0.03125 authored asset layers, 0.015625 seam and highlight accents",
        "surface_detail_policy": "directional_panels_checker_accents_object_parts_no_uniform_noise",
    })
    return spec


def _finalize_v07(
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
    *,
    template: SceneTemplate,
    engine: SceneEngine,
    layout_basis: str,
) -> dict[str, object]:
    return _finalize_v02(
        image_path,
        output_dir,
        scene_id,
        scene,
        objects,
        collisions,
        movement,
        palette,
        profile,
        note,
        photo_supported_regions,
        generated_regions,
        template=template,
        engine=engine,
        route_name="pixel_style_sample_v7",
        layout_version=PIXEL_V07_LAYOUT_VERSION,
        version="pixel-v07",
        provider_version="pixel-voxel-v7",
        pixel_spec=_v07_spec(),
        layout_basis=layout_basis,
    )


def build_pixel_living_v07(image_path: Path, output_dir: Path, scene_id: str = "pixel-v07-i02") -> dict[str, object]:
    """Add authored pixel furniture and surface layers to the I02 candidate."""

    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_living_v06
    )
    roles = palette["roles"]
    wall, floor, trim = roles["wall"], roles["floor"], roles["trim"]
    sofa, wood, metal = roles["sofa"], roles["wood"], roles["metal"]
    window, plant, lamp, dark, accent = roles["window"], roles["plant"], roles["lamp"], roles["dark"], roles["accent"]

    # A restrained checker/rug pattern makes the visible floor read as a
    # material rather than a single plane.  These are surface-only parts.
    rug_a = _mix(sofa, floor, 0.20)
    rug_b = _mix(rug_a, trim, 0.16)
    for row in range(4):
        for column in range(7):
            _add_part(
                scene, objects, [], f"pixel-q03-r3-living-rug-pixel-{row}-{column}",
                (0.54, 0.035, 0.42),
                (-1.62 + column * 0.54, 0.29, -0.82 + row * 0.42),
                rug_a if (row + column) % 2 else rug_b,
                "floor_material_detail", "procedural_completion", grid=MICRO_VOXEL,
            )

    # The sofa gets a readable back, arm blocks, seat gaps and feet; the
    # original collision envelope stays unchanged.
    for index, x in enumerate((-3.62, -0.55)):
        _add_part(scene, objects, [], f"pixel-q03-r3-living-sofa-arm-{index}", (0.22, 0.76, 0.88), (x, 1.08, -2.16), _mix(sofa, trim, 0.16), "upholstery_structure", "photo_inferred_furniture", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-r3-living-sofa-back-cushion-{index}", (1.24, 0.64, 0.16), (x + 0.70, 1.42, -2.70), _mix(sofa, wall, 0.22), "upholstery_structure", "photo_inferred_furniture", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-r3-living-sofa-back-shadow-{index}", (1.02, 0.06, 0.045), (x + 0.70, 1.17, -2.79), _shade(sofa, 0.70), "upholstery_detail", "procedural_completion", grid=MICRO_VOXEL)
        for foot_x in (x + 0.16, x + 1.18):
            _add_part(scene, objects, [], f"pixel-q03-r3-living-sofa-foot-{index}-{foot_x:.2f}", (0.12, 0.18, 0.12), (foot_x, 0.34, -2.16), dark, "furniture_detail", "procedural_completion", grid=MICRO_VOXEL)
    for index, x in enumerate((-2.75, -1.15)):
        _add_part(scene, objects, [], f"pixel-q03-r3-living-sofa-seat-gap-{index}", (0.045, 0.20, 0.82), (x, 1.02, -2.02), trim, "upholstery_detail", "procedural_completion", grid=MICRO_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-r3-living-sofa-seat-highlight-{index}", (0.62, 0.045, 0.045), (x - 0.08, 1.15, -1.72), _mix(sofa, window, 0.25), "upholstery_detail", "photo_palette_centre", grid=MICRO_VOXEL)

    # Break the table into top, apron, legs and small objects so its silhouette
    # remains recognizable when the camera moves around its side.
    for index, (x, z) in enumerate(((0.56, 0.12), (1.94, 0.12), (0.56, 0.98), (1.94, 0.98))):
        _add_part(scene, objects, [], f"pixel-q03-r3-living-table-leg-{index}", (0.14, 0.68, 0.14), (x, 0.56, z), _shade(wood, 0.70), "wood_furniture_structure", "photo_inferred_furniture", grid=FURNITURE_VOXEL)
    _add_part(scene, objects, [], "pixel-q03-r3-living-table-top-highlight", (1.22, 0.035, 0.06), (1.25, 1.10, 0.98), _mix(wood, window, 0.18), "wood_furniture_detail", "procedural_completion", grid=MICRO_VOXEL)
    for index, (x, z, colour) in enumerate(((0.64, 0.44, accent), (1.05, 0.70, lamp), (1.48, 0.32, metal), (1.82, 0.78, window))):
        _add_part(scene, objects, [], f"pixel-q03-r3-living-table-object-{index}", (0.16, 0.07, 0.16), (x, 1.15, z), colour, "tabletop_object_detail", "procedural_completion", grid=MICRO_VOXEL)

    # Layer the plant with a pot rim, stems and directional leaf clusters.
    _add_part(scene, objects, [], "pixel-q03-r3-living-plant-pot-rim", (0.86, 0.12, 0.72), (-3.62, 0.54, 0.45), _mix(wood, trim, 0.22), "vegetation_structure", "photo_inferred_vegetation", grid=FURNITURE_VOXEL)
    for index, (x, y, z, width, depth, colour) in enumerate((
        (-3.98, 1.36, 0.45, 0.10, 0.10, _shade(plant, 0.72)), (-3.64, 1.64, 0.45, 0.10, 0.10, plant),
        (-3.34, 1.48, 0.45, 0.10, 0.10, _mix(plant, window, 0.16)), (-3.82, 2.08, 0.45, 0.38, 0.22, plant),
        (-3.45, 2.28, 0.45, 0.32, 0.20, _mix(plant, window, 0.18)), (-3.10, 2.06, 0.45, 0.42, 0.24, _shade(plant, 0.78)),
        (-3.76, 2.60, 0.45, 0.28, 0.18, _mix(plant, window, 0.24)), (-3.24, 2.52, 0.45, 0.34, 0.20, plant),
    )):
        _add_part(scene, objects, [], f"pixel-q03-r3-living-plant-part-{index}", (width, 0.16 if y < 1.8 else 0.22, depth), (x, y, z), colour, "vegetation_detail", "photo_inferred_vegetation", grid=FURNITURE_VOXEL)

    # The window receives a clear mullion and a few differently sized skyline
    # blocks, which read better than repeating the same light rectangle.
    for index, x in enumerate((-0.90, 0.05)):
        _add_part(scene, objects, [], f"pixel-q03-r3-living-window-mullion-{index}", (0.06, 2.36, 0.06), (x, 2.05, -6.45), trim, "opening_structure", "photo_inferred_opening", grid=FURNITURE_VOXEL)
    for index, (x, width, height, colour) in enumerate(((-0.54, 0.30, 0.54, dark), (0.10, 0.22, 0.86, accent), (0.56, 0.42, 0.48, window), (1.18, 0.30, 1.10, dark), (1.74, 0.52, 0.66, _mix(dark, window, 0.25)))):
        _add_part(scene, objects, [], f"pixel-q03-r3-living-window-building-{index}", (width, height, 0.04), (x, 1.46 + height * 0.5, -6.38), colour, "window_background_detail", "photo_palette_upper", grid=FURNITURE_VOXEL)
        for light_index, y in enumerate((1.54 + height * 0.28, 1.54 + height * 0.62)):
            _add_part(scene, objects, [], f"pixel-q03-r3-living-window-building-{index}-light-{light_index}", (min(0.12, width * 0.45), 0.055, 0.025), (x - width * 0.15, y, -6.34), _mix(window, lamp, 0.22), "window_background_detail", "photo_palette_upper", grid=MICRO_VOXEL)

    return _finalize_v07(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "living_room",
        "像素风 V07 客厅细化候选：在 Q03 r2 的窗墙、沙发、桌面和植物识别锚点上增加分件、材质方向和表面像素层；仍是参数化风格化实体。",
        ["palette_cues", "window_and_opening_vocabulary", "furniture_colour_relationships"],
        ["room_shell", "fine_floor_layers", "authored_sofa_parts", "authored_table_parts", "vegetation_layers", "collision_envelope"],
        template=SceneTemplate.indoor_walk, engine=SceneEngine.space, layout_basis="q03_visual_index:i02:r3",
    )


def build_pixel_corridor_v07(image_path: Path, output_dir: Path, scene_id: str = "pixel-v07-i01") -> dict[str, object]:
    """Add tile, opening, door and ceiling-fixture detail to the I01 corridor."""

    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id,
        lambda source, target, identifier: build_pixel_corridor_v06(source, target, identifier, layout_variant="i01"),
    )
    roles = palette["roles"]
    wall, floor, trim = roles["wall"], roles["floor"], roles["trim"]
    wood, window, lamp, dark, metal, accent = roles["wood"], roles["window"], roles["lamp"], roles["dark"], roles["metal"], roles["accent"]

    # Long corridors need repeated scale cues. Alternating tile bands and
    # narrow side inlays make the path readable without random noise.
    for row, z in enumerate((5.55, 4.45, 3.35, 2.25, 1.15, 0.05, -1.05, -2.15, -3.25, -4.35, -5.45, -6.55, -7.65, -8.55)):
        for column, x in enumerate((-1.68, -0.84, 0.0, 0.84, 1.68)):
            _add_part(scene, objects, [], f"pixel-q03-r3-corridor-floor-tile-{row}-{column}", (0.78, 0.035, 0.96), (x, 0.19, z), _mix(floor, trim, 0.06 if (row + column) % 2 else 0.12), "floor_material_detail", "procedural_completion", grid=MICRO_VOXEL)
    for index, z in enumerate((5.30, 4.10, 2.90, 1.70, 0.50, -0.70, -1.90, -3.10, -4.30, -5.50, -6.70, -7.90)):
        _add_part(scene, objects, [], f"pixel-q03-r3-corridor-left-wall-panel-{index}", (0.045, 0.64, 0.72), (-2.33, 1.66, z), _mix(wall, trim, 0.16), "wall_material_detail", "procedural_completion", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-r3-corridor-right-wall-panel-{index}", (0.045, 0.64, 0.72), (2.33, 1.66, z), _mix(wall, trim, 0.20), "wall_material_detail", "procedural_completion", grid=FURNITURE_VOXEL)

    # Give each opening a distinct inset and handle highlight.
    for index, z in enumerate((3.5, 0.0, -3.5, -7.0)):
        for band, y in enumerate((0.92, 1.42, 1.92, 2.42)):
            _add_part(scene, objects, [], f"pixel-q03-r3-corridor-door-inset-{index}-{band}", (0.035, 0.22, 0.32), (2.28, y, z), _mix(wood, trim, 0.18 + band * 0.03), "door_material_detail", "procedural_completion", grid=MICRO_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-r3-corridor-door-handle-{index}", (0.12, 0.08, 0.08), (2.22, 1.44, z + 0.22), metal, "door_detail", "procedural_completion", grid=MICRO_VOXEL)
        for band, y in enumerate((1.00, 1.56, 2.12)):
            _add_part(scene, objects, [], f"pixel-q03-r3-corridor-window-light-{index}-{band}", (0.035, 0.12, 0.34), (-2.28, y, z), _mix(window, lamp, 0.10 + band * 0.05), "window_material_detail", "photo_palette_upper", grid=MICRO_VOXEL)

    # Add authored pixels to the end artwork and make the bench readable from
    # its side, while retaining the existing obstacle collider.
    for index, (x, y, colour) in enumerate(((-1.22, 2.05, accent), (-1.02, 2.32, window), (0.82, 2.00, lamp), (1.02, 2.34, accent))):
        _add_part(scene, objects, [], f"pixel-q03-r3-corridor-end-art-pixel-{index}", (0.16, 0.14, 0.03), (x, y, 6.27), colour, "wall_art_detail", "procedural_completion", grid=MICRO_VOXEL)
    _add_part(scene, objects, [], "pixel-q03-r3-corridor-bench-back", (1.36, 0.48, 0.10), (0.0, 0.98, -1.22), _mix(wood, wall, 0.18), "furniture_structure", "photo_inferred_furniture", grid=FURNITURE_VOXEL)
    for index, x in enumerate((-0.56, 0.56)):
        _add_part(scene, objects, [], f"pixel-q03-r3-corridor-bench-leg-{index}", (0.12, 0.54, 0.12), (x, 0.44, -1.0), dark, "furniture_structure", "procedural_completion", grid=FURNITURE_VOXEL)
    for index, z in enumerate((4.3, 2.2, 0.1, -2.0, -4.2, -6.4, -8.5)):
        _add_part(scene, objects, [], f"pixel-q03-r3-corridor-ceiling-fixture-{index}", (0.52, 0.045, 0.16), (0.0, 3.67, z), _mix(lamp, window, 0.18), "ceiling_fixture_detail", "photo_palette_centre", grid=MICRO_VOXEL)

    return _finalize_v07(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "corridor",
        "像素风 V07 走廊细化候选：在 I01 的窗侧方向、门列和尽端关系上增加重复地砖、开口内衬、门扇分件和可读长凳；仍是参数化风格化实体。",
        ["palette_cues", "corridor_direction", "window_and_opening_vocabulary"],
        ["corridor_shell", "door_frames", "window_frames", "authored_floor_tiles", "bench_parts", "collision_envelope"],
        template=SceneTemplate.indoor_walk, engine=SceneEngine.space, layout_basis="q03_visual_index:i01:r3",
    )


def build_pixel_nature_v04(image_path: Path, output_dir: Path, scene_id: str = "pixel-v07-n01") -> dict[str, object]:
    """Add structured snow, rock and vegetation layers to the N01 candidate."""

    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_nature_v03
    )
    roles = palette["roles"]
    floor, wall, window, plant, dark, accent = roles["floor"], roles["wall"], roles["window"], roles["plant"], roles["dark"], roles["accent"]

    # Close ground uses organized bands rather than full-surface noise.
    for row, z in enumerate((5.0, 3.8, 2.6, 1.4, 0.2, -1.0, -2.2, -3.4, -4.6, -5.8, -7.0)):
        for column, x in enumerate((-1.20, -0.40, 0.40, 1.20)):
            _add_part(scene, objects, [], f"pixel-q03-r3-nature-path-pixel-{row}-{column}", (0.70, 0.035, 0.86), (x, 0.24, z), _mix(floor, window, 0.08 + ((row + column) % 3) * 0.04), "snow_path_detail", "photo_palette_lower", grid=MICRO_VOXEL)

    # Add stepped facet bands in front of the three existing ridges; each band
    # is shallow and non-colliding, so the mountain remains a background layer.
    for ridge_index, (z, y, span, colour) in enumerate(((-9.48, 2.20, 9.2, _mix(window, floor, 0.24)), (-13.48, 1.64, 8.4, _mix(window, wall, 0.22)), (-17.48, 1.18, 7.4, _mix(window, dark, 0.18)))):
        for band in range(4):
            x = -span * 0.5 + band * span / 3.0
            width = span / 3.8
            height = 0.14 + band * 0.045
            _add_part(scene, objects, [], f"pixel-q03-r3-nature-ridge-facet-{ridge_index}-{band}", (width, height, 0.04), (x, y + band * 0.22, z), _mix(colour, accent, 0.10 + band * 0.04), "distant_ridge_detail", "photo_palette_upper", grid=FURNITURE_VOXEL)

    # Give rocks and edge vegetation a blocky but legible silhouette.
    for index, (x, y, z, colour) in enumerate(((-3.0, 1.36, -2.0, _mix(dark, floor, 0.18)), (-3.0, 1.10, -2.0, _mix(dark, accent, 0.14)), (3.15, 1.05, -5.2, _mix(dark, window, 0.24)), (3.15, 0.82, -5.2, _mix(dark, accent, 0.18)))):
        _add_part(scene, objects, [], f"pixel-q03-r3-nature-rock-facet-{index}", (0.58, 0.20, 0.72), (x, y, z), colour, "rock_surface_detail", "photo_inferred_rock", grid=FURNITURE_VOXEL)
    for index, (x, z) in enumerate(((-5.0, 1.5), (-4.4, 0.8), (4.8, -1.8), (5.2, -2.5), (-5.6, -5.0), (5.5, -7.2))):
        _add_part(scene, objects, [], f"pixel-q03-r3-nature-pine-trunk-{index}", (0.16, 1.10, 0.16), (x, 0.66, z), _mix(dark, floor, 0.26), "vegetation_structure", "photo_inferred_vegetation", grid=FURNITURE_VOXEL)
        for layer, (width, height, y) in enumerate(((0.82, 0.34, 1.10), (0.62, 0.38, 1.42), (0.42, 0.42, 1.78))):
            _add_part(scene, objects, [], f"pixel-q03-r3-nature-pine-crown-{index}-{layer}", (width, height, 0.44), (x, y, z), _mix(plant, window, 0.08 + layer * 0.08), "vegetation_detail", "photo_inferred_vegetation", grid=FURNITURE_VOXEL)

    # The fence gets a restrained highlight on alternating posts so it reads
    # as a constructed foreground object rather than one dark rail.
    for index, x in enumerate((-4.50, -3.00, -1.50, 0.0, 1.50, 3.00, 4.50)):
        _add_part(scene, objects, [], f"pixel-q03-r3-nature-fence-post-highlight-{index}", (0.035, 0.84, 0.035), (x - 0.04, 1.34, 5.94), _mix(window, dark, 0.25), "foreground_fence_detail", "photo_inferred_foreground_fence", grid=MICRO_VOXEL)

    return _finalize_v07(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "snow_mountain",
        "像素风 V07 自然候选：在 N01 的近地路径、三层远山、岩石和前景栏杆基础上增加组织化雪面、山脊色面和分层植被；不把远山接成长坡。",
        ["palette_cues", "near_ground_colour", "horizon_depth_order"],
        ["continuous_walk_surface", "structured_snow_path", "ridge_facets", "rock_facets", "layered_vegetation", "collision_envelope"],
        template=SceneTemplate.landscape_journey, engine=SceneEngine.terrain, layout_basis="q03_visual_index:n01:r3",
    )


def build_pixel_street_v06(image_path: Path, output_dir: Path, scene_id: str = "pixel-v07-s01") -> dict[str, object]:
    """Add structured road, traffic and object-separation details to S01."""

    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_street_v05
    )
    roles = palette["roles"]
    floor, wall, wood = roles["floor"], roles["wall"], roles["wood"]
    metal, plant, window, lamp, dark, accent, trim = roles["metal"], roles["plant"], roles["window"], roles["lamp"], roles["dark"], roles["accent"], roles["trim"]

    for row, z in enumerate((7.0, 5.8, 4.6, 3.4, 2.2, 1.0, -0.2, -1.4, -2.6, -3.8, -5.0, -6.2, -7.4, -8.6, -9.8, -11.0)):
        for column, x in enumerate((-4.80, -3.60, -2.40, -1.20, 0.0, 1.20, 2.40, 3.60, 4.80)):
            _add_part(scene, objects, [], f"pixel-q03-r3-street-road-pixel-{row}-{column}", (1.02, 0.025, 0.98), (x, 0.15, z), _mix(floor, wall, 0.05 if (row + column) % 2 else 0.10), "road_surface_detail", "procedural_completion", grid=MICRO_VOXEL)
    curb = _mix(trim, floor, 0.18)
    for side, x in (("left", -5.84), ("right", 5.84)):
        for index, z in enumerate((7.0, 5.2, 3.4, 1.6, -0.2, -2.0, -3.8, -5.6, -7.4, -9.2, -11.0, -12.8)):
            _add_part(scene, objects, [], f"pixel-q03-r3-street-curb-pixel-{side}-{index}", (0.16, 0.10, 0.62), (x, 0.30, z), curb if index % 2 else _mix(curb, window, 0.18), "curb_detail", "photo_inferred_sidewalk", grid=FURNITURE_VOXEL)

    # Cars get front/rear identity and headlights rather than only a coloured
    # cuboid; their colliders remain the existing vehicle proxies.
    for index, (x, z, colour) in enumerate(((-2.55, 1.2, wood), (2.65, -4.0, metal))):
        _add_part(scene, objects, [], f"pixel-q03-r3-street-car-grille-{index}", (0.72, 0.16, 0.045), (x, 0.56, z - 1.28), dark, "vehicle_detail", "procedural_completion", grid=MICRO_VOXEL)
        for light_index, light_x in enumerate((x - 0.42, x + 0.42)):
            _add_part(scene, objects, [], f"pixel-q03-r3-street-car-headlight-{index}-{light_index}", (0.18, 0.12, 0.04), (light_x, 0.62, z - 1.32), _mix(window, lamp, 0.18), "vehicle_detail", "photo_palette_upper", grid=MICRO_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-r3-street-car-roof-highlight-{index}", (0.84, 0.035, 0.10), (x, 1.14, z), _mix(colour, window, 0.18), "vehicle_detail", "procedural_completion", grid=MICRO_VOXEL)

    # A traffic light and two signs provide upright scale cues on the side
    # walk, with no collision because they are outside the documented route.
    for index, (x, z) in enumerate(((-5.0, 4.8), (5.0, -6.0))):
        _add_part(scene, objects, [], f"pixel-q03-r3-street-light-pole-{index}", (0.10, 2.60, 0.10), (x, 1.30, z), dark, "street_fixture", "procedural_completion", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-r3-street-light-head-{index}", (0.28, 0.22, 0.22), (x, 2.62, z), lamp, "street_fixture", "photo_palette_centre", grid=FURNITURE_VOXEL)
        for light_index, y in enumerate((2.52, 2.62, 2.72)):
            _add_part(scene, objects, [], f"pixel-q03-r3-street-light-pixel-{index}-{light_index}", (0.08, 0.045, 0.08), (x - 0.12, y, z), _mix(window, lamp, 0.24), "street_fixture_detail", "procedural_completion", grid=MICRO_VOXEL)

    return _finalize_v07(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "street",
        "像素风 V07 街道候选：在 S01 的道路方向、人车树分离和路缘结构上增加有组织路面像素、车辆身份细节和街道设施；仍不声称完整主体重建。",
        ["palette_cues", "road_direction", "foreground_object_separation"],
        ["continuous_road", "structured_road_surface", "vehicle_detail", "street_fixtures", "collision_envelope"],
        template=SceneTemplate.street_descent, engine=SceneEngine.street, layout_basis="q03_visual_index:s01:r3",
    )


def build_pixel_building_v06(image_path: Path, output_dir: Path, scene_id: str = "pixel-v07-b01") -> dict[str, object]:
    """Add authored facade depth, rooftop and window-room detail to B01."""

    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_building_v05
    )
    roles = palette["roles"]
    wall, trim = roles["wall"], roles["trim"]
    window, wood, lamp, plant, accent, dark, metal = roles["window"], roles["wood"], roles["lamp"], roles["plant"], roles["accent"], roles["dark"], roles["metal"]

    # Offset bands and columns create a facade rhythm while retaining the
    # single external collision boundary.
    for row, y in enumerate((1.04, 3.08, 5.12, 7.16, 9.20)):
        for column, x in enumerate((-6.40, -3.84, -1.28, 1.28, 3.84, 6.40)):
            _add_part(scene, objects, [], f"pixel-q03-r3-building-facade-block-{row}-{column}", (1.86, 0.08, 0.08), (x + (0.16 if row % 2 else 0.0), y, -5.03), _mix(wall, trim, 0.18 + (column % 2) * 0.06), "facade_surface_detail", "photo_inferred_building_mass", grid=FURNITURE_VOXEL)
    for row in range(4):
        y = 1.75 + row * 2.05
        for column in range(5):
            x = -5.30 + column * 2.65
            pane = _mix(window, lamp if (row + column) % 3 == 0 else accent, 0.16)
            for pane_index, (dx, dy, width, height) in enumerate(((-0.24, 0.22, 0.26, 0.22), (0.24, 0.22, 0.26, 0.22), (-0.24, -0.22, 0.26, 0.22), (0.24, -0.22, 0.26, 0.22))):
                _add_part(scene, objects, [], f"pixel-q03-r3-building-window-room-{row}-{column}-{pane_index}", (width, height, 0.025), (x + dx, y + dy, -5.04), _mix(pane, dark, 0.10 if pane_index == 3 else 0.0), "window_room_detail", "photo_palette_upper", grid=MICRO_VOXEL)
    for index, (x, y, width) in enumerate(((-6.2, 0.82, 1.24), (6.2, 2.86, 1.62), (-1.6, 10.70, 1.86), (3.3, 10.70, 1.20))):
        _add_part(scene, objects, [], f"pixel-q03-r3-building-roof-unit-{index}", (width, 0.36, 0.48), (x, y, -4.76), _mix(metal, dark, 0.18), "rooftop_detail", "photo_inferred_building_mass", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-r3-building-roof-unit-light-{index}", (width * 0.58, 0.06, 0.035), (x, y + 0.22, -4.48), _mix(window, lamp, 0.20), "rooftop_detail", "photo_palette_upper", grid=MICRO_VOXEL)

    # Near foliage receives separate stems and leaf clusters so foreground
    # depth does not collapse into one green rectangle.
    for index, (x, y, z) in enumerate(((-7.15, 1.44, -1.0), (-6.85, 1.92, -1.0), (7.18, 1.70, -0.78), (7.48, 2.15, -0.58))):
        _add_part(scene, objects, [], f"pixel-q03-r3-building-leaf-stem-{index}", (0.08, 0.72, 0.08), (x, y, z), _mix(dark, plant, 0.45), "foreground_vegetation", "photo_inferred_foreground", grid=MICRO_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-r3-building-leaf-cluster-{index}", (0.44, 0.30, 0.34), (x + (0.12 if index % 2 else -0.12), y + 0.34, z), _mix(plant, window, 0.10 + (index % 2) * 0.08), "foreground_vegetation", "photo_inferred_foreground", grid=FURNITURE_VOXEL)

    return _finalize_v07(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "facade",
        "像素风 V07 建筑候选：在 B01 的外部楼体、窗格、阳台和前景线关系上增加分块立面、窗内像素、屋顶设备与前景植物；仍不承诺进入未知室内。",
        ["palette_cues", "facade_outline", "window_line_and_foreground_lines"],
        ["facade_thickness", "window_grid", "window_room_pixels", "rooftop_units", "foreground_lines", "collision_envelope"],
        template=SceneTemplate.facade_flight, engine=SceneEngine.facade, layout_basis="q03_visual_index:b01:r3",
    )


# Q03 r4 is a composition pass, not a lighting pass.  The previous detail
# pass added many small parts, but the GPU screenshots still read as large
# monochrome blocks.  These helpers make compact, authored pixel patterns on
# the surfaces that are already visible in each candidate.  They never add a
# collision box; the scene description and movement contract remain those of
# the r3 candidate.
PIXEL_V08_LAYOUT_VERSION = "pixel-v08-authored-composition-pass-3"


def _add_pattern_xz(
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    prefix: str,
    pattern: tuple[str, ...],
    centre: tuple[float, float, float],
    cell: tuple[float, float],
    depth: float,
    colours: dict[str, list[int]],
    role: str,
    source: str,
    grid: float = MICRO_VOXEL,
) -> None:
    """Add a small pixel mosaic on an X/Z-facing surface."""

    width = max((len(row) for row in pattern), default=0)
    rows = len(pattern)
    origin_x, y, origin_z = centre
    for row_index, row in enumerate(pattern):
        for column_index, mark in enumerate(row):
            colour = colours.get(mark)
            if colour is None:
                continue
            x = origin_x + (column_index - (width - 1) / 2.0) * cell[0]
            z = origin_z + ((rows - 1) / 2.0 - row_index) * cell[1]
            _add_part(
                scene,
                objects,
                [],
                f"{prefix}-{row_index}-{column_index}",
                (cell[0] * 0.82, depth, cell[1] * 0.82),
                (x, y, z),
                colour,
                role,
                source,
                grid=grid,
            )


def _add_pattern_xy(
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    prefix: str,
    pattern: tuple[str, ...],
    centre: tuple[float, float, float],
    cell: tuple[float, float],
    depth: float,
    colours: dict[str, list[int]],
    role: str,
    source: str,
    grid: float = MICRO_VOXEL,
) -> None:
    """Add a small pixel mosaic on a horizontal X/Y-facing surface."""

    width = max((len(row) for row in pattern), default=0)
    rows = len(pattern)
    origin_x, origin_y, z = centre
    for row_index, row in enumerate(pattern):
        for column_index, mark in enumerate(row):
            colour = colours.get(mark)
            if colour is None:
                continue
            x = origin_x + (column_index - (width - 1) / 2.0) * cell[0]
            y = origin_y + ((rows - 1) / 2.0 - row_index) * cell[1]
            _add_part(
                scene,
                objects,
                [],
                f"{prefix}-{row_index}-{column_index}",
                (cell[0] * 0.82, cell[1] * 0.82, depth),
                (x, y, z),
                colour,
                role,
                source,
                grid=grid,
            )


def _add_pattern_yz(
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    prefix: str,
    pattern: tuple[str, ...],
    centre: tuple[float, float, float],
    cell: tuple[float, float],
    depth: float,
    colours: dict[str, list[int]],
    role: str,
    source: str,
    grid: float = MICRO_VOXEL,
) -> None:
    """Add a small pixel mosaic on a Y/Z-facing side surface."""

    width = max((len(row) for row in pattern), default=0)
    rows = len(pattern)
    x, origin_y, origin_z = centre
    for row_index, row in enumerate(pattern):
        for column_index, mark in enumerate(row):
            colour = colours.get(mark)
            if colour is None:
                continue
            y = origin_y + (column_index - (width - 1) / 2.0) * cell[0]
            z = origin_z + ((rows - 1) / 2.0 - row_index) * cell[1]
            _add_part(
                scene,
                objects,
                [],
                f"{prefix}-{row_index}-{column_index}",
                (depth, cell[0] * 0.82, cell[1] * 0.82),
                (x, y, z),
                colour,
                role,
                source,
                grid=grid,
            )


def _v08_spec() -> dict[str, object]:
    spec = _v07_spec()
    spec.update({
        "detail_pass": "v08-authored-composition-pass-3",
        "composition_policy": "semantic_pixel_patterns_before_lighting",
        "lighting_status": "not_added_in_q03",
    })
    return spec


def _finalize_v08(
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
    *,
    template: SceneTemplate,
    engine: SceneEngine,
    layout_basis: str,
) -> dict[str, object]:
    return _finalize_v02(
        image_path,
        output_dir,
        scene_id,
        scene,
        objects,
        collisions,
        movement,
        palette,
        profile,
        note,
        photo_supported_regions,
        generated_regions,
        template=template,
        engine=engine,
        route_name="pixel_style_sample_v8",
        layout_version=PIXEL_V08_LAYOUT_VERSION,
        version="pixel-v08",
        provider_version="pixel-voxel-v8",
        pixel_spec=_v08_spec(),
        layout_basis=layout_basis,
    )


def build_pixel_living_v08(image_path: Path, output_dir: Path, scene_id: str = "pixel-v08-i02") -> dict[str, object]:
    """Add semantic surface mosaics and furniture silhouettes to I02."""

    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_living_v07
    )
    roles = palette["roles"]
    wall, floor, sofa, wood = roles["wall"], roles["floor"], roles["sofa"], roles["wood"]
    trim, window, plant, lamp = roles["trim"], roles["window"], roles["plant"], roles["lamp"]
    dark, accent = roles["dark"], roles["accent"]
    palette_map = {
        "a": _mix(sofa, wall, 0.12), "b": _mix(sofa, window, 0.20),
        "c": _shade(sofa, 0.70), "d": trim, "e": accent, "f": lamp,
        "g": plant, "h": _shade(plant, 0.68), "i": wood, "j": dark,
    }

    # A bounded wall-art grid and a shelf create the multi-scale interior
    # reading seen in the reference: large composition, framed object, small
    # highlights.  The motifs are explicitly procedural, not claimed photo
    # segmentation.
    _add_pattern_xz(
        scene, objects, "pixel-q03-r4-living-wall-art-a",
        ("..eee..", ".eaaae.", "eabbae", ".eaaae.", "..eee.."),
        (-2.95, 1.86, 5.43), (0.18, 0.18), 0.045,
        palette_map, "wall_art_pixel_surface", "procedural_completion",
    )
    _add_pattern_xz(
        scene, objects, "pixel-q03-r4-living-wall-art-b",
        (".ddddd.", "d..f..d", "d.fjf.d", "d..f..d", ".ddddd."),
        (-0.72, 1.74, 5.43), (0.14, 0.18), 0.045,
        palette_map, "wall_art_pixel_surface", "procedural_completion",
    )
    _add_part(scene, objects, [], "pixel-q03-r4-living-rear-shelf", (2.80, 0.10, 0.12), (-0.42, 1.10, 5.32), wood, "wall_furniture_structure", "procedural_completion", grid=FURNITURE_VOXEL)
    for index, (x, height, colour) in enumerate(((-1.40, 0.42, accent), (-0.92, 0.58, lamp), (-0.42, 0.34, window), (0.10, 0.50, dark))):
        _add_part(scene, objects, [], f"pixel-q03-r4-living-shelf-object-{index}", (0.18, height, 0.18), (x, 1.38 + height * 0.5, 5.28), colour, "shelf_object_detail", "procedural_completion", grid=FURNITURE_VOXEL)

    # The sofa face is a shallow pixel illustration with two cushions, a seam
    # and feet.  It is placed on the existing visible silhouette, with no new
    # collider, so more detail does not change the tested route.
    _add_pattern_xy(
        scene, objects, "pixel-q03-r4-living-sofa-face",
        (".bbbb..bbbb.", "baaa..aaab.", "baac..caab.", "baaa..aaab.", ".bbbb..bbbb."),
        (-1.95, 1.02, -1.56), (0.18, 0.16), 0.045,
        palette_map, "upholstery_pixel_surface", "photo_inferred_furniture",
    )
    _add_pattern_xy(
        scene, objects, "pixel-q03-r4-living-table-top",
        (".iiiiii.", "i..e..i", "i.f..fi", "i..e..i", ".iiiiii."),
        (1.25, 1.16, 0.55), (0.16, 0.08), 0.045,
        palette_map, "tabletop_pixel_surface", "photo_inferred_furniture",
    )
    # Denser but organized foliage reads as a plant rather than a single
    # green mass; the source photo still supplies the colour family.
    _add_pattern_xz(
        scene, objects, "pixel-q03-r4-living-plant-crown",
        ("....g....", "...ggg...", "..ghhgg..", ".ggggggg.", "..hgggh..", "...ggg..."),
        (-3.52, 2.24, 0.45), (0.20, 0.20), 0.10,
        palette_map, "vegetation_pixel_surface", "photo_inferred_vegetation",
        grid=FURNITURE_VOXEL,
    )

    return _finalize_v08(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "living_room",
        "像素风 V08 客厅构图精修候选：在 V07 的实体分件上增加有组织的墙面像素图案、层板小物、沙发/桌面材质图案和分层植被；光影仍留到后续步骤。",
        ["palette_cues", "window_and_opening_vocabulary", "furniture_colour_relationships"],
        ["semantic_wall_mosaics", "shelf_objects", "upholstery_pixel_surface", "tabletop_pixel_surface", "layered_plant_surface", "collision_envelope"],
        template=SceneTemplate.indoor_walk, engine=SceneEngine.space, layout_basis="q03_visual_index:i02:r4",
    )


def build_pixel_corridor_v08(image_path: Path, output_dir: Path, scene_id: str = "pixel-v08-i01") -> dict[str, object]:
    """Add readable door, window, art and floor motifs to I01."""

    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_corridor_v07
    )
    roles = palette["roles"]
    wall, floor, trim = roles["wall"], roles["floor"], roles["trim"]
    wood, window, lamp, dark, accent = roles["wood"], roles["window"], roles["lamp"], roles["dark"], roles["accent"]
    palette_map = {
        "a": wall, "b": _mix(wall, window, 0.30), "c": _mix(wall, trim, 0.35),
        "d": trim, "e": accent, "f": lamp, "g": wood, "h": dark,
    }

    for index, z in enumerate((3.5, 0.0, -3.5, -7.0)):
        _add_pattern_yz(
            scene, objects, f"pixel-q03-r4-corridor-door-panel-{index}",
            (".dddd.", "dabbad", "dbaabd", "dabbad", ".dddd."),
            (2.275, 1.42, z), (0.16, 0.24), 0.045,
            palette_map, "door_pixel_surface", "photo_inferred_opening",
        )
        _add_pattern_yz(
            scene, objects, f"pixel-q03-r4-corridor-window-panel-{index}",
            ("bbbbbb", "b..e.b", "b.e..b", "b..e.b", "bbbbbb"),
            (-2.275, 1.42, z), (0.16, 0.24), 0.045,
            palette_map, "window_pixel_surface", "photo_inferred_opening",
        )
    for index, z in enumerate((4.9, 2.45, 0.0, -2.45, -4.9, -7.35)):
        _add_pattern_xz(
            scene, objects, f"pixel-q03-r4-corridor-wall-marker-{index}",
            (".ee.", "eaae", "eaae", ".ee."),
            (-2.30, 2.10, z), (0.18, 0.18), 0.045,
            palette_map, "wall_marker_detail", "procedural_completion",
        )
    _add_pattern_xy(
        scene, objects, "pixel-q03-r4-corridor-floor-runner",
        (".bbbbbbbb.", "b..cc..b.", "b..cc..b.", "b..cc..b.", ".bbbbbbbb."),
        (0.0, 0.20, -1.35), (0.38, 0.26), 0.045,
        palette_map, "floor_runner_detail", "procedural_completion",
        grid=FURNITURE_VOXEL,
    )

    return _finalize_v08(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "corridor",
        "像素风 V08 走廊构图精修候选：用有限像素图案区分门扇、窗面、墙面标记和地面导向，不改变 I01 的长向空间或碰撞。",
        ["palette_cues", "corridor_direction", "window_and_opening_vocabulary"],
        ["corridor_shell", "semantic_door_panels", "semantic_window_panels", "wall_markers", "floor_runner", "collision_envelope"],
        template=SceneTemplate.indoor_walk, engine=SceneEngine.space, layout_basis="q03_visual_index:i01:r4",
    )


def build_pixel_nature_v05(image_path: Path, output_dir: Path, scene_id: str = "pixel-v08-n01") -> dict[str, object]:
    """Add snow/rock/foliage motifs without turning distant mountains into terrain."""

    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_nature_v04
    )
    roles = palette["roles"]
    floor, window, plant, dark, accent = roles["floor"], roles["window"], roles["plant"], roles["dark"], roles["accent"]
    palette_map = {
        "a": _mix(floor, window, 0.16), "b": _mix(floor, window, 0.32),
        "c": _shade(floor, 0.72), "d": plant, "e": _mix(plant, window, 0.18),
        "f": _shade(plant, 0.66), "g": dark, "h": accent,
    }
    _add_pattern_xy(
        scene, objects, "pixel-q03-r4-nature-snow-path",
        (".aaaa..aaaa.", "aabbaa.bbaa", "..aa..aa..a", "a..bb..bb.a", ".aaaa..aaaa."),
        (0.0, 0.25, 2.18), (0.36, 0.22), 0.045,
        palette_map, "snow_path_pixel_surface", "photo_inferred_near_ground",
        grid=FURNITURE_VOXEL,
    )
    for index, (x, z, scale) in enumerate(((-5.0, 1.6, 1.0), (-4.3, 0.6, 0.82), (4.5, -2.0, 1.0), (5.0, -2.8, 0.78))):
        _add_pattern_xz(
            scene, objects, f"pixel-q03-r4-nature-foliage-{index}",
            ("...d...", "..ded..", ".deeed.", "defffed", "..ded.."),
            (x, 1.45 * scale, z), (0.18 * scale, 0.18 * scale), 0.10,
            palette_map, "vegetation_pixel_surface", "photo_inferred_vegetation",
            grid=FURNITURE_VOXEL,
        )
    for ridge_index, (z, y, base) in enumerate(((-9.30, 2.30, "ab"), (-13.30, 1.72, "bc"), (-17.30, 1.24, "ac"))):
        _add_pattern_xz(
            scene, objects, f"pixel-q03-r4-nature-ridge-{ridge_index}",
            ("....a....", "...abb...", "..abbb...", ".abbbb...", "abbbbb..."),
            (0.0, y, z), (0.72, 0.18), 0.045,
            {"a": palette_map[base[0]], "b": palette_map[base[1]]},
            "distant_ridge_pixel_surface", "photo_palette_upper",
            grid=FURNITURE_VOXEL,
        )

    return _finalize_v08(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "snow_mountain",
        "像素风 V08 自然构图精修候选：用组织化雪面图案、近景植被图形和分层山脊色面增加景深，不把远山变成近处长坡。",
        ["palette_cues", "near_ground_colour", "horizon_depth_order"],
        ["continuous_walk_surface", "snow_path_motif", "layered_foliage_motifs", "ridge_pixel_surfaces", "collision_envelope"],
        template=SceneTemplate.landscape_journey, engine=SceneEngine.terrain, layout_basis="q03_visual_index:n01:r4",
    )


def build_pixel_street_v07(image_path: Path, output_dir: Path, scene_id: str = "pixel-v08-s01") -> dict[str, object]:
    """Add road markings, vehicle faces and sidewalk material patterns to S01."""

    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_street_v06
    )
    roles = palette["roles"]
    floor, wall, window, lamp, dark, accent = roles["floor"], roles["wall"], roles["window"], roles["lamp"], roles["dark"], roles["accent"]
    palette_map = {
        "a": _mix(floor, wall, 0.12), "b": _mix(floor, window, 0.16),
        "c": _mix(floor, accent, 0.20), "d": window, "e": lamp,
        "f": dark, "g": accent,
    }
    _add_pattern_xy(
        scene, objects, "pixel-q03-r4-street-road-texture",
        ("a..b..a..b..", ".a..b..a..b.", "..a..b..a..b", "b..a..b..a..", "a..b..a..b.."),
        (0.0, 0.18, -1.0), (0.62, 0.34), 0.035,
        palette_map, "road_pixel_surface", "procedural_completion",
        grid=FURNITURE_VOXEL,
    )
    for index, (x, z) in enumerate(((-2.55, 1.2), (2.65, -4.0))):
        _add_pattern_xz(
            scene, objects, f"pixel-q03-r4-street-car-face-{index}",
            (".dddd.", "dffefd", "dggffd", "dffefd", ".dddd."),
            (x, 0.74, z - 1.34), (0.18, 0.15), 0.045,
            palette_map, "vehicle_pixel_surface", "photo_inferred_vehicle",
        )
    for side, x in (("left", -6.84), ("right", 6.84)):
        for index, z in enumerate((4.0, 0.0, -4.0, -8.0)):
            _add_pattern_yz(
                scene, objects, f"pixel-q03-r4-street-sidewalk-{side}-{index}",
                (".bb.", "baab", "b..b", ".bb."),
                (x, 0.28, z), (0.16, 0.20), 0.04,
                palette_map, "sidewalk_pixel_surface", "photo_inferred_sidewalk",
            )

    return _finalize_v08(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "street",
        "像素风 V08 街道构图精修候选：增加有节奏的路面材质、车辆前后识别图案和人行道分块，保持俯拍照片对应的道路方向。",
        ["palette_cues", "road_direction", "foreground_object_separation"],
        ["continuous_road", "road_pixel_motif", "vehicle_face_motifs", "sidewalk_motifs", "collision_envelope"],
        template=SceneTemplate.street_descent, engine=SceneEngine.street, layout_basis="q03_visual_index:s01:r4",
    )


def build_pixel_building_v07(image_path: Path, output_dir: Path, scene_id: str = "pixel-v08-b01") -> dict[str, object]:
    """Add facade bands and window-room pixel patterns to B01."""

    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_building_v06
    )
    roles = palette["roles"]
    wall, window, lamp, dark, accent, trim = roles["wall"], roles["window"], roles["lamp"], roles["dark"], roles["accent"], roles["trim"]
    palette_map = {
        "a": _mix(wall, trim, 0.18), "b": _mix(window, wall, 0.12),
        "c": _mix(window, accent, 0.20), "d": lamp, "e": accent,
        "f": dark, "g": trim,
    }
    for row in range(4):
        y = 1.75 + row * 2.05
        for column in range(5):
            x = -5.30 + column * 2.65
            _add_pattern_xz(
                scene, objects, f"pixel-q03-r4-building-window-room-{row}-{column}",
                (".bb..bb.", "b..cc..b", "b.cd..db", "b..cc..b", ".bb..bb."),
                (x, y, -5.075), (0.15, 0.15), 0.045,
                palette_map, "window_room_pixel_surface", "photo_palette_upper",
            )
    for index, x in enumerate((-5.20, -2.60, 0.0, 2.60, 5.20)):
        _add_pattern_xz(
            scene, objects, f"pixel-q03-r4-building-facade-sign-{index}",
            ("..ee..", ".eaa e.".replace(" ", ""), "..ee.."),
            (x, 0.66, -5.075), (0.16, 0.16), 0.045,
            palette_map, "facade_pixel_surface", "procedural_completion",
        )
    for index, (x, z) in enumerate(((-7.0, -0.80), (7.0, -0.55))):
        _add_pattern_xz(
            scene, objects, f"pixel-q03-r4-building-leaf-motif-{index}",
            ("...c...", "..cce..", ".cceeec", "cceeecc", "..cce.."),
            (x, 1.84, z), (0.16, 0.16), 0.10,
            {"c": _mix(roles["plant"], window, 0.12), "e": roles["plant"]},
            "foreground_vegetation_pixel_surface", "photo_inferred_foreground",
            grid=FURNITURE_VOXEL,
        )

    return _finalize_v08(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "facade",
        "像素风 V08 建筑构图精修候选：把窗格内部拆成有节奏的室内像素块，补充立面标识和前景叶簇；保持外部观察边界，不承诺进入未知室内。",
        ["palette_cues", "facade_outline", "window_line_and_foreground_lines"],
        ["facade_thickness", "window_grid", "window_room_motifs", "facade_sign_motifs", "foreground_leaf_motifs", "collision_envelope"],
        template=SceneTemplate.facade_flight, engine=SceneEngine.facade, layout_basis="q03_visual_index:b01:r4",
    )


# Q03 r5 is a material/readability pass.  It does not claim to add physical
# lighting: the purpose is to stop semantic parts from collapsing into one
# grey value before Q04 lighting work starts.  Colours remain bounded by the
# photo-derived palette bands and a small style anchor set per category.
PIXEL_V09_LAYOUT_VERSION = "pixel-v09-material-contrast-pass-4"


def _saturate(colour: list[int], amount: float = 1.18) -> list[int]:
    mean = sum(colour[:3]) / 3.0
    return _clamp_colour([mean + (channel - mean) * amount for channel in colour[:3]])


def _v09_palette(palette: dict[str, object], profile: str) -> dict[str, list[int]]:
    bands = palette.get("photo_bands", {})
    source = palette.get("roles", {})
    if not isinstance(bands, dict) or not isinstance(source, dict):
        raise ValueError("pixel palette bands and roles are required for v09")

    def band(name: str, fallback: list[int]) -> list[int]:
        value = bands.get(name, fallback)
        return _saturate(value if isinstance(value, list) else fallback, 1.20)

    anchors: dict[str, tuple[list[int], list[int], float]] = {
        "living_room": {
            "wall": (band("upper", [180, 180, 176]), [196, 190, 177], 0.48),
            "floor": (band("lower", [125, 104, 88]), [126, 98, 76], 0.44),
            "trim": (band("left", [64, 66, 74]), [45, 48, 60], 0.52),
            "sofa": (band("centre", [190, 186, 178]), [218, 214, 202], 0.56),
            "wood": (band("lower", [125, 104, 88]), [112, 66, 35], 0.54),
            "metal": (band("right", [82, 94, 108]), [70, 86, 105], 0.48),
            "window": (band("upper", [120, 155, 178]), [78, 145, 190], 0.48),
            "plant": (band("right", [80, 120, 82]), [52, 126, 66], 0.56),
            "lamp": (band("centre", [188, 160, 112]), [235, 173, 72], 0.54),
            "dark": (band("left", [48, 50, 58]), [36, 38, 48], 0.52),
        },
        "corridor": {
            "wall": (band("upper", [174, 180, 184]), [169, 176, 178], 0.42),
            "floor": (band("lower", [130, 112, 98]), [126, 101, 82], 0.46),
            "trim": (band("left", [70, 76, 82]), [49, 57, 70], 0.52),
            "wood": (band("lower", [130, 96, 70]), [119, 70, 40], 0.52),
            "window": (band("upper", [120, 160, 184]), [86, 153, 190], 0.50),
            "lamp": (band("centre", [180, 150, 100]), [232, 169, 75], 0.50),
            "dark": (band("left", [52, 58, 68]), [42, 46, 58], 0.50),
        },
        "snow_mountain": {
            "floor": (band("lower", [172, 180, 182]), [184, 194, 198], 0.38),
            "wall": (band("upper", [115, 145, 168]), [105, 144, 180], 0.42),
            "window": (band("upper", [126, 160, 181]), [139, 181, 207], 0.42),
            "plant": (band("right", [78, 112, 84]), [57, 120, 76], 0.54),
            "dark": (band("left", [54, 65, 74]), [43, 54, 66], 0.50),
            "accent": (band("centre", [150, 150, 138]), [224, 187, 112], 0.42),
        },
        "street": {
            "floor": (band("lower", [120, 112, 102]), [105, 99, 88], 0.44),
            "wall": (band("upper", [104, 105, 96]), [85, 88, 82], 0.44),
            "window": (band("upper", [105, 145, 167]), [85, 164, 194], 0.52),
            "wood": (band("centre", [124, 94, 68]), [126, 77, 48], 0.48),
            "plant": (band("right", [78, 110, 72]), [54, 123, 66], 0.54),
            "lamp": (band("centre", [164, 136, 78]), [230, 168, 67], 0.50),
            "dark": (band("left", [50, 52, 58]), [37, 43, 54], 0.52),
        },
        "facade": {
            "wall": (band("upper", [94, 94, 86]), [78, 79, 73], 0.46),
            "floor": (band("lower", [123, 104, 91]), [115, 89, 71], 0.42),
            "trim": (band("left", [52, 54, 59]), [38, 42, 50], 0.52),
            "window": (band("upper", [104, 144, 154]), [91, 150, 164], 0.50),
            "wood": (band("centre", [116, 84, 58]), [113, 68, 40], 0.48),
            "lamp": (band("centre", [170, 134, 72]), [234, 165, 63], 0.56),
            "plant": (band("right", [76, 110, 74]), [54, 126, 69], 0.54),
            "dark": (band("left", [45, 47, 53]), [31, 35, 44], 0.52),
        },
    }[profile]
    enhanced: dict[str, list[int]] = {}
    for role, original in source.items():
        if role in anchors:
            photo_colour, anchor, amount = anchors[role]
            enhanced[role] = _mix(photo_colour, anchor, amount)
        elif isinstance(original, list):
            enhanced[role] = _saturate(original, 1.14)
    # Roles omitted by a profile inherit the old colour, keeping the function
    # compatible with the shared builders while making the material decision
    # explicit in the manifest.
    for role, original in source.items():
        if role not in enhanced and isinstance(original, list):
            enhanced[role] = list(original)
    return enhanced


def _v09_role_colour(role: str, roles: dict[str, list[int]]) -> list[int] | None:
    lowered = role.lower()
    if any(token in lowered for token in ("floor", "ground", "road", "sidewalk", "snow_path", "runner", "curb")):
        return roles.get("floor")
    if any(token in lowered for token in ("wall", "facade", "ceiling", "building_mass", "ridge")):
        return roles.get("wall")
    if any(token in lowered for token in ("window", "opening", "skyline")):
        return roles.get("window")
    if any(token in lowered for token in ("sofa", "upholstery")):
        return roles.get("sofa")
    if any(token in lowered for token in ("wood", "table", "bench", "door", "furniture", "vehicle")):
        return roles.get("wood")
    if any(token in lowered for token in ("plant", "vegetation", "tree", "foliage", "leaf")):
        return roles.get("plant")
    if any(token in lowered for token in ("lamp", "light", "accent", "sign", "marker", "lane")):
        return roles.get("lamp")
    if any(token in lowered for token in ("metal", "wire", "pole", "fixture", "service")):
        return roles.get("metal")
    if any(token in lowered for token in ("trim", "frame", "rail", "foreground_line", "detail")):
        return roles.get("trim")
    return None


def _apply_v09_materials(scene: trimesh.Scene, objects: list[dict[str, object]], roles: dict[str, list[int]]) -> None:
    by_id = {str(item.get("id")): item for item in objects}
    for name, mesh in scene.geometry.items():
        entry = by_id.get(name)
        if not entry:
            continue
        colour = _v09_role_colour(str(entry.get("role", "")), roles)
        if colour is None:
            continue
        mesh.visual.vertex_colors = np.tile(np.asarray([*colour, 255], dtype=np.uint8), (len(mesh.vertices), 1))
        mesh.visual.material = trimesh.visual.material.PBRMaterial(
            baseColorFactor=[*colour, 255], metallicFactor=0.0, roughnessFactor=0.82
        )


def _finalize_v09(
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
    *,
    template: SceneTemplate,
    engine: SceneEngine,
    layout_basis: str,
) -> dict[str, object]:
    return _finalize_v02(
        image_path,
        output_dir,
        scene_id,
        scene,
        objects,
        collisions,
        movement,
        palette,
        profile,
        note,
        photo_supported_regions,
        generated_regions,
        template=template,
        engine=engine,
        route_name="pixel_style_sample_v9",
        layout_version=PIXEL_V09_LAYOUT_VERSION,
        version="pixel-v09",
        provider_version="pixel-voxel-v9",
        pixel_spec={**_v08_spec(), "detail_pass": "v09-material-contrast-pass-4", "lighting_status": "not_added_in_q03"},
        layout_basis=layout_basis,
    )


def _build_v09_from_v08(image_path: Path, output_dir: Path, scene_id: str, builder, profile: str, template: SceneTemplate, engine: SceneEngine, basis: str, note: str, supported: list[str], generated: list[str]) -> dict[str, object]:
    scene, objects, collisions, palette, movement = _load_candidate_for_detail(image_path, output_dir, scene_id, builder)
    enhanced = _v09_palette(palette, profile)
    palette["roles"] = enhanced
    _apply_v09_materials(scene, objects, enhanced)
    return _finalize_v09(image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, profile, note, supported, generated, template=template, engine=engine, layout_basis=basis)


def _build_v10_from_v09(image_path: Path, output_dir: Path, scene_id: str, builder, profile: str, template: SceneTemplate, engine: SceneEngine, basis: str, note: str, supported: list[str], generated: list[str]) -> dict[str, object]:
    scene, objects, collisions, palette, movement = _load_candidate_for_detail(image_path, output_dir, scene_id, builder)
    return _finalize_v10(image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, profile, note, supported, generated, template=template, engine=engine, basis=basis)


def build_pixel_living_v09(image_path: Path, output_dir: Path, scene_id: str = "pixel-v09-i02") -> dict[str, object]:
    return _build_v09_from_v08(image_path, output_dir, scene_id, build_pixel_living_v08, "living_room", SceneTemplate.indoor_walk, SceneEngine.space, "q03_visual_index:i02:r5", "像素风 V09 客厅材质对比候选：保留 V08 的实体构图，按照片色带与室内材质语义重建色阶；动态光影留待后续 Q04/光影步骤。", ["palette_cues", "window_and_opening_vocabulary", "furniture_colour_relationships"], ["semantic_pixel_composition", "material_contrast", "collision_envelope"])


def build_pixel_corridor_v09(image_path: Path, output_dir: Path, scene_id: str = "pixel-v09-i01") -> dict[str, object]:
    return _build_v09_from_v08(image_path, output_dir, scene_id, build_pixel_corridor_v08, "corridor", SceneTemplate.indoor_walk, SceneEngine.space, "q03_visual_index:i01:r5", "像素风 V09 走廊材质对比候选：保留 I01 长向结构和 V08 门窗图案，增强地面、木门、窗光与深色边框的可读层次；动态光影未加入。", ["palette_cues", "corridor_direction", "window_and_opening_vocabulary"], ["semantic_pixel_composition", "material_contrast", "collision_envelope"])


def build_pixel_nature_v06(image_path: Path, output_dir: Path, scene_id: str = "pixel-v09-n01") -> dict[str, object]:
    return _build_v09_from_v08(image_path, output_dir, scene_id, build_pixel_nature_v05, "snow_mountain", SceneTemplate.landscape_journey, SceneEngine.terrain, "q03_visual_index:n01:r5", "像素风 V09 自然材质对比候选：增强雪面、天空、植被与远山的色阶分层，保留远近分离和可行走面；没有用光雾替代地形。", ["palette_cues", "near_ground_colour", "horizon_depth_order"], ["semantic_pixel_composition", "material_contrast", "collision_envelope"])


def build_pixel_street_v08(image_path: Path, output_dir: Path, scene_id: str = "pixel-v09-s01") -> dict[str, object]:
    return _build_v09_from_v08(image_path, output_dir, scene_id, build_pixel_street_v07, "street", SceneTemplate.street_descent, SceneEngine.street, "q03_visual_index:s01:r5", "像素风 V09 街道材质对比候选：保留道路方向和分离对象，提升路面、车辆、建筑窗口与植被的色阶关系；不改路线碰撞。", ["palette_cues", "road_direction", "foreground_object_separation"], ["semantic_pixel_composition", "material_contrast", "collision_envelope"])


def build_pixel_building_v08(image_path: Path, output_dir: Path, scene_id: str = "pixel-v09-b01") -> dict[str, object]:
    return _build_v09_from_v08(image_path, output_dir, scene_id, build_pixel_building_v07, "facade", SceneTemplate.facade_flight, SceneEngine.facade, "q03_visual_index:b01:r5", "像素风 V09 建筑材质对比候选：保留楼体、窗格和前景线，强化夜景立面、窗内层次和暖色小光点；仍只提供外部观察。", ["palette_cues", "facade_outline", "window_line_and_foreground_lines"], ["semantic_pixel_composition", "material_contrast", "collision_envelope"])


# Q03 r6 targets the start-camera composition.  V08/V09 details existed in
# the GLB, but several of them were outside the first useful view or too small
# to explain the room.  This pass adds a few large, bounded pixel motifs at
# eye level and keeps all movement data inherited from v09.
PIXEL_V10_LAYOUT_VERSION = "pixel-v10-start-composition-pass-5"


def _finalize_v10(
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
    supported: list[str],
    generated: list[str],
    *,
    template: SceneTemplate,
    engine: SceneEngine,
    basis: str,
) -> dict[str, object]:
    return _finalize_v02(
        image_path,
        output_dir,
        scene_id,
        scene,
        objects,
        collisions,
        movement,
        palette,
        profile,
        note,
        supported,
        generated,
        template=template,
        engine=engine,
        route_name="pixel_style_sample_v10",
        layout_version=PIXEL_V10_LAYOUT_VERSION,
        version="pixel-v10",
        provider_version="pixel-voxel-v10",
        pixel_spec={
            **_v08_spec(),
            "detail_pass": "v10-start-composition-pass-5",
            "lighting_status": "not_added_in_q03",
            "composition_policy": "start_camera_hero_motifs_before_lighting",
        },
        layout_basis=basis,
    )


def build_pixel_living_v10(image_path: Path, output_dir: Path, scene_id: str = "pixel-v10-i02") -> dict[str, object]:
    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_living_v09
    )
    roles = palette["roles"]
    wall, sofa, wood = roles["wall"], roles["sofa"], roles["wood"]
    trim, window, plant, lamp = roles["trim"], roles["window"], roles["plant"], roles["lamp"]
    dark, accent = roles["dark"], roles["accent"]
    colours = {"a": wall, "b": _mix(sofa, window, 0.20), "c": _shade(sofa, 0.66), "d": trim, "e": accent, "f": lamp, "g": plant, "h": _shade(plant, 0.64), "i": wood, "j": dark}

    # Side-wall frames are intentionally in the start frustum, unlike the
    # earlier rear-wall art.  They provide readable scale and a controlled
    # interpretation of the photographed wall decoration.
    for index, (x, z, mark) in enumerate(((-4.43, 1.10, "e"), (-4.43, -0.90, "f"), (4.43, 0.70, "b"), (4.43, -1.35, "e"))):
        _add_pattern_yz(
            scene, objects, f"pixel-q03-r6-living-side-frame-{index}",
            (".dddd.", f"d{mark}{mark}{mark}d", f"d{mark}j{mark}d", f"d{mark}{mark}{mark}d", ".dddd."),
            (x, 1.84, z), (0.18, 0.20), 0.045,
            colours, "wall_art_pixel_surface", "procedural_completion",
        )
    _add_part(scene, objects, [], "pixel-q03-r6-living-console-shelf", (1.80, 0.10, 0.16), (3.28, 1.10, -4.05), wood, "wall_furniture_structure", "photo_inferred_furniture", grid=FURNITURE_VOXEL)
    for index, (y, height, colour) in enumerate(((1.34, 0.30, accent), (1.54, 0.46, window), (1.76, 0.24, lamp))):
        _add_part(scene, objects, [], f"pixel-q03-r6-living-console-object-{index}", (0.18, height, 0.16), (3.28, y, -4.02), colour, "shelf_object_detail", "procedural_completion", grid=FURNITURE_VOXEL)
    # A larger cushion face makes the photographed sofa read as upholstery,
    # not a single block, at the distance used by the offline verifier.
    _add_pattern_xz(
        scene, objects, "pixel-q03-r6-living-sofa-back-composition",
        (".bbbbbb.", "baacc a b".replace(" ", ""), "baacccab", "baacc a b".replace(" ", ""), ".bbbbbb."),
        (-1.90, 1.46, -2.74), (0.22, 0.18), 0.055,
        colours, "upholstery_pixel_surface", "photo_inferred_furniture",
        grid=FURNITURE_VOXEL,
    )
    for index, (x, y) in enumerate(((-3.92, 2.56), (-3.52, 2.86), (-3.08, 2.54), (-2.72, 2.90))):
        _add_part(scene, objects, [], f"pixel-q03-r6-living-plant-leaf-{index}", (0.42, 0.18, 0.22), (x, y, 0.42), plant if index % 2 else _mix(plant, window, 0.22), "vegetation_pixel_surface", "photo_inferred_vegetation", grid=FURNITURE_VOXEL)

    return _finalize_v10(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "living_room",
        "像素风 V10 客厅起点构图候选：补充起点可见的侧墙画框、沙发大面分件、电视柜层板和多层植物；仍不加入动态光影。",
        ["palette_cues", "window_and_opening_vocabulary", "furniture_colour_relationships"],
        ["start_camera_hero_motifs", "semantic_wall_art", "upholstery_composition", "console_objects", "layered_plant_surface", "collision_envelope"],
        template=SceneTemplate.indoor_walk, engine=SceneEngine.space, basis="q03_visual_index:i02:r6",
    )


def build_pixel_corridor_v10(image_path: Path, output_dir: Path, scene_id: str = "pixel-v10-i01") -> dict[str, object]:
    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_corridor_v09
    )
    roles = palette["roles"]
    wall, floor, trim = roles["wall"], roles["floor"], roles["trim"]
    wood, window, lamp, dark, accent = roles["wood"], roles["window"], roles["lamp"], roles["dark"], roles["accent"]
    colours = {"a": wall, "b": _mix(wall, window, 0.34), "c": _mix(wall, trim, 0.36), "d": trim, "e": accent, "f": lamp, "g": wood, "h": dark}
    # Create alternating wall bays between the existing openings.  This is a
    # structural rhythm cue, not another row of invented doors.
    for index, z in enumerate((4.72, 2.35, -1.18, -4.72, -8.05)):
        _add_pattern_yz(
            scene, objects, f"pixel-q03-r6-corridor-wall-bay-{index}",
            (".dddd.", "dabbad", "dcffcd", "dcb bcd".replace(" ", ""), ".dddd."),
            (2.30, 1.80, z), (0.18, 0.22), 0.045,
            colours, "wall_bay_pixel_surface", "procedural_completion",
        )
    for index, z in enumerate((4.4, 1.9, -0.6, -3.1, -5.6, -8.1)):
        _add_pattern_yz(
            scene, objects, f"pixel-q03-r6-corridor-window-bay-{index}",
            (".bbbb.", "baeeab", "baffab", "baeeab", ".bbbb."),
            (-2.30, 1.84, z), (0.18, 0.22), 0.045,
            colours, "window_bay_pixel_surface", "photo_inferred_opening",
        )
    _add_pattern_xz(
        scene, objects, "pixel-q03-r6-corridor-end-art",
        ("..ee..", ".eaa e.".replace(" ", ""), "eabb ae".replace(" ", ""), ".eaa e.".replace(" ", ""), "..ee.."),
        (0.0, 2.48, -9.30), (0.20, 0.20), 0.055,
        colours, "wall_art_pixel_surface", "procedural_completion",
        grid=FURNITURE_VOXEL,
    )

    return _finalize_v10(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "corridor",
        "像素风 V10 走廊起点构图候选：把门窗之间的空墙组织为重复墙湾和窗湾，补充尽端图形，保持 I01 的长向关系与碰撞。",
        ["palette_cues", "corridor_direction", "window_and_opening_vocabulary"],
        ["start_camera_bay_rhythm", "semantic_door_and_window_bays", "end_wall_motif", "collision_envelope"],
        template=SceneTemplate.indoor_walk, engine=SceneEngine.space, basis="q03_visual_index:i01:r6",
    )


def build_pixel_nature_v07(image_path: Path, output_dir: Path, scene_id: str = "pixel-v10-n01") -> dict[str, object]:
    return _build_v10_from_v09(image_path, output_dir, scene_id, build_pixel_nature_v06, "snow_mountain", SceneTemplate.landscape_journey, SceneEngine.terrain, "q03_visual_index:n01:r6", "像素风 V10 自然构图候选：以 V08 组织化山脊和雪面为基础增强起点可见的近景层次；光影留待后续。", ["palette_cues", "near_ground_colour", "horizon_depth_order"], ["start_camera_layers", "snow_path_motif", "ridge_pixel_surfaces", "collision_envelope"])


def build_pixel_street_v09(image_path: Path, output_dir: Path, scene_id: str = "pixel-v10-s01") -> dict[str, object]:
    return _build_v10_from_v09(image_path, output_dir, scene_id, build_pixel_street_v08, "street", SceneTemplate.street_descent, SceneEngine.street, "q03_visual_index:s01:r6", "像素风 V10 街道构图候选：以 V08 道路和车辆图案为基础增强起点道路节奏与对象分离；光影留待后续。", ["palette_cues", "road_direction", "foreground_object_separation"], ["start_camera_layers", "road_pixel_motif", "vehicle_face_motifs", "collision_envelope"])


def build_pixel_building_v09(image_path: Path, output_dir: Path, scene_id: str = "pixel-v10-b01") -> dict[str, object]:
    return _build_v10_from_v09(image_path, output_dir, scene_id, build_pixel_building_v08, "facade", SceneTemplate.facade_flight, SceneEngine.facade, "q03_visual_index:b01:r6", "像素风 V10 建筑构图候选：以 V08 窗格和立面层次为基础增强正面起点的窗内节奏；光影留待后续。", ["palette_cues", "facade_outline", "window_line_and_foreground_lines"], ["start_camera_layers", "window_room_motifs", "facade_sign_motifs", "collision_envelope"])


# Q03 lighting is intentionally a manifest-driven viewer pass.  The GLB
# remains unchanged so the v10 geometry can be compared directly; online and
# offline viewers consume the same preset and therefore cannot silently drift.
PIXEL_V11_LAYOUT_VERSION = "pixel-v11-lighting-pass-1"
PIXEL_V11_LIGHTING = {
    "living_room": "indoor_warm_window",
    "corridor": "indoor_warm_window",
    "snow_mountain": "outdoor_cool_daylight",
    "street": "street_soft_daylight",
    "facade": "facade_blue_hour",
}


def _finalize_v11(
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
    supported: list[str],
    generated: list[str],
    *,
    template: SceneTemplate,
    engine: SceneEngine,
    basis: str,
) -> dict[str, object]:
    spec = {
        **_v08_spec(),
        "detail_pass": "v11-lighting-pass-1",
        "lighting_preset": PIXEL_V11_LIGHTING[profile],
        "shadow_policy": "single_soft_key_contact_shadows_for_v11_only",
        "emissive_policy": "semantic_light_sources_only_low_global_lift",
    }
    return _finalize_v02(
        image_path,
        output_dir,
        scene_id,
        scene,
        objects,
        collisions,
        movement,
        palette,
        profile,
        note,
        supported,
        generated,
        template=template,
        engine=engine,
        route_name="pixel_style_sample_v11",
        layout_version=PIXEL_V11_LAYOUT_VERSION,
        version="pixel-v11",
        provider_version="pixel-voxel-v11",
        pixel_spec=spec,
        layout_basis=basis,
    )


def _build_v11_from_v10(image_path: Path, output_dir: Path, scene_id: str, builder, profile: str, template: SceneTemplate, engine: SceneEngine, basis: str, note: str, supported: list[str], generated: list[str]) -> dict[str, object]:
    scene, objects, collisions, palette, movement = _load_candidate_for_detail(image_path, output_dir, scene_id, builder)
    return _finalize_v11(image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, profile, note, supported, generated, template=template, engine=engine, basis=basis)


def build_pixel_living_v11(image_path: Path, output_dir: Path, scene_id: str = "pixel-v11-i02") -> dict[str, object]:
    return _build_v11_from_v10(image_path, output_dir, scene_id, build_pixel_living_v10, "living_room", SceneTemplate.indoor_walk, SceneEngine.space, "q03_visual_index:i02:r7", "像素风 V11 客厅光影候选：在 V10 构图和材质基础上使用暖窗光、冷环境补光和低强度接触阴影；几何与碰撞不变。", ["palette_cues", "window_and_opening_vocabulary", "furniture_colour_relationships"], ["start_camera_hero_motifs", "material_contrast", "warm_window_light", "soft_contact_shadows", "collision_envelope"])


def build_pixel_corridor_v11(image_path: Path, output_dir: Path, scene_id: str = "pixel-v11-i01") -> dict[str, object]:
    return _build_v11_from_v10(image_path, output_dir, scene_id, build_pixel_corridor_v10, "corridor", SceneTemplate.indoor_walk, SceneEngine.space, "q03_visual_index:i01:r7", "像素风 V11 走廊光影候选：在 V10 门窗与长向构图基础上使用暖窗光和边缘接触阴影，保持路线和碰撞不变。", ["palette_cues", "corridor_direction", "window_and_opening_vocabulary"], ["start_camera_bay_rhythm", "material_contrast", "warm_window_light", "soft_contact_shadows", "collision_envelope"])


def build_pixel_nature_v08(image_path: Path, output_dir: Path, scene_id: str = "pixel-v11-n01") -> dict[str, object]:
    return _build_v11_from_v10(image_path, output_dir, scene_id, build_pixel_nature_v07, "snow_mountain", SceneTemplate.landscape_journey, SceneEngine.terrain, "q03_visual_index:n01:r7", "像素风 V11 自然光影候选：使用冷日光天空、较弱地面补光和柔和阴影保持雪面层次；不把雾效当作地形。", ["palette_cues", "near_ground_colour", "horizon_depth_order"], ["start_camera_layers", "material_contrast", "cool_daylight", "soft_contact_shadows", "collision_envelope"])


def build_pixel_street_v10(image_path: Path, output_dir: Path, scene_id: str = "pixel-v11-s01") -> dict[str, object]:
    return _build_v11_from_v10(image_path, output_dir, scene_id, build_pixel_street_v09, "street", SceneTemplate.street_descent, SceneEngine.street, "q03_visual_index:s01:r7", "像素风 V11 街道光影候选：使用低对比日光和定向路面阴影增强道路、车辆和建筑分层；不改俯拍路线碰撞。", ["palette_cues", "road_direction", "foreground_object_separation"], ["start_camera_layers", "material_contrast", "soft_daylight", "soft_contact_shadows", "collision_envelope"])


def build_pixel_building_v10(image_path: Path, output_dir: Path, scene_id: str = "pixel-v11-b01") -> dict[str, object]:
    return _build_v11_from_v10(image_path, output_dir, scene_id, build_pixel_building_v09, "facade", SceneTemplate.facade_flight, SceneEngine.facade, "q03_visual_index:b01:r7", "像素风 V11 建筑蓝调光影候选：使用蓝调环境光、低强度暖窗光和单一柔和主光区分窗内层次；仍只提供外部观察。", ["palette_cues", "facade_outline", "window_line_and_foreground_lines"], ["start_camera_layers", "material_contrast", "blue_hour_light", "soft_contact_shadows", "collision_envelope"])


# Q03 r8 is the first image-specific indoor detail pass.  Earlier passes
# increased the number of parts, but the GPU screenshots still read too much
# like one beige template.  This pass uses the known visual anchors of I01
# (dark window rhythm, white corridor, wood door, tiled floor) and I02 (white
# sectional, dark TV wall, low console, round table, tall plants) to recolour
# existing surfaces and add bounded voxel assets.  It keeps the existing
# collision envelopes unchanged; every new part is render-only and labelled
# as photo-supported or procedural completion in the manifest.
PIXEL_V12_LAYOUT_VERSION = "pixel-v12-image-specific-indoor-detail-pass-6"


def _v12_roles(profile: str, palette: dict[str, object]) -> dict[str, object]:
    roles = dict(palette["roles"])
    if profile == "living_room":
        roles.update({
            "wall": [225, 229, 220],
            "floor": [185, 186, 180],
            "trim": [26, 33, 40],
            "sofa": [239, 239, 232],
            "wood": [96, 57, 29],
            "metal": [104, 115, 123],
            "window": [84, 150, 198],
            "plant": [42, 112, 52],
            "lamp": [255, 185, 69],
            "dark": [12, 18, 25],
            "accent": [46, 132, 202],
        })
    elif profile == "corridor":
        roles.update({
            "wall": [238, 238, 233],
            "floor": [201, 200, 195],
            "trim": [35, 40, 45],
            "wood": [139, 78, 29],
            "window": [106, 163, 201],
            "lamp": [246, 181, 91],
            "dark": [30, 35, 42],
            "accent": [83, 142, 190],
        })
    result = dict(palette)
    result["roles"] = roles
    result["v12_palette_policy"] = "image_specific_indoor_anchor_palette"
    return result


def _set_mesh_colour(mesh: trimesh.Trimesh, colour: list[int]) -> None:
    mesh.visual.vertex_colors = np.tile(np.asarray([*colour, 255], dtype=np.uint8), (len(mesh.vertices), 1))
    mesh.visual.material = trimesh.visual.material.PBRMaterial(
        baseColorFactor=[*colour, 255],
        metallicFactor=0.0,
        roughnessFactor=0.82,
    )


def _v12_colour_for_object(name: str, role: str, roles: dict[str, list[int]]) -> list[int] | None:
    lower_name = name.lower()
    lower_role = role.lower()
    if any(token in lower_name for token in ("sofa", "cushion", "upholstery")):
        return roles["sofa"]
    if any(token in lower_name for token in ("coffee-table", "round-table", "table-top-inlay")):
        return roles["metal"]
    if any(token in lower_name for token in ("screen", "tv", "display")):
        return roles["dark"]
    if any(token in lower_name for token in ("plant", "leaf", "vegetation")):
        return roles["plant"]
    if "lamp" in lower_name or "light" in lower_name:
        return roles["lamp"]
    if any(token in lower_name for token in ("door", "wood", "table", "console", "shelf")):
        return roles["wood"]
    if "window" in lower_name or "curtain" in lower_name or "city" in lower_name:
        return roles["window"]
    if any(token in lower_name for token in ("frame", "mullion", "trim", "beam", "baseboard", "seam")):
        return roles["trim"]
    if "floor" in lower_name or "ground" in lower_name or "rug" in lower_name:
        return roles["floor"]
    if lower_role in {"wall", "ceiling", "wall_detail", "wall_art"}:
        return roles["wall"]
    if lower_role in {"furniture", "furniture_detail", "wood_furniture_detail", "tabletop_object", "shelf_object_detail"}:
        return roles["wood"]
    if lower_role in {"opening_detail", "window_detail", "door_detail"}:
        return roles["trim"]
    return None


def _apply_v12_indoor_palette(scene: trimesh.Scene, objects: list[dict[str, object]], profile: str, palette: dict[str, object]) -> dict[str, object]:
    styled_palette = _v12_roles(profile, palette)
    if profile not in {"living_room", "corridor"}:
        return styled_palette
    roles = styled_palette["roles"]
    for entry in objects:
        name = str(entry["id"])
        mesh = scene.geometry.get(name)
        if mesh is None:
            continue
        colour = _v12_colour_for_object(name, str(entry.get("role", "")), roles)
        if colour is not None:
            _set_mesh_colour(mesh, colour)
    return styled_palette


def _add_cylinder_part(
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    name: str,
    radius: float,
    height: float,
    center: tuple[float, float, float],
    colour: list[int],
    role: str,
    source: str,
    *,
    sections: int = 8,
    grid: float = FURNITURE_VOXEL,
) -> trimesh.Trimesh:
    snapped_radius = max(grid, _snap(radius, grid))
    snapped_height = max(grid, _snap(height, grid))
    snapped_center = tuple(_snap(value, grid) for value in center)
    mesh = trimesh.creation.cylinder(radius=snapped_radius, height=snapped_height, sections=sections)
    mesh.apply_translation(snapped_center)
    _set_mesh_colour(mesh, colour)
    mesh.metadata["layout_name"] = name
    mesh.metadata["voxel_grid"] = grid
    scene.add_geometry(mesh, geom_name=name)
    bounds = np.asarray(mesh.bounds, dtype=float)
    objects.append({
        "id": name,
        "role": role,
        "source": source,
        "voxel_grid": grid,
        "bounds": bounds.tolist(),
    })
    return mesh


def _add_v12_living_details(scene: trimesh.Scene, objects: list[dict[str, object]], roles: dict[str, list[int]]) -> None:
    wall, sofa, wood = roles["wall"], roles["sofa"], roles["wood"]
    trim, window, plant, lamp = roles["trim"], roles["window"], roles["plant"], roles["lamp"]
    dark, accent, metal = roles["dark"], roles["accent"], roles["metal"]

    # I02 anchor: the source has a large dark TV wall with a long low console.
    # Place it beside, rather than over, the existing window so the two source
    # cues remain simultaneously visible from the start camera.
    _add_part(scene, objects, [], "pixel-q03-r8-i02-tv-wall-panel", (2.45, 1.58, 0.06), (-2.58, 2.04, -6.52), dark, "display_surface", "photo_supported_object", grid=FURNITURE_VOXEL)
    for index, (extents, centre) in enumerate((
        ((2.62, 0.07, 0.07), (-2.58, 2.88, -6.47)),
        ((2.62, 0.07, 0.07), (-2.58, 1.20, -6.47)),
        ((0.07, 1.74, 0.07), (-3.92, 2.04, -6.47)),
        ((0.07, 1.74, 0.07), (-1.24, 2.04, -6.47)),
    )):
        _add_part(scene, objects, [], f"pixel-q03-r8-i02-tv-frame-{index}", extents, centre, wood, "display_frame", "photo_supported_object", grid=MICRO_VOXEL)
    _add_pattern_xz(
        scene, objects, "pixel-q03-r8-i02-tv-pixel-art",
        ("..bbbb..", ".bbaaaab.", "baacccab", "baacccab", ".bbaaaab.", "..bbbb.."),
        (-2.58, 2.03, -6.46), (0.22, 0.19), 0.025,
        {"a": accent, "b": window, "c": lamp}, "display_surface_detail", "photo_supported_object",
    )
    _add_part(scene, objects, [], "pixel-q03-r8-i02-tv-console", (3.18, 0.48, 0.48), (-2.58, 0.48, -6.19), wood, "media_console", "photo_supported_furniture", grid=FURNITURE_VOXEL)
    for index, x in enumerate((-3.65, -2.58, -1.51)):
        _add_part(scene, objects, [], f"pixel-q03-r8-i02-tv-console-drawer-{index}", (0.72, 0.18, 0.035), (x, 0.55, -5.92), _mix(wood, trim, 0.22), "media_console_detail", "photo_supported_furniture", grid=MICRO_VOXEL)

    # The white sectional is split into seat faces, back cushions, piping and
    # patterned pillows.  These are visible details only and share the
    # already-existing sofa collision envelope.
    for index, x in enumerate((-2.70, -1.35)):
        _add_part(scene, objects, [], f"pixel-q03-r8-i02-sectional-seat-{index}", (1.16, 0.08, 0.86), (x, 0.95, -1.36), sofa, "upholstery_surface", "photo_supported_furniture", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-r8-i02-sectional-shadow-{index}", (1.02, 0.035, 0.08), (x, 0.91, -0.92), _shade(sofa, 0.62), "upholstery_detail", "photo_supported_furniture", grid=MICRO_VOXEL)
        _add_pattern_xz(
            scene, objects, f"pixel-q03-r8-i02-sectional-pillow-{index}",
            (".aaaa.", "aabbba", "abb bba".replace(" ", ""), ".aaaa."),
            (x, 1.30, -1.34), (0.16, 0.14), 0.035,
            {"a": sofa, "b": _mix(sofa, accent, 0.42)}, "upholstery_pattern", "photo_supported_furniture",
        )
    _add_part(scene, objects, [], "pixel-q03-r8-i02-sectional-arm", (0.28, 1.10, 1.05), (-0.18, 1.10, -1.34), _shade(sofa, 0.90), "upholstery_structure", "photo_supported_furniture", grid=FURNITURE_VOXEL)

    # The reference coffee table is round.  An octagonal top plus a pedestal
    # provides that cue while retaining the existing walkable route.
    _add_cylinder_part(scene, objects, "pixel-q03-r8-i02-round-table-top", 0.94, 0.12, (1.25, 1.00, 0.55), metal, "table_surface", "photo_supported_furniture")
    _add_cylinder_part(scene, objects, "pixel-q03-r8-i02-round-table-pedestal", 0.36, 0.72, (1.25, 0.52, 0.55), _shade(metal, 0.68), "table_structure", "photo_supported_furniture")
    _add_part(scene, objects, [], "pixel-q03-r8-i02-table-top-inlay", (0.72, 0.035, 0.56), (1.25, 1.08, 0.55), _mix(metal, lamp, 0.12), "table_surface_detail", "procedural_completion", grid=MICRO_VOXEL)

    # Add a second readable height tier to the photographed plant rather than
    # increasing the collision footprint of the room.
    for index, (x, y, z, width, depth, colour) in enumerate((
        (-3.95, 3.12, 0.46, 0.38, 0.24, plant), (-3.62, 3.36, 0.46, 0.46, 0.26, _mix(plant, window, 0.16)),
        (-3.28, 3.08, 0.46, 0.34, 0.22, _shade(plant, 0.78)), (-3.52, 3.62, 0.46, 0.30, 0.20, plant),
    )):
        _add_part(scene, objects, [], f"pixel-q03-r8-i02-plant-high-leaf-{index}", (width, 0.18, depth), (x, y, z), colour, "vegetation_detail", "photo_supported_vegetation", grid=FURNITURE_VOXEL)
    _add_part(scene, objects, [], "pixel-q03-r8-i02-display-cabinet", (0.72, 2.15, 0.12), (4.28, 1.55, -2.15), dark, "display_furniture", "photo_supported_furniture", grid=FURNITURE_VOXEL)
    for row in range(3):
        for column in range(2):
            _add_part(scene, objects, [], f"pixel-q03-r8-i02-display-cabinet-light-{row}-{column}", (0.24, 0.16, 0.025), (4.12 + column * 0.30, 0.86 + row * 0.48, -2.08), _mix(window, lamp, 0.22), "display_detail", "photo_supported_furniture", grid=MICRO_VOXEL)


def _add_v12_corridor_details(scene: trimesh.Scene, objects: list[dict[str, object]], roles: dict[str, list[int]]) -> None:
    wall, floor, trim, wood = roles["wall"], roles["floor"], roles["trim"], roles["wood"]
    window, lamp, dark, accent = roles["window"], roles["lamp"], roles["dark"], roles["accent"]
    # I01 anchor: tile rhythm, ceiling downlights, continuous dark window
    # mullions and the near wooden door are all visible in the source.
    for index, z in enumerate((5.15, 3.90, 2.65, 1.40, 0.15, -1.10, -2.35, -3.60, -4.85, -6.10, -7.35, -8.60)):
        _add_part(scene, objects, [], f"pixel-q03-r8-i01-floor-tile-cross-{index}", (4.24, 0.025, 0.025), (0.0, 0.17, z), trim, "floor_tile_detail", "photo_supported_floor", grid=MICRO_VOXEL)
    for index, x in enumerate((-1.42, -0.02, 1.38)):
        _add_part(scene, objects, [], f"pixel-q03-r8-i01-floor-tile-long-{index}", (0.025, 0.025, 15.15), (x, 0.17, -1.50), trim, "floor_tile_detail", "photo_supported_floor", grid=MICRO_VOXEL)
    for index, z in enumerate((4.30, 2.20, 0.10, -2.00, -4.20, -6.40, -8.50)):
        _add_part(scene, objects, [], f"pixel-q03-r8-i01-ceiling-recess-{index}", (0.62, 0.05, 0.30), (0.0, 3.67, z), dark, "ceiling_light_structure", "photo_supported_ceiling", grid=FURNITURE_VOXEL)
        _add_part(scene, objects, [], f"pixel-q03-r8-i01-ceiling-light-{index}", (0.42, 0.035, 0.18), (0.0, 3.61, z), lamp, "warm_light_accent", "photo_supported_ceiling", grid=MICRO_VOXEL)
    _add_part(scene, objects, [], "pixel-q03-r8-i01-right-wainscot", (0.05, 0.54, 15.10), (2.34, 0.68, -1.50), _mix(wall, trim, 0.10), "wall_surface_detail", "photo_supported_wall", grid=FURNITURE_VOXEL)
    for door_index, z in enumerate((3.50, 0.0, -3.50, -7.0)):
        _add_pattern_yz(
            scene, objects, f"pixel-q03-r8-i01-door-panel-{door_index}",
            (".dddd.", "dggggd", "dgaagd", "dgaagd", "dggggd", ".dddd."),
            (2.29, 1.48, z), (0.18, 0.22), 0.025,
            {"a": wood, "d": trim, "g": _mix(wood, wall, 0.24)}, "door_surface_detail", "photo_supported_opening",
        )
        _add_part(scene, objects, [], f"pixel-q03-r8-i01-door-handle-{door_index}", (0.05, 0.10, 0.05), (2.27, 1.43, z - 0.18), lamp, "door_detail", "photo_supported_opening", grid=MICRO_VOXEL)
    for window_index, z in enumerate((3.50, 0.0, -3.50, -7.0)):
        _add_pattern_yz(
            scene, objects, f"pixel-q03-r8-i01-window-city-{window_index}",
            ("..dddd..", ".dabbad.", "dabbbbad", "dabbccad", "..dddd.."),
            (-2.28, 1.76, z), (0.18, 0.22), 0.025,
            {"a": window, "b": accent, "c": lamp, "d": dark}, "window_background_detail", "photo_palette_upper",
        )
    _add_pattern_xz(
        scene, objects, "pixel-q03-r8-i01-end-window-city",
        ("..dddd..", ".dabbad.", "dabccbad", "dabbccad", "..dddd.."),
        (0.0, 2.48, -9.28), (0.22, 0.18), 0.025,
        {"a": window, "b": accent, "c": lamp, "d": dark}, "window_background_detail", "photo_palette_upper",
    )


def _finalize_v12(
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
    supported: list[str],
    generated: list[str],
    *,
    template: SceneTemplate,
    engine: SceneEngine,
    basis: str,
) -> dict[str, object]:
    spec = {
        **_v02_spec(),
        "detail_pass": "v12-image-specific-indoor-detail-pass-6",
        "lighting_preset": PIXEL_V11_LIGHTING[profile],
        "shadow_policy": "single_soft_key_contact_shadows_for_v11_only",
        "emissive_policy": "semantic_light_sources_only_low_global_lift",
        "image_specific_policy": "named_photo_anchor_objects_and_surface_layers",
    }
    return _finalize_v02(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, profile, note, supported, generated,
        template=template,
        engine=engine,
        route_name="pixel_style_sample_v12",
        layout_version=PIXEL_V12_LAYOUT_VERSION,
        version="pixel-v12",
        provider_version="pixel-voxel-v12",
        pixel_spec=spec,
        layout_basis=basis,
    )


def build_pixel_living_v12(image_path: Path, output_dir: Path, scene_id: str = "pixel-v12-i02") -> dict[str, object]:
    scene, objects, collisions, palette, movement = _load_candidate_for_detail(image_path, output_dir, scene_id, build_pixel_living_v11)
    palette = _apply_v12_indoor_palette(scene, objects, "living_room", palette)
    _add_v12_living_details(scene, objects, palette["roles"])
    return _finalize_v12(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "living_room",
        "像素风 V12 I02 图像特定细节候选：按原图的白色组合沙发、暗色电视墙、低矮电视柜、圆形茶几、植物和展示柜建立细体素表面；保留 V11 光影和原碰撞范围，不宣称真实空间复原。",
        ["palette_cues", "window_and_opening_vocabulary", "furniture_colour_relationships", "photo_supported_tv_sofa_table_plant_anchors"],
        ["image_specific_furniture_surfaces", "tv_wall_and_console", "round_table_asset", "layered_vegetation", "collision_envelope"],
        template=SceneTemplate.indoor_walk, engine=SceneEngine.space, basis="q03_visual_index:i02:r8",
    )


def build_pixel_corridor_v12(image_path: Path, output_dir: Path, scene_id: str = "pixel-v12-i01") -> dict[str, object]:
    scene, objects, collisions, palette, movement = _load_candidate_for_detail(image_path, output_dir, scene_id, build_pixel_corridor_v11)
    palette = _apply_v12_indoor_palette(scene, objects, "corridor", palette)
    _add_v12_corridor_details(scene, objects, palette["roles"])
    return _finalize_v12(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "corridor",
        "像素风 V12 I01 图像特定细节候选：按原图的连续暗窗框、城市窗景、瓷砖地面、木门、门把手和顶灯建立细体素表面；保留 V11 光影和原碰撞范围，不宣称真实空间复原。",
        ["palette_cues", "corridor_direction", "window_and_opening_vocabulary", "photo_supported_tile_door_window_anchors"],
        ["image_specific_floor_tiles", "door_panels_and_handles", "window_city_layers", "ceiling_lights", "collision_envelope"],
        template=SceneTemplate.indoor_walk, engine=SceneEngine.space, basis="q03_visual_index:i01:r8",
    )


def _build_v12_from_v11(
    image_path: Path,
    output_dir: Path,
    scene_id: str,
    builder,
    profile: str,
    template: SceneTemplate,
    engine: SceneEngine,
    basis: str,
    note: str,
    supported: list[str],
    generated: list[str],
) -> dict[str, object]:
    scene, objects, collisions, palette, movement = _load_candidate_for_detail(image_path, output_dir, scene_id, builder)
    return _finalize_v12(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, profile, note, supported, generated,
        template=template, engine=engine, basis=basis,
    )


def build_pixel_nature_v09(image_path: Path, output_dir: Path, scene_id: str = "pixel-v12-n01") -> dict[str, object]:
    return _build_v12_from_v11(image_path, output_dir, scene_id, build_pixel_nature_v08, "snow_mountain", SceneTemplate.landscape_journey, SceneEngine.terrain, "q03_visual_index:n01:r8", "像素风 V12 自然同步候选：保留 V11 冷日光与现有近中远分层，待自然图像特定细节轮次补充山脊和雪石资产。", ["palette_cues", "near_ground_colour", "horizon_depth_order"], ["start_camera_layers", "material_contrast", "cool_daylight", "collision_envelope"])


def build_pixel_street_v11(image_path: Path, output_dir: Path, scene_id: str = "pixel-v12-s01") -> dict[str, object]:
    return _build_v12_from_v11(image_path, output_dir, scene_id, build_pixel_street_v10, "street", SceneTemplate.street_descent, SceneEngine.street, "q03_visual_index:s01:r8", "像素风 V12 街道同步候选：保留 V11 柔和日光、道路标线和对象分离，待街道图像特定细节轮次补充人车树资产。", ["palette_cues", "road_direction", "foreground_object_separation"], ["start_camera_layers", "material_contrast", "soft_daylight", "collision_envelope"])


def build_pixel_building_v11(image_path: Path, output_dir: Path, scene_id: str = "pixel-v12-b01") -> dict[str, object]:
    return _build_v12_from_v11(image_path, output_dir, scene_id, build_pixel_building_v10, "facade", SceneTemplate.facade_flight, SceneEngine.facade, "q03_visual_index:b01:r8", "像素风 V12 建筑同步候选：保留 V11 蓝调光影、窗格和前景线，待建筑图像特定细节轮次补充立面材质和服务层。", ["palette_cues", "facade_outline", "window_line_and_foreground_lines"], ["start_camera_layers", "material_contrast", "blue_hour_light", "collision_envelope"])


# Q03 r9 is a focused I02 asset pass.  It does not add a new scene template:
# it takes the r8 living-room candidate, fixes the coffee-table material role,
# and adds the four high-value source anchors that were still too flat in the
# screenshot: sectional upholstery, round tabletop, vertical blinds and the
# TV/desk/cabinet surface vocabulary.  No new collision envelope is created.
PIXEL_V13_LAYOUT_VERSION = "pixel-v13-i02-semantic-asset-pass-7"


def _finalize_v13(
    image_path: Path,
    output_dir: Path,
    scene_id: str,
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    collisions: list[CollisionBox],
    movement: MovementProfile,
    palette: dict[str, object],
    note: str,
    supported: list[str],
    generated: list[str],
) -> dict[str, object]:
    spec = {
        **_v02_spec(),
        "detail_pass": "v13-i02-semantic-asset-pass-7",
        "lighting_preset": PIXEL_V11_LIGHTING["living_room"],
        "shadow_policy": "single_soft_key_contact_shadows_for_v11_only",
        "emissive_policy": "semantic_light_sources_only_low_global_lift",
        "image_specific_policy": "i02_source_anchors_split_into_four_readable_asset_layers",
    }
    return _finalize_v02(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "living_room", note,
        supported, generated,
        template=SceneTemplate.indoor_walk,
        engine=SceneEngine.space,
        route_name="pixel_style_sample_v13",
        layout_version=PIXEL_V13_LAYOUT_VERSION,
        version="pixel-v13",
        provider_version="pixel-voxel-v13",
        pixel_spec=spec,
        layout_basis="q03_visual_index:i02:r9",
    )


def build_pixel_living_v13(image_path: Path, output_dir: Path, scene_id: str = "pixel-q03-r9-i02") -> dict[str, object]:
    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_living_v12
    )
    palette = _apply_v12_indoor_palette(scene, objects, "living_room", palette)
    roles = palette["roles"]
    wall, sofa, wood = roles["wall"], roles["sofa"], roles["wood"]
    trim, window, plant, lamp = roles["trim"], roles["window"], roles["plant"], roles["lamp"]
    dark, accent, metal = roles["dark"], roles["accent"], roles["metal"]

    # Upholstery pass: use two shade bands and authored pillow motifs so the
    # sectional reads as a white fabric object instead of one pale cuboid.
    sofa_shadow = _shade(sofa, 0.68)
    pillow = _mix(sofa, accent, 0.34)
    for index, x in enumerate((-2.76, -1.42)):
        _add_part(scene, objects, [], f"pixel-q03-r9-i02-sectional-front-rail-{index}", (1.18, 0.08, 0.06), (x, 0.62, -1.38), sofa_shadow, "upholstery_edge", "photo_supported_furniture", grid=MICRO_VOXEL)
        _add_pattern_xz(
            scene, objects, f"pixel-q03-r9-i02-sectional-throw-{index}",
            (".aaaa.", "aabbba", "abccba", ".aaaa."),
            (x, 1.36, -1.39), (0.16, 0.14), 0.035,
            {"a": pillow, "b": _mix(pillow, trim, 0.22), "c": accent},
            "upholstery_pattern", "photo_supported_furniture",
        )
    _add_part(scene, objects, [], "pixel-q03-r9-i02-sectional-chaise-edge", (0.06, 0.78, 1.28), (-0.22, 0.78, -2.12), trim, "upholstery_structure", "photo_supported_furniture", grid=FURNITURE_VOXEL)

    # The octagonal table already supplies the round silhouette.  Add a
    # horizontal pixel inlay on its top and a stepped pedestal highlight so
    # its material reads as metal/glass rather than another wood block.
    _add_pattern_xy(
        scene, objects, "pixel-q03-r9-i02-round-table-inlay",
        (".aaaa.", "abb bba".replace(" ", ""), "abccba", ".aaaa."),
        (1.25, 1.08, 0.55), (0.18, 0.14), 0.025,
        {"a": _mix(metal, window, 0.30), "b": metal, "c": _mix(metal, lamp, 0.34)},
        "table_surface_detail", "photo_supported_furniture",
    )
    _add_part(scene, objects, [], "pixel-q03-r9-i02-round-table-pedestal-highlight", (0.16, 0.48, 0.16), (1.25, 0.58, 0.55), _mix(metal, window, 0.24), "table_structure_detail", "photo_supported_furniture", grid=MICRO_VOXEL)

    # The source window is covered by vertical blinds.  These thin repeated
    # elements make the opening read as a real interior surface and preserve
    # the skyline behind it.
    for index, x in enumerate((0.34, 0.78, 1.22, 1.66, 2.10, 2.54, 2.98, 3.30)):
        _add_part(scene, objects, [], f"pixel-q03-r9-i02-window-blind-{index}", (0.07, 2.05, 0.035), (x, 2.52, -6.38), _mix(wall, window, 0.18), "opening_surface_detail", "photo_supported_opening", grid=MICRO_VOXEL)

    # Desk/monitor and display cabinet details complete the right-side source
    # vocabulary without claiming that unseen furniture was recovered.
    _add_part(scene, objects, [], "pixel-q03-r9-i02-workstation-top", (1.34, 0.10, 0.42), (3.05, 1.24, -3.86), wood, "workstation_surface", "photo_supported_furniture", grid=FURNITURE_VOXEL)
    _add_part(scene, objects, [], "pixel-q03-r9-i02-workstation-monitor", (0.82, 0.72, 0.08), (3.24, 1.78, -3.94), dark, "display_surface", "photo_supported_object", grid=FURNITURE_VOXEL)
    _add_pattern_xz(
        scene, objects, "pixel-q03-r9-i02-workstation-screen",
        (".bbbb.", "baaaab", "baccab", ".bbbb."),
        (3.24, 1.78, -3.88), (0.12, 0.10), 0.025,
        {"a": window, "b": trim, "c": lamp}, "display_surface_detail", "photo_supported_object",
    )
    _add_part(scene, objects, [], "pixel-q03-r9-i02-workstation-keyboard", (0.58, 0.04, 0.20), (3.18, 1.31, -3.68), metal, "workstation_detail", "procedural_completion", grid=MICRO_VOXEL)
    for row in range(3):
        for column in range(2):
            _add_part(scene, objects, [], f"pixel-q03-r9-i02-cabinet-pane-{row}-{column}", (0.22, 0.22, 0.025), (4.18, 0.92 + row * 0.50, -2.08), _mix(window, lamp, 0.18 + column * 0.08), "display_cabinet_detail", "photo_supported_furniture", grid=MICRO_VOXEL)

    # Add a pot rim and directional leaf clusters to the tall plant; the
    # foliage remains render-only and does not enlarge the walkable obstacle.
    _add_part(scene, objects, [], "pixel-q03-r9-i02-plant-pot-rim", (0.78, 0.08, 0.78), (-3.55, 0.82, 0.45), trim, "vegetation_structure", "photo_supported_vegetation", grid=FURNITURE_VOXEL)
    for index, (x, y, z, colour) in enumerate((
        (-4.15, 3.35, 0.48, plant), (-3.84, 3.68, 0.48, _mix(plant, window, 0.18)),
        (-3.42, 3.44, 0.48, _shade(plant, 0.78)), (-3.05, 3.74, 0.48, plant),
    )):
        _add_part(scene, objects, [], f"pixel-q03-r9-i02-plant-leaf-cluster-{index}", (0.42, 0.20, 0.24), (x, y, z), colour, "vegetation_detail", "photo_supported_vegetation", grid=FURNITURE_VOXEL)

    return _finalize_v13(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette,
        "像素风 V13 I02 语义资产候选：将原图白色组合沙发、圆形茶几、垂直百叶窗、电视墙、工作台和高植株拆成轮廓、分件、表面图案和局部高光；继承 V11 光影和 V12 碰撞，仍不宣称真实空间复原。",
        ["palette_cues", "window_and_opening_vocabulary", "furniture_colour_relationships", "photo_supported_tv_sofa_table_plant_anchors"],
        ["semantic_upholstery_layers", "round_table_material_layers", "window_blinds", "workstation_and_cabinet", "layered_vegetation", "collision_envelope"],
    )


# Q03 r10 is a targeted correction based on the r9 screenshot.  The TV panel
# was too close to the back wall and could be hidden by coplanar surfaces;
# this pass moves the display and its material layers into a deterministic
# front plane.  It also increases the contrast of the sofa patterns, table
# inlay and rug boundary.  The change is intentionally limited to I02.
PIXEL_V14_LAYOUT_VERSION = "pixel-v14-i02-material-readability-pass-8"


def _finalize_v14(
    image_path: Path,
    output_dir: Path,
    scene_id: str,
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    collisions: list[CollisionBox],
    movement: MovementProfile,
    palette: dict[str, object],
) -> dict[str, object]:
    spec = {
        **_v02_spec(),
        "detail_pass": "v14-i02-material-readability-pass-8",
        "lighting_preset": PIXEL_V11_LIGHTING["living_room"],
        "shadow_policy": "single_soft_key_contact_shadows_for_v11_only",
        "emissive_policy": "semantic_light_sources_only_low_global_lift",
        "image_specific_policy": "i02_anchor_layers_depth_separated_and_contrast_checked",
    }
    return _finalize_v02(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "living_room",
        "像素风 V14 I02 材质可读性候选：修正电视墙表面遮挡并强化电视柜、组合沙发、抱枕、圆桌、百叶窗、地毯边界与植物的有限色阶；继承 V13 碰撞和室内暖窗光，仍不宣称真实空间复原。",
        ["palette_cues", "window_and_opening_vocabulary", "furniture_colour_relationships", "photo_supported_tv_sofa_table_plant_anchors"],
        ["depth_separated_tv_wall", "semantic_upholstery_layers", "round_table_material_layers", "window_blinds", "rug_boundary", "layered_vegetation", "collision_envelope"],
        template=SceneTemplate.indoor_walk,
        engine=SceneEngine.space,
        route_name="pixel_style_sample_v14",
        layout_version=PIXEL_V14_LAYOUT_VERSION,
        version="pixel-v14",
        provider_version="pixel-voxel-v14",
        pixel_spec=spec,
        layout_basis="q03_visual_index:i02:r10",
    )


def build_pixel_living_v14(image_path: Path, output_dir: Path, scene_id: str = "pixel-q03-r10-i02") -> dict[str, object]:
    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_living_v13
    )
    palette = _apply_v12_indoor_palette(scene, objects, "living_room", palette)
    roles = palette["roles"]
    wall, floor, sofa, wood = roles["wall"], roles["floor"], roles["sofa"], roles["wood"]
    trim, window, plant, lamp = roles["trim"], roles["window"], roles["plant"], roles["lamp"]
    dark, accent, metal = roles["dark"], roles["accent"], roles["metal"]

    # Depth-separated TV wall: all screen layers sit clearly in front of the
    # back wall, while the adjacent window remains unobstructed.
    _add_part(scene, objects, [], "pixel-q03-r10-i02-tv-screen-front", (2.52, 1.58, 0.10), (-2.58, 2.04, -6.22), dark, "display_surface", "photo_supported_object", grid=FURNITURE_VOXEL)
    for index, (extents, centre) in enumerate((
        ((2.72, 0.08, 0.08), (-2.58, 2.88, -6.15)),
        ((2.72, 0.08, 0.08), (-2.58, 1.20, -6.15)),
        ((0.08, 1.74, 0.08), (-3.96, 2.04, -6.15)),
        ((0.08, 1.74, 0.08), (-1.20, 2.04, -6.15)),
    )):
        _add_part(scene, objects, [], f"pixel-q03-r10-i02-tv-screen-frame-{index}", extents, centre, wood, "display_frame", "photo_supported_object", grid=MICRO_VOXEL)
    _add_pattern_xz(
        scene, objects, "pixel-q03-r10-i02-tv-screen-pixels",
        ("..bbbb..", ".baaaab.", "baacccab", "baacccab", ".baaaab.", "..bbbb.."),
        (-2.58, 2.04, -6.13), (0.22, 0.19), 0.025,
        {"a": accent, "b": window, "c": lamp}, "display_surface_detail", "photo_supported_object",
    )
    _add_part(scene, objects, [], "pixel-q03-r10-i02-media-console-front", (3.22, 0.50, 0.52), (-2.58, 0.48, -5.90), wood, "media_console", "photo_supported_furniture", grid=FURNITURE_VOXEL)
    for index, x in enumerate((-3.65, -2.58, -1.51)):
        _add_part(scene, objects, [], f"pixel-q03-r10-i02-media-console-drawer-{index}", (0.74, 0.16, 0.035), (x, 0.55, -5.62), _mix(wood, trim, 0.30), "media_console_detail", "photo_supported_furniture", grid=MICRO_VOXEL)
    for index, x in enumerate((-1.22, -0.94, -0.66)):
        _add_part(scene, objects, [], f"pixel-q03-r10-i02-tv-wall-slat-{index}", (0.12, 2.00, 0.08), (x, 2.02, -6.08), _mix(wood, wall, 0.20), "wall_surface_detail", "photo_supported_wall", grid=FURNITURE_VOXEL)

    # Stronger upholstery pattern with dark piping and one blue accent pillow.
    pillow = _mix(sofa, accent, 0.45)
    for index, x in enumerate((-2.78, -1.40)):
        _add_part(scene, objects, [], f"pixel-q03-r10-i02-sofa-piping-{index}", (1.20, 0.05, 0.06), (x, 1.06, -1.39), trim, "upholstery_edge", "photo_supported_furniture", grid=MICRO_VOXEL)
        _add_pattern_xz(
            scene, objects, f"pixel-q03-r10-i02-sofa-pillow-{index}",
            (".aaaaaa.", "abbbbbba", "abccccba", "abccccba", ".aaaaaa."),
            (x, 1.42, -1.40), (0.18, 0.15), 0.045,
            {"a": sofa, "b": pillow, "c": accent}, "upholstery_pattern", "photo_supported_furniture",
        )
        # The sofa's front face is closer to the camera than the inherited
        # cushion layers.  Keep this duplicate-free front marker slightly
        # forward so the semantic pillow motif cannot be hidden by coplanar
        # upholstery geometry in the GLB viewer.
        _add_pattern_xz(
            scene, objects, f"pixel-q03-r10-i02-sofa-front-pillow-{index}",
            (".aaaaaa.", "abbbbbba", "abccccba", "abccccba", ".aaaaaa."),
            (x, 1.42, -1.28), (0.18, 0.15), 0.035,
            {"a": sofa, "b": pillow, "c": accent}, "upholstery_front_detail", "photo_supported_furniture",
        )

    # Make the round table top read in the screenshot with a visible rim and
    # a small, high-contrast top motif; all layers remain above the old table.
    _add_cylinder_part(scene, objects, "pixel-q03-r10-i02-round-table-rim", 0.98, 0.07, (1.25, 1.10, 0.55), trim, "table_edge", "photo_supported_furniture")
    _add_pattern_xy(
        scene, objects, "pixel-q03-r10-i02-round-table-top-motif",
        (".aaaa.", "abb bba".replace(" ", ""), "abccba", ".aaaa."),
        (1.25, 1.15, 0.55), (0.18, 0.14), 0.025,
        {"a": _mix(metal, window, 0.42), "b": metal, "c": lamp}, "table_surface_detail", "photo_supported_furniture",
    )

    # A restrained rug border restores the light carpet/coffee-table grouping
    # visible in I02 without adding another collision object.
    rug_edge = _mix(sofa, floor, 0.35)
    for index, (extents, centre) in enumerate((
        ((4.42, 0.035, 0.06), (0.0, 0.23, -1.05)),
        ((4.42, 0.035, 0.06), (0.0, 0.23, 1.62)),
        ((0.06, 0.035, 2.66), (-2.20, 0.23, 0.28)),
        ((0.06, 0.035, 2.66), (2.20, 0.23, 0.28)),
    )):
        _add_part(scene, objects, [], f"pixel-q03-r10-i02-rug-border-{index}", extents, centre, rug_edge, "floor_surface_detail", "photo_supported_floor", grid=MICRO_VOXEL)

    # Increase the blind rhythm and foliage silhouette without changing the
    # room route or collision footprint.
    for index, x in enumerate((0.34, 0.78, 1.22, 1.66, 2.10, 2.54, 2.98, 3.30)):
        colour = window if index % 2 else _mix(wall, window, 0.16)
        _add_part(scene, objects, [], f"pixel-q03-r10-i02-window-blind-contrast-{index}", (0.065, 2.08, 0.04), (x, 2.52, -6.30), colour, "opening_surface_detail", "photo_supported_opening", grid=MICRO_VOXEL)
    for index, (x, y, z, colour) in enumerate((
        (-4.24, 3.25, 0.48, plant), (-3.92, 3.55, 0.48, _mix(plant, window, 0.22)),
        (-3.58, 3.30, 0.48, _shade(plant, 0.72)), (-3.20, 3.62, 0.48, plant),
        (-2.98, 3.16, 0.48, _mix(plant, lamp, 0.08)),
    )):
        _add_part(scene, objects, [], f"pixel-q03-r10-i02-plant-hero-leaf-{index}", (0.40, 0.22, 0.24), (x, y, z), colour, "vegetation_detail", "photo_supported_vegetation", grid=FURNITURE_VOXEL)

    return _finalize_v14(image_path, output_dir, scene_id, scene, objects, collisions, movement, palette)


# Q03 r11 fixes a coordinate-plane mistake exposed by the r10 screenshot:
# several authored motifs were placed on horizontal X/Z planes even though
# the readable surfaces (TV, monitor and sofa backs) face the camera along
# Z.  This pass keeps the r10 layout and collision envelope, but adds the
# authored pixels to the actual camera-facing X/Y surfaces and splits the
# sofa into recognizable back/seat/front layers.
PIXEL_V15_LAYOUT_VERSION = "pixel-v15-i02-facing-surface-readability-pass-9"


def _finalize_v15(
    image_path: Path,
    output_dir: Path,
    scene_id: str,
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    collisions: list[CollisionBox],
    movement: MovementProfile,
    palette: dict[str, object],
) -> dict[str, object]:
    spec = {
        **_v02_spec(),
        "detail_pass": "v15-i02-facing-surface-readability-pass-9",
        "lighting_preset": PIXEL_V11_LIGHTING["living_room"],
        "shadow_policy": "single_soft_key_contact_shadows_for_v11_only",
        "emissive_policy": "semantic_light_sources_only_low_global_lift",
        "image_specific_policy": "camera_facing_xy_surface_layers_and_split_upholstery",
    }
    return _finalize_v02(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "living_room",
        "像素风 V15 I02 正面材质可读性候选：修正电视、显示器和沙发纹理的朝向平面，补充分件化靠垫、坐垫、前沿、电视柜把手与地毯纹理；继承 V14 碰撞和暖窗光，仍不宣称真实空间复原。",
        ["palette_cues", "window_and_opening_vocabulary", "furniture_colour_relationships", "photo_supported_tv_sofa_table_plant_anchors"],
        ["camera_facing_surface_layers", "split_upholstery", "tv_and_monitor_pixel_surfaces", "console_hardware", "rug_surface_pattern", "collision_envelope"],
        template=SceneTemplate.indoor_walk,
        engine=SceneEngine.space,
        route_name="pixel_style_sample_v15",
        layout_version=PIXEL_V15_LAYOUT_VERSION,
        version="pixel-v15",
        provider_version="pixel-voxel-v15",
        pixel_spec=spec,
        layout_basis="q03_visual_index:i02:r11",
    )


def build_pixel_living_v15(image_path: Path, output_dir: Path, scene_id: str = "pixel-q03-r11-i02") -> dict[str, object]:
    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_living_v14
    )
    palette = _apply_v12_indoor_palette(scene, objects, "living_room", palette)
    roles = palette["roles"]
    wall, floor, sofa, wood = roles["wall"], roles["floor"], roles["sofa"], roles["wood"]
    trim, window, plant, lamp = roles["trim"], roles["window"], roles["plant"], roles["lamp"]
    dark, accent, metal = roles["dark"], roles["accent"], roles["metal"]

    # The original r10 pillow motifs were authored on X/Z (horizontal)
    # planes.  Add the same authored vocabulary to the camera-facing X/Y
    # planes so the cushions read as upholstery from the start camera.
    pillow = _mix(sofa, accent, 0.46)
    pillow_shadow = _shade(sofa, 0.70)
    for index, x in enumerate((-2.78, -1.40)):
        _add_part(
            scene, objects, [], f"pixel-q03-r11-i02-sofa-back-cushion-{index}",
            (1.18, 0.62, 0.18), (x, 1.42, -1.70), sofa,
            "upholstery_structure", "photo_supported_furniture", grid=FURNITURE_VOXEL,
        )
        _add_pattern_xy(
            scene, objects, f"pixel-q03-r11-i02-sofa-back-pattern-{index}",
            (".aaaaaa.", "abbbbbba", "abccccba", "abccccba", ".aaaaaa."),
            (x, 1.42, -1.58), (0.16, 0.14), 0.035,
            {"a": sofa, "b": pillow, "c": accent},
            "upholstery_pattern", "photo_supported_furniture",
        )
        _add_part(
            scene, objects, [], f"pixel-q03-r11-i02-sofa-seat-front-{index}",
            (1.18, 0.38, 0.08), (x, 0.80, -0.92), pillow_shadow,
            "upholstery_surface", "photo_supported_furniture", grid=FURNITURE_VOXEL,
        )
        _add_pattern_xy(
            scene, objects, f"pixel-q03-r11-i02-sofa-seat-front-detail-{index}",
            (".aaaaaa.", "abbbbbba", "abbbbbba", ".aaaaaa."),
            (x, 0.80, -0.86), (0.16, 0.10), 0.03,
            {"a": pillow_shadow, "b": sofa},
            "upholstery_front_detail", "photo_supported_furniture",
        )

    # A blocky arm and a lower base band make the sectional silhouette read
    # from the side as well as from the start view without changing collision.
    _add_part(
        scene, objects, [], "pixel-q03-r11-i02-sofa-front-base", (3.48, 0.18, 0.12),
        (-2.08, 0.55, -0.89), _shade(sofa, 0.82),
        "upholstery_structure", "photo_supported_furniture", grid=FURNITURE_VOXEL,
    )
    _add_part(
        scene, objects, [], "pixel-q03-r11-i02-sofa-chaise-back", (0.18, 1.08, 1.22),
        (-0.20, 1.24, -2.02), _shade(sofa, 0.90),
        "upholstery_structure", "photo_supported_furniture", grid=FURNITURE_VOXEL,
    )

    # Correctly face the TV and monitor motifs toward the viewer.  The older
    # r10 X/Z motifs remain in the artifact for comparison, while these
    # depth-separated layers are the active readable surfaces.
    _add_pattern_xy(
        scene, objects, "pixel-q03-r11-i02-tv-front-pixels",
        ("..bbbbbbbb..", ".baaaaaaaab.", "baacccccaab", "baacccccaab", ".baaaaaaaab.", "..bbbbbbbb.."),
        (-2.58, 2.04, -6.05), (0.18, 0.18), 0.035,
        {"a": accent, "b": window, "c": lamp},
        "display_surface_detail", "photo_supported_object",
    )
    _add_pattern_xy(
        scene, objects, "pixel-q03-r11-i02-monitor-front-pixels",
        (".bbbbbb.", "baaaaab", "baaccab", "baaaaab", ".bbbbbb."),
        (3.24, 1.78, -3.82), (0.11, 0.11), 0.03,
        {"a": window, "b": trim, "c": lamp},
        "display_surface_detail", "photo_supported_object",
    )
    for index, x in enumerate((-3.65, -2.58, -1.51)):
        _add_part(
            scene, objects, [], f"pixel-q03-r11-i02-console-handle-{index}",
            (0.08, 0.04, 0.04), (x, 0.55, -5.57), metal,
            "media_console_detail", "photo_supported_furniture", grid=MICRO_VOXEL,
        )

    # Give the photographed carpet/table grouping a restrained authored
    # surface rhythm.  It is render-only and does not create new obstacles.
    rug_light = _mix(sofa, floor, 0.30)
    rug_shadow = _mix(rug_light, trim, 0.18)
    _add_pattern_xz(
        scene, objects, "pixel-q03-r11-i02-rug-weave",
        ("aabbbbbbaa", "abbbbbbbba", "bbbbbbbbbb", "abbbbbbbba", "aabbbbbbaa"),
        (0.0, 0.28, 0.28), (0.30, 0.24), 0.025,
        {"a": rug_shadow, "b": rug_light},
        "floor_surface_detail", "photo_supported_floor",
    )

    # Add a few directional leaf voxels, not random noise, to strengthen the
    # plant silhouette against the bright window while keeping foliage out of
    # collision data.
    for index, (x, y, z, sx, sy, sz, colour) in enumerate((
        (-4.30, 2.76, 0.44, 0.22, 0.52, 0.18, plant),
        (-4.00, 3.10, 0.44, 0.34, 0.22, 0.18, _mix(plant, window, 0.18)),
        (-3.70, 3.48, 0.44, 0.22, 0.48, 0.18, _shade(plant, 0.75)),
        (-3.28, 3.14, 0.44, 0.36, 0.22, 0.18, plant),
        (-3.02, 3.58, 0.44, 0.22, 0.38, 0.18, _mix(plant, lamp, 0.08)),
    )):
        _add_part(
            scene, objects, [], f"pixel-q03-r11-i02-plant-directional-leaf-{index}",
            (sx, sy, sz), (x, y, z), colour,
            "vegetation_detail", "photo_supported_vegetation", grid=FURNITURE_VOXEL,
        )

    return _finalize_v15(image_path, output_dir, scene_id, scene, objects, collisions, movement, palette)


# Q04 collision correction: V15's outer z bound (5.10) stopped the camera
# before the expanded front-wall collision (5.20).  Keep the same visible
# geometry and character radius, but move the outer bound beyond the wall so a
# sustained W test exercises the actual collision box first.
PIXEL_V16_LAYOUT_VERSION = "pixel-v16-i02-collision-boundary-pass-10"


def _finalize_v16(
    image_path: Path,
    output_dir: Path,
    scene_id: str,
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    collisions: list[CollisionBox],
    movement: MovementProfile,
    palette: dict[str, object],
) -> dict[str, object]:
    spec = {
        **_v02_spec(),
        "detail_pass": "v16-i02-collision-boundary-pass-10",
        "lighting_preset": PIXEL_V11_LIGHTING["living_room"],
        "shadow_policy": "single_soft_key_contact_shadows_for_v11_only",
        "emissive_policy": "semantic_light_sources_only_low_global_lift",
        "image_specific_policy": "camera_facing_xy_surface_layers_and_split_upholstery",
        "collision_policy": "front_wall_box_precedes_outer_bounds_for_q04_hold_test",
    }
    return _finalize_v02(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "living_room",
        "像素风 V16 I02 Q04碰撞边界候选：保持 V15 可见细节与碰撞体，修正外边界早于前墙碰撞生效的问题；仍不宣称真实空间复原。",
        ["palette_cues", "window_and_opening_vocabulary", "furniture_colour_relationships", "photo_supported_tv_sofa_table_plant_anchors"],
        ["camera_facing_surface_layers", "split_upholstery", "tv_and_monitor_pixel_surfaces", "console_hardware", "rug_surface_pattern", "collision_envelope", "q04_collision_boundary"],
        template=SceneTemplate.indoor_walk,
        engine=SceneEngine.space,
        route_name="pixel_style_sample_v16",
        layout_version=PIXEL_V16_LAYOUT_VERSION,
        version="pixel-v16",
        provider_version="pixel-voxel-v16",
        pixel_spec=spec,
        layout_basis="q03_visual_index:i02:r11+q04_collision_boundary",
    )


def build_pixel_living_v16(image_path: Path, output_dir: Path, scene_id: str = "pixel-q04-i02-v16") -> dict[str, object]:
    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_living_v15
    )
    movement.bounds["z"][1] = 5.40
    return _finalize_v16(image_path, output_dir, scene_id, scene, objects, collisions, movement, palette)


# Q03 corridor refinement after the V12 baseline.  V12 established the I01
# corridor vocabulary, but the first screenshots still read as repeated flat
# panels.  V17 adds authored, camera-facing surface layers and long-axis scale
# cues while preserving V12's collision and movement contract.  This remains
# an isolated candidate; it does not replace the default generator.
PIXEL_V17_LAYOUT_VERSION = "pixel-v17-i01-corridor-material-readability-pass-11"


def _finalize_v17_corridor(
    image_path: Path,
    output_dir: Path,
    scene_id: str,
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    collisions: list[CollisionBox],
    movement: MovementProfile,
    palette: dict[str, object],
) -> dict[str, object]:
    spec = {
        **_v02_spec(),
        "detail_pass": "v17-i01-corridor-material-readability-pass-11",
        "lighting_preset": PIXEL_V11_LIGHTING["corridor"],
        "shadow_policy": "single_soft_key_contact_shadows_for_v11_only",
        "emissive_policy": "semantic_light_sources_only_low_global_lift",
        "image_specific_policy": "camera_facing_window_door_end_wall_layers_and_corridor_scale_cues",
    }
    return _finalize_v02(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "corridor",
        "像素风 V17 I01 走廊材质可读性候选：在 V12 图像特定窗门、地面和顶灯基础上补充实际朝向的窗外层次、门板分件、地砖反射节奏、灯具结构与尽端透视；保持原碰撞范围，不宣称真实空间复原。",
        ["palette_cues", "corridor_direction", "window_and_opening_vocabulary", "photo_supported_tile_door_window_anchors"],
        ["camera_facing_window_layers", "door_panel_material_layers", "tile_surface_rhythm", "ceiling_fixture_layers", "end_wall_perspective", "collision_envelope"],
        template=SceneTemplate.indoor_walk,
        engine=SceneEngine.space,
        route_name="pixel_style_sample_v17",
        layout_version=PIXEL_V17_LAYOUT_VERSION,
        version="pixel-v17",
        provider_version="pixel-voxel-v17",
        pixel_spec=spec,
        layout_basis="q03_visual_index:i01:r17",
    )


def build_pixel_corridor_v17(image_path: Path, output_dir: Path, scene_id: str = "pixel-q03-r17-i01") -> dict[str, object]:
    """Build the isolated Q03 I01 corridor readability candidate."""

    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_corridor_v12
    )
    palette = _apply_v12_indoor_palette(scene, objects, "corridor", palette)
    roles = palette["roles"]
    wall, floor, trim, wood = roles["wall"], roles["floor"], roles["trim"], roles["wood"]
    window, lamp, dark, accent = roles["window"], roles["lamp"], roles["dark"], roles["accent"]

    # The source corridor has a repeated window wall on the left.  These
    # shallow Y/Z-facing layers make each bay read as glass, mullion and a
    # distant city strip instead of a single blue slab.
    for window_index, z in enumerate((3.50, 0.0, -3.50, -7.0)):
        _add_pattern_yz(
            scene, objects, f"pixel-q03-r17-i01-window-bay-{window_index}",
            ("..dddd..", ".dabbad.", "dabccbad", "dabbccad", ".dabbad.", "..dddd.."),
            (-2.275, 1.78, z), (0.17, 0.20), 0.028,
            {"a": window, "b": _mix(window, accent, 0.36), "c": _mix(window, lamp, 0.20), "d": trim},
            "window_surface_detail", "photo_supported_opening",
        )
        # Alternating vertical mullions are deliberately structural and
        # remain render-only; the original window wall collision is unchanged.
        for mullion_index, offset in enumerate((-0.42, 0.0, 0.42)):
            _add_part(
                scene, objects, [], f"pixel-q03-r17-i01-window-mullion-{window_index}-{mullion_index}",
                (0.07, 2.56, 0.06), (-2.235, 1.42, z + offset), trim,
                "window_frame_detail", "photo_supported_opening", grid=MICRO_VOXEL,
            )
        for skyline_index, (width, height, x_offset, y) in enumerate((
            (0.22, 0.42, -0.28, 1.35), (0.34, 0.68, 0.02, 1.48), (0.18, 0.30, 0.28, 1.28),
        )):
            _add_part(
                scene, objects, [], f"pixel-q03-r17-i01-window-skyline-{window_index}-{skyline_index}",
                (0.025, height, width), (-2.245, y + height * 0.5, z + x_offset),
                _mix(dark, window, 0.38), "window_background_detail", "photo_palette_upper", grid=MICRO_VOXEL,
            )

    # Door faces are split into inset, trim, kick plate and hardware.  The
    # source provides a strong wooden opening cue; repeating it along the
    # right wall keeps the corridor directional without adding fake doors to
    # the left window side.
    for door_index, z in enumerate((3.50, 0.0, -3.50, -7.0)):
        _add_part(
            scene, objects, [], f"pixel-q03-r17-i01-door-slab-{door_index}",
            (0.045, 2.44, 0.82), (2.275, 1.43, z), _mix(wood, dark, 0.08),
            "door_surface_detail", "photo_supported_opening", grid=FURNITURE_VOXEL,
        )
        for band_index, y in enumerate((0.42, 0.74, 2.22, 2.62)):
            _add_part(
                scene, objects, [], f"pixel-q03-r17-i01-door-trim-{door_index}-{band_index}",
                (0.035, 0.055, 0.78 if band_index < 2 else 0.84), (2.245, y, z),
                _mix(wood, trim, 0.28), "door_surface_detail", "photo_supported_opening", grid=MICRO_VOXEL,
            )
        _add_part(
            scene, objects, [], f"pixel-q03-r17-i01-door-kickplate-{door_index}",
            (0.035, 0.23, 0.68), (2.235, 0.47, z), _mix(trim, wood, 0.18),
            "door_surface_detail", "photo_supported_opening", grid=MICRO_VOXEL,
        )
        _add_part(
            scene, objects, [], f"pixel-q03-r17-i01-door-handle-{door_index}",
            (0.08, 0.06, 0.06), (2.20, 1.43, z - 0.18), lamp,
            "door_hardware_detail", "photo_supported_opening", grid=MICRO_VOXEL,
        )

    # Tiled floor: the long seams from V12 remain, while these alternating
    # inset strips add perspective scale and a restrained reflected-window
    # rhythm.  They are shallow surface detail and do not alter walkability.
    for row_index, z in enumerate((4.55, 3.25, 1.95, 0.65, -0.65, -1.95, -3.25, -4.55, -5.85, -7.15, -8.35)):
        _add_part(
            scene, objects, [], f"pixel-q03-r17-i01-floor-cross-highlight-{row_index}",
            (4.12, 0.018, 0.035), (0.0, 0.205, z), _mix(floor, window, 0.12),
            "floor_tile_detail", "photo_supported_floor", grid=MICRO_VOXEL,
        )
        for column_index, x in enumerate((-1.42, -0.02, 1.38)):
            if (row_index + column_index) % 2 == 0:
                _add_part(
                    scene, objects, [], f"pixel-q03-r17-i01-floor-tile-reflection-{row_index}-{column_index}",
                    (0.72, 0.012, 0.38), (x, 0.218, z - 0.12), _mix(floor, window, 0.18),
                    "floor_surface_detail", "photo_palette_lower", grid=MICRO_VOXEL,
                )

    # Ceiling fixtures get a dark recess, a warm rectangular emitter and a
    # small cool edge so the light source reads as an object rather than a
    # repeated unstructured bright box.
    for light_index, z in enumerate((4.30, 2.20, 0.10, -2.00, -4.20, -6.40, -8.50)):
        _add_part(
            scene, objects, [], f"pixel-q03-r17-i01-ceiling-fixture-recess-{light_index}",
            (0.72, 0.045, 0.34), (0.0, 3.67, z), dark,
            "ceiling_light_structure", "photo_supported_ceiling", grid=FURNITURE_VOXEL,
        )
        _add_part(
            scene, objects, [], f"pixel-q03-r17-i01-ceiling-fixture-emitter-{light_index}",
            (0.48, 0.025, 0.18), (0.0, 3.61, z), lamp,
            "ceiling_light_detail", "photo_supported_ceiling", grid=MICRO_VOXEL,
        )
        _add_part(
            scene, objects, [], f"pixel-q03-r17-i01-ceiling-fixture-edge-{light_index}",
            (0.54, 0.018, 0.035), (0.0, 3.58, z - 0.12), _mix(lamp, window, 0.34),
            "ceiling_light_detail", "photo_supported_ceiling", grid=MICRO_VOXEL,
        )

    # Use the actual camera-facing X/Y plane for the far opening.  V12's
    # X/Z pattern was a useful diagnostic but did not read as a window from
    # the corridor camera; this layer restores the end-point perspective cue.
    _add_pattern_xy(
        scene, objects, "pixel-q03-r17-i01-end-wall-window",
        ("..dddddd..", ".dabbccad.", "dabbbbbbad", "dabccbbbad", "dabbbbbbad", ".dabbccad.", "..dddddd.."),
        (0.0, 2.48, -9.235), (0.20, 0.18), 0.028,
        {"a": window, "b": _mix(window, accent, 0.32), "c": _mix(window, lamp, 0.18), "d": trim},
        "window_background_detail", "photo_supported_opening",
    )
    for index, x in enumerate((-0.84, 0.0, 0.84)):
        _add_part(
            scene, objects, [], f"pixel-q03-r17-i01-end-window-mullion-{index}",
            (0.055, 1.62, 0.045), (x, 2.48, -9.20), trim,
            "window_frame_detail", "photo_supported_opening", grid=MICRO_VOXEL,
        )

    # A low baseboard on the window side and a narrow wall-marker band create
    # a continuous near/far scale cue without masking the source-supported
    # window and door surfaces.
    _add_part(
        scene, objects, [], "pixel-q03-r17-i01-left-baseboard-highlight",
        (0.045, 0.24, 15.10), (-2.275, 0.34, -1.50), _mix(trim, wall, 0.12),
        "wall_surface_detail", "photo_supported_wall", grid=FURNITURE_VOXEL,
    )
    for index, z in enumerate((4.30, 2.20, 0.10, -2.00, -4.20, -6.40, -8.50)):
        _add_part(
            scene, objects, [], f"pixel-q03-r17-i01-right-wall-marker-{index}",
            (0.035, 0.42, 0.52), (2.275, 2.40, z), _mix(wall, trim, 0.18),
            "wall_surface_detail", "procedural_completion", grid=FURNITURE_VOXEL,
        )

    return _finalize_v17_corridor(image_path, output_dir, scene_id, scene, objects, collisions, movement, palette)


# Q03's next rotation is N01.  The V12 nature candidate already separated
# sky, near ground, three ridge depths, fence and route-side rocks, but its
# large ridge faces still read as flat slabs in the GPU screenshot.  V18 adds
# authored snow facets and foreground scale cues to those existing layers.
# Collision data is inherited unchanged so this pass isolates visual quality.
PIXEL_V18_LAYOUT_VERSION = "pixel-v18-n01-mountain-surface-readability-pass-12"


def _finalize_v18_nature(
    image_path: Path,
    output_dir: Path,
    scene_id: str,
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    collisions: list[CollisionBox],
    movement: MovementProfile,
    palette: dict[str, object],
) -> dict[str, object]:
    spec = {
        **_v02_spec(),
        "detail_pass": "v18-n01-mountain-surface-readability-pass-12",
        "lighting_preset": PIXEL_V11_LIGHTING["snow_mountain"],
        "shadow_policy": "single_soft_key_contact_shadows_for_v11_only",
        "emissive_policy": "semantic_light_sources_only_low_global_lift",
        "image_specific_policy": "layered_mountain_facets_snow_fence_and_near_ground_scale_cues",
    }
    return _finalize_v02(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "snow_mountain",
        "像素风 V18 N01 山体表面可读性候选：在 V12 三层山脊、连续雪地、围栏和路线障碍基础上补充朝向相机的雪脊分面、阴影带、围栏网格和近景雪面尺度；保持碰撞范围，不把远山当作可进入地形。",
        ["palette_cues", "near_ground_colour", "horizon_depth_order", "photo_supported_snow_fence_and_mountain_layers"],
        ["layered_mountain_facets", "snow_shadow_strata", "fence_mesh_detail", "near_ground_scale_cues", "collision_envelope"],
        template=SceneTemplate.landscape_journey,
        engine=SceneEngine.terrain,
        route_name="pixel_style_sample_v18",
        layout_version=PIXEL_V18_LAYOUT_VERSION,
        version="pixel-v18",
        provider_version="pixel-voxel-v18",
        pixel_spec=spec,
        layout_basis="q03_visual_index:n01:r18",
    )


def build_pixel_nature_v18(image_path: Path, output_dir: Path, scene_id: str = "pixel-q03-r18-n01") -> dict[str, object]:
    """Build the isolated Q03 N01 mountain surface-readability candidate."""

    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_nature_v09
    )
    roles = palette["roles"]
    floor, wall = roles["floor"], roles["wall"]
    window, dark, accent = roles["window"], roles["dark"], roles["accent"]
    plant = roles["plant"]
    snow_light = _mix(window, [248, 250, 246], 0.52)
    snow_shadow = _mix(window, dark, 0.34)
    snow_blue = _mix(window, accent, 0.24)

    # The source mountain image is dominated by several separated ridges. Add
    # compact front-face mosaics rather than stretching one textured plane
    # across all depths.  Each pattern is a deliberate peak/snow/shadow motif.
    ridge_specs = (
        ("near", -10.0, 0.48, 2.72, 0.60),
        ("mid", -14.0, 0.36, 2.58, 0.48),
        ("far", -18.0, 0.25, 2.44, 0.36),
    )
    mountain_pattern = (
        "....dd....",
        "...dabb...",
        "..dabccbd..",
        ".dabbccbbd.",
        "dabbbbccbad",
        "ddddbbbbdd",
    )
    for ridge_name, center_z, front_offset, centre_y, scale in ridge_specs:
        for peak_index, (x, y_offset) in enumerate(((-5.4, 0.08), (-1.7, 0.18), (2.15, 0.0), (5.25, 0.12))):
            _add_pattern_xy(
                scene, objects, f"pixel-q03-r18-n01-{ridge_name}-peak-{peak_index}",
                mountain_pattern,
                (x, centre_y + y_offset, center_z + front_offset),
                (0.24 * scale, 0.18 * scale), 0.028,
                {"a": snow_light, "b": snow_blue, "c": _mix(snow_light, window, 0.20), "d": snow_shadow},
                "mountain_surface_detail", "photo_supported_horizon",
            )

        # Long, broken strata keep the mountain face directional and avoid a
        # uniform random-noise treatment.  They are render-only surface cues.
        for band_index, (y, width, colour) in enumerate((
            (1.72, 4.80, snow_shadow), (2.22, 3.45, snow_blue), (2.74, 5.40, _mix(snow_light, snow_blue, 0.26)),
        )):
            _add_part(
                scene, objects, [], f"pixel-q03-r18-n01-{ridge_name}-snow-strata-{band_index}",
                (width, 0.045, 0.035), (0.25 if band_index == 1 else -0.20, y, center_z + front_offset), colour,
                "mountain_surface_detail", "photo_palette_upper", grid=MICRO_VOXEL,
            )

    # Add readable stepped snowbanks near, but outside, the documented path.
    # Their positions provide foreground scale without creating new collision
    # obstacles or narrowing the walk route.
    for index, (x, z, width, height, colour) in enumerate((
        (-3.15, 3.00, 1.10, 0.22, snow_light), (3.25, 1.45, 1.28, 0.30, snow_blue),
        (-3.65, -0.85, 1.42, 0.26, _mix(snow_light, floor, 0.10)), (3.55, -3.40, 1.20, 0.22, snow_light),
        (-2.95, -5.95, 1.35, 0.30, snow_blue),
    )):
        _add_part(
            scene, objects, [], f"pixel-q03-r18-n01-snowbank-{index}",
            (width, height, 0.72), (x, 0.32 + height * 0.5, z), colour,
            "near_ground_detail", "photo_supported_near_ground", grid=FURNITURE_VOXEL,
        )
        _add_part(
            scene, objects, [], f"pixel-q03-r18-n01-snowbank-shadow-{index}",
            (width * 0.68, 0.035, 0.12), (x + 0.12, 0.50 + height, z - 0.30), snow_shadow,
            "near_ground_detail", "photo_palette_lower", grid=MICRO_VOXEL,
        )

    # The source has a wire fence across the foreground.  V12 had rails and
    # posts; V18 adds a sparse, regular mesh so it reads as a fence rather
    # than three floating bars.  It remains outside the central route and
    # render-only as in the earlier candidate.
    fence = _mix(dark, window, 0.24)
    for post_index, x in enumerate((-4.50, -3.00, -1.50, 0.0, 1.50, 3.00, 4.50)):
        for wire_index, y in enumerate((1.02, 1.34, 1.66)):
            _add_part(
                scene, objects, [], f"pixel-q03-r18-n01-fence-wire-{post_index}-{wire_index}",
                (1.38 if post_index < 6 else 0.72, 0.025, 0.025),
                (x + (0.69 if post_index < 6 else 0.0), y, 6.00), _mix(fence, snow_blue, 0.12),
                "foreground_fence_detail", "photo_supported_foreground_fence", grid=MICRO_VOXEL,
            )

    # Small ordered snow marks on the central route provide a pixel-art path
    # rhythm and reinforce the original image's tracked snow, without using a
    # full-photo projection or changing the ground plane.
    for index, z in enumerate((5.10, 4.25, 3.40, 2.55, 1.70, 0.85, 0.0, -0.85, -1.70, -2.55, -3.40, -4.25, -5.10, -5.95)):
        x = -0.42 if index % 2 else 0.32
        _add_part(
            scene, objects, [], f"pixel-q03-r18-n01-track-mark-{index}",
            (0.42, 0.025, 0.16), (x, 0.235, z), _mix(snow_shadow, floor, 0.28),
            "near_ground_detail", "photo_supported_near_ground", grid=MICRO_VOXEL,
        )

    return _finalize_v18_nature(image_path, output_dir, scene_id, scene, objects, collisions, movement, palette)


# Q05 targeted follow-up for the manually observed N01 edge penetration.  The
# V18 visual mesh stays unchanged; only the documented collision envelope of
# the right route-side rock receives a small safety margin.  This is narrower
# than changing the global character radius or movement bounds, and keeps the
# collision object visually identifiable in layout.json.
PIXEL_V21_LAYOUT_VERSION = "pixel-v21-n01-rock-collision-safety-pass-15"
PIXEL_V21_COLLISION_MARGIN = 0.08


def build_pixel_nature_v21(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r21-n01") -> dict[str, object]:
    """Build N01 V18 and add a targeted safety margin to the right rock."""

    payload = build_pixel_nature_v18(image_path, output_dir, scene_id)
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    target_id = "pixel-v03-rock-right"
    adjusted = False
    for box in collision.get("boxes", []):
        if box.get("box_id") != target_id:
            continue
        bounds = box["bounds"]
        bounds["x"] = [
            round(float(bounds["x"][0]) - PIXEL_V21_COLLISION_MARGIN, 4),
            round(float(bounds["x"][1]) + PIXEL_V21_COLLISION_MARGIN, 4),
        ]
        bounds["z"] = [
            round(float(bounds["z"][0]) - PIXEL_V21_COLLISION_MARGIN, 4),
            round(float(bounds["z"][1]) + PIXEL_V21_COLLISION_MARGIN, 4),
        ]
        box["label"] = "自然障碍简化体积（穿模安全余量 0.08）"
        adjusted = True
        break
    if not adjusted:
        raise ValueError(f"target collision box not found: {target_id}")

    layout_version = PIXEL_V21_LAYOUT_VERSION
    route_name = "pixel_style_sample_v21"
    detail_pass = "v21-n01-rock-collision-safety-pass-15"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_n01_targeted_collision_safety_margin"
    layout["pixel_spec"]["detail_pass"] = detail_pass
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + [
        "targeted_rock_collision_safety_margin"
    ]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version

    manifest["version"] = "pixel-v21"
    manifest["provider_version"] = "pixel-voxel-v21"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V21 N01 定向修复候选：保留 V18 的山体、雪面、围栏和路线视觉资产，"
        "仅为右侧路线岩石增加 0.08 体验单位碰撞安全余量，以降低边缘穿模；不改变整体移动边界。"
    )
    manifest["quality_metrics"]["collision_status"] = "layout_checked_with_targeted_safety_margin"
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + [
        "targeted_rock_collision_safety_margin"
    ]
    manifest["movement"]["collision_boxes"] = collision["boxes"]

    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V21\n\n"
        "这是 N01 自然照片的独立定向修复候选。V18 的视觉资产保持不变；\n"
        "右侧路线岩石增加 0.08 体验单位碰撞安全余量，以处理人工发现的轻微边缘穿模。\n"
        "视觉质量仍为 unverified，不能视为真实山地复原或最终质量通过。\n",
        encoding="utf-8",
    )
    return manifest


# V22 is a visual-only N01 follow-up.  The V21 collision fix is retained, but
# the foreground fence is rebuilt below the eye line so it reads as a near
# foreground element instead of a horizontal occluder across the mountain
# layers.  No movement bounds, speed or collision box is changed here.
PIXEL_V22_LAYOUT_VERSION = "pixel-v22-n01-fence-composition-pass-16"


def build_pixel_nature_v22(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r22-n01") -> dict[str, object]:
    """Build N01 V21 and lower the visual fence to restore mountain readability."""

    payload = build_pixel_nature_v21(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def is_fence(name: str) -> bool:
        return name.startswith((
            "pixel-q03-nature-fence-",
            "pixel-q03-r3-nature-fence-post-highlight-",
            "pixel-q03-r18-n01-fence-wire-",
        ))

    for name in list(scene.geometry):
        if is_fence(name):
            scene.delete_geometry(name)
    layout["objects"] = [item for item in layout.get("objects", []) if not is_fence(str(item.get("id", "")))]

    roles = layout["palette"]["roles"]
    fence = _mix(roles["dark"], roles["window"], 0.24)
    snow_blue = _mix(roles["window"], roles["accent"], 0.24)
    # Lower than V18's 1.02/1.34/1.66 wire levels; the highest visible wire
    # remains below the eye line (1.625), matching the source's low foreground
    # placement while leaving the central route open.
    for rail_index, y in enumerate((0.54, 0.86, 1.18)):
        _add_part(
            scene, layout["objects"], [], f"pixel-q05-r22-n01-fence-rail-{rail_index}",
            (9.60, 0.09, 0.10), (0.0, y, 6.02), fence,
            "foreground_fence", "photo_inferred_foreground_fence", grid=FURNITURE_VOXEL,
        )
    for post_index, x in enumerate((-4.50, -3.00, -1.50, 0.0, 1.50, 3.00, 4.50)):
        _add_part(
            scene, layout["objects"], [], f"pixel-q05-r22-n01-fence-post-{post_index}",
            (0.10, 1.10, 0.12), (x, 0.78, 6.02), _shade(fence, 0.82),
            "foreground_fence", "photo_inferred_foreground_fence", grid=FURNITURE_VOXEL,
        )
        _add_part(
            scene, layout["objects"], [], f"pixel-q05-r22-n01-fence-post-cap-{post_index}",
            (0.16, 0.08, 0.16), (x, 1.40, 6.02), _mix(fence, snow_blue, 0.18),
            "foreground_fence_detail", "photo_inferred_foreground_fence", grid=MICRO_VOXEL,
        )
    for post_index, x in enumerate((-4.50, -3.00, -1.50, 0.0, 1.50, 3.00, 4.50)):
        for wire_index, y in enumerate((0.56, 0.88, 1.20)):
            _add_part(
                scene, layout["objects"], [], f"pixel-q05-r22-n01-fence-wire-{post_index}-{wire_index}",
                (1.38 if post_index < 6 else 0.72, 0.025, 0.025),
                (x + (0.69 if post_index < 6 else 0.0), y, 6.00),
                _mix(fence, snow_blue, 0.12), "foreground_fence_detail",
                "photo_supported_foreground_fence", grid=MICRO_VOXEL,
            )

    layout_version = PIXEL_V22_LAYOUT_VERSION
    route_name = "pixel_style_sample_v22"
    detail_pass = "v22-n01-fence-composition-pass-16"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_n01_collision_safety_and_fence_composition"
    layout["pixel_spec"]["detail_pass"] = detail_pass
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + [
        "foreground_fence_eye_line_correction"
    ]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version

    manifest["version"] = "pixel-v22"
    manifest["provider_version"] = "pixel-voxel-v22"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V22 N01 构图修复候选：保留 V21 的右侧岩石碰撞安全余量，"
        "将照片前景围栏下移到相机视平线以下，恢复近景围栏与远山层次；不改变路线和移动边界。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + [
        "foreground_fence_eye_line_correction"
    ]
    manifest["movement"]["collision_boxes"] = collision["boxes"]

    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V22\n\n"
        "这是 N01 自然照片的独立构图修复候选。V21 的右侧岩石碰撞安全余量保持不变；\n"
        "前景围栏被下移到相机视平线以下，以减少遮挡并恢复远山层次。\n"
        "视觉质量仍为 unverified，不能视为真实山地复原或最终质量通过。\n",
        encoding="utf-8",
    )
    return manifest


# V23 replaces the old block-column ridge silhouette.  The previous layers
# were technically separated by depth but their repeated flat tops read like
# a city skyline in the starting frame.  This pass keeps the same walk surface
# and collision data while giving each ridge a deliberate multi-peak stepped
# profile and small directional snow bands.
PIXEL_V23_LAYOUT_VERSION = "pixel-v23-n01-mountain-silhouette-pass-17"


def build_pixel_nature_v23(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r23-n01") -> dict[str, object]:
    """Build N01 V22 and replace its skyline-like ridges with mountain profiles."""

    payload = build_pixel_nature_v22(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    def is_old_ridge(name: str) -> bool:
        return name.startswith((
            "pixel-v03-near-ridge-",
            "pixel-v03-mid-ridge-",
            "pixel-v03-far-ridge-",
            "pixel-q03-r18-n01-near-peak-",
            "pixel-q03-r18-n01-mid-peak-",
            "pixel-q03-r18-n01-far-peak-",
            "pixel-q03-r18-n01-near-snow-strata-",
            "pixel-q03-r18-n01-mid-snow-strata-",
            "pixel-q03-r18-n01-far-snow-strata-",
        ))

    for name in list(scene.geometry):
        if is_old_ridge(name):
            scene.delete_geometry(name)
    layout["objects"] = [item for item in layout.get("objects", []) if not is_old_ridge(str(item.get("id", "")))]

    roles = layout["palette"]["roles"]
    floor, wall = roles["floor"], roles["wall"]
    window, dark = roles["window"], roles["dark"]
    snow_light = _mix(window, [248, 250, 246], 0.52)
    snow_shadow = _mix(window, dark, 0.34)
    snow_blue = _mix(window, roles["accent"], 0.24)
    ridge_profiles = {
        "near": (0.22, 0.34, 0.52, 0.74, 0.91, 0.76, 0.54, 0.43, 0.62, 0.94, 1.00, 0.82, 0.61, 0.45, 0.33, 0.26, 0.20),
        "mid": (0.20, 0.31, 0.46, 0.65, 0.84, 0.72, 0.49, 0.38, 0.56, 0.82, 0.92, 0.73, 0.53, 0.40, 0.29, 0.23, 0.18),
        "far": (0.18, 0.27, 0.40, 0.56, 0.72, 0.62, 0.43, 0.34, 0.48, 0.70, 0.80, 0.64, 0.46, 0.35, 0.26, 0.21, 0.16),
    }
    ridge_specs = (
        ("near", -9.5, 5.25, 0.90, 0.82, _mix(floor, dark, 0.18), snow_light),
        ("mid", -13.6, 4.45, 0.72, 0.64, _mix(wall, dark, 0.32), _mix(window, snow_light, 0.38)),
        ("far", -17.4, 3.65, 0.56, 0.52, _mix(wall, dark, 0.48), _mix(window, snow_light, 0.56)),
    )
    for ridge_name, center_z, max_height, depth, scale, body_colour, cap_colour in ridge_specs:
        profile = ridge_profiles[ridge_name]
        for index, factor in enumerate(profile):
            x = -10.50 + index * 1.50
            height = max(0.75, round(max_height * factor * scale / BASE_VOXEL) * BASE_VOXEL)
            _add_part(
                scene, layout["objects"], [], f"pixel-q05-r23-n01-{ridge_name}-body-{index}",
                (1.52, height, depth), (x, height * 0.5, center_z),
                _mix(body_colour, wall, 0.06), "distant_ridge", "photo_inferred_horizon",
            )
            cap_height = max(0.125, round(min(0.38, height * 0.18) / FURNITURE_VOXEL) * FURNITURE_VOXEL)
            _add_part(
                scene, layout["objects"], [], f"pixel-q05-r23-n01-{ridge_name}-snow-cap-{index}",
                (1.30, cap_height, depth + 0.06), (x, height + cap_height * 0.5, center_z - 0.03),
                cap_colour, "distant_ridge_detail", "photo_palette_upper", grid=FURNITURE_VOXEL,
            )
            if index % 2 == 0 and height > 1.0:
                band_width = 0.72 if factor < 0.70 else 0.96
                _add_part(
                    scene, layout["objects"], [], f"pixel-q05-r23-n01-{ridge_name}-snow-band-{index}",
                    (band_width, 0.10, 0.035), (x - 0.10, max(0.45, height * 0.56), center_z + depth * 0.5 + 0.03),
                    snow_shadow if index % 4 == 0 else snow_blue, "distant_ridge_detail",
                    "photo_supported_snow_layer", grid=FURNITURE_VOXEL,
                )

    layout_version = PIXEL_V23_LAYOUT_VERSION
    route_name = "pixel_style_sample_v23"
    detail_pass = "v23-n01-mountain-silhouette-pass-17"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_n01_collision_safety_fence_and_mountain_silhouette"
    layout["pixel_spec"]["detail_pass"] = detail_pass
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + [
        "multi_peak_stepped_mountain_silhouette"
    ]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version

    manifest["version"] = "pixel-v23"
    manifest["provider_version"] = "pixel-voxel-v23"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V23 N01 山体轮廓候选：保留 V22 的围栏视平线修正和右侧岩石碰撞安全余量，"
        "将旧矩形山脊替换为远中近三层多峰阶梯雪山轮廓，并加入方向性雪带；不改变路线和移动边界。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + [
        "multi_peak_stepped_mountain_silhouette"
    ]
    manifest["movement"]["collision_boxes"] = collision["boxes"]

    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V23\n\n"
        "这是 N01 自然照片的独立山体轮廓细化候选。V22 的围栏构图和岩石碰撞修复保持不变；\n"
        "旧矩形山脊替换为多峰阶梯轮廓和方向性雪带，以增强雪山辨识度。\n"
        "视觉质量仍为 unverified，不能视为真实山地复原或最终质量通过。\n",
        encoding="utf-8",
    )
    return manifest


# V24 is an isolated Q03 lighting candidate.  It deliberately reuses the V23
# geometry, collision envelope, camera and route so the visual comparison
# measures lighting contrast rather than another layout change.
PIXEL_V24_LAYOUT_VERSION = "pixel-v24-n01-lighting-contrast-pass-18"


def build_pixel_nature_v24(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r24-n01") -> dict[str, object]:
    """Build N01 V23 and select the isolated higher-contrast daylight preset."""

    payload = build_pixel_nature_v23(image_path, output_dir, scene_id)
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    layout_version = PIXEL_V24_LAYOUT_VERSION
    route_name = "pixel_style_sample_v24"
    detail_pass = "v24-n01-lighting-contrast-pass-18"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_n01_mountain_silhouette_lighting_contrast"
    layout.setdefault("pixel_spec", {})["detail_pass"] = detail_pass
    layout["pixel_spec"]["lighting_preset"] = "outdoor_cool_daylight_v2"
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + [
        "directional_cool_daylight_contrast"
    ]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version

    manifest["version"] = "pixel-v24"
    manifest["provider_version"] = "pixel-voxel-v24"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V24 N01 光影候选：完全复用 V23 山体轮廓、围栏构图、碰撞安全余量和路线，"
        "仅将自然日光预设改为更明确的冷色主光、较低环境补光和较弱自发光，以拉开雪面、山体与近景层次；"
        "不改变几何、相机、移动或碰撞数据。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["lighting_status"] = "candidate_directional_contrast_v2"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["lighting_preset"] = "outdoor_cool_daylight_v2"
    manifest["pixel_spec"]["shadow_policy"] = "single_soft_key_contact_shadows_for_v24_candidate"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + [
        "directional_cool_daylight_contrast"
    ]
    manifest["movement"]["collision_boxes"] = collision["boxes"]

    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V24\n\n"
        "这是 N01 自然照片的独立光影对照候选。几何、碰撞、相机和路线完全继承 V23；\n"
        "仅使用更低环境补光、更明确冷色主光和更弱自发光，观察雪面与山体的层次是否改善。\n"
        "视觉质量仍为 unverified，不能视为真实山地复原或最终质量通过。\n",
        encoding="utf-8",
    )
    return manifest


# V25 is a paired indoor lighting candidate for I01 and I02.  Only the
# manifest-driven viewer preset changes; geometry and collision stay on the
# already-reviewed V17/V16 candidates for a fair lighting comparison.
PIXEL_V25_LAYOUT_VERSIONS = {
    "corridor": "pixel-v25-i01-indoor-lighting-contrast-pass-19",
    "living_room": "pixel-v25-i02-indoor-lighting-contrast-pass-19",
}


def _build_indoor_lighting_v25(
    image_path: Path,
    output_dir: Path,
    scene_id: str,
    base_builder,
    profile: str,
) -> dict[str, object]:
    payload = base_builder(image_path, output_dir, scene_id)
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    layout_version = PIXEL_V25_LAYOUT_VERSIONS[profile]
    route_name = "pixel_style_sample_v25"
    detail_pass = f"v25-{('i01' if profile == 'corridor' else 'i02')}-indoor-lighting-contrast-pass-19"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_indoor_material_readability_lighting_contrast"
    layout.setdefault("pixel_spec", {})["detail_pass"] = detail_pass
    layout["pixel_spec"]["lighting_preset"] = "indoor_warm_window_v2"
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + [
        "directional_warm_window_contrast"
    ]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version

    sample_name = "I01 走廊" if profile == "corridor" else "I02 客厅"
    manifest["version"] = "pixel-v25"
    manifest["provider_version"] = "pixel-voxel-v25"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        f"像素风 V25 {sample_name} 光影候选：完全复用既有几何、碰撞、相机和路线，"
        "仅将室内灯光改为较低环境补光、较明确的暖色窗光主光和较弱自发光，"
        "用于检查门窗、家具分件、地面和接触阴影是否获得更清晰层次；不改变布局。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["lighting_status"] = "candidate_warm_window_contrast_v2"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["lighting_preset"] = "indoor_warm_window_v2"
    manifest["pixel_spec"]["shadow_policy"] = "single_soft_key_contact_shadows_for_v25_candidate"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + [
        "directional_warm_window_contrast"
    ]
    manifest["movement"]["collision_boxes"] = collision["boxes"]

    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        f"Luna 像素风样板 V25 · {sample_name}\n\n"
        "这是室内光影对照候选。几何、碰撞、相机和路线继承既有样片；\n"
        "仅收紧环境光、加强暖窗主光并降低全局自发光，观察材质与接触层次。\n"
        "视觉质量仍为 unverified，不能视为最终质量通过。\n",
        encoding="utf-8",
    )
    return manifest


def build_pixel_corridor_v25(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r25-i01") -> dict[str, object]:
    return _build_indoor_lighting_v25(image_path, output_dir, scene_id, build_pixel_corridor_v17, "corridor")


def build_pixel_living_v25(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r25-i02") -> dict[str, object]:
    return _build_indoor_lighting_v25(image_path, output_dir, scene_id, build_pixel_living_v16, "living_room")


# V27 is a targeted I02 semantic-detail pass.  The added parts are small,
# named, non-colliding voxel details (pillows, table trim/objects, console
# slats and curtain pleats), not random tessellation.  Room bounds and all
# movement/collision data remain inherited from V25.
PIXEL_V27_LAYOUT_VERSION = "pixel-v27-i02-semantic-detail-pass-21"


def build_pixel_living_v27(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r27-i02") -> dict[str, object]:
    payload = build_pixel_living_v25(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    sofa = roles["sofa"]
    wood = roles["wood"]
    metal = roles["metal"]
    window = roles["window"]
    lamp = roles["lamp"]
    accent = roles["accent"]
    trim = roles["trim"]
    dark = roles["dark"]

    objects = layout["objects"]
    details = []

    def add_detail(name, size, position, colour, role, source, grid=FURNITURE_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    # Two readable cushions/throws sit on the inferred sofa back; front seams
    # make the upholstered object read as separate cushions when viewed from
    # the start and after turning around.
    add_detail("pixel-q05-r27-i02-sofa-pillow-left", (0.68, 0.22, 0.18), (-2.86, 1.18, -2.31), _mix(sofa, accent, 0.10), "sofa_detail", "photo_inferred_cushion", FURNITURE_VOXEL)
    add_detail("pixel-q05-r27-i02-sofa-pillow-right", (0.68, 0.22, 0.18), (-1.13, 1.18, -2.31), _mix(sofa, window, 0.08), "sofa_detail", "photo_inferred_cushion", FURNITURE_VOXEL)
    add_detail("pixel-q05-r27-i02-sofa-seam-left", (0.74, 0.035, 0.035), (-2.86, 0.97, -1.34), _mix(sofa, trim, 0.34), "sofa_surface_detail", "procedural_seam", MICRO_VOXEL)
    add_detail("pixel-q05-r27-i02-sofa-seam-right", (0.74, 0.035, 0.035), (-1.13, 0.97, -1.34), _mix(sofa, trim, 0.34), "sofa_surface_detail", "procedural_seam", MICRO_VOXEL)

    # The table receives a coherent trim/inlay plus two small semantic objects,
    # keeping the tabletop legible without adding a collision proxy.
    add_detail("pixel-q05-r27-i02-table-rim-front", (1.78, 0.04, 0.055), (1.25, 1.045, 1.03), _mix(wood, metal, 0.22), "table_surface_detail", "procedural_table_edge", MICRO_VOXEL)
    add_detail("pixel-q05-r27-i02-table-rim-left", (0.055, 0.04, 1.08), (0.40, 1.045, 0.49), _mix(wood, metal, 0.22), "table_surface_detail", "procedural_table_edge", MICRO_VOXEL)
    add_detail("pixel-q05-r27-i02-table-inlay", (1.05, 0.035, 0.08), (1.25, 1.075, 0.48), _mix(wood, accent, 0.18), "table_surface_detail", "photo_inferred_table_inlay", MICRO_VOXEL)
    add_detail("pixel-q05-r27-i02-table-book", (0.34, 0.065, 0.23), (0.88, 1.13, 0.48), _mix(accent, dark, 0.22), "table_object", "photo_inferred_small_object", FURNITURE_VOXEL)
    add_detail("pixel-q05-r27-i02-table-mug", (0.14, 0.14, 0.14), (1.72, 1.15, 0.55), lamp, "table_object", "photo_inferred_small_object", MICRO_VOXEL)

    # Console slats and screen pixels describe the media wall as a cabinet and
    # display, rather than a single brown/black rectangle.
    for index, y in enumerate((0.31, 0.52, 0.70)):
        add_detail(
            f"pixel-q05-r27-i02-console-slat-{index}", (1.36, 0.035, 0.045),
            (3.25, y, -4.18), _mix(wood, trim, 0.20), "console_surface_detail",
            "procedural_drawer_slat", MICRO_VOXEL,
        )
    for index, x in enumerate((2.82, 3.05, 3.28, 3.51, 3.74)):
        add_detail(
            f"pixel-q05-r27-i02-screen-highlight-{index}", (0.12, 0.08, 0.025),
            (x, 1.24 + (index % 2) * 0.18, -4.40), _mix(window, accent, 0.30),
            "display_detail", "photo_inferred_screen_pixel", MICRO_VOXEL,
        )

    # The back window is already modeled as a thick opening; extra pleats make
    # the curtain read as a layered textile instead of a flat blue plane.
    for index, x in enumerate((0.46, 0.86, 1.26, 2.22, 2.62, 3.02)):
        add_detail(
            f"pixel-q05-r27-i02-curtain-pleat-{index}", (0.045, 2.02, 0.045),
            (x, 2.48, -6.34), _mix(window, dark, 0.22), "curtain_surface_detail",
            "procedural_curtain_pleat", MICRO_VOXEL,
        )

    layout_version = PIXEL_V27_LAYOUT_VERSION
    route_name = "pixel_style_sample_v27"
    detail_pass = "v27-i02-semantic-detail-pass-21"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_i02_semantic_furniture_and_opening_detail"
    layout["pixel_spec"]["detail_pass"] = detail_pass
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + [
        "semantic_sofa_detail", "semantic_table_detail", "semantic_console_detail", "semantic_curtain_detail"
    ]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version

    manifest["version"] = "pixel-v27"
    manifest["provider_version"] = "pixel-voxel-v27"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V27 I02 语义细节候选：保留 V25 室内光影、房间边界、碰撞和路线，"
        "新增可命名的沙发靠垫/缝线、茶几边缘/书杯、电视柜抽屉条、屏幕像素和窗帘褶皱；"
        "所有新增件不参与碰撞，不改变可行走空间。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["lighting_status"] = "inherited_indoor_warm_window_v2"
    manifest["quality_metrics"]["semantic_detail_status"] = "candidate_named_voxel_details"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["asset_library_version"] = "pixel-assets-q01-r1-plus-i02-detail-v1"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + [
        "semantic_sofa_detail", "semantic_table_detail", "semantic_console_detail", "semantic_curtain_detail"
    ]
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = details

    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V27 · I02 客厅语义细节候选\n\n"
        "继承 V25 光影、房间、碰撞和路线；新增有名称、有来源的沙发、茶几、电视柜、屏幕和窗帘细节。\n"
        "新增细节不参与碰撞；视觉质量仍为 unverified。\n",
        encoding="utf-8",
    )
    return manifest


# V28 is the next Q03 visual pass.  It targets the information-density gap
# visible in the reference pixel scenes: readable surface patterns, repeated
# architectural rhythm, and small semantic props.  It deliberately inherits
# V27's room, camera and collision contract; all additions are render-only.
PIXEL_V28_LAYOUT_VERSION = "pixel-v28-i02-surface-density-pass-22"


def build_pixel_living_v28(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r28-i02") -> dict[str, object]:
    payload = build_pixel_living_v27(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
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
    accent = roles["accent"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=FURNITURE_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    def add_xy(prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL):
        _add_pattern_xy(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=grid)
        details.append(prefix)

    def add_xz(prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL):
        _add_pattern_xz(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=grid)
        details.append(prefix)

    # Upholstery: two stepped cushion faces, piping, and a restrained fabric
    # weave.  These are authored as semantic layers instead of random noise so
    # the sofa remains identifiable from front and after turning around.
    sofa_light = _mix(sofa, wall, 0.22)
    sofa_shadow = _shade(sofa, 0.72)
    sofa_high = _mix(sofa, accent, 0.18)
    for index, (x, z) in enumerate(((-2.78, -2.40), (-1.20, -2.40))):
        add_xy(
            f"pixel-q05-r28-i02-sofa-cushion-face-{index}",
            (".aaaaaaa.", "abbbbb b a".replace(" ", ""), "abcccc c a".replace(" ", ""),
             "abcccc c a".replace(" ", ""), "abbbbb b a".replace(" ", ""), ".aaaaaaa."),
            (x, 1.38, z), (0.14, 0.12), 0.025,
            {"a": sofa_shadow, "b": sofa_light, "c": sofa_high},
            "upholstery_pixel_surface", "photo_supported_furniture",
        )
        add_detail(
            f"pixel-q05-r28-i02-sofa-cushion-piping-{index}", (1.16, 0.035, 0.035),
            (x, 1.07, -1.46), sofa_shadow, "upholstery_piping", "procedural_upholstery_detail", MICRO_VOXEL,
        )
    # Stepped chaise/arm silhouettes make the side view less like a single
    # rectangular prism while remaining outside the collision proxy.
    for index, (x, z) in enumerate(((-3.72, -2.08), (-0.18, -2.08))):
        add_detail(
            f"pixel-q05-r28-i02-sofa-arm-highlight-{index}", (0.04, 0.72, 0.76),
            (x, 1.16, z), sofa_high, "upholstery_edge", "procedural_upholstery_detail", MICRO_VOXEL,
        )

    # Coffee table: a readable top pattern, inset, book and cup silhouette.
    table_dark = _shade(wood, 0.62)
    table_light = _mix(wood, wall, 0.26)
    add_xz(
        "pixel-q05-r28-i02-coffee-table-top-pattern",
        ("aabbbbbba", "abcccc cba".replace(" ", ""), "bcddddccb", "abcccc cba".replace(" ", ""), "aabbbbbba"),
        (1.25, 1.08, 0.55), (0.20, 0.14), 0.025,
        {"a": table_dark, "b": wood, "c": table_light, "d": _mix(accent, wood, 0.35)},
        "table_pixel_surface", "photo_supported_furniture",
    )
    add_detail("pixel-q05-r28-i02-coffee-table-book-cover", (0.38, 0.035, 0.28), (0.86, 1.13, 0.50), accent, "table_prop", "photo_inferred_small_object", MICRO_VOXEL)
    add_detail("pixel-q05-r28-i02-coffee-table-book-page", (0.31, 0.018, 0.20), (0.86, 1.16, 0.50), _mix(wall, lamp, 0.10), "table_prop", "photo_inferred_small_object", MICRO_VOXEL)
    add_detail("pixel-q05-r28-i02-coffee-table-mug-body", (0.16, 0.13, 0.16), (1.72, 1.15, 0.55), lamp, "table_prop", "photo_inferred_small_object", MICRO_VOXEL)
    add_detail("pixel-q05-r28-i02-coffee-table-mug-rim", (0.20, 0.025, 0.20), (1.72, 1.23, 0.55), _mix(lamp, wall, 0.28), "table_prop", "procedural_small_object_detail", MICRO_VOXEL)

    # Media wall and wall art: regular pixels give the back wall the authored
    # rhythm seen in the reference scenes without projecting the full photo.
    screen_dark = _mix(dark, trim, 0.18)
    screen_blue = _mix(window, accent, 0.35)
    add_xy(
        "pixel-q05-r28-i02-screen-pixel-mosaic",
        ("..aaaaaaaa..", ".abbbbbbbba.", "abacccc caba".replace(" ", ""),
         "abacccc caba".replace(" ", ""), ".abbbbbbbba.", "..aaaaaaaa.."),
        (3.25, 1.47, -4.43), (0.105, 0.105), 0.025,
        {"a": screen_dark, "b": screen_blue, "c": _mix(screen_blue, lamp, 0.22)},
        "display_pixel_surface", "photo_supported_display",
    )
    for index, x in enumerate((2.55, 2.85, 3.15, 3.45, 3.75)):
        add_detail(
            f"pixel-q05-r28-i02-console-drawer-highlight-{index}", (0.20, 0.035, 0.025),
            (x, 0.62, -4.17), _mix(wood, wall, 0.20), "console_surface_detail", "procedural_drawer_detail", MICRO_VOXEL,
        )

    for index, (x, y) in enumerate(((-3.35, 2.56), (-2.25, 2.62))):
        add_detail(f"pixel-q05-r28-i02-wall-art-frame-{index}", (0.78, 0.72, 0.04), (x, y, -6.50), trim, "wall_art_frame", "procedural_wall_art", MICRO_VOXEL)
        add_xy(
            f"pixel-q05-r28-i02-wall-art-pixels-{index}",
            ("..aa..", ".abbaa.", "abccba", ".abbaa.", "..aa.."),
            (x, y, -6.47), (0.10, 0.10), 0.018,
            {"a": accent, "b": window, "c": lamp}, "wall_art_pixel_surface", "procedural_wall_art", MICRO_VOXEL,
        )

    # Window view: a small stepped skyline and light bands make the opening
    # read as depth, not as a single blue slab.  It is deliberately generic
    # and is recorded as palette-guided completion rather than photo truth.
    skyline_dark = _mix(window, dark, 0.60)
    skyline_mid = _mix(window, accent, 0.25)
    add_xy(
        "pixel-q05-r28-i02-window-skyline-bands",
        ("................", "................", "...bb.....b....", "..bbb..bbbbb...",
         ".bbbb..bbbbbb..", "bbbbbbbbbbbbbbb", "bbbbbbbbbbbbbbb"),
        (1.75, 2.08, -6.43), (0.16, 0.12), 0.018,
        {"b": skyline_dark}, "window_depth_layer", "photo_palette_upper", MICRO_VOXEL,
    )
    for index, (x, height) in enumerate(((0.42, 0.46), (0.78, 0.72), (1.16, 0.36), (2.00, 0.58), (2.42, 0.84), (2.86, 0.50))):
        add_detail(
            f"pixel-q05-r28-i02-window-city-tower-{index}", (0.22, height, 0.025),
            (x, 2.08 + height * 0.5, -6.40), _mix(skyline_mid, dark, 0.35), "window_depth_layer", "photo_palette_upper", MICRO_VOXEL,
        )
        add_detail(
            f"pixel-q05-r28-i02-window-city-light-{index}", (0.045, 0.045, 0.018),
            (x, 2.10 + height * 0.55, -6.375), lamp if index % 3 == 0 else _mix(window, accent, 0.28), "window_city_light", "procedural_window_completion", MICRO_VOXEL,
        )

    # Ceiling fixtures and floor tile rhythm add the small repeated cues that
    # distinguish authored pixel environments from untextured boxes.
    for index, x in enumerate((-2.55, -1.15, 0.25, 1.65, 3.05)):
        add_detail(f"pixel-q05-r28-i02-ceiling-recess-{index}", (0.22, 0.035, 0.10), (x, 3.73, 0.05), dark, "ceiling_fixture", "photo_supported_ceiling", MICRO_VOXEL)
        add_detail(f"pixel-q05-r28-i02-ceiling-light-{index}", (0.10, 0.018, 0.035), (x, 3.70, 0.05), _mix(lamp, wall, 0.18), "ceiling_fixture", "photo_supported_ceiling", MICRO_VOXEL)
    for index, x in enumerate((-3.2, -2.1, -1.0, 0.1, 1.2, 2.3, 3.4)):
        add_detail(f"pixel-q05-r28-i02-floor-tile-seam-{index}", (0.025, 0.018, 4.10), (x, 0.145, 0.55), _mix(floor, trim, 0.35), "floor_surface_detail", "photo_supported_floor", MICRO_VOXEL)

    # Plant layering: stems, leaf highlights and shadow clusters improve the
    # silhouette without turning every voxel into a collision object.
    leaf_dark = _shade(plant, 0.62)
    leaf_light = _mix(plant, lamp, 0.16)
    for index, (x, y, z, sx, sy, sz) in enumerate((
        (-3.98, 2.15, 0.43, 0.46, 0.24, 0.18), (-3.70, 2.42, 0.43, 0.38, 0.22, 0.18),
        (-3.36, 2.72, 0.43, 0.48, 0.20, 0.18), (-3.08, 2.95, 0.43, 0.34, 0.22, 0.18),
        (-3.75, 3.18, 0.43, 0.42, 0.18, 0.18), (-3.25, 3.42, 0.43, 0.30, 0.18, 0.18),
    )):
        add_detail(f"pixel-q05-r28-i02-plant-leaf-cluster-{index}", (sx, sy, sz), (x, y, z), leaf_light if index % 2 else plant, "vegetation_pixel_cluster", "photo_supported_vegetation", FURNITURE_VOXEL)
        add_detail(f"pixel-q05-r28-i02-plant-leaf-shadow-{index}", (sx * 0.62, sy * 0.45, sz * 0.72), (x + 0.08, y - 0.11, z + 0.02), leaf_dark, "vegetation_pixel_shadow", "procedural_vegetation_detail", MICRO_VOXEL)

    layout_version = PIXEL_V28_LAYOUT_VERSION
    route_name = "pixel_style_sample_v28"
    detail_pass = "v28-i02-surface-density-pass-22"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_i02_pixel_surface_density_and_semantic_rhythm"
    layout["pixel_spec"]["detail_pass"] = detail_pass
    layout["pixel_spec"]["asset_library_version"] = "pixel-assets-q01-r1-plus-i02-detail-v2"
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + [
        "semantic_upholstery_surface", "semantic_table_surface", "media_wall_pixel_rhythm",
        "window_depth_layers", "ceiling_fixture_rhythm", "floor_tile_rhythm", "vegetation_pixel_layers",
    ]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version

    manifest["version"] = "pixel-v28"
    manifest["provider_version"] = "pixel-voxel-v28"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V28 I02 表面信息密度候选：继承 V27 的房间、灯光、碰撞和路线，"
        "以语义分件和像素表面节奏补充沙发面料、茶几纹理、电视墙、墙面装饰、窗外远景、"
        "顶灯、地砖和植物层次；不使用整图贴面，不改变碰撞空间。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = "candidate_pixel_surface_density_v2"
    manifest["quality_metrics"]["lighting_status"] = "inherited_indoor_warm_window_v2"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["surface_density_policy"] = "semantic_patterns_and_repeated_rhythm_no_uniform_noise"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + [
        "semantic_upholstery_surface", "semantic_table_surface", "media_wall_pixel_rhythm",
        "window_depth_layers", "ceiling_fixture_rhythm", "floor_tile_rhythm", "vegetation_pixel_layers",
    ]
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details

    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V28 · I02 表面信息密度候选\n\n"
        "继承 V27 的室内布局、暖窗光影、碰撞和路线；新增语义分件、像素表面图案、"
        "窗外远景层次、顶灯/地砖节奏和植物明暗簇。新增件不参与碰撞。\n"
        "这是 Q03 视觉候选，仍需人工检查参考风格、动态路线和离线包后才能改变质量状态。\n",
        encoding="utf-8",
    )
    return manifest


# V29 corrects the visibility mistake found during the V28 screenshot review:
# the previous cushion pattern was authored on the rear sofa face.  This pass
# puts the upholstery detail on the camera-facing front face and adds a
# low-poly round coffee table, which is a strong identifying feature of I02.
PIXEL_V29_LAYOUT_VERSION = "pixel-v29-i02-visible-upholstery-and-round-table-pass-23"


def build_pixel_living_v29(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r29-i02") -> dict[str, object]:
    payload = build_pixel_living_v28(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    wall = roles["wall"]
    floor = roles["floor"]
    trim = roles["trim"]
    sofa = roles["sofa"]
    wood = roles["wood"]
    metal = roles["metal"]
    window = roles["window"]
    lamp = roles["lamp"]
    dark = roles["dark"]
    accent = roles["accent"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=FURNITURE_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    def add_xy(prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL):
        _add_pattern_xy(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=grid)
        details.append(prefix)

    def add_xz(prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL):
        _add_pattern_xz(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=grid)
        details.append(prefix)

    # The actual visible sofa front is around z=-1.35 in the inherited room;
    # use stronger but still photo-related value steps so cushions read at the
    # start view and retain a pixel-art silhouette after a turn.
    sofa_lit = _mix(sofa, wall, 0.36)
    sofa_mid = _mix(sofa, accent, 0.16)
    sofa_shadow = _mix(sofa, trim, 0.42)
    for index, x in enumerate((-2.78, -1.20)):
        add_xy(
            f"pixel-q05-r29-i02-sofa-visible-cushion-{index}",
            (".aaaaaaa.", "abbbbb b a".replace(" ", ""), "abcccc c a".replace(" ", ""),
             "abcccc c a".replace(" ", ""), "abbbbb b a".replace(" ", ""), ".aaaaaaa."),
            (x, 1.02, -1.31), (0.15, 0.12), 0.035,
            {"a": sofa_shadow, "b": sofa_lit, "c": sofa_mid},
            "upholstery_visible_face", "photo_supported_furniture",
        )
        add_detail(
            f"pixel-q05-r29-i02-sofa-visible-piping-{index}", (1.18, 0.045, 0.045),
            (x, 0.72, -1.30), sofa_shadow, "upholstery_visible_edge", "procedural_upholstery_detail", MICRO_VOXEL,
        )
    # Two stepped throws introduce a second semantic colour, like the patterned
    # cushions in the source living-room photograph without copying it.
    throw = _mix(accent, window, 0.42)
    throw_shadow = _mix(throw, trim, 0.35)
    add_xy(
        "pixel-q05-r29-i02-sofa-throw-left",
        ("..aaaa..", ".abbbba.", "abccccba", "abccccba", ".abbbba.", "..aaaa.."),
        (-2.82, 1.27, -1.285), (0.12, 0.105), 0.025,
        {"a": throw_shadow, "b": throw, "c": sofa_lit}, "upholstery_throw", "photo_inferred_soft_furnishing", MICRO_VOXEL,
    )
    add_xy(
        "pixel-q05-r29-i02-sofa-throw-right",
        ("..aaaa..", ".abbbba.", "abccccba", "abccccba", ".abbbba.", "..aaaa.."),
        (-1.18, 1.27, -1.285), (0.12, 0.105), 0.025,
        {"a": throw_shadow, "b": throw, "c": sofa_lit}, "upholstery_throw", "photo_inferred_soft_furnishing", MICRO_VOXEL,
    )

    # Add a low-poly round table over the inherited table top.  It is render
    # only; collision remains the inherited rectangular proxy for safe walking.
    def add_cylinder(name: str, radius: float, height: float, position: tuple[float, float, float], colour: list[int], role: str, source: str, sections: int = 12):
        mesh = trimesh.creation.cylinder(radius=radius, height=height, sections=sections)
        mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2.0, [1.0, 0.0, 0.0]))
        mesh.apply_translation(position)
        mesh.visual.vertex_colors = np.tile(np.asarray([*colour, 255], dtype=np.uint8), (len(mesh.vertices), 1))
        mesh.visual.material = trimesh.visual.material.PBRMaterial(
            baseColorFactor=[*colour, 255], metallicFactor=0.0, roughnessFactor=0.72,
        )
        mesh.metadata["layout_name"] = name
        mesh.metadata["voxel_grid"] = FURNITURE_VOXEL
        scene.add_geometry(mesh, geom_name=name)
        bounds = np.asarray(mesh.bounds, dtype=float)
        objects.append({
            "id": name, "role": role, "source": source, "voxel_grid": FURNITURE_VOXEL,
            "bounds": bounds.tolist(),
        })
        details.append(name)

    table_top = _mix(sofa, wall, 0.42)
    table_edge = _mix(wood, metal, 0.20)
    add_cylinder("pixel-q05-r29-i02-round-coffee-table-top", 0.78, 0.16, (1.25, 1.03, 0.55), table_top, "round_table_surface", "photo_supported_furniture", 12)
    add_cylinder("pixel-q05-r29-i02-round-coffee-table-edge", 0.79, 0.045, (1.25, 0.94, 0.55), table_edge, "round_table_edge", "procedural_furniture_detail", 12)
    add_cylinder("pixel-q05-r29-i02-round-coffee-table-base", 0.30, 0.62, (1.25, 0.61, 0.55), _mix(metal, dark, 0.20), "round_table_base", "photo_supported_furniture", 12)
    add_xz(
        "pixel-q05-r29-i02-round-table-inlay",
        ("..aaaa..", ".abbbba.", "abccccba", ".abbbba.", "..aaaa.."),
        (1.25, 1.125, 0.55), (0.14, 0.11), 0.018,
        {"a": table_edge, "b": table_top, "c": _mix(accent, table_top, 0.35)},
        "round_table_surface_detail", "procedural_furniture_detail", MICRO_VOXEL,
    )

    # A narrow display shelf and small object rhythm fill the formerly blank
    # wall bands while keeping the room direction and scale unchanged.
    shelf = _mix(wood, trim, 0.16)
    for index, y in enumerate((2.02, 2.34, 2.66)):
        add_detail(f"pixel-q05-r29-i02-back-shelf-{index}", (1.34, 0.045, 0.16), (-2.58, y, -6.43), shelf, "wall_furniture_detail", "photo_inferred_furniture", MICRO_VOXEL)
        for item, x in enumerate((-3.03, -2.74, -2.45)):
            add_detail(
                f"pixel-q05-r29-i02-shelf-object-{index}-{item}", (0.08 + (item % 2) * 0.04, 0.12, 0.04),
                (x, y + 0.08, -6.38), accent if item == 1 else _mix(window, wall, 0.35), "shelf_object", "procedural_small_object_detail", MICRO_VOXEL,
            )

    layout_version = PIXEL_V29_LAYOUT_VERSION
    route_name = "pixel_style_sample_v29"
    detail_pass = "v29-i02-visible-upholstery-and-round-table-pass-23"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_i02_visible_surface_detail_and_photo_anchor_pass"
    layout["pixel_spec"]["detail_pass"] = detail_pass
    layout["pixel_spec"]["visible_surface_policy"] = "camera_facing_semantic_layers_and_low_poly_round_anchor"
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + [
        "visible_upholstery_layers", "round_coffee_table", "wall_shelf_object_rhythm",
    ]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version

    manifest["version"] = "pixel-v29"
    manifest["provider_version"] = "pixel-voxel-v29"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V29 I02 可见面修正候选：修正 V28 沙发图案位于背面的可见性问题，"
        "将靠垫、缝线和布料色阶放到相机可见前面；增加与原图语义对应的低多边形圆形茶几、"
        "底座和墙面陈设节奏。碰撞仍继承 V27/V28，不把装饰件加入碰撞。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = "candidate_visible_upholstery_and_round_table"
    manifest["quality_metrics"]["lighting_status"] = "inherited_indoor_warm_window_v2"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + [
        "visible_upholstery_layers", "round_coffee_table", "wall_shelf_object_rhythm",
    ]
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details

    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V29 · I02 可见面与圆桌语义候选\n\n"
        "在 V28 表面信息密度基础上，修正沙发纹理面朝向，并增加圆形茶几的桌面、边缘、底座和像素内嵌。\n"
        "碰撞、移动和离线入口保持不变；质量状态仍需视觉验收，不能仅由离线通过推导。\n",
        encoding="utf-8",
    )
    return manifest


# V30 is a lighting-only comparison for the V29 geometry.  Keeping it isolated
# makes the effect of stronger pixel-scene value separation measurable and
# reversible; no model, layout or collision data is silently changed.
PIXEL_V30_LAYOUT_VERSION = "pixel-v30-i02-pixel-cozy-lighting-pass-24"


def build_pixel_living_v30(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r30-i02") -> dict[str, object]:
    payload = build_pixel_living_v29(image_path, output_dir, scene_id)
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    layout_version = PIXEL_V30_LAYOUT_VERSION
    route_name = "pixel_style_sample_v30"
    detail_pass = "v30-i02-pixel-cozy-lighting-pass-24"
    preset = "indoor_pixel_cozy_v3"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_i02_pixel_value_separation_lighting_comparison"
    layout["pixel_spec"]["detail_pass"] = detail_pass
    layout["pixel_spec"]["lighting_preset"] = preset
    layout["pixel_spec"]["lighting_policy"] = "lower_ambient_stronger_single_key_small_cool_fill"
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + ["pixel_value_separation_lighting"]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version

    manifest["version"] = "pixel-v30"
    manifest["provider_version"] = "pixel-voxel-v30"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V30 I02 光影对照候选：完全继承 V29 可见沙发分件、圆形茶几、墙面陈设、"
        "房间布局和碰撞，仅降低环境与全局补光、提高单一暖色主光方向性并保留少量冷色补光，"
        "用于检查参考像素图中的明暗阶和轮廓层次；若起点过暗则退回 V29。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["lighting_status"] = "candidate_pixel_cozy_value_separation_v3"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["lighting_preset"] = preset
    manifest["pixel_spec"]["shadow_policy"] = "single_directional_soft_key_with_low_ambient_for_v30_candidate"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + ["pixel_value_separation_lighting"]
    manifest["movement"]["collision_boxes"] = collision["boxes"]

    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V30 · I02 像素明暗阶对照候选\n\n"
        "继承 V29 的可见面和语义几何，仅切换到更低环境光、更强单一主光和较弱冷色补光。\n"
        "这是光影对照，不改变布局和碰撞；若细节被压暗，保留 V29 作为更好的候选。\n",
        encoding="utf-8",
    )
    return manifest


# V31 is the micro-grid surface pass.  It keeps V29's preferred brightness
# and geometry but makes the most visible semantic surfaces use a finer cell
# size, which is the remaining direct visual gap to the supplied references.
PIXEL_V31_LAYOUT_VERSION = "pixel-v31-i02-micro-grid-surface-pass-25"


def build_pixel_living_v31(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r31-i02") -> dict[str, object]:
    payload = build_pixel_living_v29(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    wall = roles["wall"]
    sofa = roles["sofa"]
    trim = roles["trim"]
    wood = roles["wood"]
    window = roles["window"]
    lamp = roles["lamp"]
    dark = roles["dark"]
    accent = roles["accent"]
    objects = layout["objects"]
    details: list[str] = []

    def add_xy(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_xy(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    def add_xz(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_xz(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    sofa_a = _mix(sofa, trim, 0.32)
    sofa_b = _mix(sofa, wall, 0.34)
    sofa_c = _mix(sofa, accent, 0.18)
    sofa_d = _mix(sofa, dark, 0.26)
    # 0.0625-sized cells keep the same object semantics while producing
    # smaller readable steps than V29's 0.12–0.15 cells.
    for index, x in enumerate((-2.78, -1.20)):
        add_xy(
            f"pixel-q05-r31-i02-sofa-micro-weave-{index}",
            ("...aaaaaaaaa...", "..abbbbbbbbba..", ".abccccccccccba.",
             ".abccddddcccb a.".replace(" ", ""), ".abccddddcccb a.".replace(" ", ""),
             ".abccccccccccba.", "..abbbbbbbbba..", "...aaaaaaaaa..."),
            (x, 1.02, -1.285), (0.0625, 0.0625), 0.018,
            {"a": sofa_a, "b": sofa_b, "c": sofa_c, "d": sofa_d},
            "upholstery_micro_surface", "photo_supported_furniture",
        )

    table_a = _mix(wood, trim, 0.28)
    table_b = _mix(wood, wall, 0.24)
    table_c = _mix(accent, wood, 0.32)
    add_xz(
        "pixel-q05-r31-i02-round-table-micro-inlay",
        ("....aaaaa....", "..abbbbbbbba..", ".abccccccc cba".replace(" ", ""),
         "abccddddddccba", ".abccccccc cba".replace(" ", ""), "..abbbbbbbba..", "....aaaaa...."),
        (1.25, 1.135, 0.55), (0.075, 0.06), 0.014,
        {"a": table_a, "b": table_b, "c": table_c, "d": _mix(table_c, wall, 0.36)},
        "round_table_micro_surface", "procedural_furniture_detail",
    )

    # The TV face and window skyline use compact blocks to approach the
    # repeated, high-density window/sign rhythm of the supplied pixel scenes.
    screen_a = _mix(dark, trim, 0.12)
    screen_b = _mix(window, accent, 0.42)
    screen_c = _mix(screen_b, lamp, 0.22)
    add_xy(
        "pixel-q05-r31-i02-tv-micro-screen",
        ("..aaaaaaaaaaaa..", ".abbbbbbbbbbbba.", "abacccbbbcccaba", "abacccbbbcccaba",
         ".abbbbbbbbbbbba.", "..aaaaaaaaaaaa.."),
        (-2.58, 2.04, -6.00), (0.075, 0.075), 0.018,
        {"a": screen_a, "b": screen_b, "c": screen_c}, "display_micro_surface", "photo_supported_display",
    )
    skyline_a = _mix(window, dark, 0.56)
    skyline_b = _mix(window, accent, 0.22)
    add_xy(
        "pixel-q05-r31-i02-window-micro-city",
        ("......................", "......................", "...bb....b......b.....",
         "..bbb..bbb....bbb....", ".bbbbbbbbbb..bbbbbb..", "bbbbbbbbbbbbbbbbbbbbb",
         "bbbbbbbbbbbbbbbbbbbbb"),
        (1.75, 2.10, -6.40), (0.085, 0.075), 0.014,
        {"b": skyline_a}, "window_micro_depth", "photo_palette_upper",
    )
    for index, (x, y) in enumerate(((0.54, 2.45), (0.88, 2.63), (1.28, 2.34), (2.02, 2.56), (2.46, 2.76), (2.90, 2.38))):
        _add_part(scene, objects, [], f"pixel-q05-r31-i02-window-micro-light-{index}", (0.035, 0.035, 0.016), (x, y, -6.375), lamp if index % 2 else skyline_b, "window_micro_light", "procedural_window_completion", grid=MICRO_VOXEL)
        details.append(f"pixel-q05-r31-i02-window-micro-light-{index}")

    layout_version = PIXEL_V31_LAYOUT_VERSION
    route_name = "pixel_style_sample_v31"
    detail_pass = "v31-i02-micro-grid-surface-pass-25"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_i02_micro_grid_semantic_surface_pass"
    layout["pixel_spec"]["detail_pass"] = detail_pass
    layout["pixel_spec"]["micro_surface_voxel"] = MICRO_VOXEL
    layout["pixel_spec"]["surface_density_policy"] = "0.0625_micro_cells_on_visible_semantic_surfaces"
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + [
        "micro_grid_upholstery", "micro_grid_round_table", "micro_grid_display", "micro_grid_window_city",
    ]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version

    manifest["version"] = "pixel-v31"
    manifest["provider_version"] = "pixel-voxel-v31"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V31 I02 微栅格表面候选：继承 V29 的可见沙发、圆形茶几和暖窗光影，"
        "仅在相机可见的沙发、茶几、电视和窗外层次使用 0.0625/0.015625 级细胞，"
        "增加可读的织物、边缘、屏幕和城市光点；不增加碰撞、不投射整张照片。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = "candidate_micro_grid_visible_surfaces"
    manifest["quality_metrics"]["lighting_status"] = "inherited_indoor_warm_window_v2"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["micro_surface_voxel"] = MICRO_VOXEL
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + [
        "micro_grid_upholstery", "micro_grid_round_table", "micro_grid_display", "micro_grid_window_city",
    ]
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details

    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V31 · I02 微栅格表面候选\n\n"
        "继承 V29 的几何、碰撞和光影，仅把可见语义表面细化到微栅格：沙发织物、圆桌内嵌、"
        "电视面和窗外城市像素。质量状态仍为 unverified，需与 V29 并排视觉比较。\n",
        encoding="utf-8",
    )
    return manifest


# V32 rotates Q03's fine-detail work through the two exterior categories that
# most directly map to the supplied cyberpunk/night pixel reference: facade
# window rhythm and street-level light/vehicle cues.  Geometry and collisions
# are inherited from the previously reviewed candidates.
PIXEL_V32_LAYOUT_VERSIONS = {
    "street": "pixel-v32-s01-micro-window-and-light-pass-26",
    "building": "pixel-v32-b01-micro-window-and-light-pass-26",
}


def _build_building_detail_v32(image_path: Path, output_dir: Path, scene_id: str, base_builder) -> dict[str, object]:
    payload = base_builder(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    trim, window, lamp, dark, accent = roles["trim"], roles["window"], roles["lamp"], roles["dark"], roles["accent"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=MICRO_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    lit = _mix(window, lamp, 0.30)
    dim = _mix(window, dark, 0.40)
    neon = _mix(accent, lamp, 0.35)
    # Existing B01 windows are arranged in five columns and four visible
    # floors.  Small inset panes and alternating lit pixels add the repeated
    # cadence of the reference without replacing the facade silhouette.
    xs = (-5.31, -2.66, 0.0, 2.66, 5.31)
    ys = (1.72, 3.78, 5.84, 7.90)
    for row, y in enumerate(ys):
        for column, x in enumerate(xs):
            add_detail(
                f"pixel-q05-r32-b01-window-inset-{row}-{column}", (0.72, 0.055, 0.025),
                (x, y, -5.075), lit if (row + column) % 3 else dim,
                "facade_window_micro_inset", "photo_supported_window_grid", MICRO_VOXEL,
            )
            for light_index, offset in enumerate((-0.24, 0.0, 0.24)):
                add_detail(
                    f"pixel-q05-r32-b01-window-light-{row}-{column}-{light_index}", (0.055, 0.055, 0.018),
                    (x + offset, y + 0.20, -5.03), neon if (row + column + light_index) % 7 == 0 else lit,
                    "facade_window_light_pixel", "photo_palette_window_completion", MICRO_VOXEL,
                )
    # A few balcony undersides and facade seams give the eye depth cues between
    # the repeated windows; they remain render-only.
    for row, y in enumerate((2.56, 4.62, 6.68, 8.74)):
        add_detail(f"pixel-q05-r32-b01-facade-seam-{row}", (14.0, 0.035, 0.035), (0.0, y, -5.02), trim, "facade_seam", "procedural_facade_detail", MICRO_VOXEL)
    for index, x in enumerate((-6.75, 6.75)):
        add_detail(f"pixel-q05-r32-b01-edge-light-{index}", (0.05, 8.8, 0.035), (x, 4.5, -5.03), _mix(lamp, dark, 0.20), "facade_edge_light", "procedural_facade_detail", MICRO_VOXEL)
    # Door signage is a small pixel motif, not a copied logo or text asset.
    _add_pattern_xy(
        scene, objects, "pixel-q05-r32-b01-entry-light-motif",
        ("..aaaa..", ".abbbba.", "abccccba", "abccccba", ".abbbba.", "..aaaa.."),
        (0.0, 1.54, -5.00), (0.10, 0.09), 0.018,
        {"a": dark, "b": neon, "c": lit}, "facade_entry_pixel_motif", "procedural_facade_detail", MICRO_VOXEL,
    )
    details.append("pixel-q05-r32-b01-entry-light-motif")

    layout_version = PIXEL_V32_LAYOUT_VERSIONS["building"]
    route_name = "pixel_style_sample_v32"
    detail_pass = "v32-b01-micro-window-and-light-pass-26"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_b01_micro_window_light_and_facade_seam_pass"
    layout["pixel_spec"]["detail_pass"] = detail_pass
    layout["pixel_spec"]["micro_surface_voxel"] = MICRO_VOXEL
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + ["micro_window_insets", "facade_light_pixels", "facade_seams"]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version
    manifest["version"] = "pixel-v32"
    manifest["provider_version"] = "pixel-voxel-v32"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V32 B01 立面细节候选：继承 V20/V26 建筑体块、窗格、前景线和碰撞，"
        "增加窗内明暗像素、霓虹灯点、立面缝和入口小型光纹；不复制参考图文字或角色，不改变路线。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = "candidate_facade_micro_window_light"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["micro_surface_voxel"] = MICRO_VOXEL
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + ["micro_window_insets", "facade_light_pixels", "facade_seams"]
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details
    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V32 · B01 立面微窗格与灯点候选\n\n"
        "在已有建筑候选上补充窗内明暗、霓虹灯点、立面缝和入口光纹；碰撞和路线保持继承。\n"
        "视觉质量仍为 unverified。\n", encoding="utf-8",
    )
    return manifest


def _build_street_detail_v32(image_path: Path, output_dir: Path, scene_id: str, base_builder) -> dict[str, object]:
    payload = base_builder(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    trim, window, lamp, dark, accent, plant = roles["trim"], roles["window"], roles["lamp"], roles["dark"], roles["accent"], roles["plant"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=MICRO_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    lit = _mix(window, lamp, 0.24)
    dim = _mix(window, dark, 0.42)
    neon = _mix(accent, lamp, 0.35)
    # Add smaller windows on the road-facing inner faces of the existing
    # building rows, where the first-person camera actually sees them.
    for side, x in (("left", -5.10), ("right", 5.10)):
        for row, y in enumerate((1.58, 2.66, 3.74)):
            for column, z in enumerate((4.88, 3.98, 0.38, -3.22, -7.12, -11.0)):
                add_detail(
                    f"pixel-q05-r32-s01-{side}-window-inset-{row}-{column}", (0.025, 0.46, 0.34),
                    (x, y, z), lit if (row + column) % 3 else dim,
                    "street_window_micro_inset", "photo_supported_facade_grid", MICRO_VOXEL,
                )
                add_detail(
                    f"pixel-q05-r32-s01-{side}-window-light-{row}-{column}", (0.018, 0.07, 0.09),
                    (x + (0.04 if side == "left" else -0.04), y + 0.12, z + 0.12),
                    neon if (row + column) % 8 == 0 else lit, "street_window_light_pixel", "photo_palette_window_completion", MICRO_VOXEL,
                )
    # Street-level sign/light markers break up the long road plane and echo the
    # reference's luminous urban rhythm without adding fake collision barriers.
    for index, z in enumerate((4.50, 1.0, -2.5, -6.0, -9.5)):
        add_detail(f"pixel-q05-r32-s01-lane-light-{index}", (0.10, 0.035, 0.22), (0.0, 0.18, z), neon if index % 2 else lit, "street_lane_light", "procedural_street_detail", MICRO_VOXEL)
    for index, (x, z) in enumerate(((-4.95, 4.70), (4.95, -6.00))):
        add_detail(f"pixel-q05-r32-s01-sign-pole-{index}", (0.06, 2.2, 0.06), (x, 1.25, z), dark, "street_sign_pole", "procedural_street_detail", MICRO_VOXEL)
        add_detail(f"pixel-q05-r32-s01-sign-light-{index}", (0.18, 0.12, 0.04), (x, 2.35, z), neon, "street_sign_light", "photo_palette_accent", MICRO_VOXEL)
    # Tree crowns get a small highlight/shadow breakup, not uniform random
    # noise, so they retain the existing silhouette and stay non-colliding.
    for index, (x, y, z) in enumerate(((-4.45, 2.15, 4.25), (4.35, 2.12, -8.50), (-4.50, 2.15, -11.0), (4.45, 2.05, 1.5))):
        add_detail(f"pixel-q05-r32-s01-tree-highlight-{index}", (0.42, 0.18, 0.18), (x - 0.18, y, z), _mix(plant, lamp, 0.12), "tree_pixel_highlight", "photo_supported_vegetation", FURNITURE_VOXEL)
        add_detail(f"pixel-q05-r32-s01-tree-shadow-{index}", (0.38, 0.16, 0.18), (x + 0.16, y - 0.16, z), _shade(plant, 0.65), "tree_pixel_shadow", "procedural_vegetation_detail", FURNITURE_VOXEL)

    layout_version = PIXEL_V32_LAYOUT_VERSIONS["street"]
    route_name = "pixel_style_sample_v32"
    detail_pass = "v32-s01-micro-window-and-light-pass-26"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_s01_micro_window_light_and_tree_layer_pass"
    layout["pixel_spec"]["detail_pass"] = detail_pass
    layout["pixel_spec"]["micro_surface_voxel"] = MICRO_VOXEL
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + ["street_micro_windows", "street_light_rhythm", "tree_pixel_layers"]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version
    manifest["version"] = "pixel-v32"
    manifest["provider_version"] = "pixel-voxel-v32"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V32 S01 街道微细节候选：继承 V19/V26 道路、建筑、人车树分离、"
        "碰撞和路线，增加道路两侧内向窗格、窗内灯点、车道灯、路牌和树冠明暗簇；不新增虚构墙体。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = "candidate_street_micro_window_light"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["micro_surface_voxel"] = MICRO_VOXEL
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + ["street_micro_windows", "street_light_rhythm", "tree_pixel_layers"]
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details
    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V32 · S01 街道微窗格与灯点候选\n\n"
        "在已有街道候选上补充道路两侧窗内像素、车道灯、路牌和树冠明暗；碰撞和路线保持继承。\n"
        "视觉质量仍为 unverified。\n", encoding="utf-8",
    )
    return manifest


def build_pixel_building_v32(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r32-b01") -> dict[str, object]:
    return _build_building_detail_v32(image_path, output_dir, scene_id, build_pixel_building_v26)


def build_pixel_street_v32(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r32-s01") -> dict[str, object]:
    return _build_street_detail_v32(image_path, output_dir, scene_id, build_pixel_street_v26)


# V33 rotates the Q03 fine-detail pass to the two remaining representative
# samples.  It keeps V25/V24 room and collision contracts intact and adds only
# authored, image-supported surface cues: corridor glazing/door panels and
# repeated ceiling/floor rhythm, plus separated snow ridge facets and a
# readable foreground fence/path for N01.  Decorative pieces are non-colliding.
PIXEL_V33_LAYOUT_VERSIONS = {
    "corridor": "pixel-v33-i01-window-door-surface-pass-27",
    "nature": "pixel-v33-n01-ridge-fence-surface-pass-27",
}


def _build_corridor_detail_v33(image_path: Path, output_dir: Path, scene_id: str, base_builder) -> dict[str, object]:
    base_builder(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    wall, floor = roles["wall"], roles["floor"]
    trim, window = roles["trim"], roles["window"]
    wood, metal = roles["wood"], roles["metal"]
    lamp, dark, accent = roles["lamp"], roles["dark"], roles["accent"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=MICRO_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    def add_yz(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_yz(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    glass_dark = _mix(window, dark, 0.32)
    glass_mid = _mix(window, accent, 0.28)
    glass_high = _mix(window, wall, 0.18)
    door_mid = _mix(wood, wall, 0.18)
    door_shadow = _mix(wood, dark, 0.26)

    # I01 has a repeated left-side window rhythm and a repeated right-side
    # wooden-door rhythm.  Small inner silhouettes make each opening read as
    # depth and material rather than a uniform blue/brown slab.
    window_centres = (3.50, 0.0, -3.50, -7.00)
    window_pattern = (
        "..aa....aa..",
        ".abbb..bbba.",
        "abccccccccba",
        "abccddccddba",
        "abccccccccba",
        ".abbb..bbba.",
        "..aa....aa..",
    )
    for index, z in enumerate(window_centres):
        add_yz(
            f"pixel-q05-r33-i01-window-depth-{index}", window_pattern,
            (-2.255, 1.45, z), (0.105, 0.22), 0.018,
            {"a": glass_dark, "b": glass_mid, "c": glass_high, "d": _mix(glass_mid, dark, 0.35)},
            "window_depth_pixel_surface", "photo_supported_window_opening",
        )
        # Exterior skyline strips are deliberately small and layered behind
        # the mullion; they preserve the original photo's outside-city cue
        # without turning the window into a flat poster.
        for tower, (y, height, colour) in enumerate(((0.82, 0.48, glass_dark), (1.28, 0.75, glass_mid), (1.84, 0.36, glass_high))):
            add_detail(
                f"pixel-q05-r33-i01-window-city-tower-{index}-{tower}", (0.28, height, 0.035),
                (-2.235, y + height * 0.5, z), colour, "window_city_depth", "photo_palette_upper", MICRO_VOXEL,
            )

    door_pattern = (
        "aaaaaaaaaa",
        "abbbbbbbba",
        "abccddccba",
        "abccccccba",
        "abbbbbbbba",
        "abccddccba",
        "abccccccba",
        "abbbbbbbba",
        "aaaaaaaaaa",
    )
    for index, z in enumerate(window_centres):
        add_yz(
            f"pixel-q05-r33-i01-door-panel-{index}", door_pattern,
            (2.235, 1.42, z), (0.10, 0.18), 0.018,
            {"a": door_shadow, "b": door_mid, "c": _mix(wood, accent, 0.18), "d": _mix(metal, wood, 0.18)},
            "door_panel_pixel_surface", "photo_supported_door_opening",
        )
        add_detail(
            f"pixel-q05-r33-i01-door-handle-highlight-{index}", (0.035, 0.06, 0.12),
            (2.18, 1.42, z + 0.18), _mix(lamp, metal, 0.28), "door_hardware_detail", "photo_supported_door_hardware", MICRO_VOXEL,
        )

    # The source corridor's ceiling fixtures and glossy tile floor are strong
    # perspective cues.  Add a compact luminous core and broken grout rhythm,
    # not a full-screen texture.
    for index, z in enumerate((4.30, 2.15, 0.08, -2.05, -4.20, -6.35, -8.50)):
        add_detail(f"pixel-q05-r33-i01-ceiling-light-core-{index}", (0.18, 0.035, 0.08), (0.0, 3.61, z), _mix(lamp, wall, 0.22), "ceiling_fixture_pixel", "photo_supported_ceiling_light", MICRO_VOXEL)
        add_detail(f"pixel-q05-r33-i01-ceiling-light-shadow-{index}", (0.34, 0.025, 0.12), (0.0, 3.53, z), _mix(dark, trim, 0.30), "ceiling_fixture_pixel", "procedural_fixture_shadow", MICRO_VOXEL)
    for index, z in enumerate((4.90, 3.85, 2.80, 1.75, 0.70, -0.35, -1.40, -2.45, -3.50, -4.55, -5.60, -6.65, -7.70, -8.75)):
        for side, x in enumerate((-1.35, 1.35)):
            add_detail(
                f"pixel-q05-r33-i01-floor-tile-highlight-{index}-{side}", (0.62, 0.018, 0.025),
                (x, 0.15, z), _mix(floor, wall, 0.16), "floor_tile_surface", "photo_supported_floor_tile", MICRO_VOXEL,
            )

    # The central bench is the only large free-standing anchor in the I01
    # candidate; a seat cap and two legs give it a recognizable silhouette.
    add_detail("pixel-q05-r33-i01-bench-seat-highlight", (1.18, 0.045, 0.12), (0.0, 0.91, -1.0), _mix(wood, wall, 0.22), "bench_surface_detail", "photo_inferred_bench", MICRO_VOXEL)
    for side, x in enumerate((-0.48, 0.48)):
        add_detail(f"pixel-q05-r33-i01-bench-leg-{side}", (0.10, 0.56, 0.10), (x, 0.46, -1.0), _mix(wood, dark, 0.25), "bench_surface_detail", "photo_inferred_bench", FURNITURE_VOXEL)

    layout_version = PIXEL_V33_LAYOUT_VERSIONS["corridor"]
    route_name = "pixel_style_sample_v33"
    detail_pass = "v33-i01-window-door-surface-pass-27"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_i01_window_door_surface_and_perspective_rhythm"
    layout["pixel_spec"]["detail_pass"] = detail_pass
    layout["pixel_spec"]["micro_surface_voxel"] = MICRO_VOXEL
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + [
        "window_depth_pixel_surfaces", "door_panel_pixel_surfaces", "corridor_floor_tile_rhythm", "corridor_fixture_rhythm",
    ]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version
    manifest["version"] = "pixel-v33"
    manifest["provider_version"] = "pixel-voxel-v33"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V33 I01 走廊细节候选：继承 V25 的布局、暖窗光影、碰撞和路线，"
        "为重复窗户增加外景深度像素，为木门增加分格、门锁高光，并补充顶灯核心、地砖节奏和中央长椅分件；"
        "全部新增件不参与碰撞，未把程序补全称为照片真实复原。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = "candidate_corridor_window_door_surface"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["micro_surface_voxel"] = MICRO_VOXEL
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + [
        "window_depth_pixel_surfaces", "door_panel_pixel_surfaces", "corridor_floor_tile_rhythm", "corridor_fixture_rhythm",
    ]
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details
    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V33 · I01 走廊窗门表面候选\n\n"
        "继承 V25 室内布局、灯光、碰撞和路线；增加窗口外景深度、门板分格、门锁、顶灯核心、地砖节奏和长椅分件。\n"
        "新增细节不参与碰撞，视觉质量仍为 unverified。\n", encoding="utf-8",
    )
    return manifest


def _build_nature_detail_v33(image_path: Path, output_dir: Path, scene_id: str, base_builder) -> dict[str, object]:
    base_builder(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    floor, window = roles["floor"], roles["window"]
    trim, dark, accent, lamp = roles["trim"], roles["dark"], roles["accent"], roles["lamp"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=MICRO_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    def add_xy(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_xy(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    snow_light = _mix(window, [248, 250, 246], 0.52)
    snow_mid = _mix(window, accent, 0.26)
    snow_shadow = _mix(window, dark, 0.38)
    fence = _mix(dark, window, 0.26)

    # N01's source separates near rolling snow, middle ridges and a far alpine
    # line.  Add small, ordered facet patches at those depths rather than one
    # large noisy texture; the existing ridge bodies remain the silhouette.
    ridge_specs = (
        ("near", -7.2, 0.34, 2.10, 0.42),
        ("mid", -12.7, 0.24, 1.55, 0.30),
        ("far", -17.3, 0.16, 1.10, 0.22),
    )
    ridge_pattern = (
        "....aa....",
        "...abbaa...",
        "..abbccba..",
        ".abccccbba.",
        "abbbbbbbbba",
    )
    for ridge_name, z, y, scale, _ in ridge_specs:
        for peak_index, x in enumerate((-7.0, -3.7, -0.4, 3.0, 6.4)):
            add_xy(
                f"pixel-q05-r33-n01-{ridge_name}-facet-{peak_index}", ridge_pattern,
                (x, y, z), (0.20 * scale, 0.14 * scale), 0.026,
                {"a": snow_shadow, "b": snow_mid, "c": snow_light},
                "mountain_pixel_facet", "photo_supported_horizon",
            )
    # Foreground snow receives stepped blue shadow bands and compact track
    # marks, matching the source's directional terrain cues without modifying
    # the walkable ground or its collision envelope.
    for index, (x, z, width) in enumerate(((-4.4, 5.3, 1.9), (-2.6, 3.9, 1.2), (2.9, 2.6, 1.7), (-3.4, -0.2, 1.5), (3.5, -3.5, 1.8), (-1.8, -5.8, 1.3))):
        add_detail(
            f"pixel-q05-r33-n01-snow-shadow-band-{index}", (width, 0.025, 0.15),
            (x, 0.28, z), snow_shadow if index % 2 else snow_mid, "snow_surface_detail", "photo_supported_near_ground", MICRO_VOXEL,
        )
    for index, z in enumerate((5.6, 4.9, 4.2, 3.5, 2.8, 2.1, 1.4, 0.7, 0.0, -0.7, -1.4, -2.1, -2.8, -3.5, -4.2, -4.9, -5.6)):
        x = -0.34 if index % 2 else 0.28
        add_detail(
            f"pixel-q05-r33-n01-snow-track-{index}", (0.26, 0.025, 0.12),
            (x, 0.30, z), _mix(snow_shadow, floor, 0.22), "snow_surface_detail", "photo_supported_near_ground", MICRO_VOXEL,
        )

    # The foreground fence is a strong photo anchor.  Add post caps, brace
    # nodes and alternating wire highlights so it reads as a coherent object
    # when the player turns, while preserving its existing non-blocking status.
    for index, x in enumerate((-4.5, -3.0, -1.5, 0.0, 1.5, 3.0, 4.5)):
        add_detail(f"pixel-q05-r33-n01-fence-post-cap-{index}", (0.13, 0.12, 0.13), (x, 2.22, 6.0), _mix(fence, snow_mid, 0.22), "foreground_fence_detail", "photo_supported_foreground_fence", FURNITURE_VOXEL)
        add_detail(f"pixel-q05-r33-n01-fence-post-shadow-{index}", (0.06, 0.24, 0.06), (x + 0.06, 1.00, 6.03), _mix(fence, dark, 0.28), "foreground_fence_detail", "procedural_fence_shadow", MICRO_VOXEL)
    for index, x in enumerate((-3.75, -2.25, -0.75, 0.75, 2.25, 3.75)):
        add_detail(f"pixel-q05-r33-n01-fence-brace-node-{index}", (0.09, 0.09, 0.09), (x, 1.42, 6.0), _mix(fence, lamp, 0.12), "foreground_fence_detail", "photo_supported_foreground_fence", MICRO_VOXEL)

    layout_version = PIXEL_V33_LAYOUT_VERSIONS["nature"]
    route_name = "pixel_style_sample_v33"
    detail_pass = "v33-n01-ridge-fence-surface-pass-27"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_n01_ridge_facet_snow_path_and_fence_surface"
    layout["pixel_spec"]["detail_pass"] = detail_pass
    layout["pixel_spec"]["micro_surface_voxel"] = MICRO_VOXEL
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + [
        "multi_depth_ridge_facets", "snow_shadow_bands", "snow_track_marks", "fence_post_pixel_layers",
    ]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version
    manifest["version"] = "pixel-v33"
    manifest["provider_version"] = "pixel-voxel-v33"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V33 N01 雪山细节候选：继承 V24 的冷色日光、分层山体、围栏碰撞安全余量和路线，"
        "增加近中远山脊的有序雪面像素、前景雪影/脚印和围栏柱帽/节点；不把天空或大平面当作山体，不改变碰撞。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = "candidate_nature_ridge_snow_fence_surface"
    manifest["quality_metrics"]["lighting_status"] = "inherited_outdoor_cool_daylight_v2"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["micro_surface_voxel"] = MICRO_VOXEL
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + [
        "multi_depth_ridge_facets", "snow_shadow_bands", "snow_track_marks", "fence_post_pixel_layers",
    ]
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details
    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V33 · N01 雪脊与围栏表面候选\n\n"
        "继承 V24 自然层次、冷色日光、碰撞和路线；增加近中远雪脊面、雪影/足迹和围栏细节。\n"
        "新增细节不参与碰撞，视觉质量仍为 unverified。\n", encoding="utf-8",
    )
    return manifest


def build_pixel_corridor_v33(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r33-i01") -> dict[str, object]:
    return _build_corridor_detail_v33(image_path, output_dir, scene_id, build_pixel_corridor_v25)


def build_pixel_nature_v33(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r33-n01") -> dict[str, object]:
    return _build_nature_detail_v33(image_path, output_dir, scene_id, build_pixel_nature_v24)


# V34 is an isolated lighting comparison for the exterior candidates.  It does
# not add geometry, alter camera, or change collision boxes; the purpose is to
# test whether the darker V32 night/street candidates need a clearer value
# hierarchy before another semantic-detail pass is attempted.
PIXEL_V34_LAYOUT_VERSIONS = {
    "street": "pixel-v34-s01-lighting-readability-pass-28",
    "building": "pixel-v34-b01-lighting-readability-pass-28",
}


def _build_exterior_lighting_v34(image_path: Path, output_dir: Path, scene_id: str, base_builder, profile: str) -> dict[str, object]:
    base_builder(image_path, output_dir, scene_id)
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    layout_version = PIXEL_V34_LAYOUT_VERSIONS[profile]
    route_name = "pixel_style_sample_v34"
    sample_name = "S01 街道" if profile == "street" else "B01 建筑"
    preset = "street_soft_daylight_v3" if profile == "street" else "facade_blue_hour_v3"
    detail_pass = f"v34-{('s01' if profile == 'street' else 'b01')}-lighting-readability-pass-28"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_exterior_value_hierarchy_lighting_comparison"
    layout.setdefault("pixel_spec", {})["detail_pass"] = detail_pass
    layout["pixel_spec"]["lighting_preset"] = preset
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + ["directional_exterior_value_hierarchy_v3"]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version
    manifest["version"] = "pixel-v34"
    manifest["provider_version"] = "pixel-voxel-v34"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        f"像素风 V34 {sample_name} 光影对照候选：完全继承 V32 的体块、微细节、相机、碰撞和路线，"
        f"只切换到 {preset}，提高暗部可读性、窗口/灯点层次和前后景分离；不改变几何，需与 V32 截图并排决定是否保留。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["lighting_status"] = "candidate_exterior_value_hierarchy_v3"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["lighting_preset"] = preset
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + ["directional_exterior_value_hierarchy_v3"]
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        f"Luna 像素风样板 V34 · {sample_name} 光影可读性对照候选\n\n"
        "继承 V32 几何、微细节、碰撞和路线；仅提高外景暗部、窗口灯点和前后景层次。\n"
        "这是隔离对照，视觉质量仍为 unverified。\n", encoding="utf-8",
    )
    return manifest


def build_pixel_street_v34(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r34-s01") -> dict[str, object]:
    return _build_exterior_lighting_v34(image_path, output_dir, scene_id, build_pixel_street_v32, "street")


def build_pixel_building_v34(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r34-b01") -> dict[str, object]:
    return _build_exterior_lighting_v34(image_path, output_dir, scene_id, build_pixel_building_v32, "building")


# V35 is the next Q03 semantic-composition pass.  It keeps V34's lighting,
# camera, route and collision contract, but adds image-specific anchors that
# are visible in S01/B01: road markings and bicycle-lane rhythm for the
# top-down street photo, and staggered warm windows, balconies, service units
# and stepped foreground wires for the night facade photo.
PIXEL_V35_LAYOUT_VERSIONS = {
    "street": "pixel-v35-s01-semantic-road-composition-pass-29",
    "building": "pixel-v35-b01-semantic-facade-composition-pass-29",
}


def _build_street_semantic_v35(image_path: Path, output_dir: Path, scene_id: str) -> dict[str, object]:
    base_builder = build_pixel_street_v34
    base_builder(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    floor, wall = roles["floor"], roles["wall"]
    wood, metal, window = roles["wood"], roles["metal"], roles["window"]
    plant, lamp, dark, accent, trim = roles["plant"], roles["lamp"], roles["dark"], roles["accent"], roles["trim"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=MICRO_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    lane = _mix(_mix(wood, lamp, 0.18), [190, 72, 66], 0.55)
    lane_shadow = _mix(lane, dark, 0.24)
    marking = _mix(window, [238, 238, 220], 0.62)
    pavement = _mix(floor, wall, 0.18)
    bicycle = _mix(accent, window, 0.16)

    # The source image is a high-angle crossing with a red bicycle lane.  Put
    # the cue on the walkable road surface, not in the skybox or as a card.
    add_detail("pixel-q05-r35-s01-bike-lane-surface", (2.05, 0.035, 10.40), (-3.10, 0.27, -0.65), lane, "road_marking", "photo_supported_bike_lane", FURNITURE_VOXEL)
    for index, z in enumerate((4.55, 2.85, 1.15, -0.55, -2.25, -3.95, -5.65)):
        add_detail(f"pixel-q05-r35-s01-bike-lane-dash-{index}", (0.18, 0.045, 0.72), (-3.10, 0.31, z), lane_shadow, "road_marking_detail", "photo_supported_bike_lane", MICRO_VOXEL)
    for index, x in enumerate((-3.90, -2.60, -1.30, 0.0, 1.30, 2.60, 3.90)):
        add_detail(f"pixel-q05-r35-s01-crosswalk-stripe-{index}", (0.72, 0.045, 0.52), (x, 0.31, 4.05), marking, "crosswalk_detail", "photo_supported_crosswalk", FURNITURE_VOXEL)
    # A compact pixel bicycle icon makes the lane semantic without copying the
    # source's painted glyph as an image texture.
    for index, x in enumerate((-3.43, -2.77)):
        add_detail(f"pixel-q05-r35-s01-bike-icon-wheel-{index}", (0.08, 0.05, 0.34), (x, 0.34, -4.65), bicycle, "bike_lane_icon", "photo_supported_bike_lane", MICRO_VOXEL)
    add_detail("pixel-q05-r35-s01-bike-icon-frame", (0.60, 0.05, 0.07), (-3.10, 0.35, -4.65), bicycle, "bike_lane_icon", "photo_supported_bike_lane", MICRO_VOXEL)
    add_detail("pixel-q05-r35-s01-bike-icon-stem", (0.07, 0.05, 0.34), (-2.86, 0.35, -4.42), bicycle, "bike_lane_icon", "photo_supported_bike_lane", MICRO_VOXEL)

    # Make the sidewalks read as tiled, tree-lined edges like the source.
    for side, x in (("left", -5.62), ("right", 5.62)):
        for index, z in enumerate((5.4, 4.25, 3.10, 1.95, 0.80, -0.35, -1.50, -2.65, -3.80, -4.95, -6.10)):
            add_detail(f"pixel-q05-r35-s01-sidewalk-tile-{side}-{index}", (1.55, 0.025, 0.92), (x, 0.34, z), pavement if index % 2 else _mix(pavement, trim, 0.14), "sidewalk_surface_detail", "photo_supported_sidewalk", MICRO_VOXEL)

    # Existing tree masses remain the collision-free silhouettes.  These
    # ordered clusters add canopy depth and highlights instead of random noise.
    for tree_index, (x, z) in enumerate(((-4.45, 4.25), (4.35, -8.50), (-4.50, -11.0), (4.45, 1.50))):
        for leaf_index, (dx, dy, dz, colour) in enumerate((
            (-0.48, 2.30, 0.0, _shade(plant, 0.72)), (-0.20, 2.62, 0.04, plant),
            (0.16, 2.42, 0.0, _mix(plant, window, 0.16)), (0.48, 2.72, -0.04, _shade(plant, 0.82)),
            (0.0, 3.02, 0.0, _mix(plant, lamp, 0.10)),
        )):
            add_detail(f"pixel-q05-r35-s01-tree-canopy-{tree_index}-{leaf_index}", (0.52, 0.34, 0.46), (x + dx, dy, z + dz), colour, "tree_canopy_detail", "photo_supported_tree_canopy", FURNITURE_VOXEL)

    # A few separated riders and bicycles preserve the source's foreground
    # human-scale cue without pretending to reconstruct identifiable people.
    for person_index, (x, z, body_colour) in enumerate(((-2.30, 3.10, wood), (3.45, 2.60, accent), (4.15, 0.95, window))):
        add_detail(f"pixel-q05-r35-s01-person-{person_index}-body", (0.24, 0.90, 0.24), (x, 0.78, z), body_colour, "person_proxy", "photo_supported_foreground_person", FURNITURE_VOXEL)
        add_detail(f"pixel-q05-r35-s01-person-{person_index}-head", (0.30, 0.30, 0.30), (x, 1.42, z), _mix(wood, lamp, 0.18), "person_proxy", "photo_supported_foreground_person", MICRO_VOXEL)
        add_detail(f"pixel-q05-r35-s01-bike-{person_index}-wheel-a", (0.07, 0.38, 0.38), (x - 0.22, 0.40, z), bicycle, "bicycle_proxy", "photo_supported_foreground_bicycle", FURNITURE_VOXEL)
        add_detail(f"pixel-q05-r35-s01-bike-{person_index}-wheel-b", (0.07, 0.38, 0.38), (x + 0.22, 0.40, z), bicycle, "bicycle_proxy", "photo_supported_foreground_bicycle", FURNITURE_VOXEL)
        add_detail(f"pixel-q05-r35-s01-bike-{person_index}-frame", (0.50, 0.07, 0.07), (x, 0.72, z), bicycle, "bicycle_proxy", "photo_supported_foreground_bicycle", MICRO_VOXEL)

    layout_version = PIXEL_V35_LAYOUT_VERSIONS["street"]
    route_name = "pixel_style_sample_v35"
    detail_pass = "v35-s01-semantic-road-composition-pass-29"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_s01_photo_anchor_road_crossing_bicycle_tree_pass"
    layout["pixel_spec"]["detail_pass"] = detail_pass
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + ["bike_lane_surface", "crosswalk_rhythm", "sidewalk_tile_detail", "tree_canopy_layers", "human_bicycle_proxies"]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version
    manifest["version"] = "pixel-v35"
    manifest["provider_version"] = "pixel-voxel-v35"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V35 S01 街道语义构图候选：继承 V34 光影、道路体块、建筑、人车树分离、碰撞和路线，"
        "补充照片可核对的红色非机动车道、斑马线、路缘砖、树冠层、自行车和非识别性人形代理；"
        "新增件均不参与碰撞，不声称还原可识别人物。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = "candidate_street_photo_anchor_composition"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + ["bike_lane_surface", "crosswalk_rhythm", "sidewalk_tile_detail", "tree_canopy_layers", "human_bicycle_proxies"]
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details
    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V35 · S01 街道照片锚点构图候选\n\n"
        "继承 V34 的光影、碰撞和路线；以原图可核对的红色车道、斑马线、路缘、树冠、人车自行车层补足语义构图。\n"
        "新增细节不参与碰撞，视觉质量仍为 unverified。\n", encoding="utf-8",
    )
    return manifest


def _build_building_semantic_v35(image_path: Path, output_dir: Path, scene_id: str) -> dict[str, object]:
    base_builder = build_pixel_building_v34
    base_builder(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    wall, trim, window = roles["wall"], roles["trim"], roles["window"]
    wood, metal, lamp = roles["wood"], roles["metal"], roles["lamp"]
    plant, dark, accent = roles["plant"], roles["dark"], roles["accent"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=MICRO_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    warm = _mix(lamp, accent, 0.18)
    warm_dim = _mix(warm, dark, 0.26)
    glass = _mix(window, accent, 0.22)
    facade_mid = _mix(wall, trim, 0.24)

    # The source facade is irregular and dense rather than a single regular
    # grid.  Staggered room boxes and warm panes create that rhythm while
    # remaining shallow, render-only surface layers.
    window_specs = (
        (-5.75, 1.20, 0.92, 0.82, warm), (-3.75, 1.62, 0.70, 1.12, glass), (-1.45, 1.18, 0.84, 0.78, warm_dim),
        (1.10, 1.64, 0.76, 1.16, warm), (3.72, 1.20, 0.92, 0.84, glass), (5.82, 1.82, 0.68, 1.26, warm_dim),
        (-5.20, 3.45, 0.78, 0.94, glass), (-2.80, 3.30, 0.98, 0.72, warm_dim), (-0.25, 3.66, 0.70, 1.12, warm),
        (2.35, 3.18, 0.90, 0.88, glass), (5.18, 3.58, 0.78, 1.02, warm),
        (-5.72, 5.62, 0.72, 1.04, warm), (-3.35, 5.35, 0.94, 0.78, glass), (-0.85, 5.74, 0.82, 1.08, warm_dim),
        (1.80, 5.42, 0.98, 0.82, warm), (4.80, 5.78, 0.74, 1.12, glass),
        (-4.82, 7.55, 0.86, 0.82, warm_dim), (-2.15, 7.34, 0.70, 1.08, warm), (0.55, 7.68, 0.92, 0.88, glass),
        (3.38, 7.30, 0.74, 1.10, warm), (5.82, 7.78, 0.78, 0.78, warm_dim),
    )
    for index, (x, y, width, height, colour) in enumerate(window_specs):
        add_detail(f"pixel-q05-r35-b01-room-window-{index}", (width, height, 0.045), (x, y, -5.075), colour, "facade_room_window", "photo_supported_lit_window", FURNITURE_VOXEL)
        add_detail(f"pixel-q05-r35-b01-room-window-v-{index}", (0.045, height + 0.08, 0.035), (x, y, -5.045), trim, "facade_window_frame", "photo_supported_window_frame", MICRO_VOXEL)
        add_detail(f"pixel-q05-r35-b01-room-window-h-{index}", (width + 0.08, 0.045, 0.035), (x, y, -5.045), trim, "facade_window_frame", "photo_supported_window_frame", MICRO_VOXEL)
        for pane_index in range(2):
            add_detail(f"pixel-q05-r35-b01-room-window-pane-{index}-{pane_index}", (0.055, height * 0.62, 0.022), (x + (pane_index - 0.5) * width * 0.38, y - height * 0.10, -5.02), _mix(colour, dark, 0.14 if pane_index else 0.03), "facade_window_pane", "photo_supported_lit_window", MICRO_VOXEL)

    # Staggered balconies and protruding service boxes translate the source's
    # layered facade into actual shallow geometry with visible side edges.
    balcony_specs = ((-3.90, 2.42, 1.75), (2.95, 3.98, 2.05), (-2.55, 5.92, 1.65), (4.35, 7.72, 1.85), (-5.30, 8.58, 1.35))
    for index, (x, y, width) in enumerate(balcony_specs):
        add_detail(f"pixel-q05-r35-b01-balcony-slab-{index}", (width, 0.12, 0.46), (x, y, -4.90), _mix(trim, dark, 0.16), "balcony_structure", "photo_supported_balcony_layer", FURNITURE_VOXEL)
        add_detail(f"pixel-q05-r35-b01-balcony-front-{index}", (width, 0.32, 0.06), (x, y + 0.18, -4.66), facade_mid, "balcony_structure", "photo_supported_balcony_layer", FURNITURE_VOXEL)
        for rail_index in range(4):
            rail_x = x - width * 0.42 + rail_index * width * 0.28
            add_detail(f"pixel-q05-r35-b01-balcony-rail-{index}-{rail_index}", (0.045, 0.40, 0.045), (rail_x, y + 0.42, -4.62), trim, "balcony_detail", "photo_supported_balcony_railing", MICRO_VOXEL)
    for index, (x, y) in enumerate(((-6.05, 2.10), (5.40, 3.28), (-4.85, 6.22), (5.80, 7.35), (0.10, 9.08))):
        add_detail(f"pixel-q05-r35-b01-service-box-{index}", (0.52, 0.34, 0.18), (x, y, -4.82), _mix(metal, dark, 0.18), "facade_service_unit", "photo_supported_facade_service_unit", FURNITURE_VOXEL)
        add_detail(f"pixel-q05-r35-b01-service-box-light-{index}", (0.16, 0.06, 0.025), (x, y + 0.08, -4.71), lamp, "facade_service_unit", "photo_palette_lit_detail", MICRO_VOXEL)

    # Stepwise diagonal wire runs preserve foreground density without using a
    # texture card.  Each segment is intentionally short and non-colliding.
    wire_colour = _mix(dark, trim, 0.18)
    for wire_index, (x_start, y_start, direction) in enumerate(((-8.2, 7.90, 1), (-7.4, 5.90, 1), (7.6, 6.95, -1), (-7.8, 2.25, 1))):
        for segment in range(15):
            x = x_start + direction * segment * 1.05
            y = y_start - segment * 0.16
            add_detail(f"pixel-q05-r35-b01-wire-{wire_index}-{segment}", (0.72, 0.045, 0.045), (x, y, -4.58), wire_colour, "foreground_wire", "photo_supported_foreground_wire", MICRO_VOXEL)

    # A leafy top-corner silhouette keeps the source's foreground obstruction
    # and gives the facade a near/mid/far separation when the camera turns.
    for index, (x, y, z, colour) in enumerate(((-7.1, 7.6, -4.45, plant), (-6.65, 8.1, -4.40, _shade(plant, 0.72)), (-7.55, 8.25, -4.35, _mix(plant, lamp, 0.10)), (6.85, 9.1, -4.48, _shade(plant, 0.78)))):
        add_detail(f"pixel-q05-r35-b01-leaf-cluster-{index}", (0.74, 0.42, 0.34), (x, y, z), colour, "foreground_vegetation", "photo_supported_foreground_leaf", FURNITURE_VOXEL)

    layout_version = PIXEL_V35_LAYOUT_VERSIONS["building"]
    route_name = "pixel_style_sample_v35"
    detail_pass = "v35-b01-semantic-facade-composition-pass-29"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_b01_photo_anchor_window_balcony_wire_pass"
    layout["pixel_spec"]["detail_pass"] = detail_pass
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + ["irregular_lit_window_rhythm", "staggered_balconies", "service_units", "stepped_foreground_wires", "foreground_leaf_layers"]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version
    manifest["version"] = "pixel-v35"
    manifest["provider_version"] = "pixel-voxel-v35"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V35 B01 建筑语义构图候选：继承 V34 蓝调光影、楼体厚度、碰撞和外部路线，"
        "用原图可核对的错落暖窗、阳台层、空调/服务盒、密集前景电线和叶簇替代单一规则窗格；"
        "新增件均不参与碰撞，仍不承诺进入未知室内。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = "candidate_building_photo_anchor_composition"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + ["irregular_lit_window_rhythm", "staggered_balconies", "service_units", "stepped_foreground_wires", "foreground_leaf_layers"]
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details
    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V35 · B01 建筑照片锚点立面候选\n\n"
        "继承 V34 光影、碰撞和路线；增加错落窗内层、阳台、服务盒、前景电线和叶簇层。\n"
        "新增细节不参与碰撞，视觉质量仍为 unverified。\n", encoding="utf-8",
    )
    return manifest


def build_pixel_street_v35(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r35-s01") -> dict[str, object]:
    return _build_street_semantic_v35(image_path, output_dir, scene_id)


def build_pixel_building_v35(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r35-b01") -> dict[str, object]:
    return _build_building_semantic_v35(image_path, output_dir, scene_id)


# V26 applies the same isolated lighting-only comparison to the existing street
# and facade candidates.  The output remains a candidate until the screenshots
# and routes are reviewed; no geometry or collision data is regenerated here.
PIXEL_V26_LAYOUT_VERSIONS = {
    "street": "pixel-v26-s01-exterior-lighting-contrast-pass-20",
    "facade": "pixel-v26-b01-exterior-lighting-contrast-pass-20",
}


def _build_exterior_lighting_v26(
    image_path: Path,
    output_dir: Path,
    scene_id: str,
    base_builder,
    profile: str,
) -> dict[str, object]:
    payload = base_builder(image_path, output_dir, scene_id)
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    layout_version = PIXEL_V26_LAYOUT_VERSIONS[profile]
    route_name = "pixel_style_sample_v26"
    sample_name = "S01 街道" if profile == "street" else "B01 建筑"
    preset = "street_soft_daylight_v2" if profile == "street" else "facade_blue_hour_v2"
    detail_pass = f"v26-{('s01' if profile == 'street' else 'b01')}-exterior-lighting-contrast-pass-20"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_exterior_readability_lighting_contrast"
    layout.setdefault("pixel_spec", {})["detail_pass"] = detail_pass
    layout["pixel_spec"]["lighting_preset"] = preset
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + [
        "directional_exterior_contrast"
    ]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version

    manifest["version"] = "pixel-v26"
    manifest["provider_version"] = "pixel-voxel-v26"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        f"像素风 V26 {sample_name} 光影候选：完全复用既有几何、碰撞、相机和路线，"
        "仅收紧环境补光并增强方向性主光；建筑保留蓝调夜色并提高局部暖色补光，"
        "街道保留冷暖日景关系，用于检查道路、车辆、窗格和前景线层次；不改变布局。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["lighting_status"] = "candidate_exterior_contrast_v2"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["lighting_preset"] = preset
    manifest["pixel_spec"]["shadow_policy"] = "single_soft_key_contact_shadows_for_v26_candidate"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + [
        "directional_exterior_contrast"
    ]
    manifest["movement"]["collision_boxes"] = collision["boxes"]

    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        f"Luna 像素风样板 V26 · {sample_name}\n\n"
        "这是外部场景光影对照候选。几何、碰撞、相机和路线继承既有样片；\n"
        "仅调整环境光、方向性主光和局部补光，视觉质量仍为 unverified。\n",
        encoding="utf-8",
    )
    return manifest


def build_pixel_street_v26(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r26-s01") -> dict[str, object]:
    return _build_exterior_lighting_v26(image_path, output_dir, scene_id, build_pixel_street_v19, "street")


def build_pixel_building_v26(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r26-b01") -> dict[str, object]:
    return _build_exterior_lighting_v26(image_path, output_dir, scene_id, build_pixel_building_v20, "facade")


# Q03 street rotation.  S01's V12 candidate had the correct broad road and
# separated proxies, but the first view still read as a few large masses.  V19
# adds front-facing facade windows, vehicle faces, curb rhythm and clustered
# tree silhouettes.  As with the preceding visual passes, collision data is
# inherited unchanged and the candidate remains isolated.
PIXEL_V19_LAYOUT_VERSION = "pixel-v19-s01-street-object-readability-pass-13"


def _finalize_v19_street(
    image_path: Path,
    output_dir: Path,
    scene_id: str,
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    collisions: list[CollisionBox],
    movement: MovementProfile,
    palette: dict[str, object],
) -> dict[str, object]:
    spec = {
        **_v02_spec(),
        "detail_pass": "v19-s01-street-object-readability-pass-13",
        "lighting_preset": PIXEL_V11_LIGHTING["street"],
        "shadow_policy": "single_soft_key_contact_shadows_for_v11_only",
        "emissive_policy": "semantic_light_sources_only_low_global_lift",
        "image_specific_policy": "front_facing_facade_vehicle_tree_and_road_layers",
    }
    return _finalize_v02(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "street",
        "像素风 V19 S01 街道对象可读性候选：在 V12 道路、建筑体块、人车树分离和车道标线基础上补充朝向相机的窗格、车辆前脸、路缘节奏和树冠分层；保持俯拍照片与第一人称路线的区别，不承诺街景真实几何复原。",
        ["palette_cues", "road_direction", "foreground_object_separation", "photo_supported_road_building_vehicle_tree_cues"],
        ["facade_window_rhythm", "vehicle_front_layers", "tree_cluster_layers", "curb_and_road_surface", "collision_envelope"],
        template=SceneTemplate.street_descent,
        engine=SceneEngine.street,
        route_name="pixel_style_sample_v19",
        layout_version=PIXEL_V19_LAYOUT_VERSION,
        version="pixel-v19",
        provider_version="pixel-voxel-v19",
        pixel_spec=spec,
        layout_basis="q03_visual_index:s01:r19",
    )


def build_pixel_street_v19(image_path: Path, output_dir: Path, scene_id: str = "pixel-q03-r19-s01") -> dict[str, object]:
    """Build the isolated Q03 S01 street object-readability candidate."""

    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_street_v11
    )
    roles = palette["roles"]
    floor, wall, wood = roles["floor"], roles["wall"], roles["wood"]
    metal, plant, window, lamp = roles["metal"], roles["plant"], roles["window"], roles["lamp"]
    dark, accent, trim = roles["dark"], roles["accent"], roles["trim"]

    # Give each street-side mass a front facade with a repeated but bounded
    # window rhythm.  The pattern is placed on the actual front Z plane, not
    # as a full-photo billboard, so the blocks retain depth when the camera
    # turns.
    for side, x in (("left", -6.0), ("right", 6.0)):
        for building_index, z in enumerate((3.6, -2.0, -7.6)):
            front_z = z + 2.13
            for row_index, y in enumerate((1.30, 2.22, 3.14, 4.06)):
                for column_index, x_offset in enumerate((-0.52, 0.0, 0.52)):
                    colour = window if (row_index + column_index) % 3 else _mix(window, accent, 0.32)
                    _add_part(
                        scene, objects, [], f"pixel-q03-r19-s01-{side}-building-{building_index}-window-{row_index}-{column_index}",
                        (0.30, 0.42, 0.045), (x + x_offset, y, front_z), colour,
                        "building_window_detail", "photo_supported_window_line", grid=FURNITURE_VOXEL,
                    )
                    if column_index < 2:
                        _add_part(
                            scene, objects, [], f"pixel-q03-r19-s01-{side}-building-{building_index}-window-frame-{row_index}-{column_index}",
                            (0.035, 0.46, 0.055), (x + x_offset + 0.26, y, front_z + 0.01), trim,
                            "building_window_frame", "photo_supported_window_line", grid=MICRO_VOXEL,
                        )
            _add_part(
                scene, objects, [], f"pixel-q03-r19-s01-{side}-building-{building_index}-facade-band",
                (1.38, 0.055, 0.06), (x, 0.86, front_z + 0.02), _mix(wall, dark, 0.24),
                "building_facade_detail", "photo_inferred_background_building", grid=MICRO_VOXEL,
            )

    # Vehicles are separate low-poly proxies.  Add a windshield, grille and
    # lamp pattern to their camera-facing ends so they read as cars rather
    # than unrelated brown/grey blocks.
    for index, (x, z, body, glass) in enumerate(((-2.55, 1.2, wood, window), (2.65, -4.0, metal, accent))):
        _add_pattern_xy(
            scene, objects, f"pixel-q03-r19-s01-car-{index}-front",
            (".dddd.", "dabbad", "daccad", ".dddd."),
            (x, 0.82, z + 1.33), (0.18, 0.12), 0.035,
            {"a": glass, "b": _mix(glass, body, 0.24), "c": lamp, "d": dark},
            "vehicle_front_detail", "photo_supported_vehicle",
        )
        _add_part(
            scene, objects, [], f"pixel-q03-r19-s01-car-{index}-bumper",
            (1.12, 0.08, 0.07), (x, 0.35, z + 1.32), trim,
            "vehicle_front_detail", "procedural_completion", grid=MICRO_VOXEL,
        )
        for lamp_index, x_offset in enumerate((-0.44, 0.44)):
            _add_part(
                scene, objects, [], f"pixel-q03-r19-s01-car-{index}-headlamp-{lamp_index}",
                (0.16, 0.12, 0.035), (x + x_offset, 0.62, z + 1.34), lamp,
                "vehicle_front_detail", "procedural_completion", grid=MICRO_VOXEL,
            )

    # Trees gain trunk/branch separation and a small number of directed leaf
    # clusters.  The clusters are intentionally ordered silhouettes, not
    # random noise or flat image cards.
    for index, (x, z) in enumerate(((-4.35, 4.2), (4.25, -8.2), (-4.50, -11.0))):
        branch = _mix(wood, dark, 0.18)
        for branch_index, (dx, dy, dz, extents) in enumerate((
            (-0.36, 0.56, 0.0, (0.62, 0.10, 0.10)), (0.0, 0.78, 0.0, (0.10, 0.10, 0.72)),
            (0.36, 0.54, 0.0, (0.62, 0.10, 0.10)),
        )):
            _add_part(
                scene, objects, [], f"pixel-q03-r19-s01-tree-{index}-branch-{branch_index}",
                extents, (x + dx, 1.66 + dy, z + dz), branch,
                "tree_structure_detail", "photo_inferred_tree", grid=MICRO_VOXEL,
            )
        for leaf_index, (dx, dy, dz, colour) in enumerate((
            (-0.58, 2.15, 0.0, plant), (-0.28, 2.42, 0.0, _mix(plant, window, 0.12)),
            (0.0, 2.18, 0.18, plant), (0.34, 2.50, 0.0, _shade(plant, 0.76)),
            (0.62, 2.12, 0.0, plant), (0.0, 2.76, 0.0, _mix(plant, accent, 0.10)),
        )):
            _add_part(
                scene, objects, [], f"pixel-q03-r19-s01-tree-{index}-leaf-cluster-{leaf_index}",
                (0.46, 0.34, 0.46), (x + dx, dy, z + dz), colour,
                "tree_surface_detail", "photo_inferred_tree", grid=FURNITURE_VOXEL,
            )

    # Add a restrained road-perspective stripe and curb highlight to keep the
    # route legible from the first-person start camera.
    for index, z in enumerate((6.4, 5.0, 3.6, 2.2, 0.8, -0.6, -2.0, -3.4, -4.8, -6.2, -7.6, -9.0, -10.4)):
        _add_part(
            scene, objects, [], f"pixel-q03-r19-s01-road-perspective-highlight-{index}",
            (0.11, 0.018, 0.72), (0.0, 0.235, z), _mix(window, floor, 0.22),
            "road_surface_detail", "photo_supported_road_marking", grid=MICRO_VOXEL,
        )
    for side, x in (("left", -5.86), ("right", 5.86)):
        for index, z in enumerate((6.0, 3.2, 0.4, -2.4, -5.2, -8.0, -10.8)):
            _add_part(
                scene, objects, [], f"pixel-q03-r19-s01-curb-highlight-{side}-{index}",
                (0.035, 0.06, 1.10), (x, 0.43, z), _mix(trim, window, 0.18),
                "curb_surface_detail", "photo_supported_sidewalk", grid=MICRO_VOXEL,
            )

    return _finalize_v19_street(image_path, output_dir, scene_id, scene, objects, collisions, movement, palette)


# Q03 building rotation.  The V12 facade already has thickness, windows,
# balconies and foreground lines, but the dark first view compresses those
# into a regular grid.  V20 adds controlled facade courses, lit room patterns,
# balcony depth and roof/service silhouettes.  It stays external-only and
# inherits the existing boundary collision.
PIXEL_V20_LAYOUT_VERSION = "pixel-v20-b01-facade-layer-readability-pass-14"


def _finalize_v20_building(
    image_path: Path,
    output_dir: Path,
    scene_id: str,
    scene: trimesh.Scene,
    objects: list[dict[str, object]],
    collisions: list[CollisionBox],
    movement: MovementProfile,
    palette: dict[str, object],
) -> dict[str, object]:
    spec = {
        **_v02_spec(),
        "detail_pass": "v20-b01-facade-layer-readability-pass-14",
        "lighting_preset": PIXEL_V11_LIGHTING["facade"],
        "shadow_policy": "single_soft_key_contact_shadows_for_v11_only",
        "emissive_policy": "semantic_light_sources_only_low_global_lift",
        "image_specific_policy": "facade_courses_lit_room_patterns_balcony_depth_and_foreground_lines",
    }
    return _finalize_v02(
        image_path, output_dir, scene_id, scene, objects, collisions, movement, palette, "facade",
        "像素风 V20 B01 立面层次候选：在 V12 楼体厚度、窗格、阳台和前景线基础上补充分区立面课程、窗内房间像素、阳台底面与栏杆层、屋顶服务设备和夜色局部光点；保持外部观察边界，不承诺未知室内。",
        ["palette_cues", "facade_outline", "window_line_and_foreground_lines", "photo_supported_facade_and_night_layers"],
        ["facade_course_layers", "lit_room_patterns", "balcony_depth_layers", "roof_service_silhouettes", "foreground_line_detail", "collision_envelope"],
        template=SceneTemplate.facade_flight,
        engine=SceneEngine.facade,
        route_name="pixel_style_sample_v20",
        layout_version=PIXEL_V20_LAYOUT_VERSION,
        version="pixel-v20",
        provider_version="pixel-voxel-v20",
        pixel_spec=spec,
        layout_basis="q03_visual_index:b01:r20",
    )


def build_pixel_building_v20(image_path: Path, output_dir: Path, scene_id: str = "pixel-q03-r20-b01") -> dict[str, object]:
    """Build the isolated Q03 B01 facade-layer readability candidate."""

    scene, objects, collisions, palette, movement = _load_candidate_for_detail(
        image_path, output_dir, scene_id, build_pixel_building_v11
    )
    roles = palette["roles"]
    wall, floor, trim = roles["wall"], roles["floor"], roles["trim"]
    window, wood, lamp = roles["window"], roles["wood"], roles["lamp"]
    plant, accent, dark, metal = roles["plant"], roles["accent"], roles["dark"], roles["metal"]

    # The facade plane faces the start camera along -Z.  Put the new details
    # just in front of the facade's existing front face, keeping a thin
    # separation from the old layers so the result is stable in GLB viewers.
    facade_z = -5.30
    for course_index, y in enumerate((0.84, 2.86, 4.90, 6.94, 8.98)):
        _add_part(
            scene, objects, [], f"pixel-q03-r20-b01-facade-course-{course_index}",
            (13.70, 0.055, 0.065), (0.0, y, facade_z), _mix(trim, wall, 0.22),
            "facade_surface_detail", "photo_supported_building_mass", grid=MICRO_VOXEL,
        )
        if course_index < 4:
            for block_index, x in enumerate((-6.0, -3.0, 0.0, 3.0, 6.0)):
                _add_part(
                    scene, objects, [], f"pixel-q03-r20-b01-facade-block-{course_index}-{block_index}",
                    (1.22, 0.035, 0.045), (x + (0.18 if course_index % 2 else -0.12), y + 0.34, facade_z + 0.01),
                    _mix(wall, trim, 0.16 + (block_index % 2) * 0.08),
                    "facade_surface_detail", "photo_inferred_building_mass", grid=FURNITURE_VOXEL,
                )

    # Replace a flat pane read with four ordered interior pixels per window:
    # cool room field, dark mullion, warm source and small reflective edge.
    for row in range(4):
        y = 1.75 + row * 2.05
        for column in range(5):
            x = -5.30 + column * 2.65
            warm = (row + column) % 3 == 0
            room = _mix(window, lamp if warm else accent, 0.22 if warm else 0.12)
            _add_pattern_xy(
                scene, objects, f"pixel-q03-r20-b01-window-room-{row}-{column}",
                (".dddd.", "dabbad", "daccad", "dabbad", ".dddd."),
                (x, y, -5.255), (0.17, 0.18), 0.028,
                {"a": room, "b": _mix(room, dark, 0.26), "c": lamp if warm else window, "d": trim},
                "window_room_pixel_surface", "photo_supported_window_grid",
            )
            _add_part(
                scene, objects, [], f"pixel-q03-r20-b01-window-sill-{row}-{column}",
                (1.28, 0.07, 0.08), (x, y - 0.70, -5.24), _mix(trim, dark, 0.18),
                "window_detail", "procedural_completion", grid=MICRO_VOXEL,
            )

    # The entrance gets a legible recess, lintel, threshold and door split.
    _add_part(
        scene, objects, [], "pixel-q03-r20-b01-entry-recess",
        (2.34, 2.96, 0.06), (0.0, 1.52, -5.25), _mix(dark, trim, 0.20),
        "entry_surface_detail", "photo_supported_opening", grid=FURNITURE_VOXEL,
    )
    _add_part(
        scene, objects, [], "pixel-q03-r20-b01-entry-door",
        (1.46, 2.38, 0.04), (0.0, 1.28, -5.20), _mix(wood, dark, 0.32),
        "entry_surface_detail", "photo_supported_opening", grid=FURNITURE_VOXEL,
    )
    for index, x in enumerate((-0.58, 0.0, 0.58)):
        _add_part(
            scene, objects, [], f"pixel-q03-r20-b01-entry-door-panel-{index}",
            (0.38, 1.56, 0.035), (x, 1.28, -5.16), _mix(wood, window, 0.10 + index * 0.06),
            "entry_surface_detail", "photo_supported_opening", grid=MICRO_VOXEL,
        )
    _add_part(
        scene, objects, [], "pixel-q03-r20-b01-entry-lintel",
        (2.52, 0.14, 0.10), (0.0, 3.05, -5.18), _mix(trim, lamp, 0.12),
        "entry_detail", "procedural_completion", grid=FURNITURE_VOXEL,
    )

    # Balconies receive a slab underside and regular rail posts so their depth
    # remains visible during a lateral camera move.
    for index, (x, y) in enumerate(((-2.65, 3.78), (2.65, 5.83), (-2.65, 7.88), (2.65, 9.93))):
        _add_part(
            scene, objects, [], f"pixel-q03-r20-b01-balcony-under-{index}",
            (2.24, 0.10, 0.56), (x, y - 0.10, -5.03), _mix(trim, dark, 0.14),
            "balcony_surface_detail", "photo_supported_facade_layer", grid=FURNITURE_VOXEL,
        )
        for rail_index in range(5):
            _add_part(
                scene, objects, [], f"pixel-q03-r20-b01-balcony-rail-{index}-{rail_index}",
                (0.045, 0.46, 0.08), (x - 0.84 + rail_index * 0.42, y + 0.22, -4.72), trim,
                "balcony_detail", "procedural_completion", grid=MICRO_VOXEL,
            )
        _add_part(
            scene, objects, [], f"pixel-q03-r20-b01-balcony-rail-top-{index}",
            (2.10, 0.055, 0.08), (x, y + 0.44, -4.72), _mix(trim, window, 0.14),
            "balcony_detail", "procedural_completion", grid=MICRO_VOXEL,
        )

    # Rooftop units and the visible foreground service lines get distinct
    # caps/highlights, preserving the night-city silhouette and depth cues.
    for index, (x, y, width) in enumerate(((-1.6, 10.70, 1.86), (3.3, 10.70, 1.20), (-6.2, 0.82, 1.24), (6.2, 2.86, 1.62))):
        _add_part(
            scene, objects, [], f"pixel-q03-r20-b01-roof-unit-cap-{index}",
            (width * 0.72, 0.08, 0.56), (x, y + 0.22, -4.65), _mix(metal, dark, 0.14),
            "rooftop_detail", "photo_supported_building_mass", grid=FURNITURE_VOXEL,
        )
        _add_part(
            scene, objects, [], f"pixel-q03-r20-b01-roof-unit-light-{index}",
            (width * 0.44, 0.035, 0.045), (x, y + 0.30, -4.34), _mix(window, lamp, 0.26),
            "rooftop_detail", "photo_palette_upper", grid=MICRO_VOXEL,
        )
    for index, (x, y, z) in enumerate(((-8.0, 5.5, -1.6), (8.0, 4.0, -2.8), (-6.8, 1.0, -8.8))):
        _add_part(
            scene, objects, [], f"pixel-q03-r20-b01-service-line-node-{index}",
            (0.15, 0.15, 0.15), (x, y, z), _mix(lamp, accent, 0.18),
            "foreground_line_detail", "photo_inferred_foreground_line", grid=MICRO_VOXEL,
        )

    return _finalize_v20_building(image_path, output_dir, scene_id, scene, objects, collisions, movement, palette)


# V36 is a focused indoor semantic-detail pass.  It keeps the reviewed V33
# corridor and V31 living-room candidates as the geometry/collision baseline;
# only visible, image-supported surface layers are added.  The goal is more
# readable object separation, not a larger undifferentiated voxel count.
PIXEL_V36_LAYOUT_VERSIONS = {
    "corridor": "pixel-v36-i01-indoor-surface-separation-pass-30",
    "living_room": "pixel-v36-i02-indoor-surface-separation-pass-30",
}


def _build_indoor_precision_v36(
    image_path: Path,
    output_dir: Path,
    scene_id: str,
    base_builder,
    profile: str,
) -> dict[str, object]:
    base_builder(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    wall, floor = roles["wall"], roles["floor"]
    trim, window = roles["trim"], roles["window"]
    wood, metal = roles["wood"], roles["metal"]
    sofa, plant = roles["sofa"], roles["plant"]
    lamp, dark, accent = roles["lamp"], roles["dark"], roles["accent"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=MICRO_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    def add_yz(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_yz(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    def add_xy(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_xy(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    if profile == "corridor":
        glass_dark = _mix(window, dark, 0.34)
        glass_high = _mix(window, wall, 0.22)
        wood_mid = _mix(wood, wall, 0.20)
        metal_high = _mix(metal, lamp, 0.18)

        # Add a second, thinner frame hierarchy to the window bays.  The
        # existing V33 panes remain visible behind these rails, so the result
        # reads as glass + mullion + sill rather than a single coloured wall.
        for index, z in enumerate((3.50, 0.0, -3.50, -7.0)):
            add_detail(
                f"pixel-q05-r36-i01-window-sill-{index}", (0.07, 0.10, 1.72),
                (-2.16, 0.72, z), _mix(trim, wall, 0.14),
                "window_frame_detail", "photo_supported_window_sill", FURNITURE_VOXEL,
            )
            add_detail(
                f"pixel-q05-r36-i01-window-centre-mullion-{index}", (0.07, 1.86, 0.06),
                (-2.14, 1.55, z), trim,
                "window_frame_detail", "photo_supported_window_frame", MICRO_VOXEL,
            )
            add_yz(
                f"pixel-q05-r36-i01-window-reflection-{index}",
                ("..aa..", ".abb a.".replace(" ", ""), "abccba", ".abb a.".replace(" ", ""), "..aa.."),
                (-2.105, 1.70, z + 0.18), (0.075, 0.11), 0.014,
                {"a": glass_dark, "b": glass_high, "c": _mix(window, accent, 0.18)},
                "window_reflection_pixel", "photo_palette_upper",
            )

        # The source corridor has a long wall rail and a repeating ceiling
        # service/lighting rhythm.  These small pieces give scale to the long
        # room without changing its walkable shell.
        add_detail(
            "pixel-q05-r36-i01-right-wall-handrail", (0.055, 0.10, 12.80),
            (2.16, 1.02, -1.80), _mix(metal, trim, 0.22),
            "wall_handrail_detail", "photo_supported_wall_rail", FURNITURE_VOXEL,
        )
        for index, z in enumerate((3.92, 1.82, -0.28, -2.38, -4.48, -6.58, -8.68)):
            add_detail(
                f"pixel-q05-r36-i01-ceiling-vent-{index}", (0.42, 0.035, 0.24),
                (0.0, 3.70, z), _mix(metal, dark, 0.24),
                "ceiling_service_detail", "photo_supported_ceiling_service", FURNITURE_VOXEL,
            )
            add_detail(
                f"pixel-q05-r36-i01-ceiling-vent-light-{index}", (0.24, 0.018, 0.035),
                (0.0, 3.66, z - 0.08), _mix(lamp, wall, 0.20),
                "ceiling_service_detail", "photo_supported_ceiling_light", MICRO_VOXEL,
            )
        for index, z in enumerate((4.70, 3.55, 2.40, 1.25, 0.10, -1.05, -2.20, -3.35, -4.50, -5.65, -6.80, -7.95)):
            add_detail(
                f"pixel-q05-r36-i01-floor-grout-highlight-{index}", (3.40, 0.014, 0.018),
                (0.0, 0.226, z), _mix(floor, trim, 0.24),
                "floor_surface_detail", "photo_supported_floor_tile", MICRO_VOXEL,
            )

        # Split the door face into inset, trim and hardware highlights.  The
        # repeated pattern is a material rule, not a claim that every hidden
        # door has been reconstructed from the photograph.
        for index, z in enumerate((3.50, 0.0, -3.50, -7.0)):
            add_detail(
                f"pixel-q05-r36-i01-door-inset-{index}", (0.05, 1.28, 0.58),
                (2.15, 1.54, z), wood_mid,
                "door_panel_surface", "photo_supported_door_panel", FURNITURE_VOXEL,
            )
            for band, y in enumerate((0.58, 1.12, 2.30)):
                add_detail(
                    f"pixel-q05-r36-i01-door-trim-{index}-{band}", (0.035, 0.035, 0.64),
                    (2.12, y, z), _mix(wood, trim, 0.26),
                    "door_panel_surface", "photo_supported_door_trim", MICRO_VOXEL,
                )
            add_detail(
                f"pixel-q05-r36-i01-door-hardware-{index}", (0.035, 0.10, 0.055),
                (2.09, 1.48, z - 0.16), metal_high,
                "door_hardware_detail", "photo_supported_door_hardware", MICRO_VOXEL,
            )

        layout_version = PIXEL_V36_LAYOUT_VERSIONS["corridor"]
        detail_pass = "v36-i01-indoor-surface-separation-pass-30"
        generated_regions = [
            "window_mullion_and_reflection_layers", "corridor_handrail_scale_cue",
            "ceiling_service_rhythm", "floor_grout_rhythm", "door_inset_hardware_layers",
        ]
        note = (
            "像素风 V36 I01 走廊表面分离候选：继承 V33 的窗门、地砖、顶灯、碰撞和路线，"
            "增加窗台/中挺/反射小层、墙面扶手、顶面服务节奏、地砖缝和门板硬件；"
            "新增件只参与视觉表达，不改变可行走空间。"
        )
        quality_status = "candidate_indoor_surface_separation"
    else:
        sofa_light = _mix(sofa, wall, 0.30)
        sofa_shadow = _mix(sofa, trim, 0.38)
        table_edge = _mix(wood, metal, 0.24)
        rug = _mix(floor, accent, 0.16)
        leaf_dark = _shade(plant, 0.62)
        leaf_light = _mix(plant, lamp, 0.18)

        # The sofa is the largest foreground anchor in I02.  A stepped front
        # seam, arm caps and small cushion patterns make its parts legible from
        # the start and after a turn without changing the inherited proxy.
        for index, x in enumerate((-2.78, -1.20)):
            add_detail(
                f"pixel-q05-r36-i02-sofa-front-seam-{index}", (0.045, 0.54, 1.18),
                (x, 0.89, -1.34), sofa_shadow,
                "upholstery_seam_detail", "photo_supported_furniture", MICRO_VOXEL,
            )
            add_xy(
                f"pixel-q05-r36-i02-cushion-pixel-{index}",
                (".aa.", "abca", "abca", ".aa."),
                (x, 1.21, -1.28), (0.10, 0.10), 0.018,
                {"a": sofa_shadow, "b": sofa_light, "c": _mix(sofa, accent, 0.16)},
                "upholstery_pixel_detail", "photo_supported_cushion",
            )
        for index, x in enumerate((-3.70, 0.02)):
            add_detail(
                f"pixel-q05-r36-i02-sofa-arm-cap-{index}", (0.70, 0.08, 0.12),
                (x, 1.22, -1.36), sofa_light,
                "upholstery_edge_detail", "photo_supported_sofa_arm", FURNITURE_VOXEL,
            )

        # The round table receives a segmented top rim and visible pedestal
        # facets.  These are deliberately render-only, so collision remains
        # the tested inherited proxy.
        for index, (x, z) in enumerate(((0.60, 0.55), (1.90, 0.55), (1.25, -0.10), (1.25, 1.20))):
            add_detail(
                f"pixel-q05-r36-i02-table-rim-segment-{index}", (0.48, 0.035, 0.06),
                (x, 1.14, z), table_edge,
                "round_table_edge_detail", "photo_supported_furniture", MICRO_VOXEL,
            )
        for index, x in enumerate((1.08, 1.25, 1.42)):
            add_detail(
                f"pixel-q05-r36-i02-table-base-facet-{index}", (0.11, 0.42, 0.18),
                (x, 0.70, 0.55), _mix(metal, dark, 0.16 + index * 0.08),
                "round_table_base_detail", "photo_supported_furniture", FURNITURE_VOXEL,
            )

        # A rug border and a few directional floor pixels connect the table to
        # the room instead of leaving it on an unarticulated floor plane.
        for index, (size, position) in enumerate(((2.90, (1.25, 0.17, 0.55)), (2.90, (1.25, 0.17, 0.55)))):
            if index == 0:
                add_detail(
                    "pixel-q05-r36-i02-rug-front-border", (size, 0.025, 0.045),
                    (position[0], position[1], position[2] - 1.34), _mix(rug, trim, 0.24),
                    "rug_surface_detail", "photo_supported_rug", MICRO_VOXEL,
                )
            else:
                add_detail(
                    "pixel-q05-r36-i02-rug-side-border", (0.045, 0.025, 2.55),
                    (position[0] - 1.44, position[1], position[2]), _mix(rug, trim, 0.24),
                    "rug_surface_detail", "photo_supported_rug", MICRO_VOXEL,
                )

        # Vertical blind rhythm and a deeper plant silhouette reinforce the
        # rear opening and foreground layering visible in the source living
        # room, without using a flat photo card.
        for index, x in enumerate((0.38, 0.72, 1.06, 1.40, 2.08, 2.42, 2.76, 3.10)):
            add_detail(
                f"pixel-q05-r36-i02-window-blind-{index}", (0.035, 2.05, 0.045),
                (x, 2.38, -6.36), _mix(window, dark, 0.20 if index % 2 else 0.30),
                "window_blind_detail", "photo_supported_window_covering", MICRO_VOXEL,
            )
        add_detail(
            "pixel-q05-r36-i02-plant-stem", (0.07, 1.54, 0.07),
            (-3.55, 1.84, 0.44), _mix(plant, dark, 0.32),
            "vegetation_structure", "photo_supported_vegetation", MICRO_VOXEL,
        )
        for index, (x, y, z, colour) in enumerate((
            (-3.94, 2.12, 0.44, leaf_dark), (-3.70, 2.34, 0.44, leaf_light),
            (-3.40, 2.58, 0.44, plant), (-3.08, 2.82, 0.44, leaf_light),
            (-3.56, 3.10, 0.44, leaf_dark),
        )):
            add_detail(
                f"pixel-q05-r36-i02-plant-leaf-{index}", (0.42, 0.22, 0.20),
                (x, y, z), colour, "vegetation_surface_detail", "photo_supported_vegetation", FURNITURE_VOXEL,
            )

        layout_version = PIXEL_V36_LAYOUT_VERSIONS["living_room"]
        detail_pass = "v36-i02-indoor-surface-separation-pass-30"
        generated_regions = [
            "sofa_seam_and_cushion_layers", "round_table_rim_and_base_facets",
            "rug_border_scale_cue", "window_blind_rhythm", "plant_stem_leaf_layers",
        ]
        note = (
            "像素风 V36 I02 客厅表面分离候选：继承 V31 的微栅格沙发、圆桌、电视和窗外层次，"
            "增加沙发分缝/靠垫、圆桌边缘/底座分件、地毯边界、百叶节奏和植物茎叶；"
            "新增件只参与视觉表达，不改变碰撞和路线。"
        )
        quality_status = "candidate_indoor_surface_separation"

    route_name = "pixel_style_sample_v36"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = f"q05_{'i01' if profile == 'corridor' else 'i02'}_surface_separation_pass"
    layout.setdefault("pixel_spec", {})["detail_pass"] = detail_pass
    layout["pixel_spec"]["micro_surface_voxel"] = MICRO_VOXEL
    layout["pixel_spec"]["surface_density_policy"] = "named_semantic_layers_over_inherited_collision_shell"
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + generated_regions
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version
    manifest["version"] = "pixel-v36"
    manifest["provider_version"] = "pixel-voxel-v36"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = note
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = quality_status
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["micro_surface_voxel"] = MICRO_VOXEL
    manifest["pixel_spec"]["surface_density_policy"] = "named_semantic_layers_over_inherited_collision_shell"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + generated_regions
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details
    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        f"Luna 像素风样板 V36 · {'I01 走廊' if profile == 'corridor' else 'I02 客厅'}表面分离候选\n\n"
        "继承上一轮最佳候选的空间、光影、碰撞和路线；仅增加有来源的微细分件和表面节奏。\n"
        "质量状态仍为 unverified，需与上一轮候选并排视觉检查。\n",
        encoding="utf-8",
    )
    return manifest


def build_pixel_corridor_v36(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r36-i01") -> dict[str, object]:
    return _build_indoor_precision_v36(image_path, output_dir, scene_id, build_pixel_corridor_v33, "corridor")


def build_pixel_living_v36(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r36-i02") -> dict[str, object]:
    return _build_indoor_precision_v36(image_path, output_dir, scene_id, build_pixel_living_v31, "living_room")


# V37 is a composition pass for the living-room sample.  V36 improved local
# surfaces, but the GPU view still read as separated props.  This pass adds a
# continuous sectional-sofa silhouette, a patterned rug anchor and a clearer
# TV/window/plant relationship while retaining V36's tested collision shell.
PIXEL_V37_LAYOUT_VERSION = "pixel-v37-i02-photo-anchor-composition-pass-31"


def build_pixel_living_v37(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r37-i02") -> dict[str, object]:
    base_builder = build_pixel_living_v36
    base_builder(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    wall, floor = roles["wall"], roles["floor"]
    trim, window = roles["trim"], roles["window"]
    wood, metal = roles["wood"], roles["metal"]
    sofa, plant = roles["sofa"], roles["plant"]
    lamp, dark, accent = roles["lamp"], roles["dark"], roles["accent"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=MICRO_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    def add_xy(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_xy(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    # The source I02 is dominated by a continuous white sectional sofa.  V31
    # had readable cushions but too much separation between them; these low
    # bases, back cushions and a corner block restore the silhouette.
    sofa_shadow = _mix(sofa, trim, 0.34)
    sofa_mid = _mix(sofa, wall, 0.16)
    sofa_high = _mix(sofa, accent, 0.05)
    add_detail("pixel-q05-r37-i02-sectional-front-base", (3.52, 0.20, 0.20), (-2.10, 0.56, -0.92), sofa_shadow, "upholstery_structure", "photo_supported_sectional_sofa", FURNITURE_VOXEL)
    add_detail("pixel-q05-r37-i02-sectional-chaise-base", (0.92, 0.20, 1.78), (-0.16, 0.56, -1.94), sofa_shadow, "upholstery_structure", "photo_supported_sectional_sofa", FURNITURE_VOXEL)
    add_detail("pixel-q05-r37-i02-sectional-corner", (0.82, 1.05, 0.82), (-0.28, 1.04, -1.28), sofa_mid, "upholstery_structure", "photo_supported_sectional_sofa", FURNITURE_VOXEL)
    for index, (x, z, width) in enumerate(((-2.78, -1.45, 1.20), (-1.40, -1.45, 1.20), (-0.10, -1.45, 0.72))):
        add_detail(f"pixel-q05-r37-i02-sectional-back-{index}", (width, 0.72, 0.18), (x, 1.46, z), sofa_mid, "upholstery_structure", "photo_supported_sectional_sofa", FURNITURE_VOXEL)
        add_xy(
            f"pixel-q05-r37-i02-sectional-back-pixels-{index}",
            (".aaaaaa.", "abbbbbba", "abccccba", "abccccba", ".aaaaaa."),
            (x, 1.46, z + 0.115), (0.12, 0.12), 0.022,
            {"a": sofa_shadow, "b": sofa_mid, "c": sofa_high},
            "upholstery_pixel_surface", "photo_supported_sectional_sofa",
        )

    # Use a compact, ordered rug pattern to bind the table and sofa into one
    # foreground group.  It is a surface layer and remains non-colliding.
    rug_dark = _mix(floor, trim, 0.28)
    rug_light = _mix(floor, sofa, 0.18)
    add_xy(
        "pixel-q05-r37-i02-rug-centre-weave",
        ("..aaaaaaaa..", ".abbbbbbbba.", "abacccccaba", "abcccccc cba".replace(" ", ""),
         "abcccccc cba".replace(" ", ""), "abacccccaba", ".abbbbbbbba.", "..aaaaaaaa.."),
        (0.05, 0.255, 0.34), (0.18, 0.035), 0.018,
        {"a": rug_dark, "b": rug_light, "c": _mix(rug_light, accent, 0.08)},
        "rug_pixel_surface", "photo_supported_rug",
    )
    for index, x in enumerate((-1.55, -0.95, -0.35, 0.25, 0.85, 1.45)):
        add_detail(f"pixel-q05-r37-i02-rug-weave-line-{index}", (0.42, 0.018, 0.025), (x, 0.275, 0.34), rug_dark, "rug_surface_detail", "photo_supported_rug", MICRO_VOXEL)

    # The reference living room separates a dark TV wall from a bright rear
    # window.  Add a narrow cabinet top, TV lower edge and a few blind shadows
    # to make that depth ordering survive a small camera turn.
    add_detail("pixel-q05-r37-i02-tv-wall-lower-edge", (3.05, 0.08, 0.10), (-2.58, 1.05, -6.02), _mix(wood, dark, 0.28), "display_frame_detail", "photo_supported_tv_wall", FURNITURE_VOXEL)
    add_detail("pixel-q05-r37-i02-tv-wall-screen-glint", (1.88, 0.025, 0.025), (-2.58, 2.70, -5.99), _mix(window, accent, 0.18), "display_surface_detail", "photo_supported_tv_wall", MICRO_VOXEL)
    for index, x in enumerate((0.34, 0.76, 1.18, 1.60, 2.02, 2.44, 2.86, 3.28)):
        add_detail(f"pixel-q05-r37-i02-blind-shadow-{index}", (0.035, 1.84, 0.025), (x, 2.34, -6.335), _mix(window, dark, 0.42), "window_blind_shadow", "photo_supported_window_covering", MICRO_VOXEL)

    # Replace the plant's single blocky edge with a stem/leaf fan whose three
    # values remain readable against the bright wall.
    add_detail("pixel-q05-r37-i02-plant-pot-rim", (0.74, 0.10, 0.74), (-3.62, 0.58, 0.44), _mix(sofa, wall, 0.06), "vegetation_container", "photo_supported_plant_pot", FURNITURE_VOXEL)
    add_detail("pixel-q05-r37-i02-plant-stem-main", (0.075, 1.58, 0.075), (-3.62, 1.72, 0.44), _mix(plant, dark, 0.32), "vegetation_structure", "photo_supported_vegetation", MICRO_VOXEL)
    for index, (x, y, colour) in enumerate((
        (-4.02, 2.14, plant), (-3.78, 2.40, _mix(plant, window, 0.16)),
        (-3.44, 2.62, _shade(plant, 0.72)), (-3.10, 2.90, _mix(plant, lamp, 0.10)),
        (-3.54, 3.18, plant),
    )):
        add_detail(f"pixel-q05-r37-i02-plant-fan-{index}", (0.48, 0.24, 0.20), (x, y, 0.44), colour, "vegetation_surface_detail", "photo_supported_vegetation", FURNITURE_VOXEL)

    layout_version = PIXEL_V37_LAYOUT_VERSION
    detail_pass = "v37-i02-photo-anchor-composition-pass-31"
    route_name = "pixel_style_sample_v37"
    generated_regions = [
        "continuous_sectional_sofa", "rug_centre_weave", "tv_wall_depth_anchor",
        "window_blind_shadow_layers", "plant_fan_silhouette",
    ]
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_i02_photo_anchor_composition_pass"
    layout.setdefault("pixel_spec", {})["detail_pass"] = detail_pass
    layout["pixel_spec"]["composition_policy"] = "continuous_furniture_grouping_before_micro_decoration"
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + generated_regions
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version
    manifest["version"] = "pixel-v37"
    manifest["provider_version"] = "pixel-voxel-v37"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V37 I02 客厅照片锚点构图候选：继承 V36 的表面细节、碰撞和路线，"
        "把白色组合沙发、茶几地毯、电视墙、后窗百叶和植物组织为连续前中后景；"
        "新增件只参与视觉表达，不改变碰撞，不声称精确恢复不可见空间。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = "candidate_living_room_photo_anchor_composition"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["composition_policy"] = "continuous_furniture_grouping_before_micro_decoration"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + generated_regions
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details
    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V37 · I02 客厅照片锚点构图候选\n\n"
        "在 V36 局部表面分离基础上，优先恢复组合沙发、茶几地毯、电视墙、后窗与植物的整体关系。\n"
        "碰撞与移动保持继承；质量状态仍为 unverified。\n",
        encoding="utf-8",
    )
    return manifest


# V38 translates the supplied pixel-art references into a denser surface
# language: dark contour pixels, limited shade steps, repeated material motifs
# and a small number of semantic light sources.  It inherits V37's composition
# and collision contract, so this remains a visual candidate rather than a
# silent layout rewrite.
PIXEL_V38_LAYOUT_VERSION = "pixel-v38-i02-pixel-material-light-pass-32"


def build_pixel_living_v38(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r38-i02") -> dict[str, object]:
    build_pixel_living_v37(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    wall, floor = roles["wall"], roles["floor"]
    trim, window = roles["trim"], roles["window"]
    wood, metal = roles["wood"], roles["metal"]
    sofa, plant = roles["sofa"], roles["plant"]
    lamp, dark, accent = roles["lamp"], roles["dark"], roles["accent"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=MICRO_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    def add_xy(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_xy(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    def add_xz(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_xz(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    contour = _mix(dark, trim, 0.10)
    sofa_shadow = _mix(sofa, trim, 0.38)
    sofa_mid = _mix(sofa, wall, 0.18)
    sofa_light = _mix(sofa, [255, 250, 236], 0.20)

    # A dark one-pixel contour and three value steps make the sectional read
    # like authored pixel art rather than several unconnected beige boxes.
    for index, (x, z, width) in enumerate(((-2.78, -1.45, 1.20), (-1.40, -1.45, 1.20), (-0.10, -1.45, 0.72))):
        add_detail(f"pixel-q05-r38-i02-sofa-contour-top-{index}", (width + 0.10, 0.035, 0.045), (x, 1.86, z), contour, "upholstery_contour", "pixel_style_contour_rule", MICRO_VOXEL)
        add_detail(f"pixel-q05-r38-i02-sofa-contour-side-{index}", (0.045, 0.72, 0.045), (x - width * 0.52, 1.48, z - 0.12), contour, "upholstery_contour", "pixel_style_contour_rule", MICRO_VOXEL)
        add_xy(
            f"pixel-q05-r38-i02-sofa-fabric-grid-{index}",
            ("..aaaaaaaa..", ".abbbbbbbba.", "abacccccaba", "abcccccc cba".replace(" ", ""), "abacccccaba", ".abbbbbbbba.", "..aaaaaaaa.."),
            (x, 1.48, z + 0.12), (0.075, 0.075), 0.018,
            {"a": contour, "b": sofa_shadow, "c": sofa_light},
            "upholstery_pixel_surface", "photo_supported_sectional_sofa",
        )
    # Small dark breaks separate cushions without adding random noise.
    for index, x in enumerate((-2.10, -0.72)):
        add_detail(f"pixel-q05-r38-i02-sofa-cushion-break-{index}", (0.035, 0.58, 0.06), (x, 1.38, -1.30), contour, "upholstery_seam_detail", "pixel_style_material_break", MICRO_VOXEL)

    # The coffee table gets a compact radial-ish pixel motif and a warm rim;
    # the pattern is flat and low cost but gives the reference-style focal
    # object a readable highlight/shadow hierarchy.
    table_dark = _mix(wood, dark, 0.28)
    table_mid = _mix(wood, wall, 0.24)
    table_high = _mix(lamp, wall, 0.16)
    add_xz(
        "pixel-q05-r38-i02-table-pixel-inlay",
        ("...aaaa...", ".abbbbbba.", "abacccaba", "abccccbba", "abacccaba", ".abbbbbba.", "...aaaa..."),
        (1.25, 1.18, 0.55), (0.12, 0.10), 0.016,
        {"a": table_dark, "b": table_mid, "c": table_high},
        "table_pixel_surface", "photo_supported_coffee_table",
    )
    add_detail("pixel-q05-r38-i02-table-warm-rim", (1.62, 0.035, 0.04), (1.25, 1.23, 0.55), table_high, "table_light_detail", "pixel_style_semantic_light_source", MICRO_VOXEL)
    for index, x in enumerate((1.08, 1.25, 1.42)):
        add_detail(f"pixel-q05-r38-i02-table-base-contour-{index}", (0.04, 0.44, 0.24), (x, 0.70, 0.55), contour, "table_contour", "pixel_style_contour_rule", MICRO_VOXEL)

    # Floor and rug receive a controlled checker/stripe cadence like the
    # supplied references, with enough empty space to preserve readability.
    rug_shadow = _mix(floor, trim, 0.30)
    rug_light = _mix(floor, sofa, 0.16)
    add_xz(
        "pixel-q05-r38-i02-rug-pixel-weave",
        ("aabbbbbbaa", "abccccc cba".replace(" ", ""), "bccddccddb", "abccccc cba".replace(" ", ""), "aabbbbbbaa"),
        (0.05, 0.29, 0.34), (0.20, 0.14), 0.014,
        {"a": rug_shadow, "b": rug_light, "c": _mix(rug_light, accent, 0.10), "d": _mix(rug_shadow, trim, 0.25)},
        "rug_pixel_surface", "photo_supported_rug",
    )
    for row, z in enumerate((1.40, 0.80, 0.20, -0.40, -1.00)):
        add_detail(f"pixel-q05-r38-i02-floor-reflection-band-{row}", (2.20, 0.012, 0.028), (0.15, 0.235, z), _mix(floor, window, 0.14 if row % 2 else 0.08), "floor_reflection_detail", "photo_supported_floor_light", MICRO_VOXEL)

    # The TV and rear opening use small bright pixels rather than global
    # emissive lift.  This is the same semantic-light rule used by the
    # reference-style night scenes, adapted to the photographed living room.
    screen_dark = _mix(dark, trim, 0.16)
    screen_mid = _mix(window, accent, 0.34)
    screen_light = _mix(screen_mid, lamp, 0.24)
    add_xy(
        "pixel-q05-r38-i02-tv-dense-screen-grid",
        ("..aaaaaaaaaaaa..", ".abbbbbbbbbbbba.", "abacccccc caba".replace(" ", ""), "abacccccc caba".replace(" ", ""), ".abbbbbbbbbbbba.", "..aaaaaaaaaaaa.."),
        (-2.58, 2.04, -5.98), (0.075, 0.075), 0.018,
        {"a": screen_dark, "b": screen_mid, "c": screen_light},
        "display_pixel_surface", "photo_supported_tv_wall",
    )
    for index, x in enumerate((-2.00, -1.64, -1.28, -0.92, -0.56)):
        add_detail(f"pixel-q05-r38-i02-tv-status-pixel-{index}", (0.055, 0.035, 0.018), (x, 1.33, -5.94), lamp if index == 2 else screen_light, "display_light_detail", "pixel_style_semantic_light_source", MICRO_VOXEL)
    for index, x in enumerate((0.36, 0.70, 1.04, 1.38, 2.10, 2.44, 2.78, 3.12)):
        add_detail(f"pixel-q05-r38-i02-window-light-pixel-{index}", (0.035, 0.08, 0.025), (x, 2.34 + (index % 2) * 0.18, -6.30), _mix(window, lamp, 0.22), "window_light_detail", "pixel_style_semantic_light_source", MICRO_VOXEL)

    # Plant leaves are layered into dark/mid/high clusters so the silhouette
    # reads at a glance while staying an actual 3D object, not a billboard.
    leaf_dark = _shade(plant, 0.58)
    leaf_mid = plant
    leaf_high = _mix(plant, lamp, 0.18)
    for index, (x, y, z, colour) in enumerate((
        (-4.08, 2.08, 0.44, leaf_dark), (-3.88, 2.36, 0.44, leaf_mid),
        (-3.58, 2.58, 0.44, leaf_high), (-3.22, 2.82, 0.44, leaf_mid),
        (-3.00, 3.10, 0.44, leaf_dark), (-3.52, 3.28, 0.44, leaf_high),
    )):
        add_detail(f"pixel-q05-r38-i02-plant-pixel-leaf-{index}", (0.32, 0.16, 0.16), (x, y, z), colour, "vegetation_pixel_surface", "photo_supported_vegetation", FURNITURE_VOXEL)

    layout_version = PIXEL_V38_LAYOUT_VERSION
    detail_pass = "v38-i02-pixel-material-light-pass-32"
    route_name = "pixel_style_sample_v38"
    generated_regions = [
        "pixel_contour_hierarchy", "micro_fabric_grid", "table_pixel_inlay",
        "rug_pixel_weave", "semantic_tv_light_pixels", "window_light_pixels",
        "layered_plant_pixel_leaves",
    ]
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_i02_pixel_material_and_light_pass"
    layout.setdefault("pixel_spec", {})["detail_pass"] = detail_pass
    layout["pixel_spec"]["lighting_preset"] = "indoor_pixel_detail_v4"
    layout["pixel_spec"]["surface_density_policy"] = "micro_pixel_material_steps_and_dark_contours_no_uniform_noise"
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + generated_regions
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version
    manifest["version"] = "pixel-v38"
    manifest["provider_version"] = "pixel-voxel-v38"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V38 I02 微像素材质与光影候选：继承 V37 的照片锚点构图、碰撞和路线，"
        "增加深色轮廓、微像素织物/地毯/桌面纹理、电视与窗光语义像素、植物明暗层，"
        "并使用独立室内像素光影预设；不使用整图投影。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = "candidate_pixel_material_light_hierarchy"
    manifest["quality_metrics"]["lighting_status"] = "candidate_indoor_pixel_detail_v4"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["lighting_preset"] = "indoor_pixel_detail_v4"
    manifest["pixel_spec"]["surface_density_policy"] = "micro_pixel_material_steps_and_dark_contours_no_uniform_noise"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + generated_regions
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details
    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V38 · I02 微像素材质与光影候选\n\n"
        "增加参考图方向的深色轮廓、有限色阶、微像素表面和局部语义光点；布局、碰撞和移动保持继承。\n"
        "质量状态仍为 unverified。\n",
        encoding="utf-8",
    )
    return manifest


# V39 applies the same fine-pixel material language to I01.  The corridor has
# fewer furniture anchors than I02, so its precision comes from window/door
# depth, tile cadence, wall rails and a repeated ceiling-light rhythm.
PIXEL_V39_LAYOUT_VERSION = "pixel-v39-i01-pixel-material-light-pass-33"


def build_pixel_corridor_v39(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r39-i01") -> dict[str, object]:
    build_pixel_corridor_v36(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    wall, floor = roles["wall"], roles["floor"]
    trim, window = roles["trim"], roles["window"]
    wood, metal = roles["wood"], roles["metal"]
    lamp, dark, accent = roles["lamp"], roles["dark"], roles["accent"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=MICRO_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    def add_yz(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_yz(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    def add_xy(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_xy(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    contour = _mix(dark, trim, 0.08)
    glass_dark = _mix(window, dark, 0.42)
    glass_mid = _mix(window, accent, 0.24)
    glass_high = _mix(window, wall, 0.20)
    door_mid = _mix(wood, wall, 0.18)
    door_light = _mix(wood, lamp, 0.12)

    for index, z in enumerate((3.50, 0.0, -3.50, -7.0)):
        add_detail(f"pixel-q05-r39-i01-window-contour-left-{index}", (0.045, 2.30, 0.045), (-2.12, 1.55, z), contour, "window_contour", "pixel_style_contour_rule", MICRO_VOXEL)
        add_detail(f"pixel-q05-r39-i01-window-sill-left-{index}", (0.06, 0.08, 1.72), (-2.10, 0.72, z), _mix(trim, wall, 0.12), "window_frame_detail", "photo_supported_window_sill", FURNITURE_VOXEL)
        add_yz(
            f"pixel-q05-r39-i01-window-fine-reflection-{index}",
            ("..aaaa..", ".abbbba.", "abacccba", "abccccba", "abacccba", ".abbbba.", "..aaaa.."),
            (-2.075, 1.60, z + 0.08), (0.070, 0.095), 0.014,
            {"a": contour, "b": glass_dark, "c": glass_high},
            "window_pixel_surface", "photo_supported_window_opening",
        )
        for light_index, offset in enumerate((-0.28, 0.02, 0.32)):
            add_detail(f"pixel-q05-r39-i01-window-city-light-{index}-{light_index}", (0.045, 0.045, 0.025), (-2.045, 1.22 + light_index * 0.22, z + offset), _mix(glass_mid, lamp, 0.16), "window_light_detail", "photo_palette_upper", MICRO_VOXEL)

        add_detail(f"pixel-q05-r39-i01-door-contour-right-{index}", (0.045, 2.50, 0.045), (2.10, 1.48, z), contour, "door_contour", "pixel_style_contour_rule", MICRO_VOXEL)
        add_yz(
            f"pixel-q05-r39-i01-door-fine-panel-{index}",
            ("aaaaaaaa", "abbbbbba", "abccddba", "abccccba", "abccddba", "abccccba", "abbbbbba", "aaaaaaaa"),
            (2.06, 1.48, z), (0.075, 0.15), 0.014,
            {"a": contour, "b": door_mid, "c": _mix(wood, accent, 0.12), "d": door_light},
            "door_pixel_surface", "photo_supported_door_panel",
        )
        add_detail(f"pixel-q05-r39-i01-door-warm-handle-{index}", (0.035, 0.09, 0.055), (2.02, 1.48, z - 0.18), _mix(lamp, metal, 0.24), "door_light_detail", "photo_supported_door_hardware", MICRO_VOXEL)

    # Alternating tile bands and small reflected-window pixels keep the long
    # corridor floor from reading as a single untextured plane.
    tile_dark = _mix(floor, trim, 0.34)
    tile_light = _mix(floor, window, 0.12)
    for row, z in enumerate((4.65, 3.50, 2.35, 1.20, 0.05, -1.10, -2.25, -3.40, -4.55, -5.70, -6.85, -8.0)):
        add_detail(f"pixel-q05-r39-i01-floor-tile-contour-{row}", (4.10, 0.014, 0.028), (0.0, 0.225, z), tile_dark, "floor_tile_contour", "pixel_style_material_break", MICRO_VOXEL)
        for column, x in enumerate((-1.54, -0.84, -0.14, 0.56, 1.26)):
            if (row + column) % 3 != 1:
                add_detail(f"pixel-q05-r39-i01-floor-reflection-{row}-{column}", (0.22, 0.012, 0.08), (x, 0.244, z - 0.10), tile_light, "floor_reflection_detail", "photo_supported_window_light", MICRO_VOXEL)

    # Recessed ceiling fixtures get dark outlines, warm cores and a short cool
    # edge, giving the same deliberate light-source vocabulary as the sample
    # pixel references without applying a global glow.
    for index, z in enumerate((4.30, 2.20, 0.10, -2.00, -4.20, -6.40, -8.50)):
        add_detail(f"pixel-q05-r39-i01-ceiling-light-contour-{index}", (0.72, 0.04, 0.34), (0.0, 3.72, z), contour, "ceiling_light_contour", "pixel_style_contour_rule", FURNITURE_VOXEL)
        add_detail(f"pixel-q05-r39-i01-ceiling-light-core-{index}", (0.44, 0.018, 0.16), (0.0, 3.67, z), _mix(lamp, wall, 0.16), "ceiling_light_detail", "photo_supported_ceiling_light", MICRO_VOXEL)
        add_detail(f"pixel-q05-r39-i01-ceiling-light-cool-edge-{index}", (0.28, 0.014, 0.025), (0.0, 3.64, z - 0.10), _mix(window, lamp, 0.24), "ceiling_light_detail", "photo_palette_upper", MICRO_VOXEL)

    # Small wall plaques and a continuous rail provide the corridor's human
    # scale and break the broad side walls into designed sections.
    add_detail("pixel-q05-r39-i01-right-handrail-contour", (0.045, 0.10, 12.80), (2.05, 1.02, -1.80), contour, "wall_handrail_contour", "pixel_style_contour_rule", MICRO_VOXEL)
    for index, z in enumerate((2.80, 0.90, -1.00, -2.90, -4.80, -6.70)):
        add_xy(
            f"pixel-q05-r39-i01-wall-plaque-{index}",
            ("aaaaaa", "abbbba", "abccba", "abbbba", "aaaaaa"),
            (2.015, 2.35, z), (0.08, 0.08), 0.012,
            {"a": contour, "b": _mix(wall, trim, 0.18), "c": _mix(accent, lamp, 0.16)},
            "wall_plaque_pixel_surface", "procedural_corridor_wayfinding",
        )

    layout_version = PIXEL_V39_LAYOUT_VERSION
    detail_pass = "v39-i01-pixel-material-light-pass-33"
    route_name = "pixel_style_sample_v39"
    generated_regions = [
        "window_contour_and_reflection_pixels", "door_fine_panel_pixels",
        "floor_tile_contours_and_reflections", "ceiling_light_pixel_sources",
        "corridor_handrail_and_wayfinding_plaques",
    ]
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_i01_pixel_material_and_light_pass"
    layout.setdefault("pixel_spec", {})["detail_pass"] = detail_pass
    layout["pixel_spec"]["lighting_preset"] = "indoor_pixel_detail_v4"
    layout["pixel_spec"]["surface_density_policy"] = "micro_pixel_material_steps_and_dark_contours_no_uniform_noise"
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + generated_regions
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version
    manifest["version"] = "pixel-v39"
    manifest["provider_version"] = "pixel-voxel-v39"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V39 I01 微像素材质与光影候选：继承 V36 的走廊结构、窗门、碰撞和路线，"
        "加入深色轮廓、窗外反射像素、门板细分、地砖反射、顶灯语义光源和墙面导视节奏；"
        "不改变可行走空间，不使用整图投影。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = "candidate_corridor_pixel_material_light_hierarchy"
    manifest["quality_metrics"]["lighting_status"] = "candidate_indoor_pixel_detail_v4"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["lighting_preset"] = "indoor_pixel_detail_v4"
    manifest["pixel_spec"]["surface_density_policy"] = "micro_pixel_material_steps_and_dark_contours_no_uniform_noise"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + generated_regions
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details
    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V39 · I01 走廊微像素材质与光影候选\n\n"
        "继承走廊空间和碰撞，增加窗门细像素、地砖反射、顶灯光源和墙面导视层。\n"
        "质量状态仍为 unverified。\n",
        encoding="utf-8",
    )
    return manifest


# V40-V42 carry the fine-pixel material language to the three exterior
# samples.  These are render-only surface passes: they inherit the reviewed
# camera, route and collision contracts from V33/V35 and do not add collision
# boxes.  The intent is to make the existing semantic anchors read as authored
# pixel art from the start view and after a turn, rather than merely increasing
# the number of undifferentiated blocks.
PIXEL_V40_LAYOUT_VERSION = "pixel-v40-n01-pixel-material-light-pass-34"
PIXEL_V41_LAYOUT_VERSION = "pixel-v41-s01-pixel-material-light-pass-34"
PIXEL_V42_LAYOUT_VERSION = "pixel-v42-b01-pixel-material-light-pass-34"


def _finalize_exterior_pixel_pass(
    image_path: Path,
    output_dir: Path,
    scene: trimesh.Scene,
    layout: dict[str, object],
    collision: dict[str, object],
    manifest: dict[str, object],
    details: list[str],
    layout_version: str,
    route_name: str,
    detail_pass: str,
    authoring: str,
    note: str,
    generated_regions: list[str],
    lighting_preset: str,
    semantic_status: str,
) -> dict[str, object]:
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = authoring
    layout.setdefault("pixel_spec", {})["detail_pass"] = detail_pass
    layout["pixel_spec"]["lighting_preset"] = lighting_preset
    layout["pixel_spec"]["surface_density_policy"] = "ordered_micro_pixel_material_steps_dark_contours_semantic_lights_no_uniform_noise"
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + generated_regions
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version

    manifest["version"] = route_name.replace("pixel_style_sample_v", "pixel-v")
    manifest["provider_version"] = f"pixel-voxel-{route_name.rsplit('v', 1)[-1]}"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = note
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = semantic_status
    manifest["quality_metrics"]["lighting_status"] = f"candidate_{lighting_preset}"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["lighting_preset"] = lighting_preset
    manifest["pixel_spec"]["surface_density_policy"] = "ordered_micro_pixel_material_steps_dark_contours_semantic_lights_no_uniform_noise"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + generated_regions
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details

    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        f"Luna 像素风样板 {route_name} · 外部细像素材质与光影候选\n\n"
        f"{note}\n视觉质量仍为 unverified；新增表面细节不参与碰撞。\n",
        encoding="utf-8",
    )
    return manifest


def build_pixel_nature_v40(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r40-n01") -> dict[str, object]:
    build_pixel_nature_v33(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout = json.loads((output_dir / "layout.json").read_text(encoding="utf-8"))
    collision = json.loads((output_dir / "collision.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    scene = trimesh.load(scene_path, force="scene")
    roles = layout["palette"]["roles"]
    floor, window = roles["floor"], roles["window"]
    trim, dark, accent, lamp = roles["trim"], roles["dark"], roles["accent"], roles["lamp"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=MICRO_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    def add_xy(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_xy(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    snow_light = _mix(window, [255, 255, 248], 0.46)
    snow_mid = _mix(window, accent, 0.22)
    snow_shadow = _mix(window, dark, 0.40)
    contour = _mix(dark, trim, 0.16)

    # Three depth bands use different facet scales.  The ordered chevrons make
    # the mountain silhouette and snow direction readable without turning the
    # entire terrain into random checker noise.
    facet_patterns = {
        "near": ("..aaaa..", ".abbbba.", "abacccba", "abccccba", "abacccba", ".abbbba.", "..aaaa.."),
        "mid": ("..aaa..", ".abbbba.", "abcccba", ".abbbba.", "..aaa.."),
        "far": (".aaa.", "abcca", "abccb", ".aaa."),
    }
    facet_specs = (
        ("near", -7.2, 0.44, 0.20, 0.15, 1.75),
        ("mid", -12.7, 0.31, 0.16, 0.12, 1.35),
        ("far", -17.3, 0.20, 0.12, 0.09, 0.96),
    )
    for ridge_name, z, y, cell_x, cell_y, spread in facet_specs:
        pattern = facet_patterns[ridge_name]
        for index, x in enumerate((-7.0, -4.1, -1.2, 1.8, 4.8)):
            add_xy(
                f"pixel-q05-r40-n01-{ridge_name}-snow-facet-{index}", pattern,
                (x, y, z), (cell_x, cell_y), 0.022,
                {"a": contour, "b": snow_shadow, "c": snow_light},
                "mountain_pixel_facet", "photo_supported_snow_ridge",
            )
            add_detail(
                f"pixel-q05-r40-n01-{ridge_name}-facet-cap-{index}", (spread, 0.026, 0.045),
                (x, y + 0.42, z - 0.08), snow_light, "mountain_pixel_highlight", "photo_supported_snow_ridge", MICRO_VOXEL,
            )

    # Keep the foreground's broad snow plane readable with a small number of
    # stepped shadow ribbons and directional track pixels.
    for index, (x, z, width) in enumerate(((-4.3, 5.2, 2.0), (-1.9, 4.1, 1.25), (2.5, 2.65, 1.7), (-3.6, -0.05, 1.45), (3.2, -3.25, 1.85), (-1.4, -5.55, 1.28))):
        add_detail(
            f"pixel-q05-r40-n01-snow-contour-band-{index}", (width, 0.024, 0.12),
            (x, 0.285, z), snow_shadow if index % 2 else snow_mid,
            "snow_surface_contour", "photo_supported_near_ground", MICRO_VOXEL,
        )
    for index, (x, z) in enumerate(((-0.30, 5.35), (0.22, 4.72), (-0.24, 4.05), (0.28, 3.38), (-0.22, 2.71), (0.28, 2.04), (-0.24, 1.37), (0.28, 0.70), (-0.24, 0.03), (0.28, -0.64), (-0.24, -1.31), (0.28, -1.98), (-0.24, -2.65), (0.28, -3.32), (-0.24, -3.99), (0.28, -4.66), (-0.24, -5.33))):
        add_detail(
            f"pixel-q05-r40-n01-track-highlight-{index}", (0.24, 0.026, 0.10),
            (x, 0.305, z), _mix(snow_shadow, floor, 0.24),
            "snow_track_detail", "photo_supported_near_ground", MICRO_VOXEL,
        )

    # The fence is a strong foreground anchor in the photograph.  Add small
    # cap/brace highlights and alternating wire segments to make it readable
    # after a turn without changing its inherited non-blocking collision rule.
    fence = _mix(dark, window, 0.24)
    for index, x in enumerate((-4.5, -3.0, -1.5, 0.0, 1.5, 3.0, 4.5)):
        add_detail(f"pixel-q05-r40-n01-fence-cap-{index}", (0.14, 0.10, 0.14), (x, 2.22, 6.0), _mix(fence, lamp, 0.10), "foreground_fence_detail", "photo_supported_foreground_fence", FURNITURE_VOXEL)
        for wire, y in enumerate((1.60, 1.12, 0.64)):
            add_detail(f"pixel-q05-r40-n01-fence-wire-pixel-{index}-{wire}", (0.50, 0.025, 0.025), (x + 0.25, y, 6.0), _mix(fence, snow_mid, 0.12 if wire == 1 else 0.0), "foreground_fence_detail", "photo_supported_foreground_fence", MICRO_VOXEL)

    return _finalize_exterior_pixel_pass(
        image_path, output_dir, scene, layout, collision, manifest, details,
        PIXEL_V40_LAYOUT_VERSION, "pixel_style_sample_v40", "v40-n01-pixel-material-light-pass-34",
        "q05_n01_fine_pixel_ridge_snow_fence_surface",
        "像素风 V40 N01 雪山细像素材质候选：继承 V33 的分层山体、冷色日光、碰撞和路线，"
        "补充近中远雪脊的方向性像素面、前景雪影/足迹和围栏线层；只增加视觉细节，不把远景或天空当作可走地面。",
        ["ridge_directional_pixel_facets", "snow_contour_bands", "snow_track_highlights", "fence_wire_pixel_layers"],
        "outdoor_cool_daylight_v2", "candidate_nature_pixel_material_light_hierarchy",
    )


def build_pixel_street_v41(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r41-s01") -> dict[str, object]:
    build_pixel_street_v35(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout = json.loads((output_dir / "layout.json").read_text(encoding="utf-8"))
    collision = json.loads((output_dir / "collision.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    scene = trimesh.load(scene_path, force="scene")
    roles = layout["palette"]["roles"]
    floor, wall = roles["floor"], roles["wall"]
    wood, metal, window = roles["wood"], roles["metal"], roles["window"]
    plant, lamp, dark, accent, trim = roles["plant"], roles["lamp"], roles["dark"], roles["accent"], roles["trim"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=MICRO_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    def add_xy(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_xy(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    road_dark = _mix(floor, dark, 0.32)
    road_light = _mix(floor, window, 0.22)
    lane = _mix(_mix(wood, lamp, 0.18), [190, 72, 66], 0.55)
    lane_high = _mix(lane, lamp, 0.20)
    vehicle_dark = _mix(metal, dark, 0.20)
    vehicle_glass = _mix(window, accent, 0.22)

    # Add a restrained road contour cadence.  The markings sit on the actual
    # road surface and use long/short segments to reinforce depth rather than
    # covering it with a flat texture.
    for index, z in enumerate((6.0, 4.65, 3.30, 1.95, 0.60, -0.75, -2.10, -3.45, -4.80, -6.15, -7.50, -8.85, -10.20)):
        add_detail(f"pixel-q05-r41-s01-road-contour-{index}", (0.08, 0.024, 0.70 if index % 2 else 0.46), (0.0, 0.245, z), road_dark, "road_surface_contour", "photo_supported_road_surface", MICRO_VOXEL)
        add_detail(f"pixel-q05-r41-s01-road-glint-{index}", (0.24 if index % 2 else 0.14, 0.018, 0.025), (0.42, 0.27, z - 0.22), road_light, "road_surface_detail", "photo_supported_road_surface", MICRO_VOXEL)
    for index, z in enumerate((4.55, 2.85, 1.15, -0.55, -2.25, -3.95, -5.65)):
        add_detail(f"pixel-q05-r41-s01-bike-lane-highlight-{index}", (0.11, 0.028, 0.52), (-3.10, 0.345, z), lane_high, "road_marking_detail", "photo_supported_bike_lane", MICRO_VOXEL)

    # Vehicles gain a readable windshield, cabin split, grille and lamp order;
    # each layer remains render-only and is kept within the inherited proxy.
    for index, (x, z, body) in enumerate(((-2.55, 1.2, wood), (2.65, -4.0, metal))):
        add_xy(
            f"pixel-q05-r41-s01-vehicle-face-{index}",
            (".aaaa.", "abbbba", "acccca", "abddba", ".aaaa."),
            (x, 0.84, z + 1.34), (0.15, 0.10), 0.026,
            {"a": vehicle_dark, "b": _mix(body, vehicle_glass, 0.28), "c": vehicle_glass, "d": lamp},
            "vehicle_pixel_surface", "photo_supported_vehicle",
        )
        add_detail(f"pixel-q05-r41-s01-vehicle-bumper-{index}", (1.08, 0.055, 0.06), (x, 0.40, z + 1.34), _mix(trim, dark, 0.16), "vehicle_pixel_detail", "photo_supported_vehicle", MICRO_VOXEL)
        for lamp_index, x_offset in enumerate((-0.42, 0.42)):
            add_detail(f"pixel-q05-r41-s01-vehicle-lamp-{index}-{lamp_index}", (0.13, 0.10, 0.03), (x + x_offset, 0.63, z + 1.37), _mix(lamp, window, 0.18), "vehicle_light_detail", "photo_supported_vehicle", MICRO_VOXEL)

    # The front-facing side masses receive small window groups and facade
    # bands, giving the street a layered city rhythm while preserving the
    # original building proxies and open route.
    for side, x in (("left", -6.0), ("right", 6.0)):
        for building_index, z in enumerate((3.6, -2.0, -7.6)):
            front_z = z + 2.16
            for row_index, y in enumerate((1.30, 2.22, 3.14, 4.06)):
                add_xy(
                    f"pixel-q05-r41-s01-{side}-building-{building_index}-window-pixels-{row_index}",
                    (".aaa.", "abcca", "abdda", ".aaa."),
                    (x, y, front_z), (0.12, 0.13), 0.020,
                    {"a": _mix(dark, trim, 0.10), "b": _mix(window, wall, 0.10), "c": window, "d": _mix(window, lamp, 0.18)},
                    "building_window_pixel_surface", "photo_supported_window_line",
                )
            add_detail(f"pixel-q05-r41-s01-{side}-building-{building_index}-facade-shadow", (1.60, 0.045, 0.06), (x, 0.88, front_z + 0.025), _mix(wall, dark, 0.26), "building_facade_contour", "photo_inferred_background_building", MICRO_VOXEL)

    # Canopy clusters receive a dark branch step and a few bright leaf pixels;
    # this is enough to separate near foliage from the sidewalk without noise.
    for tree_index, (x, z) in enumerate(((-4.45, 4.25), (4.35, -8.50), (-4.50, -11.0), (4.45, 1.50))):
        add_detail(f"pixel-q05-r41-s01-tree-trunk-contour-{tree_index}", (0.08, 1.20, 0.08), (x, 1.45, z), _mix(wood, dark, 0.28), "tree_structure_detail", "photo_inferred_tree", MICRO_VOXEL)
        for leaf_index, (dx, dy, dz, colour) in enumerate((
            (-0.52, 2.24, 0.0, _shade(plant, 0.62)), (-0.24, 2.48, 0.04, plant),
            (0.06, 2.28, 0.0, _mix(plant, window, 0.14)), (0.38, 2.62, -0.02, _shade(plant, 0.78)),
            (0.0, 2.90, 0.0, _mix(plant, lamp, 0.08)),
        )):
            add_detail(f"pixel-q05-r41-s01-tree-leaf-pixel-{tree_index}-{leaf_index}", (0.34, 0.22, 0.28), (x + dx, dy, z + dz), colour, "tree_pixel_surface", "photo_supported_tree_canopy", FURNITURE_VOXEL)

    return _finalize_exterior_pixel_pass(
        image_path, output_dir, scene, layout, collision, manifest, details,
        PIXEL_V41_LAYOUT_VERSION, "pixel_style_sample_v41", "v41-s01-pixel-material-light-pass-34",
        "q05_s01_fine_pixel_road_vehicle_facade_tree_surface",
        "像素风 V41 S01 街道细像素材质候选：继承 V35 的道路、车道、人车树分离、碰撞和路线，"
        "增加道路轮廓与反光节奏、车辆前脸像素、侧面建筑窗格和树冠明暗层；新增件不参与碰撞。",
        ["road_contour_and_glints", "vehicle_pixel_faces", "street_facade_window_pixels", "tree_pixel_surface_layers"],
        "street_soft_daylight_v3", "candidate_street_pixel_material_light_hierarchy",
    )


def build_pixel_building_v42(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r42-b01") -> dict[str, object]:
    build_pixel_building_v35(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout = json.loads((output_dir / "layout.json").read_text(encoding="utf-8"))
    collision = json.loads((output_dir / "collision.json").read_text(encoding="utf-8"))
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    scene = trimesh.load(scene_path, force="scene")
    roles = layout["palette"]["roles"]
    wall, trim, window = roles["wall"], roles["trim"], roles["window"]
    wood, metal, lamp = roles["wood"], roles["metal"], roles["lamp"]
    plant, dark, accent = roles["plant"], roles["dark"], roles["accent"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=MICRO_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    def add_xy(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_xy(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    contour = _mix(dark, trim, 0.12)
    facade_mid = _mix(wall, trim, 0.24)
    glass_dark = _mix(window, dark, 0.34)
    glass_mid = _mix(window, accent, 0.20)
    glass_high = _mix(window, lamp, 0.18)
    warm = _mix(lamp, accent, 0.18)

    # Long facade courses make the large mass read as masonry panels rather
    # than a single colored slab.  Short interruptions preserve the irregular
    # night-city rhythm of the reference image.
    for index, y in enumerate((0.72, 2.78, 4.84, 6.90, 8.96)):
        add_detail(f"pixel-q05-r42-b01-facade-contour-course-{index}", (13.72, 0.05, 0.065), (0.0, y, -5.12), contour if index % 2 else facade_mid, "facade_contour", "photo_supported_facade_mass", MICRO_VOXEL)
        for segment, x in enumerate((-5.85, -2.95, 0.0, 2.95, 5.85)):
            if (index + segment) % 3 != 1:
                add_detail(f"pixel-q05-r42-b01-facade-block-{index}-{segment}", (1.08, 0.035, 0.045), (x, y + 0.30, -5.08), _mix(facade_mid, trim, 0.12 * ((index + segment) % 2)), "facade_surface_detail", "photo_inferred_building_mass", MICRO_VOXEL)

    # Each existing irregular window receives an authored four-value pixel
    # core.  This gives the facade the compact local glow and pane separation
    # visible in the supplied night reference without a full-photo projection.
    window_specs = (
        (-5.75, 1.20, 0.92, 0.82), (-3.75, 1.62, 0.70, 1.12), (-1.45, 1.18, 0.84, 0.78), (1.10, 1.64, 0.76, 1.16), (3.72, 1.20, 0.92, 0.84), (5.82, 1.82, 0.68, 1.26),
        (-5.20, 3.45, 0.78, 0.94), (-2.80, 3.30, 0.98, 0.72), (-0.25, 3.66, 0.70, 1.12), (2.35, 3.18, 0.90, 0.88), (5.18, 3.58, 0.78, 1.02),
        (-5.72, 5.62, 0.72, 1.04), (-3.35, 5.35, 0.94, 0.78), (-0.85, 5.74, 0.82, 1.08), (1.80, 5.42, 0.98, 0.82), (4.80, 5.78, 0.74, 1.12),
        (-4.82, 7.55, 0.86, 0.82), (-2.15, 7.34, 0.70, 1.08), (0.55, 7.68, 0.92, 0.88), (3.38, 7.30, 0.74, 1.10), (5.82, 7.78, 0.78, 0.78),
    )
    for index, (x, y, width, height) in enumerate(window_specs):
        warm_window = index % 3 != 1
        add_xy(
            f"pixel-q05-r42-b01-window-pixel-core-{index}",
            (".aaaa.", "abbbba", "acccda", "abddba", ".aaaa."),
            (x, y, -5.045), (max(0.10, width * 0.22), max(0.10, height * 0.19)), 0.020,
            {"a": contour, "b": warm if warm_window else glass_dark, "c": glass_mid if warm_window else window, "d": glass_high if warm_window else _mix(window, accent, 0.10)},
            "facade_window_pixel_surface", "photo_supported_lit_window",
        )
        add_detail(f"pixel-q05-r42-b01-window-sill-{index}", (width + 0.10, 0.035, 0.045), (x, y - height * 0.52, -5.02), _mix(trim, dark, 0.12), "facade_window_detail", "photo_supported_window_frame", MICRO_VOXEL)

    # Balcony rails and service boxes get small lit nodes, making their depth
    # visible from side views instead of disappearing into the facade.
    balcony_specs = ((-3.90, 2.42, 1.75), (2.95, 3.98, 2.05), (-2.55, 5.92, 1.65), (4.35, 7.72, 1.85), (-5.30, 8.58, 1.35))
    for index, (x, y, width) in enumerate(balcony_specs):
        add_detail(f"pixel-q05-r42-b01-balcony-front-contour-{index}", (width, 0.045, 0.055), (x, y + 0.40, -4.60), contour, "balcony_contour", "photo_supported_balcony_layer", MICRO_VOXEL)
        for rail_index in range(5):
            rail_x = x - width * 0.42 + rail_index * width * 0.21
            add_detail(f"pixel-q05-r42-b01-balcony-light-node-{index}-{rail_index}", (0.035, 0.07, 0.025), (rail_x, y + 0.48, -4.57), _mix(window, lamp, 0.16 if rail_index % 2 else 0.04), "balcony_light_detail", "photo_palette_lit_detail", MICRO_VOXEL)
    for index, (x, y) in enumerate(((-6.05, 2.10), (5.40, 3.28), (-4.85, 6.22), (5.80, 7.35), (0.10, 9.08))):
        add_detail(f"pixel-q05-r42-b01-service-box-face-{index}", (0.32, 0.18, 0.035), (x, y, -4.70), _mix(metal, window, 0.12), "facade_service_unit", "photo_supported_facade_service_unit", MICRO_VOXEL)
        add_detail(f"pixel-q05-r42-b01-service-box-status-{index}", (0.08, 0.035, 0.018), (x + 0.10, y + 0.04, -4.67), lamp, "facade_service_unit", "photo_palette_lit_detail", MICRO_VOXEL)

    # Foreground wires receive occasional bright nodes and vegetation gets
    # two-tone leaf pixels; both are depth cues, not collision geometry.
    for index, (x, y, z) in enumerate(((-8.0, 5.5, -1.6), (8.0, 4.0, -2.8), (-6.8, 1.0, -8.8))):
        add_detail(f"pixel-q05-r42-b01-wire-node-{index}", (0.12, 0.12, 0.12), (x, y, z), _mix(lamp, accent, 0.20), "foreground_wire_detail", "photo_supported_foreground_wire", MICRO_VOXEL)
    for index, (x, y, z) in enumerate(((-7.1, 7.6, -4.45), (-6.65, 8.1, -4.40), (-7.55, 8.25, -4.35), (6.85, 9.1, -4.48))):
        add_detail(f"pixel-q05-r42-b01-leaf-shadow-{index}", (0.56, 0.30, 0.22), (x, y, z), _shade(plant, 0.58), "foreground_vegetation", "photo_supported_foreground_leaf", FURNITURE_VOXEL)
        add_detail(f"pixel-q05-r42-b01-leaf-highlight-{index}", (0.24, 0.15, 0.12), (x + 0.15, y + 0.16, z + 0.02), _mix(plant, lamp, 0.16), "foreground_vegetation", "photo_supported_foreground_leaf", MICRO_VOXEL)

    return _finalize_exterior_pixel_pass(
        image_path, output_dir, scene, layout, collision, manifest, details,
        PIXEL_V42_LAYOUT_VERSION, "pixel_style_sample_v42", "v42-b01-pixel-material-light-pass-34",
        "q05_b01_fine_pixel_facade_window_balcony_light_surface",
        "像素风 V42 B01 建筑细像素材质候选：继承 V35 的蓝调立面、错落暖窗、阳台、前景线、碰撞和外部路线，"
        "增加立面分段轮廓、窗内局部像素光、阳台节点、服务盒和前景线/叶片层；仍只承诺外部观察。",
        ["facade_contour_courses", "window_pixel_cores", "balcony_light_nodes", "service_box_pixels", "foreground_wire_leaf_layers"],
        "facade_blue_hour_v3", "candidate_building_pixel_material_light_hierarchy",
    )


# V43/V44 are targeted corrections from the V40-V42 screenshot review.  N01
# needed a clearer mountain silhouette and less visual weight from the nearest
# fence wires.  B01 needed a brighter local night-value hierarchy; this is a
# lighting-only comparison and deliberately does not alter its geometry.
PIXEL_V43_LAYOUT_VERSION = "pixel-v43-n01-ridge-silhouette-fence-balance-pass-35"
PIXEL_V44_LAYOUT_VERSION = "pixel-v44-b01-blue-hour-readability-pass-35"


def build_pixel_nature_v43(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r43-n01") -> dict[str, object]:
    build_pixel_nature_v40(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    window, dark, accent, trim, floor = roles["window"], roles["dark"], roles["accent"], roles["trim"], roles["floor"]
    objects = layout["objects"]
    details: list[str] = []

    # The V40 screenshot showed the three inherited broad rails dominating the
    # middle of the image.  Keep the lower rail and posts as a photo-supported
    # foreground anchor, remove only the two redundant render meshes, and keep
    # the thinner wire/detail layers.  Collision data is untouched.
    removed_ids = {
        "pixel-q05-r22-n01-fence-rail-1",
        "pixel-q05-r22-n01-fence-rail-2",
    }
    for geometry_id in removed_ids:
        if geometry_id in scene.geometry:
            scene.delete_geometry(geometry_id)
    layout["objects"] = [item for item in objects if item["id"] not in removed_ids]
    manifest["detail_object_ids"] = [item for item in manifest.get("detail_object_ids", []) if item not in removed_ids]
    objects = layout["objects"]

    def add_detail(name, size, position, colour, role, source, grid=MICRO_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    contour = _mix(dark, trim, 0.10)
    snow = _mix(window, [255, 255, 248], 0.42)
    snow_shadow = _mix(window, dark, 0.38)
    # Add stepped crest pixels at each depth band.  Unlike a repeated facet
    # stamp, these pieces describe a continuous skyline and remain visible at
    # the first-person horizon.
    crest_specs = (
        ("near", -7.9, ((-6.2, 1.72), (-5.0, 2.05), (-3.8, 2.34), (-2.6, 2.10), (-1.4, 1.78), (-0.2, 2.16), (1.0, 2.48), (2.2, 2.22), (3.4, 1.86), (4.6, 2.08), (5.8, 1.76))),
        ("mid", -12.8, ((-6.6, 1.92), (-5.0, 2.20), (-3.4, 2.44), (-1.8, 2.18), (-0.2, 2.02), (1.4, 2.38), (3.0, 2.58), (4.6, 2.22), (6.0, 2.00))),
        ("far", -17.4, ((-6.8, 2.18), (-5.2, 2.36), (-3.6, 2.52), (-2.0, 2.32), (-0.4, 2.20), (1.2, 2.42), (2.8, 2.64), (4.4, 2.40), (5.8, 2.26))),
    )
    for band, z, points in crest_specs:
        for index, (x, y) in enumerate(points):
            add_detail(f"pixel-q05-r43-n01-{band}-ridge-crest-{index}", (0.92, 0.12, 0.16), (x, y, z), snow_shadow if index % 3 == 0 else snow, "mountain_ridge_contour", "photo_supported_snow_ridge", FURNITURE_VOXEL)
            if index % 2 == 0:
                add_detail(f"pixel-q05-r43-n01-{band}-ridge-edge-{index}", (0.40, 0.035, 0.035), (x + 0.18, y + 0.09, z - 0.09), contour, "mountain_ridge_contour", "pixel_style_contour_rule", MICRO_VOXEL)

    # A few directional snow planes connect the newly readable crests to the
    # existing near-ground surface; they are not collision surfaces.
    for index, (x, z, width) in enumerate(((-5.2, -7.1, 1.35), (-2.8, -7.7, 1.10), (0.2, -8.0, 1.48), (3.3, -7.5, 1.22), (5.3, -7.0, 0.92))):
        add_detail(f"pixel-q05-r43-n01-snow-slope-plane-{index}", (width, 0.028, 0.24), (x, 0.52, z), _mix(snow, accent, 0.10 if index % 2 else 0.0), "snow_surface_detail", "photo_supported_near_ground", MICRO_VOXEL)

    layout_version = PIXEL_V43_LAYOUT_VERSION
    route_name = "pixel_style_sample_v43"
    detail_pass = "v43-n01-ridge-silhouette-fence-balance-pass-35"
    generated_regions = ["stepped_multi_depth_ridge_contours", "snow_slope_connection_planes", "foreground_fence_weight_balance"]
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_n01_ridge_silhouette_and_fence_weight_correction"
    layout.setdefault("pixel_spec", {})["detail_pass"] = detail_pass
    layout["pixel_spec"]["lighting_preset"] = "outdoor_cool_daylight_v2"
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + generated_regions
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version
    manifest["version"] = "pixel-v43"
    manifest["provider_version"] = "pixel-voxel-v43"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V43 N01 定向修正候选：继承 V40 的雪面像素、冷色光影、碰撞和路线，"
        "删除两条过重的重复围栏渲染轨，保留低位围栏与细线，并用近中远连续阶梯雪脊强化地平线；"
        "删除仅影响视觉权重，不改变碰撞，仍需动态回头验收。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = "candidate_nature_ridge_silhouette_fence_balance"
    manifest["quality_metrics"]["lighting_status"] = "candidate_outdoor_cool_daylight_v2"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["lighting_preset"] = "outdoor_cool_daylight_v2"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + generated_regions
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details
    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V43 · N01 雪脊轮廓与围栏权重修正候选\n\n"
        "继承 V40；仅调整可见围栏层级并增加连续阶梯雪脊，不改变碰撞。质量状态仍为 unverified。\n",
        encoding="utf-8",
    )
    return manifest


def build_pixel_building_v44(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r44-b01") -> dict[str, object]:
    build_pixel_building_v42(image_path, output_dir, scene_id)
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    layout_version = PIXEL_V44_LAYOUT_VERSION
    route_name = "pixel_style_sample_v44"
    detail_pass = "v44-b01-blue-hour-readability-pass-35"
    preset = "facade_blue_hour_v4"
    generated_regions = ["blue_hour_local_value_lift"]
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_b01_blue_hour_local_value_readability_comparison"
    layout.setdefault("pixel_spec", {})["detail_pass"] = detail_pass
    layout["pixel_spec"]["lighting_preset"] = preset
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + generated_regions
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version
    manifest["version"] = "pixel-v44"
    manifest["provider_version"] = "pixel-voxel-v44"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V44 B01 光影可读性对照候选：完全继承 V42 的立面、窗内像素、阳台、前景线、"
        "碰撞和外部路线，仅提高蓝调夜景的环境补光与局部暖窗可读性，不改变几何。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = "candidate_building_pixel_material_light_hierarchy"
    manifest["quality_metrics"]["lighting_status"] = "candidate_facade_blue_hour_v4"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["lighting_preset"] = preset
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + generated_regions
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V44 · B01 蓝调夜景光影可读性对照候选\n\n"
        "完全继承 V42 几何、碰撞和路线，仅提高环境补光与局部暖窗层次；质量状态仍为 unverified。\n",
        encoding="utf-8",
    )
    return manifest


# V45 responds to the user-provided N01 route recording.  The route proved
# the controller and collision margin, but side turns exposed empty grey space
# because the inherited mountain masses were concentrated on the forward
# -Z view.  Add bounded side shoulder terrain and stepped lateral ridges as
# procedural completion, without enclosing the scene in a fake skybox or
# changing the walkable/collision contract.
PIXEL_V45_LAYOUT_VERSION = "pixel-v45-n01-lateral-terrain-closure-pass-36"


def build_pixel_nature_v45(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r45-n01") -> dict[str, object]:
    build_pixel_nature_v43(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    floor, window = roles["floor"], roles["window"]
    dark, accent, trim = roles["dark"], roles["accent"], roles["trim"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=MICRO_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    contour = _mix(dark, trim, 0.12)
    shoulder_dark = _mix(floor, dark, 0.24)
    shoulder_mid = _mix(floor, window, 0.16)
    shoulder_light = _mix(window, accent, 0.12)

    # Bounded side shoulders occupy the near/mid terrain bands that were empty
    # when the user turned away from the forward composition.  They are broken
    # into stepped masses, so side views show terrain depth rather than a flat
    # enclosing wall.
    shoulder_specs = (
        ("left", -7.8, ((-1.8, 0.48, 1.20, 2.40), (-4.8, 0.66, 1.60, 2.90), (-7.9, 0.84, 1.90, 3.20), (-11.0, 1.08, 2.20, 3.50))),
        ("right", 7.8, ((-1.8, 0.48, 1.20, 2.40), (-4.8, 0.66, 1.60, 2.90), (-7.9, 0.84, 1.90, 3.20), (-11.0, 1.08, 2.20, 3.50))),
    )
    for side, x, entries in shoulder_specs:
        for index, (z, y, height, depth) in enumerate(entries):
            add_detail(
                f"pixel-q05-r45-n01-{side}-shoulder-mass-{index}", (1.35, height, depth), (x, y, z),
                shoulder_dark if index % 2 else shoulder_mid, "lateral_terrain_mass", "procedural_completion", FURNITURE_VOXEL,
            )
            add_detail(
                f"pixel-q05-r45-n01-{side}-shoulder-snow-cap-{index}", (1.16, 0.08, depth * 0.78), (x, y + height * 0.52, z - 0.05),
                shoulder_light, "lateral_terrain_surface", "procedural_completion", MICRO_VOXEL,
            )
            if index < 3:
                add_detail(
                    f"pixel-q05-r45-n01-{side}-shoulder-contour-{index}", (0.82, 0.035, 0.05), (x - (0.18 if side == "left" else -0.18), y + height * 0.52 + 0.06, z - depth * 0.22),
                    contour, "lateral_terrain_contour", "pixel_style_contour_rule", MICRO_VOXEL,
                )

    # Far lateral ridges add a second depth layer at the turn without
    # extending the near terrain across the whole screen.
    for side, x in (("left", -6.2), ("right", 6.2)):
        for index, (z, y, width, height) in enumerate(((-13.0, 1.52, 1.55, 1.10), (-15.1, 1.72, 1.85, 1.34), (-17.2, 1.92, 2.10, 1.55))):
            add_detail(
                f"pixel-q05-r45-n01-{side}-far-ridge-{index}", (width, height, 1.10), (x, y, z), _mix(shoulder_mid, dark, 0.14),
                "lateral_ridge_mass", "procedural_completion", FURNITURE_VOXEL,
            )
            add_detail(
                f"pixel-q05-r45-n01-{side}-far-ridge-edge-{index}", (width * 0.72, 0.04, 0.05), (x, y + height * 0.54, z - 0.22), shoulder_light,
                "lateral_ridge_contour", "procedural_completion", MICRO_VOXEL,
            )

    layout_version = PIXEL_V45_LAYOUT_VERSION
    route_name = "pixel_style_sample_v45"
    detail_pass = "v45-n01-lateral-terrain-closure-pass-36"
    generated_regions = ["bounded_lateral_terrain_shoulders", "side_view_ridge_layers", "route_recording_driven_background_closure"]
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = "q05_n01_route_driven_lateral_terrain_closure"
    layout.setdefault("pixel_spec", {})["detail_pass"] = detail_pass
    layout["pixel_spec"]["lighting_preset"] = "outdoor_cool_daylight_v2"
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + generated_regions
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version
    manifest["version"] = "pixel-v45"
    manifest["provider_version"] = "pixel-voxel-v45"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = (
        "像素风 V45 N01 路线驱动侧向地形闭合候选：继承 V43 的雪脊、围栏权重、冷色光影、碰撞和路线，"
        "针对录像中回头/侧转暴露的空灰背景，增加有限范围的左右近地肩部、远侧山脊和雪帽；"
        "不使用整屏天空或背景卡片，不新增碰撞，仍需重新录制侧转路线确认。"
    )
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = "candidate_nature_lateral_terrain_closure"
    manifest["quality_metrics"]["lighting_status"] = "candidate_outdoor_cool_daylight_v2"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["lighting_preset"] = "outdoor_cool_daylight_v2"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + generated_regions
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details
    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna 像素风样板 V45 · N01 侧向地形闭合候选\n\n"
        "根据 V43 路线录像补充有限范围侧向肩部与远侧山脊；不改变碰撞，不用背景卡片遮挡空区。质量状态仍为 unverified。\n",
        encoding="utf-8",
    )
    return manifest


# V46 is a shared micro-surface precision pass across the five reviewed
# samples.  The previous candidates had semantic anchors, but their surfaces
# still read as large blocks at route distance.  This pass adds authored,
# sparse micro-patterns to existing visible surfaces.  It deliberately does
# not change camera, movement, collision or the photo-to-layout policy.
PIXEL_V46_LAYOUT_VERSIONS = {
    "corridor": "pixel-v46-i01-micro-surface-precision-pass-37",
    "living": "pixel-v46-i02-micro-surface-precision-pass-37",
    "nature": "pixel-v46-n01-micro-surface-precision-pass-37",
    "street": "pixel-v46-s01-micro-surface-precision-pass-37",
    "building": "pixel-v46-b01-micro-surface-precision-pass-37",
}


def _build_pixel_micro_surface_v46(
    image_path: Path,
    output_dir: Path,
    scene_id: str,
    base_builder,
    profile: str,
) -> dict[str, object]:
    base_builder(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    wall, floor = roles["wall"], roles["floor"]
    trim, window = roles["trim"], roles["window"]
    wood, metal = roles["wood"], roles["metal"]
    sofa, plant = roles["sofa"], roles["plant"]
    lamp, dark, accent = roles["lamp"], roles["dark"], roles["accent"]
    objects = layout["objects"]
    details: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=MICRO_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    def add_xy(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_xy(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    def add_xz(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_xz(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    def add_yz(prefix, pattern, centre, cell, depth, colours, role, source):
        _add_pattern_yz(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=MICRO_VOXEL)
        details.append(prefix)

    contour = _mix(dark, trim, 0.10)
    light = _mix(window, lamp, 0.16)
    mid = _mix(window, accent, 0.16)
    shadow = _mix(floor, dark, 0.26)
    generated_regions: list[str] = []

    if profile == "corridor":
        # Make the repeated windows and doors readable as small authored
        # surfaces instead of flat coloured rectangles.
        for index, z in enumerate((3.50, 0.0, -3.50, -7.0)):
            add_yz(
                f"pixel-q05-r46-i01-window-micro-grid-{index}",
                (".aaaa.", "abbbba", "acccda", "abddba", ".aaaa."),
                (-2.025, 1.62, z + 0.10), (0.050, 0.070), 0.012,
                {"a": contour, "b": _mix(window, dark, 0.30), "c": mid, "d": light},
                "window_micro_surface", "photo_supported_window_opening",
            )
            add_yz(
                f"pixel-q05-r46-i01-door-micro-grid-{index}",
                ("aaaaaa", "abbbba", "acccda", "abddba", "abbbba", "aaaaaa"),
                (2.025, 1.48, z), (0.055, 0.11), 0.012,
                {"a": contour, "b": _mix(wood, wall, 0.18), "c": _mix(wood, accent, 0.12), "d": light},
                "door_micro_surface", "photo_supported_door_panel",
            )
        for row, z in enumerate((4.60, 3.45, 2.30, 1.15, 0.0, -1.15, -2.30, -3.45, -4.60, -5.75, -6.90, -8.05)):
            for column, x in enumerate((-1.70, -1.05, -0.40, 0.25, 0.90, 1.55)):
                add_detail(
                    f"pixel-q05-r46-i01-floor-micro-glint-{row}-{column}", (0.075, 0.012, 0.035),
                    (x, 0.247, z - 0.16), _mix(floor, window, 0.16 if (row + column) % 3 else 0.24),
                    "floor_micro_surface", "photo_supported_floor_tile", MICRO_VOXEL,
                )
        generated_regions += ["corridor_window_micro_grids", "corridor_door_micro_grids", "corridor_floor_micro_glints"]
        lighting_preset = "indoor_pixel_detail_v4"
        note = "像素风 V46 I01 微表面精修候选：继承 V39 走廊结构、窗门层、碰撞和路线，增加窗门 0.015625 微网格及有序地砖高光；不改变路线。"
        semantic_status = "candidate_corridor_micro_surface_precision"
        authoring = "q05_i01_micro_surface_precision_pass"
    elif profile == "living":
        # The living room's large anchors receive material-specific micro
        # marks: upholstery stitching, table top grain, console slats and
        # plant highlights.  Empty surface remains intentional.
        sofa_dark = _mix(sofa, trim, 0.42)
        sofa_light = _mix(sofa, wall, 0.28)
        for index, (x, z) in enumerate(((-2.78, -1.45), (-1.40, -1.45), (-0.10, -1.45))):
            add_xy(
                f"pixel-q05-r46-i02-sofa-micro-stitch-{index}",
                (".aaaa.", "abbbba", "acccca", "abddba", "acccca", "abbbba", ".aaaa."),
                (x, 1.52, z + 0.12), (0.045, 0.045), 0.012,
                {"a": contour, "b": sofa_dark, "c": sofa_light, "d": _mix(sofa, accent, 0.14)},
                "upholstery_micro_surface", "photo_supported_sectional_sofa",
            )
        add_xz(
            "pixel-q05-r46-i02-tabletop-micro-grain",
            ("..aaaa..", ".abbbba.", "abaccca", "abccc cba".replace(" ", ""), "abaccca", ".abbbba.", "..aaaa.."),
            (1.25, 1.235, 0.55), (0.065, 0.065), 0.012,
            {"a": contour, "b": _mix(wood, dark, 0.20), "c": _mix(wood, wall, 0.20)},
            "table_micro_surface", "photo_supported_coffee_table",
        )
        for index, x in enumerate((2.30, 2.58, 2.86, 3.14)):
            add_detail(
                f"pixel-q05-r46-i02-console-micro-slat-{index}", (0.045, 0.34, 0.022),
                (x, 0.62, -5.96), _mix(wood, dark, 0.28), "console_micro_surface", "photo_supported_tv_wall", MICRO_VOXEL,
            )
        for index, (x, y, z) in enumerate(((-3.92, 2.16, 0.44), (-3.68, 2.42, 0.44), (-3.34, 2.68, 0.44), (-3.04, 2.86, 0.44), (-3.55, 3.12, 0.44))):
            add_detail(
                f"pixel-q05-r46-i02-plant-micro-leaf-{index}", (0.22, 0.12, 0.12), (x, y, z), _mix(plant, lamp, 0.12 if index % 2 else 0.0),
                "vegetation_micro_surface", "photo_supported_vegetation", MICRO_VOXEL,
            )
        generated_regions += ["living_upholstery_micro_stitches", "living_tabletop_micro_grain", "living_console_micro_slats", "living_plant_micro_leaves"]
        lighting_preset = "indoor_pixel_detail_v4"
        note = "像素风 V46 I02 微表面精修候选：继承 V38 客厅构图、材质层、光影、碰撞和路线，增加沙发缝线、桌面纹理、电视柜细条和植物微叶；不以体素数量替代语义。"
        semantic_status = "candidate_living_micro_surface_precision"
        authoring = "q05_i02_micro_surface_precision_pass"
    elif profile == "nature":
        # Mountain and lateral shoulders use sparse snow facets at different
        # scales.  These are visible texture cues, not a blanket of random
        # boxes and not new walkable/collision terrain.
        snow_dark = _mix(window, dark, 0.40)
        snow_mid = _mix(window, accent, 0.20)
        snow_light = _mix(window, [255, 255, 248], 0.42)
        for index, (x, y, z) in enumerate(((-7.8, 1.12, -1.8), (-7.8, 1.42, -4.8), (-7.8, 1.78, -7.9), (-7.8, 2.02, -11.0), (7.8, 1.12, -1.8), (7.8, 1.42, -4.8), (7.8, 1.78, -7.9), (7.8, 2.02, -11.0))):
            add_xy(
                f"pixel-q05-r46-n01-lateral-snow-micro-{index}",
                (".aaa.", "abcca", "abdda", ".aaa."),
                (x, y + 0.08, z), (0.070, 0.070), 0.014,
                {"a": contour, "b": snow_dark, "c": snow_mid, "d": snow_light},
                "lateral_terrain_micro_surface", "procedural_completion",
            )
        for index, z in enumerate((-7.2, -8.0, -8.8, -12.7, -13.5, -14.3, -17.0, -17.8)):
            add_detail(
                f"pixel-q05-r46-n01-horizon-snow-pixel-{index}", (0.38, 0.035, 0.045),
                ((-4.6 + (index % 4) * 3.0), 2.22 - (index % 3) * 0.08, z), snow_light if index % 2 else snow_mid,
                "mountain_micro_surface", "photo_supported_snow_ridge", MICRO_VOXEL,
            )
        generated_regions += ["lateral_shoulder_micro_facets", "horizon_snow_micro_pixels"]
        lighting_preset = "outdoor_cool_daylight_v2"
        note = "像素风 V46 N01 微表面精修候选：继承 V45 的路线驱动侧向地形闭合、雪脊、围栏、碰撞和路线，增加有限雪面微图案；不扩张为天空盒。"
        semantic_status = "candidate_nature_micro_surface_precision"
        authoring = "q05_n01_micro_surface_precision_pass"
    elif profile == "street":
        road_dark = _mix(floor, dark, 0.34)
        road_light = _mix(floor, window, 0.20)
        car_dark = _mix(metal, dark, 0.22)
        car_glass = _mix(window, accent, 0.20)
        for index, z in enumerate((5.8, 4.4, 3.0, 1.6, 0.2, -1.2, -2.6, -4.0, -5.4, -6.8, -8.2, -9.6)):
            add_detail(
                f"pixel-q05-r46-s01-road-micro-mark-{index}", (0.035, 0.018, 0.32 if index % 2 else 0.20),
                (0.0, 0.272, z), road_dark, "road_micro_surface", "photo_supported_road_surface", MICRO_VOXEL,
            )
            add_detail(
                f"pixel-q05-r46-s01-road-micro-glint-{index}", (0.11, 0.014, 0.022),
                (0.32, 0.284, z - 0.18), road_light, "road_micro_surface", "photo_supported_road_surface", MICRO_VOXEL,
            )
        for index, (x, z, body) in enumerate(((-2.55, 1.2, wood), (2.65, -4.0, metal))):
            add_xy(
                f"pixel-q05-r46-s01-car-micro-face-{index}",
                (".aaaa.", "abccba", "acddca", "abccba", ".aaaa."),
                (x, 0.86, z + 1.37), (0.075, 0.055), 0.012,
                {"a": car_dark, "b": _mix(body, car_glass, 0.18), "c": car_glass, "d": lamp},
                "vehicle_micro_surface", "photo_supported_vehicle",
            )
        for side, x in (("left", -6.0), ("right", 6.0)):
            for building_index, z in enumerate((3.6, -2.0, -7.6)):
                for row_index, y in enumerate((1.30, 2.22, 3.14, 4.06)):
                    add_xy(
                        f"pixel-q05-r46-s01-{side}-window-micro-{building_index}-{row_index}",
                        (".aa.", "abca", "acda", ".aa."),
                        (x, y, z + 2.18), (0.070, 0.070), 0.010,
                        {"a": contour, "b": _mix(window, wall, 0.12), "c": window, "d": _mix(window, lamp, 0.14)},
                        "building_window_micro_surface", "photo_supported_window_line",
                    )
        generated_regions += ["road_micro_markings", "vehicle_micro_faces", "street_window_micro_surfaces"]
        lighting_preset = "street_soft_daylight_v3"
        note = "像素风 V46 S01 微表面精修候选：继承 V41 道路、车辆、窗格、树冠、碰撞和路线，增加道路微标记、车辆前脸微图案和侧面窗内像素。"
        semantic_status = "candidate_street_micro_surface_precision"
        authoring = "q05_s01_micro_surface_precision_pass"
    else:
        glass_dark = _mix(window, dark, 0.34)
        glass_mid = _mix(window, accent, 0.18)
        glass_high = _mix(window, lamp, 0.18)
        warm = _mix(lamp, accent, 0.16)
        window_specs = (
            (-5.75, 1.20), (-3.75, 1.62), (-1.45, 1.18), (1.10, 1.64), (3.72, 1.20), (5.82, 1.82),
            (-5.20, 3.45), (-2.80, 3.30), (-0.25, 3.66), (2.35, 3.18), (5.18, 3.58),
            (-5.72, 5.62), (-3.35, 5.35), (-0.85, 5.74), (1.80, 5.42), (4.80, 5.78),
            (-4.82, 7.55), (-2.15, 7.34), (0.55, 7.68), (3.38, 7.30), (5.82, 7.78),
        )
        for index, (x, y) in enumerate(window_specs):
            add_xy(
                f"pixel-q05-r46-b01-window-micro-core-{index}",
                (".aaaa.", "abbbba", "acccda", "abddba", "abccba", ".aaaa."),
                (x, y, -5.035), (0.048, 0.060), 0.010,
                {"a": contour, "b": warm if index % 3 else glass_dark, "c": glass_mid, "d": glass_high},
                "facade_window_micro_surface", "photo_supported_lit_window",
            )
        for index, y in enumerate((0.72, 2.78, 4.84, 6.90, 8.96)):
            for segment, x in enumerate((-5.85, -3.90, -1.95, 0.0, 1.95, 3.90, 5.85)):
                if (index + segment) % 2 == 0:
                    add_detail(
                        f"pixel-q05-r46-b01-facade-micro-joint-{index}-{segment}", (0.28, 0.018, 0.022),
                        (x, y + 0.34, -5.055), _mix(trim, dark, 0.18), "facade_micro_surface", "photo_inferred_building_mass", MICRO_VOXEL,
                    )
        for index, (x, y) in enumerate(((-3.90, 2.42), (2.95, 3.98), (-2.55, 5.92), (4.35, 7.72), (-5.30, 8.58))):
            for node in range(4):
                add_detail(
                    f"pixel-q05-r46-b01-balcony-micro-node-{index}-{node}", (0.025, 0.045, 0.018),
                    (x - 0.48 + node * 0.32, y + 0.50, -4.56), _mix(window, lamp, 0.12 if node % 2 else 0.03),
                    "balcony_micro_surface", "photo_supported_balcony_layer", MICRO_VOXEL,
                )
        generated_regions += ["facade_window_micro_cores", "facade_micro_joints", "balcony_micro_nodes"]
        lighting_preset = "facade_blue_hour_v4"
        note = "像素风 V46 B01 微表面精修候选：继承 V44 立面、窗内光、阳台节点、蓝调光影、碰撞和路线，增加窗内微核心、立面接缝和阳台微节点。"
        semantic_status = "candidate_building_micro_surface_precision"
        authoring = "q05_b01_micro_surface_precision_pass"

    layout_version = PIXEL_V46_LAYOUT_VERSIONS[profile]
    route_name = "pixel_style_sample_v46"
    detail_pass = f"v46-{profile}-micro-surface-precision-pass-37"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = authoring
    layout.setdefault("pixel_spec", {})["detail_pass"] = detail_pass
    layout["pixel_spec"]["lighting_preset"] = lighting_preset
    layout["pixel_spec"]["surface_density_policy"] = "sparse_semantic_micro_patterns_0_015625_no_uniform_noise"
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + generated_regions
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version
    manifest["version"] = "pixel-v46"
    manifest["provider_version"] = "pixel-voxel-v46"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = note
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = semantic_status
    manifest["quality_metrics"]["lighting_status"] = f"candidate_{lighting_preset}"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["lighting_preset"] = lighting_preset
    manifest["pixel_spec"]["surface_density_policy"] = "sparse_semantic_micro_patterns_0_015625_no_uniform_noise"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + generated_regions
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details
    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        f"Luna 像素风样板 V46 · {profile} 微表面精修候选\n\n"
        f"{note}\n新增微表面不参与碰撞；质量状态仍为 unverified。\n",
        encoding="utf-8",
    )
    return manifest


def build_pixel_corridor_v46(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r46-i01") -> dict[str, object]:
    return _build_pixel_micro_surface_v46(image_path, output_dir, scene_id, build_pixel_corridor_v39, "corridor")


def build_pixel_living_v46(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r46-i02") -> dict[str, object]:
    return _build_pixel_micro_surface_v46(image_path, output_dir, scene_id, build_pixel_living_v38, "living")


def build_pixel_nature_v46(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r46-n01") -> dict[str, object]:
    return _build_pixel_micro_surface_v46(image_path, output_dir, scene_id, build_pixel_nature_v45, "nature")


def build_pixel_street_v46(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r46-s01") -> dict[str, object]:
    return _build_pixel_micro_surface_v46(image_path, output_dir, scene_id, build_pixel_street_v41, "street")


def build_pixel_building_v46(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r46-b01") -> dict[str, object]:
    return _build_pixel_micro_surface_v46(image_path, output_dir, scene_id, build_pixel_building_v44, "building")


# V47 is still a Q03 visual-correction pass.  V46 increased local pixel
# density, but the GPU start frames showed that several large surfaces still
# read as unstructured blocks.  V47 adds a second, larger authored hierarchy:
# panels, ledges, cornices, furniture separations and distant silhouette
# bands.  It deliberately inherits V46 and never adds collision boxes.
PIXEL_V47_LAYOUT_VERSIONS = {
    "corridor": "pixel-v47-i01-semantic-surface-hierarchy-pass-38",
    "living": "pixel-v47-i02-semantic-surface-hierarchy-pass-38",
    "nature": "pixel-v47-n01-semantic-surface-hierarchy-pass-38",
    "street": "pixel-v47-s01-semantic-surface-hierarchy-pass-38",
    "building": "pixel-v47-b01-semantic-surface-hierarchy-pass-38",
}


def _build_pixel_semantic_surface_v47(
    image_path: Path,
    output_dir: Path,
    scene_id: str,
    base_builder,
    profile: str,
) -> dict[str, object]:
    base_builder(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    roles = layout["palette"]["roles"]
    wall, floor = roles["wall"], roles["floor"]
    trim, window = roles["trim"], roles["window"]
    wood, metal = roles["wood"], roles["metal"]
    sofa, plant = roles["sofa"], roles["plant"]
    lamp, dark, accent = roles["lamp"], roles["dark"], roles["accent"]
    objects = layout["objects"]
    details: list[str] = []
    generated_regions: list[str] = []

    def add_detail(name, size, position, colour, role, source, grid=FURNITURE_VOXEL):
        _add_part(scene, objects, [], name, size, position, colour, role, source, grid=grid)
        details.append(name)

    def add_xy(prefix, pattern, centre, cell, depth, colours, role, source, grid=FURNITURE_VOXEL):
        _add_pattern_xy(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=grid)
        details.append(prefix)

    def add_xz(prefix, pattern, centre, cell, depth, colours, role, source, grid=FURNITURE_VOXEL):
        _add_pattern_xz(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=grid)
        details.append(prefix)

    def add_yz(prefix, pattern, centre, cell, depth, colours, role, source, grid=FURNITURE_VOXEL):
        _add_pattern_yz(scene, objects, prefix, pattern, centre, cell, depth, colours, role, source, grid=grid)
        details.append(prefix)

    contour = _mix(dark, trim, 0.12)
    shadow = _mix(dark, wall, 0.30)
    warm = _mix(lamp, accent, 0.16)
    cool = _mix(window, accent, 0.18)

    if profile == "corridor":
        # A repeated ceiling-light rhythm and wall wainscot break the long
        # flat hallway planes while preserving its original direction.
        for index, z in enumerate((4.20, 2.65, 1.10, -0.45, -2.00, -3.55, -5.10, -6.65, -8.20)):
            add_detail(
                f"pixel-q05-r47-i01-ceiling-light-housing-{index}", (0.34, 0.065, 0.16),
                (0.0, 3.01, z), contour, "ceiling_light_structure", "photo_supported_ceiling_fixture",
            )
            add_detail(
                f"pixel-q05-r47-i01-ceiling-light-core-{index}", (0.19, 0.018, 0.08),
                (0.0, 2.96, z), warm, "ceiling_light_detail", "photo_supported_ceiling_fixture", MICRO_VOXEL,
            )
        for side, x in (("left", -2.62), ("right", 2.62)):
            add_detail(
                f"pixel-q05-r47-i01-{side}-wainscot-rail", (0.055, 0.26, 12.70),
                (x, 0.70, -1.45), _mix(trim, wall, 0.16), "wall_panel_structure", "photo_supported_wall_rail",
            )
            for index, z in enumerate((3.15, 0.25, -2.65, -5.55)):
                add_detail(
                    f"pixel-q05-r47-i01-{side}-wall-panel-break-{index}", (0.035, 0.62, 0.86),
                    (x + (0.04 if side == "left" else -0.04), 1.20, z), shadow, "wall_panel_detail", "photo_inferred_wall_panel", MICRO_VOXEL,
                )
        generated_regions += ["corridor_ceiling_light_rhythm", "corridor_wainscot_structure", "corridor_wall_panel_breaks"]
        lighting_preset = "indoor_pixel_detail_v4"
        note = "像素风 V47 I01 语义表面层次候选：继承 V46，增加吊顶灯具节奏、墙裙导轨和分段墙面层次；不改变碰撞与路线。"
        semantic_status = "candidate_corridor_semantic_surface_hierarchy"
        authoring = "q05_i01_semantic_surface_hierarchy_pass"
    elif profile == "living":
        # Add readable object separation around the photographed room's main
        # anchors: cushions, media wall, curtain rhythm and table edges.
        for index, (x, z) in enumerate(((-2.78, -1.45), (-1.40, -1.45), (-0.10, -1.45))):
            add_detail(
                f"pixel-q05-r47-i02-sofa-back-cushion-{index}", (0.92, 0.48, 0.10),
                (x, 1.78, z + 0.32), _mix(sofa, wall, 0.18), "upholstery_structure", "photo_supported_sectional_sofa",
            )
            add_detail(
                f"pixel-q05-r47-i02-sofa-seat-break-{index}", (0.72, 0.035, 0.045),
                (x, 1.10, z - 0.08), contour, "upholstery_seam_detail", "photo_supported_sectional_sofa", MICRO_VOXEL,
            )
        for index, x in enumerate((-3.70, -3.25, -2.80, -2.35, -1.90, -1.45, -1.00, -0.55, -0.10)):
            add_detail(
                f"pixel-q05-r47-i02-curtain-fold-{index}", (0.045, 2.05, 0.025),
                (x, 2.10, -6.24), _mix(wall, window, 0.10 + (index % 2) * 0.08), "curtain_surface_detail", "photo_supported_window_covering", MICRO_VOXEL,
            )
        add_xy(
            "pixel-q05-r47-i02-media-wall-panel",
            ("aaaaaaaaaaaaaaaa", "abbbbbbbbbbbbbba", "abacccccccccccba", "abacddddddddd cba".replace(" ", ""), "abacccccccccccba", "abbbbbbbbbbbbbba", "aaaaaaaaaaaaaaaa"),
            (-2.58, 1.62, -6.02), (0.12, 0.12), 0.020,
            {"a": contour, "b": shadow, "c": cool, "d": warm}, "media_wall_pixel_surface", "photo_supported_tv_wall", FURNITURE_VOXEL,
        )
        for index, x in enumerate((0.48, 0.96, 1.44, 1.92, 2.40, 2.88)):
            add_detail(
                f"pixel-q05-r47-i02-media-console-separation-{index}", (0.035, 0.40, 0.055),
                (x, 0.68, -5.98), contour, "media_console_structure", "photo_supported_tv_wall", MICRO_VOXEL,
            )
        generated_regions += ["living_cushion_separation", "living_curtain_fold_rhythm", "living_media_wall_panel", "living_console_separation"]
        lighting_preset = "indoor_pixel_detail_v4"
        note = "像素风 V47 I02 语义表面层次候选：继承 V46，增加沙发靠垫分件、窗帘折线、电视墙面板和电视柜分隔；不改变碰撞与路线。"
        semantic_status = "candidate_living_semantic_surface_hierarchy"
        authoring = "q05_i02_semantic_surface_hierarchy_pass"
    elif profile == "nature":
        # The previous start frame had a readable walkable snowfield but a
        # broad low-information horizon.  These stepped, multi-scale ridge
        # bands restore a pixel-art mountain silhouette without creating a
        # fake skybox or changing the walkable ground.
        ridge_specs = (
            ("far", -18.0, 3.40, 0.34, _mix(window, dark, 0.38)),
            ("middle", -15.4, 2.72, 0.28, _mix(window, accent, 0.18)),
            ("near", -12.8, 2.18, 0.22, _mix(window, [255, 255, 248], 0.32)),
        )
        ridge_patterns = (
            ("..aa....bb....aa..", ".abbb..abbbba..bbba.", "abccccabccddccabccba", "abccccccccccccccccba", "..abbbbbbbbbbbbbba.."),
            ("...aa..bbb..aa...", ".abbb.abccba.bbbba.", "abcccccccccccccccba", "..abbbbbbbbbbbbbba.."),
            ("....aa..bb..aa....", ".abbbabccccabbbba.", "abccccccccccccccba", "..abbbbbbbbbbbbba.."),
        )
        for (name, z, y, cell_size, colour), pattern in zip(ridge_specs, ridge_patterns):
            add_xz(
                f"pixel-q05-r47-n01-{name}-ridge-silhouette", pattern, (0.0, y, z), (cell_size, cell_size), 0.028,
                {"a": contour, "b": colour, "c": _mix(colour, window, 0.18), "d": _mix(colour, [255, 255, 248], 0.28)},
                "mountain_silhouette_surface", "photo_supported_snow_ridge", FURNITURE_VOXEL,
            )
        for index, x in enumerate((-6.0, -4.5, -3.0, -1.5, 0.0, 1.5, 3.0, 4.5, 6.0)):
            add_detail(
                f"pixel-q05-r47-n01-near-snow-contour-{index}", (0.72, 0.035, 0.075),
                (x, 1.06 + (index % 3) * 0.06, -6.4 - (index % 2) * 0.42), _mix(window, [255, 255, 248], 0.24),
                "snow_surface_contour", "photo_supported_snowfield", MICRO_VOXEL,
            )
        generated_regions += ["nature_far_middle_near_ridge_silhouettes", "nature_snow_surface_contours"]
        lighting_preset = "outdoor_cool_daylight_v2"
        note = "像素风 V47 N01 语义表面层次候选：继承 V46，增加远中近三层阶梯山脊剪影与近地雪面等高线；不新增地形碰撞、不扩张为天空盒。"
        semantic_status = "candidate_nature_semantic_surface_hierarchy"
        authoring = "q05_n01_semantic_surface_hierarchy_pass"
    elif profile == "street":
        # The street scene needs a clearer façade cadence and road hierarchy;
        # the added parts sit on existing masses and stay outside collision.
        for side, x in (("left", -5.90), ("right", 5.90)):
            for band, y in enumerate((1.04, 2.02, 3.00, 3.98, 4.96)):
                add_detail(
                    f"pixel-q05-r47-s01-{side}-facade-cornice-{band}", (0.045, 0.055, 12.20),
                    (x, y, -1.70), _mix(trim, dark, 0.18), "street_facade_structure", "photo_inferred_building_mass", MICRO_VOXEL,
                )
            for building, z in enumerate((3.60, -2.00, -7.60)):
                add_yz(
                    f"pixel-q05-r47-s01-{side}-shop-window-grid-{building}",
                    ("aaaaaa", "abccba", "acddca", "abccba", "aaaaaa"), (x, 2.46, z + 2.22), (0.20, 0.18), 0.018,
                    {"a": contour, "b": _mix(window, wall, 0.12), "c": cool, "d": warm},
                    "street_shop_window_surface", "photo_supported_window_line", FURNITURE_VOXEL,
                )
        for index, x in enumerate((-3.84, -2.56, -1.28, 0.0, 1.28, 2.56, 3.84)):
            add_detail(
                f"pixel-q05-r47-s01-crosswalk-pixel-{index}", (0.46, 0.020, 0.16),
                (x, 0.29, 1.62), _mix(window, floor, 0.16), "road_marking_surface", "photo_supported_road_surface", MICRO_VOXEL,
            )
        generated_regions += ["street_facade_cornice_cadence", "street_shop_window_grids", "street_crosswalk_surface"]
        lighting_preset = "street_soft_daylight_v3"
        note = "像素风 V47 S01 语义表面层次候选：继承 V46，增加两侧建筑檐口节奏、店面窗格和道路横向标线；不改变道路碰撞与出生点。"
        semantic_status = "candidate_street_semantic_surface_hierarchy"
        authoring = "q05_s01_semantic_surface_hierarchy_pass"
    else:
        # The building frame already has many windows, but its large façade
        # fields need depth breaks so that side turns do not read as one slab.
        for band, y in enumerate((0.58, 2.58, 4.58, 6.58, 8.58)):
            add_detail(
                f"pixel-q05-r47-b01-facade-horizontal-ledge-{band}", (12.40, 0.055, 0.10),
                (0.0, y, -4.96), _mix(trim, dark, 0.22), "facade_depth_structure", "photo_inferred_building_mass", FURNITURE_VOXEL,
            )
        for index, x in enumerate((-6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0)):
            add_detail(
                f"pixel-q05-r47-b01-facade-pilaster-{index}", (0.075, 8.40, 0.10),
                (x, 4.52, -4.96), _mix(trim, wall, 0.12), "facade_depth_structure", "photo_inferred_building_mass", FURNITURE_VOXEL,
            )
        for index, (x, y) in enumerate(((-5.72, 1.20), (-3.75, 3.30), (-1.45, 5.42), (1.10, 3.18), (3.72, 5.40), (5.82, 7.38))):
            add_yz(
                f"pixel-q05-r47-b01-window-recess-shadow-{index}",
                ("aaaa", "abca", "acda", "abca", "aaaa"), (x, y, -5.08), (0.12, 0.15), 0.026,
                {"a": shadow, "b": cool, "c": glass_mid if "glass_mid" in locals() else window, "d": warm},
                "facade_window_recess", "photo_supported_lit_window", FURNITURE_VOXEL,
            )
        generated_regions += ["facade_horizontal_ledge_depth", "facade_vertical_pilaster_rhythm", "facade_window_recess_shadows"]
        lighting_preset = "facade_blue_hour_v4"
        note = "像素风 V47 B01 语义表面层次候选：继承 V46，增加立面横向檐口、竖向分格和窗洞阴影；不改变外部路线与碰撞。"
        semantic_status = "candidate_building_semantic_surface_hierarchy"
        authoring = "q05_b01_semantic_surface_hierarchy_pass"

    layout_version = PIXEL_V47_LAYOUT_VERSIONS[profile]
    route_name = "pixel_style_sample_v47"
    detail_pass = f"v47-{profile}-semantic-surface-hierarchy-pass-38"
    layout["layout_version"] = layout_version
    layout["route"] = route_name
    layout["style_route"] = route_name
    layout["layout_authoring"] = authoring
    layout.setdefault("pixel_spec", {})["detail_pass"] = detail_pass
    layout["pixel_spec"]["lighting_preset"] = lighting_preset
    layout["pixel_spec"]["surface_density_policy"] = "semantic_surface_hierarchy_on_v46_no_uniform_noise"
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + generated_regions
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = layout_version
    manifest["version"] = "pixel-v47"
    manifest["provider_version"] = "pixel-voxel-v47"
    manifest["generation_source"] = route_name
    manifest["style_route"] = route_name
    manifest["layout_version"] = layout_version
    manifest["generated_region_note"] = note
    manifest["quality_metrics"]["detail_pass"] = detail_pass
    manifest["quality_metrics"]["semantic_detail_status"] = semantic_status
    manifest["quality_metrics"]["lighting_status"] = f"candidate_{lighting_preset}"
    manifest["pixel_spec"]["detail_pass"] = detail_pass
    manifest["pixel_spec"]["lighting_preset"] = lighting_preset
    manifest["pixel_spec"]["surface_density_policy"] = "semantic_surface_hierarchy_on_v46_no_uniform_noise"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + generated_regions
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + details
    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        f"Luna 像素风样板 V47 · {profile} 语义表面层次候选\n\n"
        f"{note}\n新增表面层不参与碰撞；质量状态仍为 unverified。\n",
        encoding="utf-8",
    )
    return manifest


def build_pixel_corridor_v47(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r47-i01") -> dict[str, object]:
    return _build_pixel_semantic_surface_v47(image_path, output_dir, scene_id, build_pixel_corridor_v46, "corridor")


def build_pixel_living_v47(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r47-i02") -> dict[str, object]:
    return _build_pixel_semantic_surface_v47(image_path, output_dir, scene_id, build_pixel_living_v46, "living")


def build_pixel_nature_v47(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r47-n01") -> dict[str, object]:
    return _build_pixel_semantic_surface_v47(image_path, output_dir, scene_id, build_pixel_nature_v46, "nature")


def build_pixel_street_v47(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r47-s01") -> dict[str, object]:
    return _build_pixel_semantic_surface_v47(image_path, output_dir, scene_id, build_pixel_street_v46, "street")


def build_pixel_building_v47(image_path: Path, output_dir: Path, scene_id: str = "pixel-q05-r47-b01") -> dict[str, object]:
    return _build_pixel_semantic_surface_v47(image_path, output_dir, scene_id, build_pixel_building_v46, "building")
