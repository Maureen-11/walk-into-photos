from __future__ import annotations

"""Isolated R1 comparison for the current MoGe post-processing chain.

This script deliberately writes only to the requested output directory. It
does not change the production generator or the database. It runs one model
inference and exports the same image through four geometry stages so visual
review can identify the source of holes and stretched triangles.
"""

import argparse
import gc
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
import trimesh
from PIL import Image

# Allow direct execution from backend/scripts/bakeoff without installing the
# backend as a package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import Settings
from app.services.context_shell import add_context_shell
from app.services.geometry import (
    _filter_extreme_faces,
    _stabilize_depth_points,
    _camera_spec,
    scale_glb_uniformly_from_camera,
)
from app.services.scene_quality import inspect_scene


def _model_output(image_path: Path, settings: Settings, version: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None, np.ndarray, np.ndarray]:
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    from moge.model import import_model_class_by_version
    try:
        import utils3d_moge as utils3d
    except ImportError:
        import utils3d

    image = cv2.cvtColor(cv2.imread(str(image_path)), cv2.COLOR_BGR2RGB)
    if image is None:
        raise ValueError(f"无法读取输入图片: {image_path}")
    original_height, original_width = image.shape[:2]
    resize_to = settings.moge_full_resize if version == "full" else settings.moge_quick_resize
    height, width = original_height, original_width
    if resize_to:
        height = min(resize_to, int(resize_to * original_height / original_width))
        width = min(resize_to, int(resize_to * original_width / original_height))
        image = cv2.resize(image, (width, height), cv2.INTER_AREA)
    image_tensor = torch.tensor(image / 255, dtype=torch.float32, device="cuda").permute(2, 0, 1)
    model = import_model_class_by_version(settings.moge_version).from_pretrained(settings.moge_pretrained).to("cuda").eval()
    if settings.moge_version != "v3":
        model.half()
    with torch.inference_mode():
        output = model.infer(image_tensor, fov_x=None, resolution_level=9, num_tokens=None, use_fp16=True)
    points = output["points"].detach().float().cpu().numpy()
    mask = output["mask"].detach().cpu().numpy().astype(bool)
    intrinsics = output["intrinsics"].detach().float().cpu().numpy()
    normal_tensor = output.get("normal")
    normal = normal_tensor.detach().float().cpu().numpy() if normal_tensor is not None else None
    depth = output["depth"].detach().float().cpu().numpy()
    del model, output, image_tensor
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()
    return image, points, mask, normal, depth, intrinsics


def _build_variant(name: str, image: np.ndarray, points: np.ndarray, mask: np.ndarray, normal: np.ndarray | None, depth: np.ndarray, intrinsics: np.ndarray, output_dir: Path) -> dict[str, object]:
    try:
        import utils3d_moge as utils3d
    except ImportError:
        import utils3d
    height, width = image.shape[:2]
    working_points = points
    working_depth = depth
    removed = 0
    if name in {"stabilized", "filtered", "filtered_shell"}:
        working_points, working_depth = _stabilize_depth_points(points, depth)
    mask_cleaned = mask & ~utils3d.np.depth_map_edge(working_depth, rtol=0.04)
    if normal is None:
        faces, vertices, _colors, vertex_uvs = utils3d.np.build_mesh_from_map(
            working_points, image.astype(np.float32) / 255, utils3d.np.uv_map(height, width), mask=mask_cleaned, tri=True
        )
        vertex_normals = None
    else:
        faces, vertices, _colors, vertex_uvs, vertex_normals = utils3d.np.build_mesh_from_map(
            working_points, image.astype(np.float32) / 255, utils3d.np.uv_map(height, width), normal, mask=mask_cleaned, tri=True
        )
        vertex_normals = vertex_normals * [1, -1, -1]
    if name in {"filtered", "filtered_shell"}:
        faces, removed = _filter_extreme_faces(vertices, faces)
    vertices = vertices * [1, -1, -1]
    vertex_uvs = vertex_uvs * [1, -1] + [0, 1]
    from moge.utils.io import save_glb

    variant_dir = output_dir / name
    variant_dir.mkdir(parents=True, exist_ok=True)
    scene_path = variant_dir / "scene.glb"
    save_glb(scene_path, vertices, faces, vertex_uvs, image, vertex_normals)
    normalization = scale_glb_uniformly_from_camera(scene_path)
    if name == "filtered_shell":
        shell = add_context_shell(scene_path, __import__("app.models", fromlist=["SceneTemplate"]).SceneTemplate.landscape_journey)
    else:
        shell = {"enabled": False}
    finite_depth = working_depth[np.isfinite(working_depth)]
    depth_info: dict[str, object] = {}
    if finite_depth.size:
        low, high = np.percentile(finite_depth, [2, 98])
        safe = np.nan_to_num(working_depth, nan=high, posinf=high, neginf=low)
        preview = ((np.clip(safe, low, high) - low) / max(float(high - low), 1e-6) * 255).astype(np.uint8)
        Image.fromarray(preview, mode="L").save(variant_dir / "depth-preview.png")
        depth_info = {"p02": float(low), "p98": float(high)}
    Image.fromarray((mask.astype(np.uint8) * 255), mode="L").save(variant_dir / "mask.png")
    quality = inspect_scene(scene_path)
    return {
        "variant": name,
        "scene": str(scene_path),
        "removed_extreme_faces": removed,
        "normalization": normalization,
        "shell": shell,
        "quality": quality,
        "depth": depth_info,
        "coverage": float(mask.mean()),
        "camera": _camera_spec(intrinsics, (width, height), normalization["world_scale"], np.asarray(trimesh.load(scene_path, force="scene").bounds)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", choices=["quick", "full"], default="quick")
    args = parser.parse_args()
    settings = Settings()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    image, points, mask, normal, depth, intrinsics = _model_output(args.input, settings, args.version)
    records = []
    for name in ("raw", "stabilized", "filtered", "filtered_shell"):
        records.append(_build_variant(name, image, points, mask, normal, depth, intrinsics, args.output_dir))
    report = {"input": str(args.input), "version": args.version, "variants": records}
    (args.output_dir / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
