"""Memory-bounded CPU surface normal and curvature estimation by local PCA.

Normals are oriented toward an explicitly supplied scanner viewpoint. If the
viewpoint is unknown, a deterministic sign convention is used; this makes the
vectors repeatable but does not claim inside/outside orientation.
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree


def _positive_int(value: int, name: str, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be an integer >= {minimum}") from exc
    if isinstance(value, bool) or parsed != value or parsed < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return parsed


def estimate_normals_pca(
    points: np.ndarray,
    k_neighbors: int = 16,
    viewpoint: np.ndarray | None = None,
    batch_size: int = 50000,
) -> tuple[np.ndarray, np.ndarray]:
    """Estimate unit normals and surface-variation curvature for an N x 3 cloud.

    Neighborhoods without two independent tangent directions return a zero
    normal because a line or coincident points do not define a surface normal.
    Curvature is ``lambda_min / sum(lambda)`` for valid neighborhoods and zero
    for degenerate ones.
    """
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError("points must be an N x 3 array")
    if not np.all(np.isfinite(pts)):
        raise ValueError("points must contain only finite coordinates")

    k_neighbors = _positive_int(k_neighbors, "k_neighbors", minimum=3)
    batch_size = _positive_int(batch_size, "batch_size")
    if viewpoint is not None:
        viewpoint = np.asarray(viewpoint, dtype=np.float64)
        if viewpoint.shape != (3,) or not np.all(np.isfinite(viewpoint)):
            raise ValueError("viewpoint must be a finite XYZ vector")

    n_points = len(pts)
    normals = np.zeros((n_points, 3), dtype=np.float32)
    curvature = np.zeros(n_points, dtype=np.float32)
    if n_points < 3:
        return normals, curvature

    k = min(k_neighbors, n_points)
    tree = cKDTree(pts)
    for start in range(0, n_points, batch_size):
        end = min(start + batch_size, n_points)
        batch_pts = pts[start:end]
        _, indices = tree.query(batch_pts, k=k)
        neighbors = pts[np.asarray(indices).reshape(end - start, k)]
        centered = neighbors - np.mean(neighbors, axis=1, keepdims=True)
        covariance = np.matmul(centered.swapaxes(1, 2), centered) / float(k)
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)

        total = np.sum(eigenvalues, axis=1)
        # A surface has two supported tangent directions. A line has only one,
        # so its smallest-eigenvector direction must not be presented as normal.
        valid = (total > 1e-18) & (eigenvalues[:, 1] > np.maximum(1e-18, eigenvalues[:, 2] * 1e-10))
        batch_normals = eigenvectors[:, :, 0]
        if viewpoint is None:
            dominant = np.argmax(np.abs(batch_normals), axis=1)
            sign_component = batch_normals[np.arange(len(batch_normals)), dominant]
            flip = sign_component < 0
        else:
            flip = np.sum(batch_normals * (viewpoint - batch_pts), axis=1) < 0
        batch_normals[flip] *= -1.0
        batch_normals[~valid] = 0.0

        batch_curvature = np.zeros(end - start, dtype=np.float64)
        np.divide(eigenvalues[:, 0], total, out=batch_curvature, where=valid)
        normals[start:end] = batch_normals.astype(np.float32)
        curvature[start:end] = batch_curvature.astype(np.float32)

    return normals, curvature
