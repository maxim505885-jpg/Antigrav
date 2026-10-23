import numpy as np
import pytest

from scan2bim.processing.gpu_voxel import voxel_downsample_accelerated


def test_voxel_downsample_accelerated_reduces_density():
    # 10,000 points uniformly distributed in [0, 1] cube
    rng = np.random.default_rng(42)
    pts = rng.uniform(0.0, 1.0, size=(10000, 3)).astype(np.float32)
    cols = rng.integers(0, 255, size=(10000, 3), dtype=np.uint8)

    # Voxel size 0.1m -> 10x10x10 = 1000 voxels max
    down_pts, down_cols = voxel_downsample_accelerated(pts, voxel_size_m=0.1, colors=cols)

    assert len(down_pts) <= 1000
    assert len(down_pts) > 500
    assert len(down_cols) == len(down_pts)
    assert down_pts.dtype == np.float32
    assert down_cols.dtype == np.uint8


def test_voxel_downsample_accelerated_preserves_single_point():
    single = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
    down_pts, _ = voxel_downsample_accelerated(single, voxel_size_m=0.05)
    assert len(down_pts) == 1
    assert np.allclose(down_pts[0], [1.0, 2.0, 3.0])


def test_voxel_downsample_returns_voxel_centroids_and_mean_colors():
    points = np.array([
        [0.01, 0.01, 0.01], [0.03, 0.03, 0.03],
        [0.11, 0.01, 0.01], [0.13, 0.03, 0.03],
    ], dtype=np.float32)
    colors = np.array([[10, 20, 30], [30, 40, 50], [100, 110, 120], [120, 130, 140]], dtype=np.uint8)

    down_points, down_colors = voxel_downsample_accelerated(points, voxel_size_m=0.1, colors=colors)

    assert np.allclose(down_points, [[0.02, 0.02, 0.02], [0.12, 0.02, 0.02]])
    assert np.array_equal(down_colors, [[20, 30, 40], [110, 120, 130]])


def test_voxel_downsample_rejects_mismatched_colors_and_non_finite_points():
    with pytest.raises(ValueError, match="colors"):
        voxel_downsample_accelerated(np.zeros((3, 3), dtype=np.float32), colors=np.zeros((2, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="finite"):
        voxel_downsample_accelerated(np.array([[0.0, 0.0, 0.0], [np.nan, 0.0, 0.0]], dtype=np.float32))


@pytest.mark.parametrize("voxel_size", [0.0, -0.1, float("nan"), float("inf")])
def test_voxel_downsample_rejects_invalid_voxel_size(voxel_size):
    with pytest.raises(ValueError, match="finite positive"):
        voxel_downsample_accelerated(np.zeros((3, 3), dtype=np.float32), voxel_size_m=voxel_size)
