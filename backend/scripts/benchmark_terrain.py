"""Measure terrain/horizon evidence for a natural photograph.

The report is intentionally conservative: it identifies likely horizon and
ground evidence for a future terrain engine, but does not claim that a single
image contains enough information for true terrain reconstruction.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def analyze(image_path: Path, output_dir: Path) -> dict:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取图片: {image_path}")
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 45, 135)
    row_edge_density = edges.mean(axis=1) / 255.0
    # The horizon candidate is deliberately a broad estimate.  It is only
    # useful as a starting band for review, not as a camera calibration.
    search_start = max(1, int(height * 0.18))
    search_end = max(search_start + 1, int(height * 0.75))
    candidate_rows = row_edge_density[search_start:search_end]
    horizon_y = int(search_start + int(np.argmax(candidate_rows))) if len(candidate_rows) else None
    ground_start = int(min(height - 1, max(0, (horizon_y or height // 2) + height * 0.08)))
    lower_edges = float(edges[ground_start:].mean() / 255.0) if ground_start < height else 0.0
    overlay = image.copy()
    if horizon_y is not None:
        cv2.line(overlay, (0, horizon_y), (width - 1, horizon_y), (0, 0, 255), 3)
        cv2.line(overlay, (0, ground_start), (width - 1, ground_start), (0, 220, 0), 2)
    output_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = output_dir / "terrain-horizon-evidence.png"
    cv2.imwrite(str(overlay_path), overlay)
    return {
        "input": image_path.name,
        "image_size": [width, height],
        "horizon_y_px_estimate": horizon_y,
        "horizon_y_normalized": None if horizon_y is None else round(horizon_y / max(height, 1), 4),
        "ground_band_start_y_px": ground_start,
        "lower_band_edge_density": round(lower_edges, 6),
        "overlay": overlay_path.name,
        "machine_status": "needs_visual_review",
        "interpretation": "地平线和近景带仅是地形建模的候选证据；尚未生成连续地形或行走碰撞体。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="分析自然照片的地平线与近景地形证据，不生成或批准3D地形")
    parser.add_argument("--image", type=Path, required=True, help="自然风景照片")
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
