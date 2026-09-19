"""Versioned material and lighting candidate for the detail-preserving corridor."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import trimesh

from app.services.detail_refinement import build_refined_corridor_v48


MATERIAL_LAYOUT_VERSION = "pixel-v49-i01-material-lighting-pass-40"


ROLE_MATERIALS: dict[str, dict[str, object]] = {
    "ground": {"colour": [190, 186, 176, 255], "roughness": 0.90, "metallic": 0.0},
    "floor": {"colour": [190, 186, 176, 255], "roughness": 0.90, "metallic": 0.0},
    "wall": {"colour": [232, 230, 222, 255], "roughness": 0.84, "metallic": 0.0},
    "trim": {"colour": [30, 35, 41, 255], "roughness": 0.56, "metallic": 0.28},
    "wood": {"colour": [126, 69, 29, 255], "roughness": 0.68, "metallic": 0.0},
    "door_recess_detail": {"colour": [110, 58, 27, 255], "roughness": 0.70, "metallic": 0.0},
    "door_header_detail": {"colour": [145, 84, 34, 255], "roughness": 0.62, "metallic": 0.0},
    "door_threshold_detail": {"colour": [89, 84, 82, 255], "roughness": 0.48, "metallic": 0.34},
    "window": {"colour": [91, 151, 183, 255], "roughness": 0.32, "metallic": 0.08},
    "window_recess_surface": {"colour": [83, 139, 169, 255], "roughness": 0.38, "metallic": 0.06},
    "window_mullion_detail": {"colour": [37, 48, 53, 255], "roughness": 0.50, "metallic": 0.24},
    "window_sill_detail": {"colour": [90, 84, 80, 255], "roughness": 0.55, "metallic": 0.18},
    "metal": {"colour": [92, 87, 86, 255], "roughness": 0.48, "metallic": 0.36},
    "ceiling_fixture_recess": {"colour": [24, 29, 35, 255], "roughness": 0.56, "metallic": 0.22},
    "ceiling_fixture_diffuser": {"colour": [255, 190, 96, 255], "roughness": 0.34, "metallic": 0.0},
}


def _material_for_role(role: str) -> dict[str, object] | None:
    if role in ROLE_MATERIALS:
        return ROLE_MATERIALS[role]
    if role.startswith("window"):
        return ROLE_MATERIALS["window"]
    if role.startswith("door"):
        return ROLE_MATERIALS["wood"]
    if role.startswith("ceiling"):
        return ROLE_MATERIALS["ceiling_fixture_recess"]
    return None


def build_refined_corridor_v49(
    image_path: Path,
    output_dir: Path,
    scene_id: str = "pixel-q05-r49-i01",
) -> dict[str, object]:
    """Build V48 unchanged geometrically, then apply role-based materials."""

    build_refined_corridor_v48(image_path, output_dir, scene_id)
    scene_path = output_dir / "scene.glb"
    layout_path = output_dir / "layout.json"
    manifest_path = output_dir / "manifest.json"
    collision_path = output_dir / "collision.json"

    scene = trimesh.load(scene_path, force="scene")
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    role_by_id = {item["id"]: item.get("role", "") for item in layout["objects"]}
    changed: list[dict[str, object]] = []

    for geometry_id, geometry in scene.geometry.items():
        role = role_by_id.get(geometry_id, "")
        material_spec = _material_for_role(role)
        if not material_spec or not hasattr(geometry.visual, "material"):
            continue
        material = geometry.visual.material
        material._data["baseColorFactor"] = np.asarray(material_spec["colour"], dtype=np.uint8)
        material._data["roughnessFactor"] = float(material_spec["roughness"])
        material._data["metallicFactor"] = float(material_spec["metallic"])
        changed.append({"id": geometry_id, "role": role, **material_spec})

    layout["layout_version"] = MATERIAL_LAYOUT_VERSION
    layout["route"] = "pixel_style_sample_v49"
    layout["style_route"] = "pixel_style_sample_v49"
    layout["layout_authoring"] = "q05_i01_detail_preserving_material_lighting_pass"
    layout.setdefault("pixel_spec", {})["detail_pass"] = "v49-i01-material-lighting-pass-40"
    layout["pixel_spec"]["lighting_preset"] = "indoor_pixel_detail_v5"
    layout["pixel_spec"]["material_policy"] = "role_based_contrast_preserve_v48_geometry"
    layout["material_adjustments"] = changed

    manifest["version"] = "pixel-v49"
    manifest["provider_version"] = "pixel-voxel-v49-material-lighting"
    manifest["generation_source"] = "pixel_style_sample_v49"
    manifest["style_route"] = "pixel_style_sample_v49"
    manifest["layout_version"] = MATERIAL_LAYOUT_VERSION
    manifest["quality_metrics"]["material_pass"] = "v49-i01-material-lighting-pass-40"
    manifest["quality_metrics"]["material_non_regression"] = "candidate_requires_same_viewport_comparison"
    manifest["quality_metrics"]["lighting_status"] = "candidate_indoor_pixel_detail_v5"
    manifest["pixel_spec"]["detail_pass"] = "v49-i01-material-lighting-pass-40"
    manifest["pixel_spec"]["lighting_preset"] = "indoor_pixel_detail_v5"
    manifest["pixel_spec"]["material_policy"] = "role_based_contrast_preserve_v48_geometry"
    manifest["generated_regions"] = list(manifest.get("generated_regions", [])) + [
        "corridor_role_material_contrast",
        "corridor_indoor_pixel_detail_v5_lighting",
    ]
    manifest["material_adjustment_count"] = len(changed)
    manifest["collision_resource"] = "collision.json"
    manifest["movement"]["collision_boxes"] = json.loads(collision_path.read_text(encoding="utf-8"))["boxes"]

    scene.export(scene_path, file_type="glb")
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Luna V49 I01 材质与灯光候选\n\n"
        "V49 保留 V48 的几何、碰撞、路线和相机，只按照片支持的语义角色调整材质对比，"
        "并使用版本化室内像素灯光预设；质量状态仍为 unverified。\n",
        encoding="utf-8",
    )
    return manifest
