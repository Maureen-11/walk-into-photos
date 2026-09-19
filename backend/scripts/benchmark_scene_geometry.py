"""Measure a generated scene for obvious geometry failures.

This is a machine check, not a visual approval. It catches invalid vertices,
degenerate triangles and extreme aspect ratios before a human route review.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import trimesh


def measure(scene_path: Path, manifest_path: Path | None = None) -> dict:
    loaded = trimesh.load(scene_path, force="scene")
    mesh = loaded.dump(concatenate=True) if isinstance(loaded, trimesh.Scene) else loaded
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or faces.ndim != 2 or faces.shape[1] != 3:
        raise ValueError("scene is not a triangle mesh")
    finite_vertices = bool(np.isfinite(vertices).all())
    edges = vertices[faces[:, [1, 2, 0]]] - vertices[faces[:, [0, 1, 2]]]
    lengths = np.linalg.norm(edges, axis=2)
    areas = np.linalg.norm(np.cross(edges[:, 0], edges[:, 1]), axis=1) * 0.5
    degenerate = areas <= 1e-10
    nonzero = lengths[lengths > 1e-10]
    ratios = (lengths.max(axis=1) / np.maximum(lengths.min(axis=1), 1e-10)) if len(lengths) else np.array([])
    result = {
        "scene": scene_path.name,
        "vertices": int(len(vertices)),
        "triangles": int(len(faces)),
        "finite_vertices": finite_vertices,
        "degenerate_triangle_ratio": float(degenerate.mean()) if len(degenerate) else 1.0,
        "edge_length_median": float(np.median(nonzero)) if len(nonzero) else 0.0,
        "triangle_aspect_p99": float(np.percentile(ratios, 99)) if len(ratios) else None,
        "bounds": np.asarray(mesh.bounds, dtype=float).tolist(),
        "extent": (np.asarray(mesh.bounds[1]) - np.asarray(mesh.bounds[0])).astype(float).tolist(),
        "machine_status": "failed" if not finite_vertices or float(degenerate.mean()) > 0.02 else "needs_visual_review",
    }
    if manifest_path and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        result["manifest"] = {key: manifest.get(key) for key in ("template", "version", "coverage", "quality_status", "camera")}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="测量 GLB 的明显几何风险，不替代视觉验收")
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    result = measure(args.scene, args.manifest)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0 if result["machine_status"] != "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
