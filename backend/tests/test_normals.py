import numpy as np
import pytest

from scan2bim.processing.normals import estimate_normals_pca


def test_estimate_normals_horizontal_plane():
    # 100 points on horizontal plane Z = 0
    x, y = np.meshgrid(np.linspace(0, 1, 10), np.linspace(0, 1, 10))
    z = np.zeros_like(x)
    pts = np.column_stack([x.ravel(), y.ravel(), z.ravel()]).astype(np.float32)

    normals, curvature = estimate_normals_pca(pts, k_neighbors=8, viewpoint=[0.5, 0.5, 5.0])
    assert normals.shape == (100, 3)
    assert curvature.shape == (100,)

    # On flat plane, normal should be [0, 0, 1] facing viewpoint
    for n in normals:
        assert np.allclose(n, [0.0, 0.0, 1.0], atol=1e-3)
    # Curvature should be essentially zero
    assert np.all(curvature < 1e-4)


def test_estimate_normals_vertical_wall():
    # Points on vertical wall X = 2.0 (YZ plane)
    y, z = np.meshgrid(np.linspace(0, 2, 8), np.linspace(0, 2, 8))
    x = np.full_like(y, 2.0)
    pts = np.column_stack([x.ravel(), y.ravel(), z.ravel()]).astype(np.float32)

    normals, _ = estimate_normals_pca(pts, k_neighbors=6, viewpoint=[0.0, 1.0, 1.0])
    # Normal should point towards viewpoint (along -X, [-1, 0, 0])
    for n in normals:
        assert np.allclose(n, [-1.0, 0.0, 0.0], atol=1e-3)


def test_estimate_normals_empty_and_small():
    n_empty, c_empty = estimate_normals_pca(np.empty((0, 3), dtype=np.float32))
    assert len(n_empty) == 0

    n_two, c_two = estimate_normals_pca(np.array([[0, 0, 0], [1, 1, 1]], dtype=np.float32))
    assert len(n_two) == 2
