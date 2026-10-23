"""Exact voxel-grid downsampling for derived point clouds.

CUDA is used when PyTorch and a CUDA device are available.  The NumPy fallback
uses exact integer voxel coordinates, so hash collisions cannot merge cells.
This implementation is intended for bounded derived chunks; it does not claim
that a single in-memory call can process billion-point scans.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np


def _validate_inputs(
    points: np.ndarray, voxel_size_m: float, colors: np.ndarray | None
) -> tuple[np.ndarray, float, np.ndarray | None]:
    pts = np.asarray(points)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError("points must have shape (N, 3)")
    if not np.issubdtype(pts.dtype, np.number):
        raise ValueError("points must be numeric")
    pts = np.asarray(pts, dtype=np.float64)
    if not np.isfinite(pts).all():
        raise ValueError("points must contain only finite coordinates")

    try:
        voxel_size = float(voxel_size_m)
    except (TypeError, ValueError) as exc:
        raise ValueError("voxel_size_m must be finite positive") from exc
    if not np.isfinite(voxel_size) or voxel_size <= 0:
        raise ValueError("voxel_size_m must be finite positive")
    scaled = np.floor(pts / voxel_size)
    if not np.isfinite(scaled).all() or np.any(scaled < -(2**63)) or np.any(scaled >= 2**63):
        raise ValueError("point coordinates exceed supported voxel index range")

    cols = None
    if colors is not None:
        cols = np.asarray(colors)
        if cols.ndim != 2 or cols.shape != (len(pts), 3):
            raise ValueError("colors must have shape (N, 3) matching points")
        if not np.issubdtype(cols.dtype, np.number) or not np.isfinite(cols).all():
            raise ValueError("colors must contain finite numeric values")
    return pts, voxel_size, cols


def _cpu_voxel_means(
    points: np.ndarray, voxel_size: float, colors: np.ndarray | None
) -> tuple[np.ndarray, np.ndarray | None]:
    if len(points) == 0:
        empty_points = np.empty((0, 3), dtype=np.float32)
        empty_colors = None if colors is None else np.empty((0, 3), dtype=np.uint8)
        return empty_points, empty_colors

    # Anchor the grid at the project origin so separate chunks assign points to
    # the same voxel. float64 keeps millimetre precision for normal site scales.
    scaled = np.floor(points / voxel_size)
    voxel_coords = scaled.astype(np.int64)
    _, inverse, counts = np.unique(
        voxel_coords, axis=0, return_inverse=True, return_counts=True
    )

    sums = np.zeros((len(counts), 3), dtype=np.float64)
    np.add.at(sums, inverse, points)
    centroids = (sums / counts[:, None]).astype(np.float32)

    mean_colors = None
    if colors is not None:
        color_sums = np.zeros((len(counts), 3), dtype=np.float64)
        np.add.at(color_sums, inverse, colors)
        mean_colors = np.rint(color_sums / counts[:, None]).clip(0, 255).astype(np.uint8)
    return centroids, mean_colors


def _cuda_voxel_means(
    points: np.ndarray, voxel_size: float, colors: np.ndarray | None
) -> tuple[np.ndarray, np.ndarray | None]:
    import torch

    device = torch.device("cuda")
    pts = torch.as_tensor(points, dtype=torch.float64, device=device)
    if len(points) == 0:
        empty_points = np.empty((0, 3), dtype=np.float32)
        empty_colors = None if colors is None else np.empty((0, 3), dtype=np.uint8)
        return empty_points, empty_colors

    coords = torch.floor(pts / voxel_size).to(torch.int64)
    _, inverse, counts = torch.unique(
        coords, dim=0, sorted=True, return_inverse=True, return_counts=True
    )
    sums = torch.zeros((len(counts), 3), dtype=torch.float64, device=device)
    sums.index_add_(0, inverse, pts)
    centroids = (sums / counts[:, None]).to(torch.float32).cpu().numpy()

    mean_colors = None
    if colors is not None:
        color_tensor = torch.as_tensor(colors, dtype=torch.float64, device=device)
        color_sums = torch.zeros((len(counts), 3), dtype=torch.float64, device=device)
        color_sums.index_add_(0, inverse, color_tensor)
        mean_colors = (
            torch.round(color_sums / counts[:, None])
            .clamp(0, 255)
            .to(torch.uint8)
            .cpu()
            .numpy()
        )
    return centroids, mean_colors


def voxel_downsample_accelerated(
    points: np.ndarray,
    voxel_size_m: float = 0.05,
    colors: np.ndarray | None = None,
) -> Tuple[np.ndarray, np.ndarray | None]:
    """Replace each occupied voxel with its point and color means.

    The output contains one float32 centroid per exact voxel coordinate and,
    when colors are supplied, one rounded uint8 RGB mean per voxel.
    """
    pts, voxel_size, cols = _validate_inputs(points, voxel_size_m, colors)
    if len(pts) == 0:
        return _cpu_voxel_means(pts, voxel_size, cols)

    # Import or device discovery may fail on machines without PyTorch/CUDA. A
    # CUDA execution failure is allowed to surface; silently retrying an OOM on
    # CPU can exhaust workstation memory and hide a broken GPU path.
    try:
        import torch
    except ImportError:
        torch = None
    if torch is not None and torch.cuda.is_available():
        return _cuda_voxel_means(pts, voxel_size, cols)
    return _cpu_voxel_means(pts, voxel_size, cols)
