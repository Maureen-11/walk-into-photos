from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from app.main import _write_manifest
from app.models import PhotoCategory, SceneEngine, SceneTemplate
from app.services.geometry import write_demo_glb
from app.services.photo_plan import build_plan
from app.services.scene_quality import inspect_scene
from app.services.context_shell import add_context_shell
from app.services.templates import ENGINE_BY_TEMPLATE


def test_manifest_preserves_subject_capability_and_unknown_coverage(tmp_path: Path):
    scene_path = tmp_path / "scene.glb"
    write_demo_glb(scene_path)
    plan = build_plan(PhotoCategory.animal_closeup, "cat behind cage")
    _write_manifest(
        "scene-001",
        scene_path,
        SceneTemplate.animal_diorama,
        "quick",
        False,
        datetime.now(timezone.utc) + timedelta(hours=1),
        plan,
        None,
    )

    manifest = (tmp_path / "manifest.json").read_text(encoding="utf-8")
    assert '"experience_kind": "interactive_subject"' in manifest
    assert '"action_id": "pet_head"' in manifest
    assert '"coverage": null' in manifest
    assert '"quality_status": "unverified"' in manifest


def test_real_manifest_keeps_camera_origin_and_scene_bounds(tmp_path: Path):
    scene_path = tmp_path / "scene.glb"
    write_demo_glb(scene_path)
    plan = build_plan(PhotoCategory.natural_landscape, "snow mountains")
    camera = {
        "position": [0.0, 0.0, 0.0],
        "intrinsics": [[500.0, 0.0, 384.0], [0.0, 500.0, 288.0], [0.0, 0.0, 1.0]],
        "image_size": [768, 576],
        "world_scale": 0.01,
        "near": 0.01,
        "far": 20.0,
        "fov_x": 75.0,
        "fov_y": 60.0,
        "coordinate_frame_id": "moge-opengl-camera-v1",
    }
    _write_manifest(
        "scene-002", scene_path, SceneTemplate.landscape_journey, "quick", False,
        datetime.now(timezone.utc) + timedelta(hours=1), plan, 0.58, camera,
        [[-11.0, -0.7, -18.0], [13.0, 1.9, -0.1]],
    )
    payload = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert payload["camera"]["position"] == [0.0, 0.0, 0.0]
    assert payload["camera"]["world_scale"] == 0.01
    assert payload["movement"]["start"] == [0.0, 0.0, 0.0]
    assert payload["movement"]["bounds"]["y"][0] >= -0.25
    assert payload["movement"]["bounds"]["z"][0] < -18.5
    assert payload["movement"]["bounds"]["z"][1] >= 0.0


def test_all_eight_templates_have_an_explicit_engine_route():
    expected = {
        SceneTemplate.landscape_journey: SceneEngine.terrain,
        SceneTemplate.indoor_walk: SceneEngine.space,
        SceneTemplate.street_descent: SceneEngine.street,
        SceneTemplate.facade_flight: SceneEngine.facade,
        SceneTemplate.animal_diorama: SceneEngine.diorama,
        SceneTemplate.memory_stage: SceneEngine.portrait_stage,
        SceneTemplate.tabletop_world: SceneEngine.tabletop,
        SceneTemplate.layered_canvas: SceneEngine.layered_canvas,
    }
    assert {template: ENGINE_BY_TEMPLATE[template] for template in expected} == expected


def test_scene_quality_marks_valid_mesh_for_visual_review(tmp_path: Path):
    scene_path = tmp_path / "scene.glb"
    write_demo_glb(scene_path)
    quality = inspect_scene(scene_path)
    assert quality["machine_status"] == "needs_visual_review"
    assert quality["triangle_count"] == 2
    assert quality["vertex_count"] == 4


def test_manifest_persists_machine_quality_evidence(tmp_path: Path):
    scene_path = tmp_path / "scene.glb"
    write_demo_glb(scene_path)
    plan = build_plan(PhotoCategory.indoor_space, "hallway")
    quality = inspect_scene(scene_path)
    _write_manifest(
        "scene-quality", scene_path, SceneTemplate.indoor_walk, "quick", False,
        datetime.now(timezone.utc) + timedelta(hours=1), plan, 1.0,
        quality_metrics=quality,
    )
    payload = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert payload["quality_status"] == "needs_visual_review"
    assert payload["quality_metrics"]["machine_status"] == "needs_visual_review"


def test_context_shell_is_explicit_and_keeps_scene_valid(tmp_path: Path):
    scene_path = tmp_path / "scene.glb"
    write_demo_glb(scene_path)
    result = add_context_shell(scene_path, SceneTemplate.indoor_walk)
    assert result["enabled"] is True
    assert result["status"] == "experimental_needs_visual_review"
    quality = inspect_scene(scene_path)
    assert quality["machine_status"] == "needs_visual_review"
    assert quality["vertex_count"] > 4


def test_scene_quality_bakes_gltf_node_transforms_before_measuring(tmp_path: Path):
    """Quality evidence must describe the browser-space mesh, not local nodes."""
    import trimesh

    scene_path = tmp_path / "transformed.glb"
    mesh = trimesh.creation.box(extents=[1.0, 1.0, 1.0])
    scene = trimesh.Scene()
    scene.add_geometry(mesh, transform=trimesh.transformations.scale_and_translate(
        scale=0.25, translate=[4.0, 2.0, -3.0]
    ))
    scene.export(scene_path, file_type="glb")
    quality = inspect_scene(scene_path)
    assert quality["machine_status"] == "needs_visual_review"
    bounds = quality["bounds"]
    assert bounds[0][0] == 3.875
    assert bounds[1][0] == 4.125
