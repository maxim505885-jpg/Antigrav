"""Ingestion: read a source cloud, store an immutable copy of derived arrays.

Source files are never modified. Positions are stored as float32 relative to a
per-cloud origin (the bbox centre) to keep viewer precision; the origin is saved
in metadata and can be added back to obtain world coordinates.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .config import MAX_INGEST_POINTS, MAX_PREVIEW_POINTS
from .db import dumps, execute, one, utcnow
from .formats import read_cloud
from .storage import cloud_paths, sha256_file, write_json_atomic

PREVIEW_DTYPE = np.dtype(
    [("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")]
)


def _save_npy_atomic(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # np.save appends .npy when the suffix differs, so keep .npy at the end.
    tmp = path.with_name(path.name + ".tmp.npy")
    np.save(tmp, array)
    tmp.replace(path)


def _preview_indices(count: int, target: int) -> np.ndarray | None:
    if target <= 0 or count <= target:
        return None
    idx = np.random.default_rng(20240517).choice(count, size=target, replace=False)
    idx.sort()
    return idx


def build_preview(
    positions: np.ndarray,
    colors: np.ndarray | None,
    intensity: np.ndarray | None,
    target: int = MAX_PREVIEW_POINTS,
) -> tuple[Path, int]:
    """Write the interleaved binary preview and return (path, count)."""
    idx = _preview_indices(len(positions), target)
    pos = positions if idx is None else positions[idx]
    col = colors if idx is None else (colors[idx] if colors is not None else None)
    inten = intensity if idx is None else (intensity[idx] if intensity is not None else None)
    arr = np.empty(len(pos), dtype=PREVIEW_DTYPE)
    arr["x"] = pos[:, 0]
    arr["y"] = pos[:, 1]
    arr["z"] = pos[:, 2]
    if col is not None:
        arr["r"] = col[:, 0]
        arr["g"] = col[:, 1]
        arr["b"] = col[:, 2]
    elif inten is not None and len(inten):
        # Map intensity to a neutral grey ramp; height colouring is a viewer option.
        lo, hi = float(np.min(inten)), float(np.max(inten))
        if hi > lo:
            ramp = ((inten - lo) / (hi - lo) * 220 + 20).astype(np.uint8)
            arr["r"] = ramp
            arr["g"] = ramp
            arr["b"] = ramp
        else:
            arr["r"] = arr["g"] = arr["b"] = 180
    else:
        arr["r"] = arr["g"] = arr["b"] = 0
    return arr, len(pos)


def ingest_cloud(
    project_id: str,
    cloud_id: str,
    source_path: Path,
    progress=None,
) -> dict[str, Any]:
    if progress:
        progress(0.01, "opening source file")
    raw = read_cloud(source_path, max_points=MAX_INGEST_POINTS, progress=progress)
    if len(raw.xyz) == 0:
        raise ValueError("point cloud contains no points")

    if progress:
        progress(0.88, "computing bounds and preview")
    bbox_min = raw.xyz.min(axis=0)
    bbox_max = raw.xyz.max(axis=0)
    origin = (bbox_min + bbox_max) / 2.0
    local = (raw.xyz - origin).astype(np.float32)
    colors = raw.rgb.astype(np.uint8, copy=False) if raw.rgb is not None else None
    intensity = raw.intensity.astype(np.float32, copy=False) if raw.intensity is not None else None

    paths = cloud_paths(project_id, cloud_id)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    _save_npy_atomic(paths["positions"], local)
    if colors is not None:
        _save_npy_atomic(paths["colors"], colors)
    if intensity is not None:
        _save_npy_atomic(paths["intensity"], intensity)

    preview_arr, preview_count = build_preview(local, colors, intensity)
    tmp_preview = paths["preview"].with_suffix(".bin.tmp")
    preview_arr.tofile(tmp_preview)
    tmp_preview.replace(paths["preview"])

    source_count = int(raw.metadata.get("source_point_count") or len(raw.xyz))
    decimated = bool(raw.metadata.get("decimated") or len(local) < source_count)
    warning = None
    if decimated:
        warning = (
            f"Source has ~{source_count:,} points; {len(local):,} were ingested for this "
            f"project (S2B_MAX_INGEST_POINTS={MAX_INGEST_POINTS:,}). Increase the limit or "
            "convert to LAS/E57 for full-resolution work."
        )

    checksum = None
    try:
        if source_path.stat().st_size <= 2 * 1024 * 1024 * 1024:
            checksum = sha256_file(source_path)
    except Exception:
        checksum = None

    metadata = {
        **{k: v for k, v in raw.metadata.items() if k not in {"has_color", "has_intensity"}},
        "origin": [float(x) for x in origin],
        "bbox_min": [float(x) for x in bbox_min],
        "bbox_max": [float(x) for x in bbox_max],
        "preview_count": preview_count,
        "preview_stride_bytes": PREVIEW_DTYPE.itemsize,
        "stored_point_count": int(len(local)),
        "source_point_count": source_count,
        "decimated": decimated,
        "warning": warning,
        "has_color": colors is not None,
        "has_intensity": intensity is not None,
        "crash_safe": True,
        "source_unchanged": True,
        "checksum_sha256": checksum,
    }
    write_json_atomic(paths["meta"], metadata)

    now = utcnow()
    execute(
        """
        UPDATE clouds SET
            point_count = ?, ingested_count = ?, decimated = ?, size_bytes = ?, sha256 = ?,
            origin_x = ?, origin_y = ?, origin_z = ?,
            bbox_min_x = ?, bbox_min_y = ?, bbox_min_z = ?,
            bbox_max_x = ?, bbox_max_y = ?, bbox_max_z = ?,
            has_color = ?, has_intensity = ?, status = 'ready', error = NULL,
            metadata_json = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            source_count,
            int(len(local)),
            1 if decimated else 0,
            int(source_path.stat().st_size),
            checksum,
            *[float(x) for x in origin],
            *[float(x) for x in bbox_min],
            *[float(x) for x in bbox_max],
            1 if colors is not None else 0,
            1 if intensity is not None else 0,
            dumps(metadata),
            now,
            cloud_id,
        ),
    )
    if progress:
        progress(1.0, "cloud ready")
    return {
        "cloud_id": cloud_id,
        "point_count": source_count,
        "ingested_count": int(len(local)),
        "preview_count": preview_count,
        "decimated": decimated,
        "warning": warning,
    }


def cloud_meta(cloud_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM clouds WHERE id = ?", (cloud_id,))
    if not row:
        raise KeyError(cloud_id)
    try:
        return json.loads(row.get("metadata_json") or "{}")
    except Exception:
        return {}
