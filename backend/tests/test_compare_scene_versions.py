import json
from pathlib import Path

from scripts.compare_scene_versions import compare


def _manifest(
    path: Path,
    version: str,
    coverage: float,
    triangles: int,
    aspect: float,
    bounds: dict[str, list[float]],
    *,
    complete: bool = False,
    input_sha256: str = "same-input",
    coordinate_frame_id: str = "moge-opengl-camera-v1",
    camera_position: list[float] | None = None,
    quality_status: str = "needs_visual_review",
) -> Path:
    path.mkdir(parents=True)
    (path / "scene.glb").write_bytes(b"x" * (100 if version == "quick" else 200))
    payload = {
        "version": version,
        "template": "landscape_journey",
        "movement": {"kind": "terrain", "start": [0, 0, 0], "bounds": bounds, "route_checkpoints": [[0, 0, -1]]},
        "coverage": coverage,
        "quality_metrics": {"triangle_count": triangles, "triangle_aspect_p99": aspect},
    }
    if complete:
        payload.update({
            "quality_status": quality_status,
            "input_sha256": input_sha256,
            "provider_version": "provider-v1" if version == "quick" else "provider-v2",
            "coordinate_frame_id": coordinate_frame_id,
            "resource_manifest": ["scene.glb", "source.jpg"],
            "acceptance_evidence": ["route.webm"] if version == "full" else [],
            "camera": {
                "position": camera_position or [0.0, 0.0, 0.0],
                "camera_to_world": [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]],
                "world_scale": 1.0,
                "near": 0.01,
                "far": 200.0,
                "fov_x": 72.0,
                "fov_y": 54.0,
                "coordinate_frame_id": coordinate_frame_id,
            },
        })
    manifest = path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest


def test_compare_warns_when_full_geometry_gets_worse(tmp_path: Path):
    bounds = {"x": [-1, 1], "y": [0, 1], "z": [-2, 0]}
    quick = _manifest(tmp_path / "quick", "quick", 0.58, 100, 8.0, bounds)
    full = _manifest(tmp_path / "full", "full", 0.58, 200, 11.0, bounds)
    report = compare(quick, full)
    assert report["layout_same"] is True
    assert report["measurable_upgrade_candidate"] is False
    assert len(report["warnings"]) >= 2


def test_compare_rejects_layout_switch(tmp_path: Path):
    quick = _manifest(tmp_path / "quick", "quick", 0.5, 100, 8.0, {"x": [-1, 1], "y": [0, 1], "z": [-2, 0]})
    full = _manifest(tmp_path / "full", "full", 0.8, 200, 7.0, {"x": [-2, 2], "y": [0, 1], "z": [-3, 0]})
    report = compare(quick, full)
    assert report["layout_same"] is False
    assert report["measurable_upgrade_candidate"] is False


def test_compare_allows_only_a_provenanced_quality_passed_upgrade(tmp_path: Path):
    bounds = {"x": [-1, 1], "y": [0, 1], "z": [-2, 0]}
    quick = _manifest(tmp_path / "quick", "quick", 0.50, 100, 8.0, bounds, complete=True)
    full = _manifest(tmp_path / "full", "full", 0.65, 200, 7.0, bounds, complete=True, quality_status="passed")

    report = compare(quick, full)

    assert report["input_hash_same"] is True
    assert report["camera_contract_same"] is True
    assert report["provider_changed"] is True
    assert report["metric_improvement"] is True
    assert report["measurable_upgrade_candidate"] is True


def test_compare_rejects_missing_provenance_and_camera_change(tmp_path: Path):
    bounds = {"x": [-1, 1], "y": [0, 1], "z": [-2, 0]}
    quick = _manifest(tmp_path / "quick", "quick", 0.50, 100, 8.0, bounds, complete=True)
    full = _manifest(
        tmp_path / "full",
        "full",
        0.65,
        200,
        7.0,
        bounds,
        complete=True,
        input_sha256="different-input",
        camera_position=[0.2, 0.0, 0.0],
        quality_status="passed",
    )
    payload = json.loads(full.read_text(encoding="utf-8"))
    payload.pop("provider_version")
    payload.pop("acceptance_evidence")
    full.write_text(json.dumps(payload), encoding="utf-8")

    report = compare(quick, full)

    assert report["input_hash_same"] is False
    assert report["camera_contract_same"] is False
    assert report["measurable_upgrade_candidate"] is False
    assert any("输入 SHA256" in warning for warning in report["warnings"])
    assert any("相机" in warning for warning in report["warnings"])
