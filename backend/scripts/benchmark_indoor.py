"""Build a dependency-light indoor structure report from one photograph.

This is an analysis/acceptance aid, not a 3-D reconstruction.  It measures
line evidence that can be used by a future indoor engine and writes an
overlay for human review.  It deliberately never turns a line estimate into
an approved room mesh.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def _line_angle(line: np.ndarray) -> float:
    x1, y1, x2, y2 = [float(value) for value in line]
    return float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))


def _line_length(line: np.ndarray) -> float:
    x1, y1, x2, y2 = [float(value) for value in line]
    return float(np.hypot(x2 - x1, y2 - y1))


def _intersection(first: np.ndarray, second: np.ndarray) -> tuple[float, float] | None:
    x1, y1, x2, y2 = [float(value) for value in first]
    x3, y3, x4, y4 = [float(value) for value in second]
    denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denominator) < 1e-6:
        return None
    numerator_x = (x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)
    numerator_y = (x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)
    return float(numerator_x / denominator), float(numerator_y / denominator)


def analyze(image_path: Path, output_dir: Path) -> dict:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取图片: {image_path}")
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160, apertureSize=3)
    raw = cv2.HoughLinesP(edges, 1, np.pi / 180.0, threshold=max(25, min(width, height) // 10), minLineLength=max(30, min(width, height) // 8), maxLineGap=12)
    # OpenCV returns either (N, 1, 4) or (N, 4) depending on the build.
    lines = [] if raw is None else [line.astype(np.float64) for line in np.asarray(raw).reshape(-1, 4)]
    # Keep the longest evidence lines and classify them without pretending that
    # they are actual walls.  Near-horizontal lines are useful for floor,
    # ceiling and window checks; diagonal lines provide vanishing-point clues.
    lines = sorted(lines, key=_line_length, reverse=True)[:200]
    horizontal = [line for line in lines if abs(_line_angle(line)) <= 12 or abs(abs(_line_angle(line)) - 180) <= 12]
    vertical = [line for line in lines if abs(abs(_line_angle(line)) - 90) <= 12]
    classified_ids = {id(line) for line in horizontal + vertical}
    diagonal = [line for line in lines if id(line) not in classified_ids]
    intersections: list[tuple[float, float]] = []
    for index, first in enumerate(diagonal[:40]):
        for second in diagonal[index + 1 : 40]:
            point = _intersection(first, second)
            if point is None:
                continue
            x, y = point
            # Keep plausible image-local vanishing evidence, but do not reject
            # off-image intersections: wide perspective can place them outside.
            if -4 * width < x < 5 * width and -4 * height < y < 5 * height:
                intersections.append(point)
    vanishing = None
    if intersections:
        vanishing = np.median(np.asarray(intersections), axis=0).astype(float).tolist()
    overlay = image.copy()
    for line in horizontal:
        cv2.line(overlay, tuple(int(v) for v in line[:2]), tuple(int(v) for v in line[2:]), (0, 220, 0), 2)
    for line in vertical:
        cv2.line(overlay, tuple(int(v) for v in line[:2]), tuple(int(v) for v in line[2:]), (220, 0, 0), 2)
    for line in diagonal:
        cv2.line(overlay, tuple(int(v) for v in line[:2]), tuple(int(v) for v in line[2:]), (0, 140, 220), 1)
    if vanishing is not None:
        cv2.drawMarker(overlay, tuple(int(v) for v in vanishing), (0, 0, 255), cv2.MARKER_CROSS, 24, 3)
    output_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = output_dir / "indoor-line-evidence.png"
    cv2.imwrite(str(overlay_path), overlay)
    result = {
        "input": image_path.name,
        "image_size": [width, height],
        "line_count": len(lines),
        "horizontal_line_count": len(horizontal),
        "vertical_line_count": len(vertical),
        "diagonal_line_count": len(diagonal),
        "vanishing_point_estimate": vanishing,
        "overlay": overlay_path.name,
        "machine_status": "needs_visual_review",
        "interpretation": "线段证据可用于结构约束候选；尚未生成墙地网格、深度或碰撞体。",
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="分析室内照片的直线和消失点证据，不生成或批准3D房间")
    parser.add_argument("--image", type=Path, required=True, help="室内照片")
    parser.add_argument("--output", type=Path, required=True, help="证据输出目录")
    parser.add_argument("--json", type=Path, help="可选 JSON 输出路径")
    args = parser.parse_args()
    result = analyze(args.image, args.output)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
