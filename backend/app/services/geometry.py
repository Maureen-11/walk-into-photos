from __future__ import annotations

import shutil
import json
import mimetypes
import struct
import tempfile
import gc
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
from PIL import Image
import trimesh

from app.config import Settings
from app.models import RegionConfirmation, SceneTemplate
from app.services.coarse_scene import build_coarse_scene
from app.services.photo_supported_scene import build_photo_supported_scene


def _chunk(kind: bytes, payload: bytes) -> bytes:
    padded = payload + b" " * ((4 - len(payload) % 4) % 4)
    return struct.pack("<I4s", len(padded), kind) + padded


def _pad_bytes(value: bytes, fill: bytes = b"\x00") -> bytes:
    return value + fill * ((4 - len(value) % 4) % 4)


def write_demo_glb(path: Path, image_path: Path | None = None) -> None:
    """Write a tiny valid GLB plane for viewer smoke tests.

    This is deliberately labeled demo geometry. It is not the MoGe output.
    """
    positions = struct.pack("<12f", -1.5, -1.0, 0.0, 1.5, -1.0, 0.0, 1.5, 1.2, 0.0, -1.5, 1.2, 0.0)
    indices = struct.pack("<6H", 0, 1, 2, 0, 2, 3)
    uvs = struct.pack("<8f", 0.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0)
    chunks = [_pad_bytes(positions), _pad_bytes(indices), _pad_bytes(uvs)]
    image_data: bytes | None = None
    image_mime: str | None = None
    if image_path and image_path.is_file():
        try:
            with Image.open(image_path) as image:
                image.verify()
            image_data = image_path.read_bytes()
            image_mime = mimetypes.guess_type(image_path.name)[0] or "image/png"
            chunks.append(_pad_bytes(image_data))
        except Exception:
            # The API can still produce a geometry smoke-test for a bad upload.
            image_data = None
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for chunk in chunks:
        offsets.append((cursor, len(chunk)))
        cursor += len(chunk)
    binary = b"".join(chunks)
    views = [
        {"buffer": 0, "byteOffset": offsets[0][0], "byteLength": 48, "target": 34962},
        {"buffer": 0, "byteOffset": offsets[1][0], "byteLength": 12, "target": 34963},
        {"buffer": 0, "byteOffset": offsets[2][0], "byteLength": 32, "target": 34962},
    ]
    if image_data is not None:
        views.append({"buffer": 0, "byteOffset": offsets[3][0], "byteLength": len(image_data)})
    gltf = {
        "asset": {"version": "2.0", "generator": "walk-into-photos demo"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 2}, "indices": 1, "material": 0}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views,
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3", "min": [-1.5, -1.0, 0.0], "max": [1.5, 1.2, 0.0]},
            {"bufferView": 1, "componentType": 5123, "count": 6, "type": "SCALAR"},
            {"bufferView": 2, "componentType": 5126, "count": 4, "type": "VEC2", "min": [0.0, 0.0], "max": [1.0, 1.0]},
        ],
    }
    if image_data is not None:
        gltf["images"] = [{"bufferView": 3, "mimeType": image_mime}]
        gltf["textures"] = [{"source": 0}]
        gltf["materials"] = [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0.0, "roughnessFactor": 1.0}}]
    else:
        gltf["materials"] = [{"pbrMetallicRoughness": {"baseColorFactor": [0.32, 0.36, 0.62, 1.0], "metallicFactor": 0.0, "roughnessFactor": 1.0}}]
    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    blob = b"glTF" + struct.pack("<II", 2, 12 + 8 + ((len(json_bytes) + 3) // 4) * 4 + 8 + len(binary))
    blob += _chunk(b"JSON", json_bytes) + _chunk(b"BIN\x00", binary)
    path.write_bytes(blob)


def _mask_coverage(output_dir: Path) -> float | None:
    masks = list(output_dir.rglob("*mask*.png"))
    if not masks:
        return None
    with Image.open(masks[0]).convert("L") as mask:
        pixels = list(mask.getdata())
    return sum(value > 8 for value in pixels) / max(1, len(pixels))


def scale_glb_uniformly_from_camera(scene_path: Path, target_depth: float = 18.0, world_scale_override: float | None = None) -> dict:
    """Scale a MoGe mesh uniformly around the camera origin.

    MoGe exports a camera-space mesh. Translating it or scaling x/y/z
    independently changes the original projection and was the source of the
    old stretched, empty-looking view. A single scale keeps the capture point
    at ``[0, 0, 0]`` and records the conversion for the viewer manifest.
    """
    scene = trimesh.load(scene_path, force="scene")
    bounds = np.asarray(scene.bounds, dtype=np.float64)
    if bounds.shape != (2, 3) or not np.isfinite(bounds).all():
        raise ValueError("MoGe GLB 没有有效的三维边界")
    max_depth = max(float(np.max(np.abs(bounds[:, 2]))), 1e-6)
    world_scale = float(world_scale_override) if world_scale_override is not None else min(1.0, float(target_depth) / max_depth)
    if not np.isfinite(world_scale) or world_scale <= 0:
        raise ValueError("world_scale 必须是正数")
    matrix = np.eye(4, dtype=np.float64)
    matrix[0, 0] = world_scale
    matrix[1, 1] = world_scale
    matrix[2, 2] = world_scale
    scene.apply_transform(matrix)
    scene.export(scene_path, file_type="glb")
    normalized = np.asarray(scene.bounds, dtype=np.float64)
    return {
        "before": bounds.tolist(),
        "after": normalized.tolist(),
        "world_scale": world_scale,
        "camera_position": [0.0, 0.0, 0.0],
    }


def _camera_spec(intrinsics: np.ndarray, image_size: tuple[int, int], world_scale: float, bounds: np.ndarray) -> dict:
    """Build the serializable camera contract from MoGe output."""
    try:
        import utils3d_moge as utils3d
    except ImportError:
        import utils3d
    fov_x, fov_y = utils3d.np.intrinsics_to_fov(intrinsics)
    depth = -np.asarray(bounds, dtype=np.float64)[:, 2]
    positive_depth = depth[np.isfinite(depth) & (depth > 0)]
    near = max(0.01, float(positive_depth.min() * world_scale * 0.1) if positive_depth.size else 0.01)
    # Keep a conservative far plane for camera inspection. The viewer does not
    # add a moving source-image backdrop; unseen geometry must remain visibly
    # labeled as a candidate instead of being hidden behind the photo.
    far = max(60.0, float(positive_depth.max() * world_scale * 1.25) if positive_depth.size else 60.0)
    return {
        "position": [0.0, 0.0, 0.0],
        "intrinsics": np.asarray(intrinsics, dtype=float).tolist(),
        "image_size": [int(image_size[0]), int(image_size[1])],
        "camera_to_world": [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]],
        "world_scale": float(world_scale),
        "near": near,
        "far": far,
        "fov_x": float(np.rad2deg(fov_x)),
        "fov_y": float(np.rad2deg(fov_y)),
        "coordinate_frame_id": "moge-opengl-camera-v1",
    }


def _stabilize_depth_points(points: np.ndarray, depth: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Reduce isolated depth spikes while preserving camera rays.

    A single-image depth map can contain a few extreme pixels. Feeding those
    raw values to ``build_mesh_from_map`` creates long triangles that look like
    melted ribbons when the user moves the camera. We clamp only to a robust
    finite percentile range and blend a small median-filtered neighbourhood;
    each point is then rescaled along its original camera ray. This is a
    conservative geometry stabilizer, not a claim of hidden-space recovery.
    """

    finite = np.asarray(depth, dtype=np.float32)
    valid = np.isfinite(finite) & (finite > 0)
    if not np.any(valid):
        return points, depth
    values = finite[valid]
    low, high = np.percentile(values, [1.0, 99.0])
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        return points, depth
    clipped = np.clip(np.nan_to_num(finite, nan=high, posinf=high, neginf=low), low, high)
    try:
        import cv2

        # Median filtering is intentionally small: preserve mountain ridges,
        # remove isolated spikes that otherwise stretch adjacent triangles.
        smooth = cv2.medianBlur(clipped.astype(np.float32), 5)
    except ImportError:
        smooth = clipped
    stable = clipped * 0.65 + smooth * 0.35
    stable[~valid] = finite[~valid]
    original = np.maximum(np.abs(finite), 1e-6)
    scale = np.divide(stable, original, out=np.ones_like(stable), where=valid)
    stabilized_points = np.asarray(points, dtype=np.float32) * scale[..., None]
    return stabilized_points, stable


def _filter_extreme_faces(vertices: np.ndarray, faces: np.ndarray, factor: float = 20.0) -> tuple[np.ndarray, int]:
    """Drop only triangles with an extreme edge relative to their mesh.

    MoGe's regular camera-facing grid is usually dense, but a small number of
    depth discontinuities can connect distant pixels into long ribbons. Those
    faces are worse than small, explicitly generated holes: the latter can be
    covered by a later context layer and are visible to quality review.
    """

    if len(faces) == 0:
        return faces, 0
    triangles = np.asarray(vertices, dtype=np.float32)[np.asarray(faces, dtype=np.int64)]
    edges = np.stack(
        [
            np.linalg.norm(triangles[:, 1] - triangles[:, 0], axis=1),
            np.linalg.norm(triangles[:, 2] - triangles[:, 1], axis=1),
            np.linalg.norm(triangles[:, 0] - triangles[:, 2], axis=1),
        ],
        axis=1,
    )
    longest = edges.max(axis=1)
    finite = longest[np.isfinite(longest) & (longest > 0)]
    if finite.size == 0:
        return faces, 0
    threshold = float(np.median(finite) * factor)
    keep = np.isfinite(longest) & (longest <= threshold)
    removed = int(np.count_nonzero(~keep))
    return np.asarray(faces, dtype=np.int64)[keep], removed


def _run_moge_in_process(image_path: Path, scene_path: Path, settings: Settings, version: str, world_scale_override: float | None = None) -> dict:
    """Run the official MoGe API and retain intrinsics and mask in memory.

    The Windows OpenCV build cannot write EXR maps, so calling the upstream
    model API is the reliable way to retain the mask and camera metadata while
    still exporting the official GLB mesh.
    """
    import os
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    import cv2
    import torch
    from moge.model import import_model_class_by_version
    from moge.utils.io import save_glb
    try:
        import utils3d_moge as utils3d
    except ImportError:
        import utils3d

    device = torch.device("cuda")
    image = cv2.cvtColor(cv2.imread(str(image_path)), cv2.COLOR_BGR2RGB)
    if image is None:
        raise ValueError("MoGe 无法读取输入图片")
    original_height, original_width = image.shape[:2]
    resize_to = settings.moge_full_resize if version == "full" else settings.moge_quick_resize
    height, width = original_height, original_width
    if resize_to:
        height = min(resize_to, int(resize_to * original_height / original_width))
        width = min(resize_to, int(resize_to * original_width / original_height))
        image = cv2.resize(image, (width, height), cv2.INTER_AREA)
    image_tensor = torch.tensor(image / 255, dtype=torch.float32, device=device).permute(2, 0, 1)
    model = import_model_class_by_version(settings.moge_version).from_pretrained(settings.moge_pretrained).to(device).eval()
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
    points, depth = _stabilize_depth_points(points, depth)
    mask_cleaned = mask & ~utils3d.np.depth_map_edge(depth, rtol=0.04)
    if normal is None:
        faces, vertices, _vertex_colors, vertex_uvs = utils3d.np.build_mesh_from_map(
            points, image.astype(np.float32) / 255, utils3d.np.uv_map(height, width), mask=mask_cleaned, tri=True
        )
        vertex_normals = None
    else:
        faces, vertices, _vertex_colors, vertex_uvs, vertex_normals = utils3d.np.build_mesh_from_map(
            points, image.astype(np.float32) / 255, utils3d.np.uv_map(height, width), normal, mask=mask_cleaned, tri=True
        )
        vertex_normals = vertex_normals * [1, -1, -1]
    faces, removed_extreme_faces = _filter_extreme_faces(vertices, faces)
    vertices = vertices * [1, -1, -1]
    vertex_uvs = vertex_uvs * [1, -1] + [0, 1]
    save_glb(scene_path, vertices, faces, vertex_uvs, image, vertex_normals)
    raw_bounds = np.asarray(trimesh.load(scene_path, force="scene").bounds, dtype=np.float64)
    normalization = scale_glb_uniformly_from_camera(scene_path, world_scale_override=world_scale_override)
    # Keep lightweight local evidence beside the GLB. These files are for
    # review and retry diagnostics; they are not uploaded or included in the
    # shareable archive by default.
    Image.fromarray((mask.astype(np.uint8) * 255), mode="L").save(scene_path.parent / "mask.png")
    finite_depth = depth[np.isfinite(depth)]
    if finite_depth.size:
        low, high = np.percentile(finite_depth, [2, 98])
        depth_safe = np.nan_to_num(depth, nan=high, posinf=high, neginf=low)
        depth_vis = ((np.clip(depth_safe, low, high) - low) / max(float(high - low), 1e-6) * 255).astype(np.uint8)
        Image.fromarray(depth_vis, mode="L").save(scene_path.parent / "depth-preview.png")
    result = {
        "coverage": float(mask.mean()),
        "generated_region_note": "可见区域使用照片投色；不可见区域目前仅依据深度估计形成候选几何，不代表真实空间复原，也未完成纹理补全。",
        "mock": False,
        "normalization": normalization,
        "scene_bounds": normalization["after"],
        "evidence_files": ["mask.png", "depth-preview.png"],
        "camera": _camera_spec(intrinsics, (width, height), normalization["world_scale"], raw_bounds),
        "image_size": [width, height],
        "removed_extreme_faces": removed_extreme_faces,
    }
    del model, output, image_tensor, points, mask, intrinsics, normal, depth
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()
    return result


def run_moge(
    image_path: Path,
    scene_path: Path,
    settings: Settings,
    version: str = "quick",
    template: SceneTemplate | None = None,
    world_scale_override: float | None = None,
) -> dict:
    """Run MoGe and return an explicit camera/scale contract."""
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="walk-moge-") as temp:
        # OpenCV on Windows can fail to read non-ASCII paths (for example a
        # user's `D:\\桌面\\...` file). Give the CLI an ASCII temporary path.
        cli_input = Path(temp) / "input.jpg"
        shutil.copyfile(image_path, cli_input)
        return _run_moge_in_process(cli_input, scene_path, settings, version, world_scale_override=world_scale_override)


def generate_scene(
    image_path: Path,
    scene_path: Path,
    mock: bool = True,
    settings: Settings | None = None,
    version: str = "quick",
    template: object | None = None,
    world_scale_override: float | None = None,
    manual_regions: list[RegionConfirmation] | None = None,
    quality_route: bool = True,
    stage_callback: Callable[[str, int, str], None] | None = None,
) -> dict:
    if isinstance(template, SceneTemplate):
        selected_template = template
    else:
        try:
            selected_template = SceneTemplate(str(template))
        except (TypeError, ValueError):
            selected_template = SceneTemplate.generic_layers
    if not mock and settings is not None and settings.quality_scene_enabled and quality_route:
        try:
            quality_started = time.perf_counter()
            moge_result = run_moge(
                image_path,
                scene_path,
                settings,
                version=version,
                template=selected_template,
                world_scale_override=world_scale_override,
            )
            if stage_callback:
                stage_callback("depth_and_camera", 38, "质量路线：深度与相机已完成")
            moge_result["stage_timings_ms"] = {
                "depth_and_camera": round((time.perf_counter() - quality_started) * 1000),
            }
            structure_started = time.perf_counter()
            result = build_photo_supported_scene(
                image_path,
                scene_path,
                selected_template,
                moge_result,
                settings,
                manual_regions=manual_regions,
            )
            if stage_callback:
                stage_callback("photo_supported_structure", 70, "质量路线：照片表面与类别结构已完成")
            result["stage_timings_ms"] = {
                **dict(moge_result.get("stage_timings_ms", {})),
                "photo_supported_structure": round((time.perf_counter() - structure_started) * 1000),
                "quality_total": round((time.perf_counter() - quality_started) * 1000),
            }
            return result
        except Exception as exc:
            # A model failure is recorded in the manifest instead of being
            # silently presented as a successful reconstruction. The coarse
            # route remains a usable, explicitly labelled fallback.
            if settings.coarse_scene_enabled:
                if stage_callback:
                    stage_callback("quality_route_fallback", 70, "质量路线失败，正在保留明确标记的粗模候选")
                fallback = build_coarse_scene(
                    image_path,
                    scene_path,
                    selected_template,
                    mock=False,
                    fallback_reason=f"quality_route_failed:{type(exc).__name__}",
                )
                fallback["quality_route_error"] = type(exc).__name__
                fallback["stage_timings_ms"] = {"quality_route_attempt": round((time.perf_counter() - quality_started) * 1000)}
                fallback["manual_assisted"] = bool(manual_regions)
                return fallback
            raise
    if settings is not None and settings.coarse_scene_enabled:
        return build_coarse_scene(image_path, scene_path, selected_template, mock=mock)
    if not mock:
        if settings is None:
            raise ValueError("settings is required for MoGe inference")
        return run_moge(image_path, scene_path, settings, version=version, template=template if isinstance(template, SceneTemplate) else None, world_scale_override=world_scale_override)
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    write_demo_glb(scene_path, image_path)
    return {
        "coverage": 1.0,
        "generated_region_note": "演示几何；不可见区域是流程占位，不能代表真实空间复原。",
        "mock": True,
    }
