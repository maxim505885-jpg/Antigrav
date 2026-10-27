"""Exact voxel-grid downsampling for derived point clouds.

CUDA is used when PyTorch and a CUDA device are available.  The NumPy fallback
uses exact integer voxel coordinates, so hash collisions cannot merge cells.
This implementation is intended for bounded derived chunks; it does not claim
that a single in-memory call can process billion-point scans.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np


def voxel_compute_backend() -> str:
    """Report which backend the next bounded voxel reduction will use."""
    try:
        import torch
    except ImportError:
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


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


def _pack_voxel_coordinates(voxel_coords: np.ndarray) -> np.ndarray | None:
    """Pack bounded integer XYZ cells into sortable, collision-free uint64 keys.

    A mixed-radix encoding preserves the same lexicographic ordering as
    ``np.unique(..., axis=0)``. Wide coordinate ranges return ``None`` so the
    caller can retain the exact tuple-based fallback.
    """
    coords = np.asarray(voxel_coords)
    if coords.ndim != 2 or coords.shape[1] != 3 or not np.issubdtype(coords.dtype, np.integer):
        raise ValueError("voxel_coords must be an integer array with shape (N, 3)")
    if len(coords) == 0:
        return np.empty(0, dtype=np.uint64)

    minima = coords.min(axis=0)
    spans = [int(coords[:, axis].max()) - int(minima[axis]) + 1 for axis in range(3)]
    key_space = spans[0] * spans[1] * spans[2]
    if key_space > 2**63:
        return None

    offsets = coords - minima
    x = offsets[:, 0].astype(np.uint64)
    y = offsets[:, 1].astype(np.uint64)
    z = offsets[:, 2].astype(np.uint64)
    return (x * np.uint64(spans[1]) + y) * np.uint64(spans[2]) + z


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
    packed = _pack_voxel_coordinates(voxel_coords)
    if packed is None:
        _, inverse, counts = np.unique(
            voxel_coords, axis=0, return_inverse=True, return_counts=True
        )
    else:
        _, inverse, counts = np.unique(packed, return_inverse=True, return_counts=True)

    # bincount uses optimized grouped accumulation and avoids Python-level
    # indexed updates for every point in large CPU fallback workloads.
    sums = np.column_stack(
        [np.bincount(inverse, weights=points[:, axis], minlength=len(counts)) for axis in range(3)]
    )
    centroids = (sums / counts[:, None]).astype(np.float32)

    mean_colors = None
    if colors is not None:
        color_sums = np.column_stack(
            [np.bincount(inverse, weights=colors[:, axis], minlength=len(counts)) for axis in range(3)]
        )
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
    if voxel_compute_backend() == "cuda":
        return _cuda_voxel_means(pts, voxel_size, cols)
    return _cpu_voxel_means(pts, voxel_size, cols)
