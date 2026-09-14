"""Compare quick/full scene contracts without calling either generator.

The comparison guards T09 against a common false positive: a larger GLB or a
longer run is not an upgrade when the navigation layout is different or the
coverage and geometry quality do not improve.  The final status remains
``needs_visual_review`` until the same route is recorded in a browser.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _metric(manifest: dict[str, Any], key: str) -> float | None:
    value = manifest.get("quality_metrics", {}).get(key)
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def compare(quick_manifest: Path, full_manifest: Path) -> dict[str, Any]:
    quick = json.loads(quick_manifest.read_text(encoding="utf-8"))
    full = json.loads(full_manifest.read_text(encoding="utf-8"))
    q_movement = quick.get("movement", {})
    f_movement = full.get("movement", {})
    layout_fields = ("kind", "start", "bounds", "route_checkpoints")
    layout_same = all(q_movement.get(field) == f_movement.get(field) for field in layout_fields)
    q_size = (quick_manifest.parent / "scene.glb").stat().st_size if (quick_manifest.parent / "scene.glb").is_file() else None
    f_size = (full_manifest.parent / "scene.glb").stat().st_size if (full_manifest.parent / "scene.glb").is_file() else None
    q_coverage, f_coverage = _metric(quick, "coverage"), _metric(full, "coverage")
    # coverage is usually a top-level field in older manifests
    q_coverage = q_coverage if q_coverage is not None else (float(quick["coverage"]) if quick.get("coverage") is not None else None)
    f_coverage = f_coverage if f_coverage is not None else (float(full["coverage"]) if full.get("coverage") is not None else None)
    q_triangles, f_triangles = _metric(quick, "triangle_count"), _metric(full, "triangle_count")
    q_aspect, f_aspect = _metric(quick, "triangle_aspect_p99"), _metric(full, "triangle_aspect_p99")
    measurable_improvement = (
        layout_same
        and f_triangles is not None
        and q_triangles is not None
        and f_triangles > q_triangles
        and (q_coverage is None or f_coverage is None or f_coverage > q_coverage + 0.01)
        and (q_aspect is None or f_aspect is None or f_aspect <= q_aspect)
    )
    warnings: list[str] = []
    if not layout_same:
        warnings.append("quick/full 的移动布局不同，不能安全切换位置")
    if q_coverage is not None and f_coverage is not None and f_coverage <= q_coverage + 0.01:
        warnings.append("覆盖率没有明确提升")
    if q_aspect is not None and f_aspect is not None and f_aspect > q_aspect:
        warnings.append("三角形长宽比变差，可能增加拉伸")
    if f_size is not None and q_size is not None and f_size <= q_size:
        warnings.append("完整版文件没有变大；不能仅凭时间称为增强")
    return {
        "quick_manifest": quick_manifest.name,
        "full_manifest": full_manifest.name,
        "template_same": quick.get("template") == full.get("template"),
        "layout_same": layout_same,
        "quick_bytes": q_size,
        "full_bytes": f_size,
        "quick_coverage": q_coverage,
        "full_coverage": f_coverage,
        "quick_triangle_count": q_triangles,
        "full_triangle_count": f_triangles,
        "quick_triangle_aspect_p99": q_aspect,
        "full_triangle_aspect_p99": f_aspect,
        "measurable_upgrade_candidate": measurable_improvement,
        "machine_status": "needs_visual_review",
        "warnings": warnings,
        "interpretation": "必须用相同起点、相同路线的浏览器录像确认升级；更大的GLB或更长耗时本身不是质量通过。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="比较快速版和完整版场景契约，不把更大文件当成质量升级")
    parser.add_argument("--quick-manifest", type=Path, required=True)
    parser.add_argument("--full-manifest", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True, help="写入比较报告")
    args = parser.parse_args()
    report = compare(args.quick_manifest, args.full_manifest)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
