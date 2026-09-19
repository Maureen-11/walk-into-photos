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


def _text(manifest: Any, key: str) -> str | None:
    if not isinstance(manifest, dict):
        return None
    value = manifest.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _coordinate_frame_id(manifest: dict[str, Any]) -> str | None:
    return _text(manifest, "coordinate_frame_id") or _text(manifest.get("camera", {}), "coordinate_frame_id")


def _camera_contract(manifest: dict[str, Any]) -> dict[str, Any] | None:
    camera = manifest.get("camera")
    if not isinstance(camera, dict):
        return None
    # image_size and intrinsics may legitimately change when the same source
    # is resized. The world pose, scale, clipping and FOV must not change: the
    # viewer must not silently move the user when a candidate is promoted.
    return {
        key: camera.get(key)
        for key in (
            "position",
            "camera_to_world",
            "world_scale",
            "near",
            "far",
            "fov_x",
            "fov_y",
            "coordinate_frame_id",
        )
    }


def _resources(manifest: dict[str, Any]) -> list[str] | None:
    value = manifest.get("resource_manifest")
    if not isinstance(value, list):
        return None
    resources = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return resources or None


def _evidence(manifest: dict[str, Any]) -> list[str] | None:
    value = manifest.get("acceptance_evidence")
    if not isinstance(value, list):
        return None
    evidence = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return evidence or None


def compare(quick_manifest: Path, full_manifest: Path) -> dict[str, Any]:
    quick = json.loads(quick_manifest.read_text(encoding="utf-8"))
    full = json.loads(full_manifest.read_text(encoding="utf-8"))
    q_movement = quick.get("movement", {})
    f_movement = full.get("movement", {})
    layout_fields = ("kind", "start", "bounds", "route_checkpoints")
    layout_same = all(q_movement.get(field) == f_movement.get(field) for field in layout_fields)
    template_same = quick.get("template") == full.get("template")
    quick_input_sha256 = _text(quick, "input_sha256")
    full_input_sha256 = _text(full, "input_sha256")
    input_hashes_present = quick_input_sha256 is not None and full_input_sha256 is not None
    input_hash_same = input_hashes_present and quick_input_sha256 == full_input_sha256
    quick_provider = _text(quick, "provider_version")
    full_provider = _text(full, "provider_version")
    provider_versions_present = quick_provider is not None and full_provider is not None
    provider_changed = provider_versions_present and quick_provider != full_provider
    quick_frame = _coordinate_frame_id(quick)
    full_frame = _coordinate_frame_id(full)
    coordinate_frame_present = quick_frame is not None and full_frame is not None
    coordinate_frame_same = coordinate_frame_present and quick_frame == full_frame
    camera_contract_same = _camera_contract(quick) is not None and _camera_contract(quick) == _camera_contract(full)
    quick_resources = _resources(quick)
    full_resources = _resources(full)
    resource_manifests_present = quick_resources is not None and full_resources is not None
    resources_complete = (
        resource_manifests_present
        and "scene.glb" in quick_resources
        and "scene.glb" in full_resources
    )
    full_acceptance_evidence = _evidence(full)
    full_quality_status = str(full.get("quality_status") or "unverified")
    full_quality_passed = full_quality_status == "passed"
    q_size = (quick_manifest.parent / "scene.glb").stat().st_size if (quick_manifest.parent / "scene.glb").is_file() else None
    f_size = (full_manifest.parent / "scene.glb").stat().st_size if (full_manifest.parent / "scene.glb").is_file() else None
    q_coverage, f_coverage = _metric(quick, "coverage"), _metric(full, "coverage")
    # coverage is usually a top-level field in older manifests
    q_coverage = q_coverage if q_coverage is not None else (float(quick["coverage"]) if quick.get("coverage") is not None else None)
    f_coverage = f_coverage if f_coverage is not None else (float(full["coverage"]) if full.get("coverage") is not None else None)
    q_triangles, f_triangles = _metric(quick, "triangle_count"), _metric(full, "triangle_count")
    q_aspect, f_aspect = _metric(quick, "triangle_aspect_p99"), _metric(full, "triangle_aspect_p99")
    metrics_present = all(value is not None for value in (q_coverage, f_coverage, q_triangles, f_triangles, q_aspect, f_aspect))
    metric_improvement = (
        metrics_present
        and f_triangles > q_triangles
        and f_coverage > q_coverage + 0.01
        and f_aspect <= q_aspect
    )
    measurable_improvement = all((
        template_same,
        layout_same,
        input_hash_same,
        provider_versions_present,
        coordinate_frame_same,
        camera_contract_same,
        resources_complete,
        full_acceptance_evidence is not None,
        full_quality_passed,
        metric_improvement,
    ))
    warnings: list[str] = []
    if not template_same:
        warnings.append("quick/full 模板不同，不能安全切换体验模式")
    if not layout_same:
        warnings.append("quick/full 的移动布局不同，不能安全切换位置")
    if not input_hashes_present:
        warnings.append("缺少 quick/full 输入 SHA256，不能证明是同一张照片")
    elif not input_hash_same:
        warnings.append("quick/full 输入 SHA256 不一致，不能安全切换")
    if not provider_versions_present:
        warnings.append("缺少提供器版本，不能追踪候选来源")
    elif provider_changed:
        warnings.append("提供器版本发生变化，必须在同一路线重新复核")
    if not coordinate_frame_present:
        warnings.append("缺少坐标系标识，不能证明相机合同一致")
    elif not coordinate_frame_same:
        warnings.append("quick/full 坐标系不同，不能安全切换位置")
    if not camera_contract_same:
        warnings.append("quick/full 相机位置、朝向、尺度或视场合同不同，不能安全切换")
    if not resource_manifests_present:
        warnings.append("缺少资源清单，不能确认升级候选的加载资源")
    elif not resources_complete:
        warnings.append("资源清单缺少 scene.glb，不能安全切换")
    if full_acceptance_evidence is None:
        warnings.append("完整版没有验收证据引用，不能自动升级")
    if not full_quality_passed:
        warnings.append(f"完整版质量状态为 {full_quality_status}，必须先通过机器检查和视觉复核")
    if not metrics_present:
        warnings.append("覆盖率、三角形数量或长宽比指标缺失，不能证明有改善")
    if q_coverage is not None and f_coverage is not None and f_coverage <= q_coverage + 0.01:
        warnings.append("覆盖率没有明确提升")
    if q_aspect is not None and f_aspect is not None and f_aspect > q_aspect:
        warnings.append("三角形长宽比变差，可能增加拉伸")
    if f_size is not None and q_size is not None and f_size <= q_size:
        warnings.append("完整版文件没有变大；不能仅凭时间称为增强")
    return {
        "quick_manifest": quick_manifest.name,
        "full_manifest": full_manifest.name,
        "template_same": template_same,
        "layout_same": layout_same,
        "input_hashes_present": input_hashes_present,
        "input_hash_same": input_hash_same,
        "quick_input_sha256": quick_input_sha256,
        "full_input_sha256": full_input_sha256,
        "quick_provider_version": quick_provider,
        "full_provider_version": full_provider,
        "provider_versions_present": provider_versions_present,
        "provider_changed": provider_changed,
        "quick_coordinate_frame_id": quick_frame,
        "full_coordinate_frame_id": full_frame,
        "coordinate_frame_same": coordinate_frame_same,
        "camera_contract_same": camera_contract_same,
        "resource_manifests_present": resource_manifests_present,
        "resources_complete": resources_complete,
        "full_acceptance_evidence": full_acceptance_evidence or [],
        "quick_quality_status": str(quick.get("quality_status") or "unverified"),
        "full_quality_status": full_quality_status,
        "full_quality_passed": full_quality_passed,
        "metrics_present": metrics_present,
        "metric_improvement": metric_improvement,
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
