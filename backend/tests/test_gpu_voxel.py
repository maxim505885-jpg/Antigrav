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
