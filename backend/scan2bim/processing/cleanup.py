"""Non-destructive point-cloud cleanup.

Filters are pure over arrays and return masks or index arrays; the source
``positions.npy`` is never rewritten. ``apply_cleanup`` writes a *derived*
cloud (positions + colours + meta) into a separate directory, so every result
can be traced back to the input and the original scan stays byte-identical.

The cKDTree-based filters are bounded by ``MAX_CLEANUP_POINTS``: beyond that a
tree plus queries no longer fit a desktop's memory honestly, and the API says
so instead of silently decimating or crashing.
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy.spatial import cKDTree

MAX_CLEANUP_POINTS = 5_000_000
QUERY_CHUNK = 500_000
Progress = Callable[[float, str], None] | None

METHODS = ("statistical", "radius", "voxel")


class CleanupError(ValueError):
    """Cleanup cannot be performed with the requested parameters."""


def _notify(progress: Progress, value: float, message: str) -> None:
    if progress:
        progress(float(value), message)


def _check_points(points: np.ndarray) -> np.ndarray:
    arr = np.asarray(points)
    if arr.ndim != 2 or arr.shape[1] != 3:
        raise CleanupError("points must have shape (N, 3)")
    if len(arr) > MAX_CLEANUP_POINTS:
        raise CleanupError(
            f"облако содержит {len(arr):,} точек; очистка ограничена "
            f"{MAX_CLEANUP_POINTS:,} точками на этом компьютере"
        )
    return arr


def statistical_outlier_mask(
    points: np.ndarray, k: int = 16, std_ratio: float = 2.0, progress: Progress = None
) -> tuple[np.ndarray, dict[str, Any]]:
    """Keep points whose mean distance to k neighbours is below mean+std_ratio*std."""
    arr = _check_points(points)
    n = len(arr)
    if n < 3:
        return np.ones(n, dtype=bool), {"k": 0, "reason": "fewer than 3 points"}
    k = int(max(1, min(int(k), n - 1)))
    std_ratio = float(max(0.1, std_ratio))
    tree = cKDTree(arr)
    means = np.empty(n, dtype=np.float64)
    for start in range(0, n, QUERY_CHUNK):
        end = min(n, start + QUERY_CHUNK)
        distances, _ = tree.query(arr[start:end], k=k + 1, workers=-1)
        means[start:end] = distances[:, 1:].mean(axis=1)
        _notify(progress, 0.6 * end / n, "статистический фильтр: расстояния до соседей")
    mean = float(means.mean())
    std = float(means.std())
    threshold = mean + std_ratio * std
    keep = means <= threshold
    return keep, {
        "k": k,
        "std_ratio": round(std_ratio, 3),
        "mean_distance_m": round(mean, 6),
        "std_distance_m": round(std, 6),
        "threshold_m": round(threshold, 6),
        "removed": int((~keep).sum()),
    }


def radius_outlier_mask(
    points: np.ndarray, radius: float = 0.05, min_neighbors: int = 4, progress: Progress = None
) -> tuple[np.ndarray, dict[str, Any]]:
    """Keep points with at least ``min_neighbors`` other points within ``radius``."""
    arr = _check_points(points)
    n = len(arr)
    radius = float(radius)
    if not math.isfinite(radius) or radius <= 0:
        raise CleanupError("radius_m must be a positive number")
    min_neighbors = int(max(1, min_neighbors))
    if n <= min_neighbors:
        return np.ones(n, dtype=bool), {"radius_m": radius, "min_neighbors": min_neighbors}
    tree = cKDTree(arr)
    counts = np.empty(n, dtype=np.int32)
    for start in range(0, n, QUERY_CHUNK):
        end = min(n, start + QUERY_CHUNK)
        counts[start:end] = tree.query_ball_point(
            arr[start:end], radius, workers=-1, return_length=True
        )
        _notify(progress, 0.7 * end / n, "радиусный фильтр: соседи в радиусе")
    # query_ball_point counts the point itself (distance 0), so a point needs
    # min_neighbors + 1 hits to have min_neighbors *other* neighbours.
    keep = counts >= min_neighbors + 1
    return keep, {
        "radius_m": radius,
        "min_neighbors": min_neighbors,
        "removed": int((~keep).sum()),
    }


def voxel_downsample_indices(
    points: np.ndarray, voxel_m: float, progress: Progress = None
) -> tuple[np.ndarray, dict[str, Any]]:
    """Keep one representative point per occupied voxel; return sorted indices."""
    arr = _check_points(points)
    voxel_m = float(voxel_m)
    if not math.isfinite(voxel_m) or voxel_m <= 0:
        raise CleanupError("voxel_m must be a positive number")
    if len(arr) == 0:
        return np.empty(0, dtype=np.int64), {"voxel_m": voxel_m, "voxels": 0}
    origin = arr.min(axis=0)
    keys = np.floor((arr - origin) / voxel_m).astype(np.int64)
    _notify(progress, 0.3, "воксельная сетка")
    _, first = np.unique(keys, axis=0, return_index=True)
    indices = np.sort(first.astype(np.int64))
    _notify(progress, 0.9, "представители вокселей")
    return indices, {
        "voxel_m": voxel_m,
        "voxels": int(len(indices)),
        "origin_m": [round(float(v), 4) for v in origin],
    }


def _read_colors(path: Path | None, count: int) -> np.ndarray | None:
    if path is None or not path.is_file():
        return None
    colors = np.load(path, mmap_mode="r")
    if len(colors) != count:
        return None
    return colors


def write_ply(positions: np.ndarray, colors: np.ndarray | None, out_path: Path) -> Path:
    """Write a binary little-endian PLY (x,y,z float32, optional RGB uchar)."""
    positions = np.asarray(positions, dtype=np.float32)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [("x", "<f4"), ("y", "<f4"), ("z", "<f4")]
    with_color = colors is not None and len(colors) == len(positions)
    if with_color:
        fields += [("red", "u1"), ("green", "u1"), ("blue", "u1")]
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {len(positions)}"]
    header += ["property float x", "property float y", "property float z"]
    if with_color:
        header += ["property uchar red", "property uchar green", "property uchar blue"]
    header += ["end_header", ""]
    data = np.empty(len(positions), dtype=fields)
    data["x"], data["y"], data["z"] = positions[:, 0], positions[:, 1], positions[:, 2]
    if with_color:
        rgb = np.asarray(colors)
        if rgb.dtype != np.uint8:
            if rgb.max() <= 1.0:
                rgb = rgb * 255.0
            rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        data["red"], data["green"], data["blue"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    with out_path.open("wb") as fh:
        fh.write(("\n".join(header)).encode("ascii"))
        data.tofile(fh)
    return out_path


def write_xyz(positions: np.ndarray, out_path: Path) -> Path:
    positions = np.asarray(positions, dtype=np.float64)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="ascii", newline="\n") as fh:
        for start in range(0, len(positions), QUERY_CHUNK):
            np.savetxt(fh, positions[start : start + QUERY_CHUNK], fmt="%.4f")
    return out_path


def apply_cleanup(
    positions_path: Path,
    derived_dir: Path,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    colors_path: Path | None = None,
    progress: Progress = None,
) -> dict[str, Any]:
    """Filter a cloud and write a derived artefact next to (not over) the source."""
    method = str(method)
    if method not in METHODS:
        raise CleanupError(f"unknown cleanup method: {method}")
    params = dict(params or {})
    started = time.perf_counter()

    positions = np.load(positions_path, mmap_mode="r")
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise CleanupError("source positions must have shape (N, 3)")
    total = int(positions.shape[0])
    if total > MAX_CLEANUP_POINTS:
        raise CleanupError(
            f"облако содержит {total:,} точек; очистка ограничена "
            f"{MAX_CLEANUP_POINTS:,} точками на этом компьютере"
        )
    points = np.asarray(positions, dtype=np.float32)
    finite = np.isfinite(points).all(axis=1)
    finite_indices = np.nonzero(finite)[0]
    finite_points = points[finite]
    _notify(progress, 0.15, "проверка координат")

    stats: dict[str, Any]
    if method == "statistical":
        keep, stats = statistical_outlier_mask(
            finite_points,
            k=int(params.get("k", 16)),
            std_ratio=float(params.get("std_ratio", 2.0)),
            progress=progress,
        )
        indices = finite_indices[keep]
    elif method == "radius":
        keep, stats = radius_outlier_mask(
            finite_points,
            radius=float(params.get("radius_m", 0.05)),
            min_neighbors=int(params.get("min_neighbors", 4)),
            progress=progress,
        )
        indices = finite_indices[keep]
    else:
        local, stats = voxel_downsample_indices(
            finite_points, float(params.get("voxel_m", 0.05)), progress=progress
        )
        indices = finite_indices[local]

    _notify(progress, 0.9, "запись производного облака")
    derived_dir.mkdir(parents=True, exist_ok=True)
    derived_positions = np.asarray(points[indices], dtype=np.float32)
    np.save(derived_dir / "positions.npy", derived_positions)
    colors = _read_colors(colors_path, total)
    color_written = False
    if colors is not None:
        rgb = np.asarray(colors)
        if rgb.dtype != np.uint8:
            if rgb.max() <= 1.0:
                rgb = rgb * 255.0
            rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        np.save(derived_dir / "colors.npy", rgb[indices])
        color_written = True

    meta = {
        "method": method,
        "params": params,
        "stats": stats,
        "input_count": total,
        "finite_count": int(len(finite_indices)),
        "output_count": int(len(indices)),
        "removed_count": int(total - len(indices)),
        "has_colors": color_written,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_s": round(time.perf_counter() - started, 2),
        "source": {
            "positions_file": positions_path.name,
            "source_unchanged": True,
        },
        "confidence_kind": "measured geometry, parameters chosen by the user",
    }
    (derived_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _notify(progress, 1.0, "готова очищенная копия")
    return meta
