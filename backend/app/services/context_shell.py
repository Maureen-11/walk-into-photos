from __future__ import annotations

"""Experimental context geometry for the uncovered sides of a single photo.

MoGe provides a camera-facing surface, not a complete room or landscape. This
module adds a deliberately simple, clearly-labelled shell around that surface
so we can test whether bounded exploration feels better than a black void.
It is not claimed to reconstruct unseen space and is kept behind an explicit
experimental setting until browser review passes.
"""

from pathlib import Path

import numpy as np
import trimesh

from app.models import SceneTemplate


def _box(extents: list[float], center: list[float], color: list[int]) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(center)
    mesh.visual.vertex_colors = np.tile(np.asarray([*color, 255], dtype=np.uint8), (len(mesh.vertices), 1))
    return mesh


def _add_indoor_shell(scene: trimesh.Scene, bounds: np.ndarray) -> None:
    lower, upper = bounds
    width = max(float(upper[0] - lower[0]), 3.0)
    depth = max(float(upper[2] - lower[2]), 8.0)
    height = max(float(upper[1] - lower[1]), 2.5)
    x_center = float((lower[0] + upper[0]) / 2)
    z_center = float((lower[2] + upper[2]) / 2)
    floor_y = float(lower[1] - 0.08)
    ceiling_y = float(upper[1] + 0.08)
    neutral_wall = [218, 218, 212]
    floor = _box([width + 0.8, 0.08, depth + 0.8], [x_center, floor_y, z_center], [166, 160, 150])
    ceiling = _box([width + 0.8, 0.08, depth + 0.8], [x_center, ceiling_y, z_center], [238, 238, 234])
    left = _box([0.08, height + 0.4, depth + 0.8], [lower[0] - 0.04, (lower[1] + upper[1]) / 2, z_center], neutral_wall)
    right = _box([0.08, height + 0.4, depth + 0.8], [upper[0] + 0.04, (lower[1] + upper[1]) / 2, z_center], neutral_wall)
    back = _box([width + 0.8, height + 0.4, 0.08], [x_center, (lower[1] + upper[1]) / 2, 0.18], [190, 190, 186])
    for name, mesh in (("context-floor", floor), ("context-ceiling", ceiling), ("context-left-wall", left), ("context-right-wall", right), ("context-back-wall", back)):
        scene.add_geometry(mesh, geom_name=name)


def _add_terrain_shell(scene: trimesh.Scene, bounds: np.ndarray) -> None:
    lower, upper = bounds
    width = max(float(upper[0] - lower[0]), 18.0)
    depth = max(float(upper[2] - lower[2]), 18.0)
    ground = _box([width + 35.0, 0.12, depth + 35.0], [0.0, float(lower[1] - 0.12), float((lower[2] + upper[2]) / 2 - 8.0)], [224, 232, 240])
    scene.add_geometry(ground, geom_name="context-snow-ground")

    # Low-poly inward-facing sky shell prevents the uncovered side view from
    # becoming a black void. It is intentionally plain blue and is marked as
    # generated context, not as a recovered panorama.
    sky = trimesh.creation.icosphere(subdivisions=2, radius=52.0)
    sky.invert()
    sky.visual.vertex_colors = np.tile(np.asarray([104, 145, 190, 255], dtype=np.uint8), (len(sky.vertices), 1))
    scene.add_geometry(sky, geom_name="context-generated-sky")

    # A few distant, intentionally coarse ridges give the far side a horizon
    # cue without pretending to know the unseen mountain geometry.
    for index, (x, z, radius, height) in enumerate((
        (-18.0, -34.0, 8.0, 10.0), (-6.0, -39.0, 10.0, 13.0),
        (9.0, -37.0, 9.0, 12.0), (23.0, -31.0, 7.0, 9.0),
    )):
        ridge = trimesh.creation.cone(radius=radius, height=height, sections=8)
        ridge.apply_translation([x, float(lower[1] + height / 2), z])
        ridge.visual.vertex_colors = np.tile(np.asarray([91, 123, 158, 255], dtype=np.uint8), (len(ridge.vertices), 1))
        scene.add_geometry(ridge, geom_name=f"context-generated-ridge-{index}")


def add_context_shell(scene_path: Path, template: SceneTemplate) -> dict[str, object]:
    """Add an experimental shell and return a manifest note.

    The source scene bounds are retained by the caller for navigation; the
    shell is visual context only and does not silently expand the walk area.
    """

    scene = trimesh.load(scene_path, force="scene")
    bounds = np.asarray(scene.bounds, dtype=np.float64)
    if bounds.shape != (2, 3) or not np.isfinite(bounds).all():
        raise ValueError("无法为无效场景添加上下文壳层")
    if template is SceneTemplate.indoor_walk:
        _add_indoor_shell(scene, bounds)
        shell = "indoor_room_shell"
    elif template is SceneTemplate.landscape_journey:
        _add_terrain_shell(scene, bounds)
        shell = "terrain_horizon_shell"
    else:
        return {"enabled": False, "reason": "template_not_supported"}
    scene.export(scene_path, file_type="glb")
    return {
        "enabled": True,
        "type": shell,
        "status": "experimental_needs_visual_review",
        "note": "侧后方由程序化上下文壳层补足，仅用于有限探索实验，不代表真实空间复原。",
    }
