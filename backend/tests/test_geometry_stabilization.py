import numpy as np

from app.services.geometry import _filter_extreme_faces, _stabilize_depth_points


def test_depth_stabilizer_limits_isolated_spike_along_original_ray():
    depth = np.ones((5, 5), dtype=np.float32)
    depth[2, 2] = 100.0
    points = np.zeros((5, 5, 3), dtype=np.float32)
    points[..., 2] = -depth
    stabilized, stable_depth = _stabilize_depth_points(points, depth)

    assert stable_depth[2, 2] < 100.0
    assert abs(float(stabilized[2, 2, 2])) < 100.0
    # The operation scales the point along its ray; it must not invent x/y
    # displacement for a purely forward-facing synthetic point.
    assert stabilized[2, 2, 0] == 0.0
    assert stabilized[2, 2, 1] == 0.0


def test_depth_stabilizer_leaves_invalid_pixels_invalid():
    depth = np.ones((3, 3), dtype=np.float32)
    depth[0, 0] = np.nan
    points = np.zeros((3, 3, 3), dtype=np.float32)
    points[..., 2] = -np.nan_to_num(depth, nan=0.0)
    stabilized, stable_depth = _stabilize_depth_points(points, depth)
    assert np.isnan(stable_depth[0, 0])
    assert np.isfinite(stabilized[1:, 1:]).all()


def test_extreme_face_filter_removes_long_ribbon_but_keeps_regular_faces():
    vertices = np.array(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [20, 0, 0]],
        dtype=np.float32,
    )
    faces = np.array([[0, 1, 2], [1, 3, 2], [0, 4, 2]], dtype=np.int64)
    filtered, removed = _filter_extreme_faces(vertices, faces, factor=5.0)
    assert removed == 1
    assert filtered.shape == (2, 3)
