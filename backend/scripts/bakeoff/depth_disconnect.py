from __future__ import annotations

"""Isolated depth-discontinuity ablation.

This deliberately does not touch the production geometry adapter.  It keeps
only grid quads whose four corner pixels are not adjacent to a large depth
jump, then exports comparison GLBs for review.
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
from app.services.geometry import _camera_spec, _stabilize_depth_points, scale_glb_uniformly_from_camera
from app.services.scene_quality import inspect_scene

from compare_moge import _model_output


def _safe_mask(mask: np.ndarray, depth: np.ndarray, ratio: float) -> np.ndarray:
    valid = mask & np.isfinite(depth) & (depth > 0)
    safe = valid.copy()
    a = depth[:, 1:]
    b = depth[:, :-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        horizontal = valid[:, 1:] & valid[:, :-1] & (np.maximum(a, b) / np.maximum(np.minimum(a, b), 1e-6) > ratio)
    a = depth[1:, :]
    b = depth[:-1, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        vertical = valid[1:, :] & valid[:-1, :] & (np.maximum(a, b) / np.maximum(np.minimum(a, b), 1e-6) > ratio)
    safe[:, 1:][horizontal] = False
    safe[:, :-1][horizontal] = False
    safe[1:, :][vertical] = False
    safe[:-1, :][vertical] = False
    return safe


def _build_variant(name: str, ratio: float, image: np.ndarray, points: np.ndarray, mask: np.ndarray, normal: np.ndarray | None, depth: np.ndarray, intrinsics: np.ndarray, root: Path) -> dict[str, object]:
    try:
        import utils3d_moge as utils3d
    except ImportError:
        import utils3d
    from moge.utils.io import save_glb

    points, stable_depth = _stabilize_depth_points(points, depth)
    safe = _safe_mask(mask, stable_depth, ratio)
    h, w = image.shape[:2]
    uv = utils3d.np.uv_map(h, w)
    if normal is None:
        faces, vertices, _colors, vertex_uvs = utils3d.np.build_mesh_from_map(points, image.astype(np.float32) / 255, uv, mask=safe, tri=True)
        vertex_normals = None
    else:
        faces, vertices, _colors, vertex_uvs, vertex_normals = utils3d.np.build_mesh_from_map(points, image.astype(np.float32) / 255, uv, normal, mask=safe, tri=True)
        vertex_normals = vertex_normals * [1, -1, -1]
    vertices = vertices * [1, -1, -1]
    vertex_uvs = vertex_uvs * [1, -1] + [0, 1]
    out = root / name
    out.mkdir(parents=True, exist_ok=True)
    scene_path = out / "scene.glb"
    save_glb(scene_path, vertices, faces, vertex_uvs, image, vertex_normals)
    normalization = scale_glb_uniformly_from_camera(scene_path)
    Image.fromarray((safe.astype(np.uint8) * 255), mode="L").save(out / "mask.png")
    quality = inspect_scene(scene_path)
    scene_bounds = np.asarray(trimesh.load(scene_path, force="scene").bounds, dtype=np.float64)
    return {
        "variant": name,
        "ratio": ratio,
        "coverage": float(safe.mean()),
        "scene": str(scene_path),
        "normalization": normalization,
        "quality": quality,
        "camera": _camera_spec(intrinsics, (w, h), normalization["world_scale"], scene_bounds),
        "note": "只保留深度连续区域；断边旁边会出现明确缺面，不代表遮挡区域已经补全。",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    image, points, mask, normal, depth, intrinsics = _model_output(args.input, Settings(), "quick")
    records = [_build_variant(f"ratio-{ratio:.1f}", ratio, image, points, mask, normal, depth, intrinsics, args.output_dir) for ratio in (1.3, 1.5, 2.0)]
    report = {"input": str(args.input), "ratios": [1.3, 1.5, 2.0], "variants": records}
    (args.output_dir / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    del image, points, mask, normal, depth, intrinsics
    gc.collect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
