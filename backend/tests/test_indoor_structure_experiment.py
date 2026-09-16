import numpy as np

from scripts.indoor_structure_experiment import _axis_aligned_plane, _exclude_normalized_boxes, _intersect_planes_at_z, _line_guided_masks, _normalized_box_mask, _perspective_candidate_masks, _projective_uv, _room_envelope, _support_overlay, fit_plane, ransac_plane
from PIL import Image


def test_fit_plane_returns_finite_candidate():
    x, y = np.meshgrid(np.linspace(-1, 1, 8), np.linspace(-2, 2, 8))
    points = np.stack([x, 0.5 * x + 0.2, y], axis=-1)
    result = fit_plane(points)
    assert result["point_count"] == 64
    assert np.isfinite(result["normal"]).all()
    assert np.isfinite(result["distance"])
    assert result["residual_p95"] < 1e-10


def test_fit_plane_rejects_nonfinite_short_input():
    try:
        fit_plane(np.array([[0, 0, 0], [np.nan, 0, 0]]))
    except ValueError as error:
        assert "finite" in str(error)
    else:
        raise AssertionError("expected a finite-point validation error")


def test_ransac_plane_keeps_dominant_plane_and_reports_policy():
    x, z = np.meshgrid(np.linspace(-2, 2, 30), np.linspace(-3, 3, 30))
    plane = np.stack([x, np.full_like(x, 0.25), z], axis=-1).reshape(-1, 3)
    outliers = np.array([[7.0, 4.0, -2.0], [-5.0, -3.0, 8.0], [2.0, 6.0, 6.0]])
    result, inliers = ransac_plane(np.concatenate([plane, outliers]), threshold=0.05)
    assert result["inlier_count"] >= 890
    assert result["inlier_ratio"] > 0.98
    assert result["inlier_threshold"] == 0.05
    assert np.asarray(inliers).shape[1] == 3


def test_plane_intersection_is_finite_and_room_envelope_closes_edges():
    floor = {"normal": [0.0, 1.0, 0.0], "distance": -1.0}
    ceiling = {"normal": [0.0, 1.0, 0.0], "distance": 1.0}
    left = {"normal": [1.0, 0.0, 0.0], "distance": 1.5}
    right = {"normal": [1.0, 0.0, 0.0], "distance": -1.5}
    assert np.allclose(_intersect_planes_at_z(floor, left, -2.0), [-1.5, -1.0, -2.0])
    candidates = {
        name: {"status": "candidate_only", "normal": plane["normal"], "distance": plane["distance"]}
        for name, plane in {
            "floor_candidate": floor,
            "ceiling_candidate": ceiling,
            "left_wall_candidate": left,
            "right_wall_candidate": right,
        }.items()
    }
    clouds = {
        "floor_candidate": np.array([[-1.5, -1.0, -1.0], [1.5, -1.0, -1.0], [-1.5, -1.0, -3.0], [1.5, -1.0, -3.0]]),
        "ceiling_candidate": np.array([[-1.5, 1.0, -1.0], [1.5, 1.0, -1.0], [-1.5, 1.0, -3.0], [1.5, 1.0, -3.0]]),
        "left_wall_candidate": np.array([[-1.5, -1.0, -1.0], [-1.5, 1.0, -1.0], [-1.5, -1.0, -3.0], [-1.5, 1.0, -3.0]]),
        "right_wall_candidate": np.array([[1.5, -1.0, -1.0], [1.5, 1.0, -1.0], [1.5, -1.0, -3.0], [1.5, 1.0, -3.0]]),
    }
    meshes, envelope = _room_envelope(candidates, clouds, Image.new("RGB", (8, 8), "white"), camera_clearance_z=4.0)
    assert envelope["status"] == "candidate_only"
    assert len(meshes) == 5
    assert np.isfinite(np.concatenate([mesh.vertices for mesh in meshes])).all()
    assert meshes[0].visual.material._data["doubleSided"] is True
    assert envelope["camera_clearance_z"] == 4.0
    assert max(mesh.bounds[1, 2] for mesh in meshes) == 4.0


def test_projective_uv_matches_source_camera_projection():
    intrinsics = np.array([[0.5, 0.0, 0.5], [0.0, 0.5, 0.5], [0.0, 0.0, 1.0]])
    viewer_vertices = np.array([[0.0, 0.0, -2.0], [1.0, 0.0, -2.0], [1.0, 1.0, -2.0], [0.0, 1.0, -2.0]])
    uv = _projective_uv(viewer_vertices, intrinsics)
    assert uv is not None
    assert np.allclose(uv, [[0.5, 0.5], [0.75, 0.5], [0.75, 0.75], [0.5, 0.75]])


def test_axis_aligned_plane_removes_unsupported_depth_tilt():
    points = np.array([
        [-1.2, -1.0, -1.0], [-1.2, -1.0, -3.0],
        [-1.2, 1.0, -1.0], [-1.2, 1.0, -3.0],
    ])
    free = {"normal": [-0.94, 0.0, -0.34], "distance": -0.8, "residual_median": 0.0, "residual_p95": 0.0}
    constrained = _axis_aligned_plane("left_wall_candidate", free, points)
    assert constrained["normal"] == [-1.0, 0.0, 0.0]
    assert constrained["distance"] == -1.2
    assert constrained["axis_constraint"] == "level_horizontal_and_vertical_walls"


def test_semantic_exclusion_removes_full_box_conservatively():
    mask = np.ones((10, 20), dtype=bool)
    filtered, removed = _exclude_normalized_boxes(mask, [{"x_min": 0.25, "y_min": 0.2, "x_max": 0.5, "y_max": 0.6}])
    assert removed == 20
    assert not filtered[2:6, 5:10].any()
    assert filtered[0, 0]


def test_line_guidance_is_sparse_and_reports_assignments():
    lines = [
        np.array([10.0, 90.0, 90.0, 10.0]),
        np.array([90.0, 90.0, 170.0, 10.0]),
        np.array([5.0, 10.0, 5.0, 90.0]),
        np.array([195.0, 10.0, 195.0, 90.0]),
    ]
    masks, diagnostics = _line_guided_masks(lines, 100, 200)

    assert set(masks) == {"ceiling_candidate", "floor_candidate", "left_wall_candidate", "right_wall_candidate"}
    assert diagnostics["policy"].startswith("only line-supported")
    assert diagnostics["line_assignments"]["left_wall_candidate"] >= 1
    assert diagnostics["line_assignments"]["right_wall_candidate"] >= 1
    assert sum(int(mask.sum()) for mask in masks.values()) < 100 * 200


def test_support_overlay_distinguishes_selected_and_inlier_pixels():
    image = np.full((20, 30, 3), 100, dtype=np.uint8)
    selected = np.zeros((20, 30), dtype=bool)
    selected[5:10, 5:10] = True
    inliers = np.zeros((20, 30), dtype=bool)
    inliers[7:9, 7:9] = True
    selected_masks = {"floor_candidate": selected}
    inlier_masks = {"floor_candidate": inliers}
    candidates = {"floor_candidate": {"status": "candidate_only"}}
    result = _support_overlay(image, selected_masks, inlier_masks, candidates)
    assert result.shape == image.shape
    assert not np.array_equal(result[6, 6], image[6, 6])
    assert np.array_equal(result[7, 7], np.array([40, 210, 40], dtype=np.uint8))


def test_perspective_candidate_regions_include_converging_corridor_walls():
    regions = _perspective_candidate_masks(100, 200, [100.0, 45.0])
    assert regions["left_wall_candidate"][50, 80]
    assert regions["right_wall_candidate"][50, 120]
    assert regions["floor_candidate"][60, 100]
    assert regions["ceiling_candidate"][20, 100]


def test_normalized_box_mask_is_a_positive_prior_not_a_full_image_mask():
    mask = _normalized_box_mask(10, 20, [{"x_min": 0.25, "y_min": 0.2, "x_max": 0.5, "y_max": 0.6}])
    assert int(mask.sum()) == 20
    assert mask[2, 5]
    assert not mask[0, 0]
