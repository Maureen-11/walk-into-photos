import json
from pathlib import Path

from scripts.compare_scene_versions import compare


def _manifest(path: Path, version: str, coverage: float, triangles: int, aspect: float, bounds: dict[str, list[float]]) -> Path:
    path.mkdir(parents=True)
    (path / "scene.glb").write_bytes(b"x" * (100 if version == "quick" else 200))
    payload = {
        "version": version,
        "template": "landscape_journey",
        "movement": {"kind": "terrain", "start": [0, 0, 0], "bounds": bounds, "route_checkpoints": [[0, 0, -1]]},
        "coverage": coverage,
        "quality_metrics": {"triangle_count": triangles, "triangle_aspect_p99": aspect},
    }
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
