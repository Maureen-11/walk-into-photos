from __future__ import annotations

"""Build an isolated layered-depth candidate from one MoGe prediction.

This is a diagnostic baseline inspired by layered single-image view synthesis:
depth bands are exported as independent surfaces so faces never connect two
different bands. It is intentionally not a product generator and does not
invent unseen texture.
"""

import argparse
import gc
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import Settings
from app.services.geometry import _camera_spec, _filter_extreme_faces, _stabilize_depth_points, scale_glb_uniformly_from_camera
from app.services.scene_quality import inspect_scene

from compare_moge import _model_output


def _layer_masks(mask: np.ndarray, depth: np.ndarray) -> list[np.ndarray]:
    valid = mask & np.isfinite(depth) & (depth > 0)
    values = depth[valid]
    if values.size == 0:
        return [valid, np.zeros_like(valid), np.zeros_like(valid)]
    cuts = np.percentile(values, [33.0, 66.0])
    return [valid & (depth <= cuts[0]), valid & (depth > cuts[0]) & (depth <= cuts[1]), valid & (depth > cuts[1])]


def _build(image: np.ndarray, points: np.ndarray, mask: np.ndarray, normal: np.ndarray | None, depth: np.ndarray, intrinsics: np.ndarray, out_dir: Path) -> dict[str, object]:
    try:
        import utils3d_moge as utils3d
    except ImportError:
        import utils3d
    from moge.utils.io import save_glb

    points, depth = _stabilize_depth_points(points, depth)
    h, w = image.shape[:2]
    all_vertices: list[np.ndarray] = []
    all_faces: list[np.ndarray] = []
    all_uvs: list[np.ndarray] = []
    all_normals: list[np.ndarray] = []
    layer_records: list[dict[str, object]] = []
    offset = 0
    for index, layer_mask in enumerate(_layer_masks(mask, depth)):
        uv = utils3d.np.uv_map(h, w)
        if normal is None:
            faces, vertices, _colors, vertex_uvs = utils3d.np.build_mesh_from_map(points, image.astype(np.float32) / 255, uv, mask=layer_mask, tri=True)
            vertex_normals = None
        else:
            faces, vertices, _colors, vertex_uvs, vertex_normals = utils3d.np.build_mesh_from_map(points, image.astype(np.float32) / 255, uv, normal, mask=layer_mask, tri=True)
            vertex_normals = vertex_normals * [1, -1, -1]
        faces, removed = _filter_extreme_faces(vertices, faces)
        vertices = vertices * [1, -1, -1]
        vertex_uvs = vertex_uvs * [1, -1] + [0, 1]
        all_vertices.append(vertices)
        all_faces.append(faces + offset)
        all_uvs.append(vertex_uvs)
        if vertex_normals is not None:
            all_normals.append(vertex_normals)
        layer_records.append({
            "layer": index,
            "pixel_coverage": float(layer_mask.mean()),
            "vertices": int(len(vertices)),
            "triangles_before_filter": int(len(faces) + removed),
            "triangles_after_filter": int(len(faces)),
            "removed_extreme_faces": int(removed),
        })
        offset += len(vertices)

    vertices = np.concatenate(all_vertices, axis=0)
    faces = np.concatenate(all_faces, axis=0)
    uvs = np.concatenate(all_uvs, axis=0)
    normals = np.concatenate(all_normals, axis=0) if len(all_normals) == len(all_vertices) else None
    out_dir.mkdir(parents=True, exist_ok=True)
    scene_path = out_dir / "scene.glb"
    save_glb(scene_path, vertices, faces, uvs, image, normals)
    normalization = scale_glb_uniformly_from_camera(scene_path)
    Image.fromarray((mask.astype(np.uint8) * 255), mode="L").save(out_dir / "mask.png")
    quality = inspect_scene(scene_path)
    bounds = np.asarray(trimesh.load(scene_path, force="scene").bounds, dtype=np.float64)
    result = {
        "variant": "layered_candidate",
        "scene": str(scene_path),
        "coverage": float(mask.mean()),
        "layers": layer_records,
        "normalization": normalization,
        "quality": quality,
        "camera": _camera_spec(intrinsics, (w, h), normalization["world_scale"], bounds),
        "status": "needs_visual_review",
        "limitation": "三层均来自同一张可见照片；未补全真正不可见区域，不代表自由漫游。",
    }
    (out_dir / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    image, points, mask, normal, depth, intrinsics = _model_output(args.input, Settings(), "quick")
    result = _build(image, points, mask, normal, depth, intrinsics, args.output_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    del image, points, mask, normal, depth, intrinsics
    gc.collect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
