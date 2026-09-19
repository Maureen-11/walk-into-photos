import pytest

from app.models import ExperienceKind, PhotoCategory, SceneTemplate, SubjectRegion
import trimesh

from app.services.geometry import _mask_coverage, scale_glb_uniformly_from_camera, write_demo_glb
from app.services.photo_plan import _parse_category, build_plan
from app.services.templates import CATEGORY_TEMPLATE, movement_profile


def test_all_categories_have_usable_plans():
    for category in PhotoCategory:
        plan = build_plan(category, "test image")
        assert plan.recommended_template in plan.compatible_templates
        assert plan.warnings
        assert plan.recommended_template in CATEGORY_TEMPLATE.values()


def test_normal_photos_are_never_rejected():
    for category in PhotoCategory:
        assert build_plan(category, "test image").experimental is (category is PhotoCategory.other)


def test_category_parser_accepts_model_aliases():
    assert _parse_category("natural_landscape") is PhotoCategory.natural_landscape
    assert _parse_category("a close-up cat") is PhotoCategory.animal_closeup
    assert _parse_category("unknown scene") is PhotoCategory.other


def test_movement_profiles_have_valid_bounds():
    for template in SceneTemplate:
        profile = movement_profile(template)
        for axis in ("x", "y", "z"):
            assert len(profile.bounds[axis]) == 2
            assert profile.bounds[axis][0] < profile.bounds[axis][1]
        assert len(profile.start) == 3


def test_subject_categories_expose_truthful_interaction_capabilities():
    cat = build_plan(PhotoCategory.animal_closeup, "two cats behind a cage")
    assert cat.experience_kind is ExperienceKind.interactive_subject
    assert [action.action_id for action in cat.actions] == ["pet_head"]
    assert cat.actions[0].status.value == "experimental"
    assert cat.actions[0].asset_url is None

    people = build_plan(PhotoCategory.people, "a portrait")
    assert people.experience_kind is ExperienceKind.interactive_subject
    assert people.actions[0].action_id == "wave_back"


def test_subject_regions_are_optional_and_keep_action_target_stable():
    region = SubjectRegion(region_id="primary_subject_head", label="cat", x=0.1, y=0.2, width=0.3, height=0.3)
    plan = build_plan(PhotoCategory.animal_closeup, "cat", subject_regions=[region])
    assert plan.subject_regions[0].region_id == plan.actions[0].target_region_id


def test_scene_categories_remain_spatial_and_other_is_still_fallback():
    snow = build_plan(PhotoCategory.natural_landscape, "snow mountains")
    assert snow.experience_kind is ExperienceKind.spatial_scene
    assert snow.actions == []

    other = build_plan(PhotoCategory.other, "unknown")
    assert other.experience_kind is ExperienceKind.still_fallback
    assert other.experimental is True


def test_geometry_without_mask_reports_unknown_coverage(tmp_path):
    assert _mask_coverage(tmp_path) is None


def test_uniform_camera_scale_does_not_translate_or_stretch_mesh(tmp_path):
    path = tmp_path / "scene.glb"
    write_demo_glb(path)

    evidence = scale_glb_uniformly_from_camera(path)
    bounds = trimesh.load(path, force="scene").bounds

    assert evidence["world_scale"] == pytest.approx(1.0)
    assert evidence["camera_position"] == [0.0, 0.0, 0.0]
    assert bounds[0][0] == pytest.approx(-1.5)
    assert bounds[1][0] == pytest.approx(1.5)
    assert bounds[0][2] == pytest.approx(0.0)


def test_uniform_scale_preserves_camera_projection_ratios(tmp_path):
    path = tmp_path / "camera-space.glb"
    mesh = trimesh.Trimesh(
        vertices=[[-4.0, -1.0, -8.0], [2.0, 1.0, -12.0], [0.0, 0.0, -16.0]],
        faces=[[0, 1, 2]],
        process=False,
    )
    mesh.export(path, file_type="glb")
    before = mesh.vertices.copy()
    evidence = scale_glb_uniformly_from_camera(path, target_depth=4.0)
    after = trimesh.load(path, force="mesh").vertices
    scale = evidence["world_scale"]
    assert scale == pytest.approx(0.25)
    assert (before[:, 0] / before[:, 2]).tolist() == pytest.approx((after[:, 0] / after[:, 2]).tolist())
    assert (before[:, 1] / before[:, 2]).tolist() == pytest.approx((after[:, 1] / after[:, 2]).tolist())
