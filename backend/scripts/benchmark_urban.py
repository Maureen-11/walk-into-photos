"""Measure conservative street/facade evidence from urban photographs.

This script is a T07 acceptance aid, not an urban 3-D reconstruction.  It
separates two route candidates:

* ``street``: estimate a horizon/road band and mark likely upright objects;
* ``facade``: measure facade-aligned vertical/horizontal line evidence.

The output is deliberately marked ``needs_visual_review``.  A line detector
cannot prove that people, cars, trees, windows, or building interiors are
separate walkable geometry.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def _read_image(path: Path) -> np.ndarray | None:
    """Read a Windows path even when its parent contains non-ASCII text."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def _write_png(path: Path, image: np.ndarray) -> bool:
    encoded = cv2.imencode(".png", image)[1]
    try:
        encoded.tofile(str(path))
    except OSError:
        return False
    return True


def _angle(line: np.ndarray) -> float:
    x1, y1, x2, y2 = [float(value) for value in line]
    return float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))


def _length(line: np.ndarray) -> float:
    x1, y1, x2, y2 = [float(value) for value in line]
    return float(np.hypot(x2 - x1, y2 - y1))


def _lines(image: np.ndarray) -> list[np.ndarray]:
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 55, 165, apertureSize=3)
    raw = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180.0,
        threshold=max(28, min(width, height) // 11),
        minLineLength=max(35, min(width, height) // 9),
        maxLineGap=14,
    )
    if raw is None:
        return []
    return sorted(
        [line.astype(np.float64) for line in np.asarray(raw).reshape(-1, 4)],
        key=_length,
        reverse=True,
    )[:300]


def _horizon_candidate(image: np.ndarray) -> int | None:
    height, _width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 45, 135)
    density = edges.mean(axis=1) / 255.0
    start = max(1, int(height * 0.2))
    end = max(start + 1, int(height * 0.82))
    if end <= start:
        return None
    return int(start + int(np.argmax(density[start:end])))


def analyze(image_path: Path, output_dir: Path, kind: str) -> dict[str, object]:
    if kind not in {"street", "facade"}:
        raise ValueError("kind 必须是 street 或 facade")
    image = _read_image(image_path)
    if image is None:
        raise ValueError(f"无法读取图片: {image_path}")
    height, width = image.shape[:2]
    lines = _lines(image)
    horizontal = [line for line in lines if abs(_angle(line)) <= 12 or abs(abs(_angle(line)) - 180) <= 12]
    vertical = [line for line in lines if abs(abs(_angle(line)) - 90) <= 12]
    diagonal = [
        line
        for line in lines
        if not (abs(_angle(line)) <= 12 or abs(abs(_angle(line)) - 180) <= 12)
        and not (abs(abs(_angle(line)) - 90) <= 12)
    ]
    horizon = _horizon_candidate(image)
    overlay = image.copy()
    for line in horizontal:
        cv2.line(overlay, tuple(int(v) for v in line[:2]), tuple(int(v) for v in line[2:]), (0, 220, 0), 2)
    for line in vertical:
        cv2.line(overlay, tuple(int(v) for v in line[:2]), tuple(int(v) for v in line[2:]), (220, 0, 0), 2)
    for line in diagonal[:120]:
        cv2.line(overlay, tuple(int(v) for v in line[:2]), tuple(int(v) for v in line[2:]), (0, 150, 220), 1)
    if horizon is not None:
        cv2.line(overlay, (0, horizon), (width - 1, horizon), (0, 0, 255), 3)
    output_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = output_dir / f"urban-{kind}-line-evidence.png"
    if not _write_png(overlay_path, overlay):
        raise OSError(f"无法写入叠加图: {overlay_path}")
    dominant_vertical_ratio = float(len(vertical) / max(1, len(lines)))
    dominant_horizontal_ratio = float(len(horizontal) / max(1, len(lines)))
    if kind == "street":
        interpretation = "街道线索可用于估计下降起点和道路带；行人、车辆、树木尚未分离，不能宣称可绕行。"
        route = "从俯拍视角下降到估计道路带，主体分离未通过前保持未验证。"
    else:
        interpretation = "立面线索可用于估计建筑平面；窗户、线缆和背面尚未重建，不能宣称可沿楼体飞行。"
        route = "沿立面法线方向试探飞行，需先用独立样片复核窗线和颜色。"
    return {
        "input": image_path.name,
        "kind": kind,
        "image_size": [width, height],
        "line_count": len(lines),
        "horizontal_line_count": len(horizontal),
        "vertical_line_count": len(vertical),
        "diagonal_line_count": len(diagonal),
        "vertical_line_ratio": round(dominant_vertical_ratio, 6),
        "horizontal_line_ratio": round(dominant_horizontal_ratio, 6),
        "horizon_y_px_estimate": horizon,
        "horizon_y_normalized": None if horizon is None else round(horizon / max(height, 1), 4),
        "route_candidate": route,
        "overlay": overlay_path.name,
        "machine_status": "needs_visual_review",
        "interpretation": interpretation,
        "limitations": [
            "单张照片不提供可靠的真实尺度或遮挡背面。",
            "线段不是碰撞体，也不是独立人车树或建筑网格。",
            "该结果不能替代第二样片、浏览器路线和断网导出验收。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="分析街道/建筑立面证据，不生成或批准城市3D场景")
    parser.add_argument("--image", type=Path, required=True, help="街道或建筑照片")
    parser.add_argument("--kind", choices=("street", "facade"), required=True, help="路线：street 或 facade")
    parser.add_argument("--output", type=Path, required=True, help="证据输出目录")
    parser.add_argument("--json", type=Path, help="可选 JSON 输出路径")
    args = parser.parse_args()
    result = analyze(args.image, args.output, args.kind)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
