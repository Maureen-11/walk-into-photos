"""Isolated indoor wall/floor/ceiling candidate experiment.

This script combines MoGe point/normal evidence with image line evidence.  It
only writes review artifacts to the requested directory; it never modifies
the API generator, adds a context shell, or labels the candidate as a room
reconstruction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
import trimesh
from PIL import Image
from trimesh.visual.material import PBRMaterial


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fit_plane(points: np.ndarray) -> dict[str, object]:
    """Fit a finite plane and return deterministic diagnostics."""
    values = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    values = values[np.isfinite(values).all(axis=1)]
    if len(values) < 3:
        raise ValueError("at least three finite points are required")
    if len(values) > 20000:
        values = values[np.linspace(0, len(values) - 1, 20000, dtype=np.int64)]
    center = values.mean(axis=0)
    _, singular_values, vh = np.linalg.svd(values - center, full_matrices=False)
    normal = vh[-1]
    normal = normal / max(float(np.linalg.norm(normal)), 1e-12)
    if normal[1] < 0:
        normal = -normal
    distance = -float(np.dot(normal, center))
    residual = np.abs(values @ normal + distance)
    return {
        "normal": normal.astype(float).tolist(),
        "distance": distance,
        "centroid": center.astype(float).tolist(),
        "point_count": int(len(values)),
        "residual_median": float(np.median(residual)),
        "residual_p95": float(np.percentile(residual, 95)),
        "singular_values": singular_values.astype(float).tolist(),
    }


def ransac_plane(points: np.ndarray, threshold: float = 0.05, trials: int = 250, seed: int = 7) -> tuple[dict[str, object], np.ndarray]:
    """Find a dominant finite plane and return its inlier point set.

    The fixed seed and reported threshold make this an auditable experiment,
    not a hidden per-photo threshold adjustment.
    """
    values = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    values = values[np.isfinite(values).all(axis=1)]
    if len(values) < 3:
        raise ValueError("at least three finite points are required")
    if len(values) > 30000:
        values = values[np.linspace(0, len(values) - 1, 30000, dtype=np.int64)]
    rng = np.random.default_rng(seed)
    best_mask: np.ndarray | None = None
    best_score = (-1, float("-inf"))
    for _ in range(trials):
        sample = values[rng.choice(len(values), 3, replace=False)]
        normal = np.cross(sample[1] - sample[0], sample[2] - sample[0])
        magnitude = float(np.linalg.norm(normal))
        if magnitude < 1e-8:
            continue
        normal = normal / magnitude
        distance = -float(np.dot(normal, sample[0]))
        residual = np.abs(values @ normal + distance)
        inliers = residual <= threshold
        score = (int(inliers.sum()), -float(np.median(residual[inliers])) if inliers.any() else float("-inf"))
        if score > best_score:
            best_score = score
            best_mask = inliers
    if best_mask is None or int(best_mask.sum()) < 3:
        raise ValueError("RANSAC could not find a plane")
    refined = fit_plane(values[best_mask])
    residual = np.abs(values @ np.asarray(refined["normal"]) + float(refined["distance"]))
    refined_mask = residual <= threshold
    if int(refined_mask.sum()) >= 3:
        refined = fit_plane(values[refined_mask])
    refined["inlier_count"] = int(refined_mask.sum())
    refined["inlier_ratio"] = float(refined_mask.mean())
    refined["inlier_threshold"] = threshold
    refined["ransac_trials"] = trials
    refined["ransac_seed"] = seed
    return refined, values[refined_mask]


def _line_evidence(image: np.ndarray) -> tuple[list[np.ndarray], dict[str, object]]:
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160, apertureSize=3)
    raw = cv2.HoughLinesP(edges, 1, np.pi / 180.0, threshold=max(25, min(width, height) // 10), minLineLength=max(30, min(width, height) // 8), maxLineGap=12)
    lines = [] if raw is None else [line.astype(np.float64) for line in np.asarray(raw).reshape(-1, 4)]
    lines = sorted(lines, key=lambda line: float(np.hypot(line[2] - line[0], line[3] - line[1])), reverse=True)[:200]
    horizontal = [line for line in lines if abs(np.degrees(np.arctan2(line[3] - line[1], line[2] - line[0]))) <= 12]
    vertical = [line for line in lines if abs(abs(np.degrees(np.arctan2(line[3] - line[1], line[2] - line[0]))) - 90) <= 12]
    overlay = image.copy()
    for line in horizontal:
        cv2.line(overlay, tuple(line[:2].astype(int)), tuple(line[2:].astype(int)), (0, 220, 0), 2)
    for line in vertical:
        cv2.line(overlay, tuple(line[:2].astype(int)), tuple(line[2:].astype(int)), (220, 0, 0), 2)
    for line in lines:
        angle = abs(np.degrees(np.arctan2(line[3] - line[1], line[2] - line[0])))
        if angle > 12 and abs(angle - 90) > 12:
            cv2.line(overlay, tuple(line[:2].astype(int)), tuple(line[2:].astype(int)), (0, 140, 220), 1)
    return lines, {"line_count": len(lines), "horizontal_line_count": len(horizontal), "vertical_line_count": len(vertical), "overlay": overlay}


def _line_guided_masks(lines: list[np.ndarray], height: int, width: int) -> tuple[dict[str, np.ndarray], dict[str, object]]:
    """Rasterize structural line support for a joint point/line experiment.

    Hough lines are only evidence, not a segmentation model.  The returned
    masks are deliberately sparse: a MoGe point is eligible for a plane only
    when it lies near a line that has a consistent indoor orientation and
    points toward the robust vanishing estimate.  This prevents the existing
    broad rectangles from silently counting furniture as walls.
    """
    diagonal = []
    for line in lines:
        x1, y1, x2, y2 = [float(value) for value in line]
        angle = abs(float(np.degrees(np.arctan2(y2 - y1, x2 - x1))))
        if angle > 12 and abs(angle - 90) > 12:
            diagonal.append(line)
    intersections: list[tuple[float, float]] = []
    for index, first in enumerate(diagonal[:40]):
        x1, y1, x2, y2 = [float(value) for value in first]
        for second in diagonal[index + 1 : 40]:
            x3, y3, x4, y4 = [float(value) for value in second]
            denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
            if abs(denominator) < 1e-6:
                continue
            x = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denominator
            y = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denominator
            if -4 * width < x < 5 * width and -4 * height < y < 5 * height:
                intersections.append((float(x), float(y)))
    vanishing = np.median(np.asarray(intersections), axis=0) if intersections else np.array([width * 0.5, height * 0.5])
    support = {name: np.zeros((height, width), dtype=np.uint8) for name in _candidate_masks(height, width)}
    line_assignments = {name: 0 for name in support}
    distance_limit = max(12.0, min(width, height) * 0.06)
    for line in lines:
        x1, y1, x2, y2 = [float(value) for value in line]
        length = float(np.hypot(x2 - x1, y2 - y1))
        if length < max(30.0, min(width, height) * 0.08):
            continue
        angle = abs(float(np.degrees(np.arctan2(y2 - y1, x2 - x1))))
        mid_x, mid_y = (x1 + x2) * 0.5, (y1 + y2) * 0.5
        if abs(angle - 90) <= 12:
            name = "left_wall_candidate" if mid_x < vanishing[0] else "right_wall_candidate"
        elif angle <= 12 or abs(angle - 180) <= 12:
            name = "floor_candidate" if mid_y >= vanishing[1] else "ceiling_candidate"
        else:
            direction = np.array([x2 - x1, y2 - y1], dtype=np.float64)
            offset = np.array([vanishing[0] - x1, vanishing[1] - y1], dtype=np.float64)
            # NumPy 2 removed the scalar result for ``np.cross`` on 2-D
            # vectors. Keep this explicit so the experiment is stable across
            # the pinned and bundled NumPy versions.
            cross_2d = float(direction[0] * offset[1] - direction[1] * offset[0])
            distance = abs(cross_2d) / max(length, 1e-8)
            if distance > distance_limit:
                continue
            name = "floor_candidate" if mid_y >= vanishing[1] else "ceiling_candidate"
        cv2.line(support[name], (int(round(x1)), int(round(y1))), (int(round(x2)), int(round(y2))), 255, 5)
        line_assignments[name] += 1
    kernel = np.ones((9, 9), dtype=np.uint8)
    masks = {name: cv2.dilate(mask, kernel, iterations=1).astype(bool) for name, mask in support.items()}
    return masks, {
        "vanishing_point": vanishing.astype(float).tolist(),
        "distance_limit_px": distance_limit,
        "line_assignments": line_assignments,
        "support_pixels": {name: int(mask.sum()) for name, mask in masks.items()},
        "policy": "only line-supported pixels enter point/normal plane fit; Hough lines are not segmentation",
    }


def _candidate_masks(height: int, width: int) -> dict[str, np.ndarray]:
    yy, xx = np.mgrid[0:height, 0:width]
    center = (xx > width * 0.18) & (xx < width * 0.82)
    return {
        "ceiling_candidate": (yy < height * 0.28) & center,
        "floor_candidate": (yy > height * 0.62) & center,
        "left_wall_candidate": (xx < width * 0.25) & (yy > height * 0.18) & (yy < height * 0.84),
        "right_wall_candidate": (xx > width * 0.75) & (yy > height * 0.18) & (yy < height * 0.84),
    }


def _perspective_candidate_masks(height: int, width: int, vanishing_point: list[float]) -> dict[str, np.ndarray]:
    """Build broad candidate regions from a measured image vanishing point.

    The fixed side strips above are useful as a conservative baseline but can
    exclude corridor walls whose visible boundaries converge near the image
    center.  This region is only a routing mask: line support and MoGe
    normals still gate every pixel before fitting, and the resulting artifact
    remains candidate-only.
    """
    yy, xx = np.mgrid[0:height, 0:width]
    vx, vy = [float(value) for value in vanishing_point]
    return {
        "ceiling_candidate": (yy < vy) & (xx > width * 0.05) & (xx < width * 0.95),
        "floor_candidate": (yy >= vy) & (xx > width * 0.05) & (xx < width * 0.95),
        "left_wall_candidate": (xx < vx) & (yy > height * 0.08) & (yy < height * 0.95),
        "right_wall_candidate": (xx >= vx) & (yy > height * 0.08) & (yy < height * 0.95),
    }


_SUPPORT_COLORS = {
    "ceiling_candidate": (220, 80, 220),
    "floor_candidate": (40, 210, 40),
    "left_wall_candidate": (220, 80, 40),
    "right_wall_candidate": (40, 180, 220),
}


def _support_overlay(
    image: np.ndarray,
    selected_masks: dict[str, np.ndarray],
    inlier_masks: dict[str, np.ndarray],
    candidates: dict[str, object],
) -> np.ndarray:
    """Render the pixels that actually entered each plane fit.

    The original line overlay draws candidate bounding rectangles, which are
    useful for a quick orientation check but do not show whether furniture
    pixels participated in RANSAC.  This overlay keeps the source image and
    paints selected pixels translucently, then paints refined inliers as
    opaque one-pixel marks.  It is diagnostic evidence only.
    """
    result = np.asarray(image, dtype=np.uint8).copy()
    for name, selected in selected_masks.items():
        color = np.asarray(_SUPPORT_COLORS[name], dtype=np.float32)
        mask = np.asarray(selected, dtype=bool)
        if mask.shape != result.shape[:2] or not mask.any():
            continue
        result[mask] = np.clip(result[mask].astype(np.float32) * 0.62 + color * 0.38, 0, 255).astype(np.uint8)
    for name, inliers in inlier_masks.items():
        mask = np.asarray(inliers, dtype=bool)
        if mask.shape != result.shape[:2] or not mask.any():
            continue
        result[mask] = np.asarray(_SUPPORT_COLORS[name], dtype=np.uint8)
    y = 22
    for name in _SUPPORT_COLORS:
        selected_count = int(np.asarray(selected_masks.get(name, np.zeros(result.shape[:2], dtype=bool))).sum())
        inlier_count = int(np.asarray(inlier_masks.get(name, np.zeros(result.shape[:2], dtype=bool))).sum())
        status = str(candidates.get(name, {}).get("status", "missing"))
        cv2.putText(
            result,
            f"{name}: selected={selected_count} inliers={inlier_count} {status}",
            (8, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            _SUPPORT_COLORS[name],
            1,
            cv2.LINE_AA,
        )
        y += 20
    cv2.putText(result, "translucent=selected pixels; solid=refined inliers", (8, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
    return result


def _exclude_normalized_boxes(mask: np.ndarray, boxes: list[dict[str, object]]) -> tuple[np.ndarray, int]:
    """Remove conservative semantic detection boxes from a pixel mask.

    Moondream boxes are object detections, not segmentation.  Removing their
    full rectangles is intentionally conservative: a false positive may
    reduce evidence, but it cannot silently turn furniture into a wall.
    """
    result = np.asarray(mask, dtype=bool).copy()
    height, width = result.shape
    removed = 0
    for box in boxes:
        try:
            x0 = max(0, min(width, int(np.floor(float(box["x_min"]) * width))))
            y0 = max(0, min(height, int(np.floor(float(box["y_min"]) * height))))
            x1 = max(x0, min(width, int(np.ceil(float(box["x_max"]) * width))))
            y1 = max(y0, min(height, int(np.ceil(float(box["y_max"]) * height))))
        except (KeyError, TypeError, ValueError):
            continue
        before = int(result[y0:y1, x0:x1].sum())
        result[y0:y1, x0:x1] = False
        removed += before
    return result, removed


def _load_detection_boxes(path: Path) -> dict[str, list[dict[str, object]]]:
    """Read local Moondream detection boxes grouped by their requested label."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records", [])
    if not isinstance(records, list):
        raise ValueError("detection payload records must be a list")
    grouped: dict[str, list[dict[str, object]]] = {}
    for record in records:
        if not isinstance(record, dict) or record.get("status") != "ok":
            continue
        label = record.get("label")
        objects = record.get("result", {}).get("objects", [])
        if not isinstance(label, str) or not isinstance(objects, list):
            continue
        grouped[label] = [item for item in objects if isinstance(item, dict)]
    return grouped


def _normalized_box_mask(height: int, width: int, boxes: list[dict[str, object]]) -> np.ndarray:
    """Rasterize positive normalized boxes for a conservative semantic prior."""
    mask = np.zeros((height, width), dtype=bool)
    for box in boxes:
        try:
            x0 = max(0, min(width, int(np.floor(float(box["x_min"]) * width))))
            y0 = max(0, min(height, int(np.floor(float(box["y_min"]) * height))))
            x1 = max(x0, min(width, int(np.ceil(float(box["x_max"]) * width))))
            y1 = max(y0, min(height, int(np.ceil(float(box["y_max"]) * height))))
        except (KeyError, TypeError, ValueError):
            continue
        mask[y0:y1, x0:x1] = True
    return mask


def _patch_mesh(name: str, points: np.ndarray, fit: dict[str, object], uv_region: tuple[float, float, float, float], texture: Image.Image) -> trimesh.Trimesh | None:
    values = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    values = values[np.isfinite(values).all(axis=1)]
    if len(values) < 3:
        return None
    center = np.asarray(fit["centroid"], dtype=np.float64)
    normal = np.asarray(fit["normal"], dtype=np.float64)
    basis = np.linalg.svd(values - center, full_matrices=False)[2]
    u, v = basis[0], basis[1]
    projected = np.column_stack(((values - center) @ u, (values - center) @ v))
    low = np.percentile(projected, 5, axis=0)
    high = np.percentile(projected, 95, axis=0)
    if np.any(high - low < 1e-4):
        return None
    corners = np.array([center + u * low[0] + v * low[1], center + u * high[0] + v * low[1], center + u * high[0] + v * high[1], center + u * low[0] + v * high[1]])
    # Match the viewer's MoGe -> OpenGL coordinate conversion without changing
    # the source point map used for diagnostics.
    corners = corners * np.array([1.0, -1.0, -1.0])
    mesh = trimesh.Trimesh(vertices=corners, faces=np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int64), process=False)
    u0, v0, u1, v1 = uv_region
    mesh.visual = trimesh.visual.texture.TextureVisuals(
        uv=np.array([[u0, 1 - v1], [u1, 1 - v1], [u1, 1 - v0], [u0, 1 - v0]], dtype=np.float64),
        image=texture,
    )
    return mesh


_FLIP_TO_VIEWER = np.array([1.0, -1.0, -1.0], dtype=np.float64)


def _viewer_plane(fit: dict[str, object]) -> tuple[np.ndarray, float]:
    """Convert a MoGe camera-space plane into the viewer's OpenGL frame."""
    return np.asarray(fit["normal"], dtype=np.float64) * _FLIP_TO_VIEWER, float(fit["distance"])


def _plane_y(fit: dict[str, object], x: float, z: float) -> float:
    normal, distance = _viewer_plane(fit)
    if abs(normal[1]) < 1e-8:
        raise ValueError("plane cannot solve y")
    return float(-(normal[0] * x + normal[2] * z + distance) / normal[1])


def _plane_x(fit: dict[str, object], y: float, z: float) -> float:
    normal, distance = _viewer_plane(fit)
    if abs(normal[0]) < 1e-8:
        raise ValueError("plane cannot solve x")
    return float(-(normal[1] * y + normal[2] * z + distance) / normal[0])


def _intersect_planes_at_z(first: dict[str, object], second: dict[str, object], z: float) -> np.ndarray:
    """Intersect two fitted planes with a constant-depth slice."""
    first_normal, first_distance = _viewer_plane(first)
    second_normal, second_distance = _viewer_plane(second)
    matrix = np.array([[first_normal[0], first_normal[1]], [second_normal[0], second_normal[1]]], dtype=np.float64)
    determinant = float(np.linalg.det(matrix))
    if abs(determinant) < 1e-8:
        raise ValueError("room planes do not have a stable x/y intersection")
    rhs = -np.array([
        first_normal[2] * z + first_distance,
        second_normal[2] * z + second_distance,
    ], dtype=np.float64)
    x, y = np.linalg.solve(matrix, rhs)
    return np.array([x, y, z], dtype=np.float64)


def _projective_uv(vertices: np.ndarray, intrinsics: np.ndarray) -> np.ndarray | None:
    """Project viewer-frame vertices back into the source image."""
    viewer_vertices = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
    camera_vertices = viewer_vertices * _FLIP_TO_VIEWER
    depth = camera_vertices[:, 2]
    if not np.isfinite(camera_vertices).all() or np.any(depth <= 1e-8):
        return None
    matrix = np.asarray(intrinsics, dtype=np.float64)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        return None
    fx, fy = float(matrix[0, 0]), float(matrix[1, 1])
    cx, cy = float(matrix[0, 2]), float(matrix[1, 2])
    if min(fx, fy) <= 1e-8:
        return None
    u = camera_vertices[:, 0] / depth * fx + cx
    v = camera_vertices[:, 1] / depth * fy + cy
    if not np.isfinite([u, v]).all():
        return None
    # The near boundary can be an extrapolation of an observed plane. Clamp
    # only the texture lookup, keeping the candidate geometry unchanged and
    # making the extrapolation explicit instead of allowing texture repeat.
    return np.column_stack([np.clip(u, 0.0, 1.0), np.clip(1.0 - v, 0.0, 1.0)])


def _textured_quad(
    vertices: np.ndarray,
    uv_region: tuple[float, float, float, float],
    texture: Image.Image,
    intrinsics: np.ndarray | None = None,
    texture_mapping: str = "region",
) -> trimesh.Trimesh:
    """Create a two-sided photo-textured quad for an estimated room surface."""
    u0, v0, u1, v1 = uv_region
    uv = np.array([[u0, 1 - v1], [u1, 1 - v1], [u1, 1 - v0], [u0, 1 - v0]], dtype=np.float64)
    if texture_mapping == "projected" and intrinsics is not None:
        projected = _projective_uv(vertices, intrinsics)
        if projected is not None:
            uv = projected
    mesh = trimesh.Trimesh(
        vertices=np.asarray(vertices, dtype=np.float64),
        faces=np.array([[0, 1, 2], [0, 2, 3], [2, 1, 0], [3, 2, 0]], dtype=np.int64),
        process=False,
    )
    mesh.visual = trimesh.visual.texture.TextureVisuals(
        uv=uv,
        material=PBRMaterial(
            baseColorFactor=[255, 255, 255, 255],
            baseColorTexture=texture,
            metallicFactor=0.0,
            roughnessFactor=1.0,
            doubleSided=True,
        ),
    )
    return mesh


def _axis_aligned_plane(name: str, fit: dict[str, object], inlier_points: np.ndarray) -> dict[str, object]:
    """Constrain a candidate to the simplest supported indoor axes.

    The free fit is still retained in the diagnostics.  This candidate only
    asks whether the image/model evidence is better explained by a level
    floor/ceiling and vertical side walls, rather than by a four-plane box
    whose side planes inherit depth tilt from windows or furniture.
    """
    values = np.asarray(inlier_points, dtype=np.float64).reshape(-1, 3)
    if values.ndim != 2 or values.shape[1] != 3 or len(values) < 3:
        raise ValueError("axis constraint requires at least three inlier points")
    if name in {"floor_candidate", "ceiling_candidate"}:
        normal = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    elif name == "left_wall_candidate":
        normal = np.array([-1.0, 0.0, 0.0], dtype=np.float64)
    elif name == "right_wall_candidate":
        normal = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    else:
        raise ValueError(f"unsupported axis constraint: {name}")
    distance = -float(np.median(values @ normal))
    residual = np.abs(values @ normal + distance)
    constrained = dict(fit)
    constrained["free_fit_normal"] = list(fit["normal"])
    constrained["free_fit_distance"] = float(fit["distance"])
    constrained["normal"] = normal.astype(float).tolist()
    constrained["distance"] = distance
    constrained["residual_median"] = float(np.median(residual))
    constrained["residual_p95"] = float(np.percentile(residual, 95))
    constrained["axis_constraint"] = "level_horizontal_and_vertical_walls"
    return constrained


def _room_envelope(
    candidates: dict[str, object],
    inlier_clouds: dict[str, np.ndarray],
    texture: Image.Image,
    camera_clearance_z: float = -0.25,
    intrinsics: np.ndarray | None = None,
    texture_mapping: str = "region",
) -> tuple[list[trimesh.Trimesh], dict[str, object]]:
    """Build a finite, photo-textured room envelope from fitted planes.

    The extent is derived from robust depth quantiles of the four fitted
    inlier clouds. Floor and ceiling heights follow their fitted planes; side
    boundaries follow the fitted wall planes. This is still an estimate, but
    it connects the independently fitted surfaces without introducing a
    generic gray box or an arbitrary far plane.
    """
    required = ("ceiling_candidate", "floor_candidate", "left_wall_candidate", "right_wall_candidate")
    if any(candidates.get(name, {}).get("status") != "candidate_only" for name in required):
        return [], {"status": "insufficient_plane_candidates"}
    clouds = [np.asarray(inlier_clouds[name], dtype=np.float64) * _FLIP_TO_VIEWER for name in required]
    all_points = np.concatenate(clouds, axis=0)
    all_points = all_points[np.isfinite(all_points).all(axis=1)]
    if len(all_points) < 12:
        return [], {"status": "insufficient_inlier_points"}
    far_z, observed_near_z = np.percentile(all_points[:, 2], [5.0, 95.0])
    # The camera is at z=0 while MoGe's reliable inliers begin farther into
    # the room. Extend only the fitted planes to a small camera clearance so
    # the wide-angle viewer does not expose an artificial near-edge void.
    if not np.isfinite(camera_clearance_z):
        return [], {"status": "invalid_camera_clearance"}
    near_z = max(float(observed_near_z), camera_clearance_z)
    mid_z = float((far_z + near_z) * 0.5)
    left_x = float(np.median(clouds[2][:, 0]))
    right_x = float(np.median(clouds[3][:, 0]))
    if not np.isfinite([far_z, near_z, left_x, right_x]).all() or far_z >= near_z or left_x >= right_x:
        return [], {"status": "invalid_envelope_bounds"}

    ceiling = candidates["ceiling_candidate"]
    floor = candidates["floor_candidate"]
    left = candidates["left_wall_candidate"]
    right = candidates["right_wall_candidate"]
    try:
        corners = {
            "left_floor_near": _intersect_planes_at_z(floor, left, float(near_z)),
            "right_floor_near": _intersect_planes_at_z(floor, right, float(near_z)),
            "left_floor_far": _intersect_planes_at_z(floor, left, float(far_z)),
            "right_floor_far": _intersect_planes_at_z(floor, right, float(far_z)),
            "left_ceiling_near": _intersect_planes_at_z(ceiling, left, float(near_z)),
            "right_ceiling_near": _intersect_planes_at_z(ceiling, right, float(near_z)),
            "left_ceiling_far": _intersect_planes_at_z(ceiling, left, float(far_z)),
            "right_ceiling_far": _intersect_planes_at_z(ceiling, right, float(far_z)),
        }
        if any(not np.isfinite(value).all() for value in corners.values()):
            return [], {"status": "nonfinite_plane_intersections"}
        for side in ("left", "right"):
            near_floor = corners[f"{side}_floor_near"]
            far_floor = corners[f"{side}_floor_far"]
            near_ceiling = corners[f"{side}_ceiling_near"]
            far_ceiling = corners[f"{side}_ceiling_far"]
            if near_floor[1] >= near_ceiling[1] or far_floor[1] >= far_ceiling[1]:
                return [], {"status": "inverted_vertical_planes"}
        if corners["left_floor_near"][0] >= corners["right_floor_near"][0] or corners["left_floor_far"][0] >= corners["right_floor_far"][0]:
            return [], {"status": "crossed_side_boundaries"}
        meshes = [
            _textured_quad(
                np.array([
                    corners["left_floor_near"], corners["right_floor_near"],
                    corners["right_floor_far"], corners["left_floor_far"],
                ]),
                (0.18, 0.55, 0.82, 0.99), texture, intrinsics, texture_mapping,
            ),
            _textured_quad(
                np.array([
                    corners["left_ceiling_near"], corners["right_ceiling_near"],
                    corners["right_ceiling_far"], corners["left_ceiling_far"],
                ]),
                (0.18, 0.01, 0.82, 0.45), texture, intrinsics, texture_mapping,
            ),
            _textured_quad(
                np.array([
                    corners["left_floor_near"], corners["left_floor_far"],
                    corners["left_ceiling_far"], corners["left_ceiling_near"],
                ]),
                (0.01, 0.18, 0.45, 0.84), texture, intrinsics, texture_mapping,
            ),
            _textured_quad(
                np.array([
                    corners["right_floor_near"], corners["right_floor_far"],
                    corners["right_ceiling_far"], corners["right_ceiling_near"],
                ]),
                (0.55, 0.18, 0.99, 0.84), texture, intrinsics, texture_mapping,
            ),
            # Close the observed depth interval with a textured end plane.
            # Its four corners are intersections of the fitted side and
            # floor/ceiling planes at the robust far-depth boundary; it is not
            # an unbounded backdrop or a generic gray shell.
            _textured_quad(
                np.array([
                    corners["left_floor_far"], corners["right_floor_far"],
                    corners["right_ceiling_far"], corners["left_ceiling_far"],
                ]),
                (0.34, 0.28, 0.66, 0.72), texture, intrinsics, texture_mapping,
            ),
        ]
    except ValueError as error:
        return [], {"status": "envelope_plane_intersection_failed", "error": str(error)}
    return meshes, {
        "status": "candidate_only",
        "depth_interval_z": [float(far_z), float(near_z)],
        "mid_depth_z": mid_z,
        "observed_depth_interval_z": [float(far_z), float(observed_near_z)],
        "camera_clearance_z": camera_clearance_z,
        "near_boundary_policy": "max(observed 95th percentile, -0.25 estimated experience units)",
        "side_boundaries_x": [float(np.mean([corners["left_floor_near"][0], corners["left_floor_far"][0]])), float(np.mean([corners["right_floor_near"][0], corners["right_floor_far"][0]]))],
        "boundary_source": "median transformed inlier wall points",
        "depth_source": "5th/95th percentiles of all transformed inlier points",
        "surface_source": "four fitted MoGe planes",
        "end_surface_source": "intersections of fitted side/floor/ceiling planes at far depth",
        "texture_mapping": texture_mapping,
    }


def run(
    input_path: Path,
    output_dir: Path,
    model_path: Path,
    resize: int,
    normal_cos_threshold: float = 0.85,
    inlier_threshold: float = 0.05,
    camera_clearance_z: float = -0.25,
    texture_mapping: str = "region",
    plane_constraint: str = "free",
    semantic_exclusions_path: Path | None = None,
    line_guided: bool = False,
    semantic_regions_path: Path | None = None,
    semantic_normal_fallback: bool = False,
    semantic_normal_only: bool = False,
) -> dict[str, object]:
    started = time.perf_counter()
    image = cv2.imread(str(input_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot read image: {input_path}")
    original_height, original_width = image.shape[:2]
    height = min(resize, int(resize * original_height / original_width))
    width = min(resize, int(resize * original_width / original_height))
    image = cv2.resize(image, (width, height), cv2.INTER_AREA)
    import torch
    from moge.model import import_model_class_by_version

    model = import_model_class_by_version("v2").from_pretrained(model_path).to("cuda").eval()
    model.half()
    tensor = torch.tensor(cv2.cvtColor(image, cv2.COLOR_BGR2RGB) / 255, dtype=torch.float32, device="cuda").permute(2, 0, 1)
    with torch.inference_mode():
        output = model.infer(tensor, fov_x=None, resolution_level=9, num_tokens=None, use_fp16=True)
    points = output["points"].detach().float().cpu().numpy()
    normals = output.get("normal")
    normal_map = normals.detach().float().cpu().numpy() if normals is not None else None
    mask = output["mask"].detach().cpu().numpy().astype(bool)
    intrinsics = output["intrinsics"].detach().float().cpu().numpy()
    del model, output, tensor
    torch.cuda.empty_cache()

    lines, line_result = _line_evidence(image)
    line_masks, line_guidance = _line_guided_masks(lines, height, width)
    candidate_regions = _candidate_masks(height, width)
    if line_guided:
        candidate_regions = _perspective_candidate_masks(height, width, line_guidance["vanishing_point"])
    semantic_boxes: dict[str, list[dict[str, object]]] = {}
    semantic_positive_masks: dict[str, np.ndarray] = {}
    semantic_box_counts: dict[str, int] = {}
    if semantic_regions_path is not None:
        semantic_boxes = _load_detection_boxes(semantic_regions_path)
        label_map = {
            "ceiling_candidate": ("ceiling",),
            "floor_candidate": ("floor",),
            "left_wall_candidate": ("wall",),
            "right_wall_candidate": ("wall",),
        }
        for name, labels in label_map.items():
            boxes = [box for label in labels for box in semantic_boxes.get(label, [])]
            semantic_positive_masks[name] = _normalized_box_mask(height, width, boxes)
            semantic_box_counts[name] = len(boxes)
    candidates: dict[str, object] = {}
    meshes: list[trimesh.Trimesh] = []
    texture = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    expected_normals = {
        "ceiling_candidate": np.array([0.0, 1.0, 0.0]),
        "floor_candidate": np.array([0.0, 1.0, 0.0]),
        "left_wall_candidate": np.array([-1.0, 0.0, 0.0]),
        "right_wall_candidate": np.array([1.0, 0.0, 0.0]),
    }
    exclusions: list[dict[str, object]] = []
    if semantic_exclusions_path is not None:
        loaded = json.loads(semantic_exclusions_path.read_text(encoding="utf-8"))
        exclusions = [item for item in loaded.get("boxes", []) if isinstance(item, dict)]
    exclusion_stats: dict[str, int] = {}
    selected_masks: dict[str, np.ndarray] = {}
    inlier_masks: dict[str, np.ndarray] = {}
    for name, region in candidate_regions.items():
        if semantic_regions_path is not None:
            region = region & semantic_positive_masks[name]
        valid_region = region
        line_support_required = line_guided
        if semantic_normal_only and semantic_regions_path is not None:
            line_support_required = False
        elif semantic_normal_fallback and name == "ceiling_candidate" and line_guided and not line_masks[name].any():
            line_support_required = False
        if line_support_required:
            valid_region &= line_masks[name]
        if exclusions:
            valid_region, removed = _exclude_normalized_boxes(valid_region, exclusions)
            exclusion_stats[name] = removed
        valid = valid_region & mask & np.isfinite(points).all(axis=2)
        if normal_map is not None:
            valid &= np.isfinite(normal_map).all(axis=2)
            expected = expected_normals[name]
            valid &= np.abs(np.sum(normal_map * expected, axis=2)) >= normal_cos_threshold
        selected_masks[name] = valid.copy()
        inlier_masks[name] = np.zeros_like(valid, dtype=bool)
        selected = points[valid]
        if len(selected) < 3:
            candidates[name] = {"status": "insufficient_points", "point_count": int(len(selected))}
            continue
        try:
            fit, inlier_points = ransac_plane(selected, threshold=inlier_threshold)
        except ValueError as error:
            candidates[name] = {"status": "plane_fit_failed", "point_count": int(len(selected)), "error": str(error)}
            continue
        if plane_constraint == "axis_aligned":
            try:
                fit = _axis_aligned_plane(name, fit, inlier_points)
            except ValueError as error:
                candidates[name] = {"status": "plane_constraint_failed", "point_count": int(len(selected)), "error": str(error)}
                continue
        fit["status"] = "candidate_only"
        fit["normal_cos_threshold"] = normal_cos_threshold
        fit["normal_axis"] = expected_normals[name].astype(float).tolist()
        fit["selected_point_count"] = int(len(selected))
        fit["pixel_region"] = [int(np.where(region)[1].min()), int(np.where(region)[0].min()), int(np.where(region)[1].max()), int(np.where(region)[0].max())]
        selected_residual = np.abs(selected @ np.asarray(fit["normal"]) + float(fit["distance"]))
        final_inliers = selected_residual <= inlier_threshold
        fit["inlier_count"] = int(final_inliers.sum())
        fit["inlier_ratio"] = float(final_inliers.mean())
        if int(final_inliers.sum()) < 3:
            candidates[name] = {
                "status": "insufficient_inliers_after_constraint",
                "point_count": int(len(selected)),
                "inlier_count": int(final_inliers.sum()),
                "inlier_threshold": inlier_threshold,
                "axis_constraint": fit.get("axis_constraint"),
            }
            continue
        candidates[name] = fit
        inlier_masks[name][valid] = final_inliers
        x0, y0, x1, y1 = fit["pixel_region"]
        mesh = _patch_mesh(name, selected[final_inliers], fit, (x0 / max(width - 1, 1), y0 / max(height - 1, 1), x1 / max(width - 1, 1), y1 / max(height - 1, 1)), texture)
        if mesh is not None:
            meshes.append(mesh)

    inlier_clouds: dict[str, np.ndarray] = {}
    # Recompute the exact RANSAC inlier clouds for envelope bounds. The
    # selected arrays above include the normal-filtered points; using the
    # fitted residual policy here keeps the extent tied to the reported fit.
    for name, candidate in candidates.items():
        if candidate.get("status") != "candidate_only":
            continue
        region = candidate_regions[name]
        if semantic_regions_path is not None:
            region = region & semantic_positive_masks[name]
        line_support_required = line_guided
        if semantic_normal_only and semantic_regions_path is not None:
            line_support_required = False
        elif semantic_normal_fallback and name == "ceiling_candidate" and line_guided and not line_masks[name].any():
            line_support_required = False
        if line_support_required:
            region &= line_masks[name]
        if exclusions:
            region, _ = _exclude_normalized_boxes(region, exclusions)
        valid = region & mask & np.isfinite(points).all(axis=2)
        if normal_map is not None:
            valid &= np.isfinite(normal_map).all(axis=2)
            valid &= np.abs(np.sum(normal_map * expected_normals[name], axis=2)) >= normal_cos_threshold
        selected = points[valid]
        residual = np.abs(selected @ np.asarray(candidate["normal"]) + float(candidate["distance"]))
        inlier_clouds[name] = selected[residual <= inlier_threshold]
    if texture_mapping not in {"region", "projected"}:
        raise ValueError("texture_mapping must be region or projected")
    envelope_meshes, envelope = _room_envelope(candidates, inlier_clouds, texture, camera_clearance_z=camera_clearance_z, intrinsics=intrinsics, texture_mapping=texture_mapping)
    envelope_used = bool(envelope_meshes)
    if envelope_used:
        meshes = envelope_meshes

    overlay = line_result.pop("overlay")
    for name, candidate in candidates.items():
        if candidate.get("status") != "candidate_only":
            continue
        x1, y1, x2, y2 = candidate["pixel_region"]
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (255, 80, 220), 2)
        cv2.putText(overlay, name, (x1 + 5, max(18, y1 + 20)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 80, 220), 1, cv2.LINE_AA)
    output_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = output_dir / "structure-line-plane-evidence.png"
    cv2.imwrite(str(overlay_path), overlay)
    support_path = output_dir / "plane-support-evidence.png"
    cv2.imwrite(str(support_path), _support_overlay(image, selected_masks, inlier_masks, candidates))
    scene_path = output_dir / "indoor-structure-candidate.glb"
    trimesh.Scene(meshes).export(scene_path)
    result = {
        "input": str(input_path), "input_sha256": _sha256(input_path), "model": str(model_path), "model_sha256": _sha256(model_path),
        "image_size": [width, height], "original_image_size": [original_width, original_height], "resize": resize,
        "camera_intrinsics": intrinsics.astype(float).tolist(), "mask_coverage": float(mask.mean()),
        "line_evidence": line_result, "line_guidance": line_guidance if line_guided else {"enabled": False},
        "candidate_region_policy": "vanishing_point_perspective_regions" if line_guided else "fixed_image_regions",
        "semantic_positive_regions": {
            "source": str(semantic_regions_path) if semantic_regions_path is not None else None,
            "labels": {"ceiling_candidate": ["ceiling"], "floor_candidate": ["floor"], "left_wall_candidate": ["wall"], "right_wall_candidate": ["wall"]},
            "box_counts": {name: semantic_box_counts.get(name, 0) for name in candidate_regions},
            "normal_only_fallback": (
                "all candidates with semantic_regions_path" if semantic_normal_only and semantic_regions_path is not None
                else "ceiling_candidate when line support is empty" if semantic_normal_fallback else None
            ),
        },
        "plane_candidates": candidates,
        "output_glb": scene_path.name, "output_overlay": overlay_path.name, "output_support": support_path.name,
        "geometry_status": "candidate_only", "machine_status": "needs_visual_review",
        "fit_policy": {"normal_cos_threshold": normal_cos_threshold, "inlier_threshold": inlier_threshold, "ransac_trials": 250, "ransac_seed": 7},
        "plane_constraint": plane_constraint,
        "line_guided": line_guided,
        "semantic_exclusions": {"source": str(semantic_exclusions_path) if semantic_exclusions_path is not None else None, "box_count": len(exclusions), "removed_pixels_by_candidate": exclusion_stats, "policy": "remove_full_detection_rectangles_before_plane_fit"},
        "texture_mapping": texture_mapping,
        "room_envelope": envelope,
        "surface_markers": [{"name": name, "kind": "estimated_room_envelope" if envelope_used else "estimated_planar_patch", "photo_texture": "region_projected"} for name, candidate in candidates.items() if candidate.get("status") == "candidate_only"],
        "note": "MoGe点/法线与图像线段的隔离候选；未排除玻璃、镜面、家具，未生成可行走地面或碰撞体，禁止接入主路由。",
        "elapsed_s": round(time.perf_counter() - started, 3),
    }
    (output_dir / "structure.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="用 MoGe 点图/法线与图像线段拟合室内墙地候选；只生成隔离实验产物")
    parser.add_argument("--input", type=Path, required=True, help="室内照片")
    parser.add_argument("--output", type=Path, required=True, help="独立证据目录")
    parser.add_argument("--model", type=Path, required=True, help="本地 MoGe v2 model.pt")
    parser.add_argument("--resize", type=int, default=768, help="推理长边上限")
    parser.add_argument("--normal-cos-threshold", type=float, default=0.85, help="法线与候选结构轴的最小绝对余弦")
    parser.add_argument("--inlier-threshold", type=float, default=0.05, help="RANSAC 平面内点距离阈值")
    parser.add_argument("--camera-clearance-z", type=float, default=-0.25, help="候选表面近端深度；正值表示把已有拟合面延伸到相机前方，默认不延伸")
    parser.add_argument("--texture-mapping", choices=("region", "projected"), default="region", help="照片纹理坐标策略")
    parser.add_argument("--plane-constraint", choices=("free", "axis_aligned"), default="free", help="是否将室内地面/顶面/侧墙约束为水平或竖直")
    parser.add_argument("--semantic-exclusions", type=Path, help="可选 Moondream 检测框 JSON；保守移除框内像素，不作精确分割")
    parser.add_argument("--line-guided", action="store_true", help="仅用线段支持的像素参与 MoGe 点/法线平面拟合；实验参数")
    parser.add_argument("--semantic-regions", type=Path, help="可选本地 Moondream 检测 JSON；正向框仅作候选区域先验，不作像素级分割")
    parser.add_argument("--semantic-normal-fallback", action="store_true", help="当顶面没有线段时，允许语义顶面框加 MoGe 法线作为明确实验回退")
    parser.add_argument("--semantic-normal-only", action="store_true", help="隔离实验：语义正向框与 MoGe 法线共同拟合，完全不要求线段支持")
    args = parser.parse_args()
    print(json.dumps(run(args.input, args.output, args.model, args.resize, args.normal_cos_threshold, args.inlier_threshold, args.camera_clearance_z, args.texture_mapping, args.plane_constraint, args.semantic_exclusions, args.line_guided, args.semantic_regions, args.semantic_normal_fallback, args.semantic_normal_only), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
