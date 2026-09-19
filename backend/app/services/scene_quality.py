from __future__ import annotations

"""Cheap, local geometry checks for generated GLB candidates.

These checks are deliberately not a substitute for opening the scene and
walking the route. They catch broken files, non-finite vertices, degenerate
triangles, and extreme triangle distortion before a result is presented as a
candidate. The returned status therefore remains ``needs_visual_review`` for
otherwise valid geometry.
"""

from pathlib import Path

import numpy as np
import trimesh


def _triangle_aspect_p99(mesh: trimesh.Trimesh) -> float | None:
    triangles = np.asarray(mesh.triangles, dtype=np.float64)
    if triangles.size == 0:
        return None
    edges = np.stack(
        [
            np.linalg.norm(triangles[:, 1] - triangles[:, 0], axis=1),
            np.linalg.norm(triangles[:, 2] - triangles[:, 1], axis=1),
            np.linalg.norm(triangles[:, 0] - triangles[:, 2], axis=1),
        ],
        axis=1,
    )
    longest = edges.max(axis=1)
    shortest = edges.min(axis=1)
    aspect = longest / np.maximum(shortest, 1e-12)
    finite = aspect[np.isfinite(aspect)]
    return float(np.percentile(finite, 99)) if finite.size else None


def inspect_scene(scene_path: Path) -> dict[str, object]:
    """Return machine-checkable geometry evidence for one GLB.

    ``machine_status`` is never ``passed``: visual route, scale, texture
    stretching, and collision behaviour still need an operator/browser check.
    """

    try:
        scene = trimesh.load(scene_path, force="scene")
        geometries = [geometry for geometry in scene.geometry.values() if isinstance(geometry, trimesh.Trimesh)]
        if not geometries:
            return {"machine_status": "failed", "error": "no_mesh"}
        # ``scene.geometry`` stores mesh-local vertices while GLB nodes may
        # carry a scale/rotation/translation in the scene graph. Concatenating
        # those local arrays directly makes a MoGe mesh look enormous in the
        # report even though the browser correctly applies its node transform.
        # ``to_geometry`` (the non-deprecated equivalent of dump(concatenate))
        # bakes the graph transforms before measuring quality.
        mesh = scene.to_geometry()
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        faces = np.asarray(mesh.faces, dtype=np.int64)
        if vertices.ndim != 2 or vertices.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3:
            return {"machine_status": "failed", "error": "invalid_mesh_shape"}
        finite_vertices = bool(np.isfinite(vertices).all())
        finite_faces = bool(np.isfinite(faces).all())
        if not finite_vertices or not finite_faces or len(vertices) == 0 or len(faces) == 0:
            return {
                "machine_status": "failed",
                "error": "non_finite_or_empty_mesh",
                "vertex_count": int(len(vertices)),
                "triangle_count": int(len(faces)),
            }
        areas = np.asarray(mesh.area_faces, dtype=np.float64)
        degenerate_ratio = float(np.mean(~np.isfinite(areas) | (areas <= 1e-10))) if areas.size else 1.0
        bounds = np.asarray(mesh.bounds, dtype=np.float64)
        extents = bounds[1] - bounds[0]
        edge_lengths = np.asarray(mesh.edges_unique_length, dtype=np.float64)
        edge_lengths = edge_lengths[np.isfinite(edge_lengths) & (edge_lengths > 0)]
        edge_median = float(np.median(edge_lengths)) if edge_lengths.size else None
        aspect_p99 = _triangle_aspect_p99(mesh)
        # A single-image demo plane legitimately has zero thickness on one
        # axis. Require at least two non-zero dimensions instead of rejecting
        # every planar smoke-test mesh; a line/point or collapsed mesh still
        # fails. Keep the same conservative 2% degenerate threshold as the
        # standalone benchmark script.
        failed = (
            degenerate_ratio > 0.02
            or not np.isfinite(bounds).all()
            or not np.isfinite(extents).all()
            or int(np.count_nonzero(extents > 1e-10)) < 2
        )
        return {
            "machine_status": "failed" if failed else "needs_visual_review",
            "vertex_count": int(len(vertices)),
            "triangle_count": int(len(faces)),
            "degenerate_triangle_ratio": round(degenerate_ratio, 6),
            "edge_length_median": round(edge_median, 8) if edge_median is not None else None,
            "triangle_aspect_p99": round(aspect_p99, 6) if aspect_p99 is not None else None,
            "bounds": bounds.tolist(),
            "extents": extents.tolist(),
        }
    except Exception as exc:  # malformed GLB must become evidence, not a 500
        return {"machine_status": "failed", "error": type(exc).__name__}
