"""Detail-preserving refinement candidates built on the friend V47 baseline.

The first refinement is intentionally additive. It keeps every V47 object and
collision box, then adds a small number of photo-supported depth layers around
the corridor openings, door thresholds, ceiling fixtures, and wall panels.
This makes the comparison honest: a detail gain cannot be caused by throwing
away the baseline scene.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.models import CollisionBox
from app.services.pixel_scene import (
    FURNITURE_VOXEL,
    MICRO_VOXEL,
    _add_part,
    _mix,
    _shade,
    build_pixel_corridor_v47,
)


REFINEMENT_LAYOUT_VERSION = "pixel-v48-i01-detail-preserving-refinement-pass-39"


def build_refined_corridor_v48(
    image_path: Path,
    output_dir: Path,
    scene_id: str = "pixel-q05-r48-i01",
) -> dict[str, object]:
    """Build I01 from V47 and add depth-readable semantic detail layers."""

    build_pixel_corridor_v47(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    collision_path = output_dir / "collision.json"
    manifest_path = output_dir / "manifest.json"
    import trimesh

    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    collision = json.loads(collision_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    objects = layout["objects"]
    collisions = [CollisionBox.model_validate(item) for item in collision["boxes"]]
    roles = layout["palette"]["roles"]
    wall, trim = roles["wall"], roles["trim"]
    window, wood, metal = roles["window"], roles["wood"], roles["metal"]
    dark, lamp = roles["dark"], roles["lamp"]
    detail_ids: list[str] = []

    def add(
        name: str,
        extents: tuple[float, float, float],
        centre: tuple[float, float, float],
        colour: list[int],
        role: str,
        source: str,
        grid: float = FURNITURE_VOXEL,
    ) -> None:
        _add_part(scene, objects, [], name, extents, centre, colour, role, source, grid=grid)
        detail_ids.append(name)

    # Window bays: V47 has the readable frame rhythm. These inset panes and
    # crossbars make the opening read as a shallow construction with glass,
    # rather than a flat coloured slab.
    window_zs = (3.50, 0.0, -3.50, -7.00)
    glass = _mix(window, wall, 0.30)
    glass_shadow = _mix(glass, dark, 0.28)
    for index, z in enumerate(window_zs):
        add(
            f"pixel-q05-r48-i01-left-window-{index}-recess",
            (0.028, 1.78, 0.70),
            (-2.255, 1.40, z),
            glass_shadow,
            "window_recess_surface",
            "photo_supported_opening",
            MICRO_VOXEL,
        )
        add(
            f"pixel-q05-r48-i01-left-window-{index}-horizontal-mullion",
            (0.040, 0.050, 0.82),
            (-2.230, 1.42, z),
            trim,
            "window_mullion_detail",
            "photo_supported_opening",
            MICRO_VOXEL,
        )
        add(
            f"pixel-q05-r48-i01-left-window-{index}-sill-shadow",
            (0.12, 0.070, 1.02),
            (-2.215, 0.18, z),
            _shade(trim, 0.78),
            "window_sill_detail",
            "photo_supported_opening",
            MICRO_VOXEL,
        )

    # Door bays: preserve V47 panels and handles, adding a recessed centre
    # panel, header plate, and threshold that remain outside collisions.
    for index, z in enumerate(window_zs):
        add(
            f"pixel-q05-r48-i01-right-door-{index}-recessed-panel",
            (0.030, 0.72, 0.54),
            (2.215, 1.16, z),
            _mix(wood, dark, 0.12),
            "door_recess_detail",
            "photo_supported_door_surface",
            MICRO_VOXEL,
        )
        add(
            f"pixel-q05-r48-i01-right-door-{index}-header",
            (0.040, 0.16, 0.74),
            (2.205, 2.48, z),
            _mix(wood, trim, 0.28),
            "door_header_detail",
            "photo_supported_door_surface",
            MICRO_VOXEL,
        )
        add(
            f"pixel-q05-r48-i01-right-door-{index}-threshold",
            (0.16, 0.055, 1.00),
            (2.18, 0.095, z),
            metal,
            "door_threshold_detail",
            "photo_supported_door_surface",
            MICRO_VOXEL,
        )

    # Ceiling fixtures: a dark recessed plate and a warm centre make the
    # existing V47 light rhythm read as built-in fixtures during a turn.
    for index, z in enumerate((4.25, 2.18, 0.12, -2.06, -4.19, -6.38, -8.50)):
        add(
            f"pixel-q05-r48-i01-ceiling-{index}-recess",
            (0.48, 0.030, 0.25),
            (0.0, 3.02, z),
            _mix(dark, wall, 0.12),
            "ceiling_fixture_recess",
            "photo_supported_ceiling_fixture",
            MICRO_VOXEL,
        )
        add(
            f"pixel-q05-r48-i01-ceiling-{index}-diffuser",
            (0.26, 0.018, 0.12),
            (0.0, 2.985, z),
            _mix(lamp, window, 0.20),
            "ceiling_fixture_diffuser",
            "photo_supported_ceiling_fixture",
            MICRO_VOXEL,
        )

    # Wall bays: short vertical seams provide scale and connect the existing
    # horizontal rail to the openings without covering the walls with noise.
    for side, x in (("left", -2.575), ("right", 2.575)):
        for index, z in enumerate((2.55, 0.90, -0.75, -2.40, -4.05, -5.70, -7.35)):
            add(
                f"pixel-q05-r48-i01-{side}-wall-bay-seam-{index}",
                (0.038, 0.68, 0.050),
                (x, 1.18, z),
                _mix(wall, trim, 0.20),
                "wall_bay_seam",
                "photo_inferred_wall_panel",
                MICRO_VOXEL,
            )

    layout["layout_version"] = REFINEMENT_LAYOUT_VERSION
    layout["route"] = "pixel_style_sample_v48"
    layout["style_route"] = "pixel_style_sample_v48"
    layout["layout_authoring"] = "q05_i01_detail_preserving_refinement_pass"
    layout.setdefault("pixel_spec", {})["detail_pass"] = "v48-i01-detail-preserving-refinement-pass-39"
    layout["pixel_spec"]["refinement_policy"] = "additive_depth_layers_preserve_v47_objects_and_collisions"
    layout["pixel_spec"]["detail_floor"] = "v47_visible_detail_is_non_regression_floor"
    layout["generated_regions"] = list(layout.get("generated_regions", [])) + [
        "corridor_window_recess_layers",
        "corridor_door_recess_layers",
        "corridor_ceiling_fixture_depth",
        "corridor_wall_bay_seams",
    ]
    layout["movement"]["collision_boxes"] = collision["boxes"]
    collision["layout_version"] = REFINEMENT_LAYOUT_VERSION
    manifest["version"] = "pixel-v48"
    manifest["provider_version"] = "pixel-voxel-v48-detail-refinement"
    manifest["generation_source"] = "pixel_style_sample_v48"
    manifest["style_route"] = "pixel_style_sample_v48"
    manifest["layout_version"] = REFINEMENT_LAYOUT_VERSION
    manifest["generated_region_note"] = (
        "像素风 V48 I01 精细度保持候选：完整继承朋友 V47 的走廊对象、碰撞、相机和路线，"
        "在照片支持的窗户、门扇、灯具和墙面分格处增加有厚度的分层细节；"
        "没有用删除细节或降低颜色层级换取性能，质量状态仍为 unverified。"
    )
    manifest["quality_metrics"]["detail_pass"] = "v48-i01-detail-preserving-refinement-pass-39"
    manifest["quality_metrics"]["detail_non_regression"] = "candidate_requires_same_viewport_comparison"
    manifest["quality_metrics"]["lighting_status"] = "inherited_indoor_pixel_detail_v4"
    manifest["pixel_spec"]["detail_pass"] = "v48-i01-detail-preserving-refinement-pass-39"
    manifest["pixel_spec"]["refinement_policy"] = "additive_depth_layers_preserve_v47_objects_and_collisions"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + [
        "corridor_window_recess_layers",
        "corridor_door_recess_layers",
        "corridor_ceiling_fixture_depth",
        "corridor_wall_bay_seams",
    ]
    manifest["movement"]["collision_boxes"] = collision["boxes"]
    manifest["detail_object_ids"] = list(manifest.get("detail_object_ids", [])) + detail_ids
    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    collision_path.write_text(json.dumps(collision, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna V48 I01 走廊精细度保持候选\n\n"
        "V48 完整继承 V47，并只增加窗、门、灯具和墙面分格的有厚度细节。"
        "候选仍需同一视口的五观察点、性能和真实离线运行验收；质量状态为 unverified。\n",
        encoding="utf-8",
    )
    return manifest
