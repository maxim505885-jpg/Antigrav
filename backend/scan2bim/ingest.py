"""Ingestion: read a source cloud, store an immutable copy of derived arrays.

Source files are never modified. Positions are stored as float32 relative to a
per-cloud origin (the bbox centre) to keep viewer precision; the origin is saved
in metadata and can be added back to obtain world coordinates.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from typing import Any

import numpy as np

from .config import MAX_INGEST_POINTS, MAX_PREVIEW_POINTS
from .db import dumps, execute, one, utcnow
from .formats import read_cloud
from .formats.rcs_native import extract_rcs_native, native_available
from .storage import cloud_paths, sha256_file, write_json_atomic

PREVIEW_DTYPE = np.dtype(
    [("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")]
)
INGEST_CHECKPOINT_VERSION = 1
MIN_INGEST_DISK_RESERVE_BYTES = int(os.environ.get("S2B_INGEST_DISK_RESERVE_BYTES", str(1024**3)))


class CheckpointSourceChanged(ValueError):
    """The source no longer matches the source for a complete ingest checkpoint."""


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


def _source_identity(path: Path) -> dict[str, Any]:
    resolved = str(path.resolve())
    try:
        stat = path.stat()
    except OSError:
        return {"path": resolved, "missing": True}
    return {"path": resolved, "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _file_record(path: Path) -> dict[str, Any]:
    return {"size_bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _record_matches(path: Path, record: dict[str, Any]) -> bool:
    try:
        return path.is_file() and path.stat().st_size == record["size_bytes"] and sha256_file(path) == record["sha256"]
    except (OSError, KeyError, TypeError):
        return False


def _load_checkpoint(stage_dir: Path, paths: dict[str, Path], source_path: Path, cloud_id: str) -> dict[str, Any] | None:
    manifest_path = stage_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("version") != INGEST_CHECKPOINT_VERSION or manifest.get("cloud_id") != cloud_id:
            return None
        identity = manifest["source_identity"]
        if identity.get("path") != str(source_path.resolve()):
            raise CheckpointSourceChanged("source changed since ingest checkpoint: source path differs")
        current_identity = _source_identity(source_path)
        # Once a complete, checksummed derived package exists, finalization no
        # longer depends on the source still being present. If it is present,
        # however, its recorded identity must still match.
        if not current_identity.get("missing") and current_identity != identity:
            raise CheckpointSourceChanged("source changed since ingest checkpoint: file identity differs")
        records = manifest["files"]
        for key, record in records.items():
            if key not in {"positions", "colors", "intensity", "preview", "meta"}:
                return None
            staged = stage_dir / record["name"]
            final = paths[key]
            if not (_record_matches(staged, record) or _record_matches(final, record)):
                return None
        if not {"positions", "preview", "meta"} <= set(records):
            return None
        return manifest
    except CheckpointSourceChanged:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _discard_incomplete_stage(
    stage_dir: Path, paths: dict[str, Path], *, preserve_raw_stream: bool = False
) -> None:
    if preserve_raw_stream and (stage_dir / "raw").is_dir():
        for child in stage_dir.iterdir():
            if child.name == "raw":
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
    else:
        shutil.rmtree(stage_dir, ignore_errors=True)
    # These paths are exclusively derived outputs for this cloud. A source
    # upload lives in the separate `source/` directory and is never removed.
    for key in ("positions", "colors", "intensity", "preview", "meta"):
        paths[key].unlink(missing_ok=True)


def _finalize_checkpoint(
    project_id: str,
    cloud_id: str,
    paths: dict[str, Path],
    stage_dir: Path,
    manifest: dict[str, Any],
    progress=None,
) -> dict[str, Any]:
    if progress:
        progress(0.98, "checkpoint ready; finalizing")
    for key, record in manifest["files"].items():
        staged = stage_dir / record["name"]
        destination = paths[key]
        if _record_matches(destination, record):
            continue
        if not _record_matches(staged, record):
            raise RuntimeError(f"ingest checkpoint file is missing or corrupt: {record['name']}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, destination)

    cloud = manifest["cloud"]
    now = utcnow()
    execute(
        """UPDATE clouds SET
            point_count = ?, ingested_count = ?, decimated = ?, size_bytes = ?, sha256 = ?,
            origin_x = ?, origin_y = ?, origin_z = ?,
            bbox_min_x = ?, bbox_min_y = ?, bbox_min_z = ?,
            bbox_max_x = ?, bbox_max_y = ?, bbox_max_z = ?,
            has_color = ?, has_intensity = ?, status = 'ready', error = NULL,
            metadata_json = ?, updated_at = ?
        WHERE id = ?""",
        (
            cloud["point_count"], cloud["ingested_count"], int(cloud["decimated"]), cloud["size_bytes"], cloud["sha256"],
            *cloud["origin"], *cloud["bbox_min"], *cloud["bbox_max"],
            int(cloud["has_color"]), int(cloud["has_intensity"]), dumps(cloud["metadata"]), now, cloud_id,
        ),
    )
    result = manifest["result"]
    if progress:
        progress(1.0, "cloud ready")
    shutil.rmtree(stage_dir, ignore_errors=True)
    return result


def _ingest_full_rcs_stream(
    project_id: str,
    cloud_id: str,
    source_path: Path,
    paths: dict[str, Path],
    stage_dir: Path,
    source_identity: dict[str, Any],
    progress=None,
) -> dict[str, Any]:
    """Convert a full native RCS disk stream into derived arrays with bounded RAM."""
    raw = extract_rcs_native(source_path, stage_dir / "raw", progress=progress)
    source_count = int(raw["point_count"])
    if source_count <= 0:
        raise ValueError("RCS stream contains no points")
    raw_xyz_path = Path(raw["xyz_path"])
    raw_rgb_path = Path(raw["rgb_path"])
    raw_xyz = np.memmap(raw_xyz_path, mode="r", dtype="<f8", shape=(source_count, 3))
    raw_rgb = np.memmap(raw_rgb_path, mode="r", dtype="u1", shape=(source_count, 3))
    chunk_size = 500_000
    bbox_min = np.full(3, np.inf, dtype=np.float64)
    bbox_max = np.full(3, -np.inf, dtype=np.float64)
    valid_count = 0
    for start in range(0, source_count, chunk_size):
        chunk = np.asarray(raw_xyz[start : start + chunk_size])
        finite = np.isfinite(chunk).all(axis=1)
        if finite.any():
            valid = chunk[finite]
            bbox_min = np.minimum(bbox_min, valid.min(axis=0))
            bbox_max = np.maximum(bbox_max, valid.max(axis=0))
            valid_count += int(finite.sum())
    if valid_count == 0:
        raise ValueError("RCS stream contains no finite XYZ points")
    derived_bytes = valid_count * (3 * np.dtype("<f4").itemsize + 3 * np.dtype("u1").itemsize)
    preview_bytes = min(valid_count, MAX_PREVIEW_POINTS) * PREVIEW_DTYPE.itemsize
    required_free = derived_bytes + preview_bytes + MIN_INGEST_DISK_RESERVE_BYTES
    free_bytes = shutil.disk_usage(stage_dir).free
    if free_bytes < required_free:
        raise OSError(
            "not enough free disk space to finalize full-resolution RCS import: "
            f"need about {required_free:,} free bytes including reserve, have {free_bytes:,}"
        )
    origin = (bbox_min + bbox_max) / 2.0
    if progress:
        progress(0.62, "RCS bounds measured; writing local memmaps")

    stage_dir.mkdir(parents=True, exist_ok=True)
    staged_files: dict[str, Path] = {
        "positions": stage_dir / paths["positions"].name,
        "colors": stage_dir / paths["colors"].name,
        "preview": stage_dir / paths["preview"].name,
        "meta": stage_dir / paths["meta"].name,
    }
    positions = np.lib.format.open_memmap(
        staged_files["positions"], mode="w+", dtype="<f4", shape=(valid_count, 3)
    )
    colors = np.lib.format.open_memmap(
        staged_files["colors"], mode="w+", dtype="u1", shape=(valid_count, 3)
    )
    out_start = 0
    for start in range(0, source_count, chunk_size):
        end = min(source_count, start + chunk_size)
        xyz_chunk = np.asarray(raw_xyz[start:end])
        finite = np.isfinite(xyz_chunk).all(axis=1)
        count = int(finite.sum())
        if count:
            out_end = out_start + count
            positions[out_start:out_end] = (xyz_chunk[finite] - origin).astype(np.float32)
            colors[out_start:out_end] = raw_rgb[start:end][finite]
            out_start = out_end
        if progress:
            progress(0.62 + 0.28 * (end / source_count), "writing full-resolution RCS points")
    positions.flush()
    colors.flush()
    raw_xyz._mmap.close()
    raw_rgb._mmap.close()
    del positions, colors, raw_xyz, raw_rgb

    positions = np.load(staged_files["positions"], mmap_mode="r")
    colors = np.load(staged_files["colors"], mmap_mode="r")
    preview_arr, preview_count = build_preview(positions, colors, None)
    preview_tmp = staged_files["preview"].with_suffix(".bin.tmp")
    preview_arr.tofile(preview_tmp)
    preview_tmp.replace(staged_files["preview"])
    positions._mmap.close()
    colors._mmap.close()
    del positions, colors

    checksum = None
    try:
        if source_path.stat().st_size <= 2 * 1024 * 1024 * 1024:
            checksum = sha256_file(source_path)
    except OSError:
        pass
    if _source_identity(source_path) != source_identity:
        _discard_incomplete_stage(stage_dir, paths)
        raise RuntimeError("source identity changed while cloud import was running")

    metadata = {
        **raw["reader"],
        "origin": [float(x) for x in origin],
        "bbox_min": [float(x) for x in bbox_min],
        "bbox_max": [float(x) for x in bbox_max],
        "preview_count": preview_count,
        "preview_stride_bytes": PREVIEW_DTYPE.itemsize,
        "stored_point_count": valid_count,
        "source_point_count": source_count,
        "decimated": False,
        "dropped_non_finite": source_count - valid_count,
        "warning": None,
        "has_color": True,
        "has_intensity": False,
        "crash_safe": True,
        "source_unchanged": True,
        "checksum_sha256": checksum,
        "source_identity": source_identity,
    }
    write_json_atomic(staged_files["meta"], metadata)
    cloud = {
        "point_count": source_count,
        "ingested_count": valid_count,
        "decimated": False,
        "size_bytes": int(source_path.stat().st_size),
        "sha256": checksum,
        "origin": [float(x) for x in origin],
        "bbox_min": [float(x) for x in bbox_min],
        "bbox_max": [float(x) for x in bbox_max],
        "has_color": True,
        "has_intensity": False,
        "metadata": metadata,
    }
    result = {
        "cloud_id": cloud_id,
        "point_count": source_count,
        "ingested_count": valid_count,
        "preview_count": preview_count,
        "decimated": False,
        "warning": None,
    }
    files = {
        key: {"name": staged.name, **_file_record(staged)}
        for key, staged in staged_files.items()
    }
    manifest = {
        "version": INGEST_CHECKPOINT_VERSION,
        "cloud_id": cloud_id,
        "source_identity": source_identity,
        "files": files,
        "cloud": cloud,
        "result": result,
    }
    write_json_atomic(stage_dir / "manifest.json", manifest)
    return _finalize_checkpoint(project_id, cloud_id, paths, stage_dir, manifest, progress)


def ingest_cloud(
    project_id: str,
    cloud_id: str,
    source_path: Path,
    progress=None,
) -> dict[str, Any]:
    paths = cloud_paths(project_id, cloud_id)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    stage_dir = paths["dir"] / ".ingest-stage"
    manifest = _load_checkpoint(stage_dir, paths, source_path, cloud_id)
    if manifest is not None:
        return _finalize_checkpoint(project_id, cloud_id, paths, stage_dir, manifest, progress)

    full_rcs_stream = (
        source_path.suffix.lower() in {".rcs", ".rcp"}
        and MAX_INGEST_POINTS == 0
        and native_available()["dll_exists"]
    )
    preserve_raw_stream = full_rcs_stream and (stage_dir / "raw" / "stream.json").is_file()
    if stage_dir.exists() or any(paths[key].exists() for key in ("positions", "colors", "intensity", "preview", "meta")):
        _discard_incomplete_stage(stage_dir, paths, preserve_raw_stream=preserve_raw_stream)
    source_identity = _source_identity(source_path)
    if full_rcs_stream:
        return _ingest_full_rcs_stream(
            project_id, cloud_id, source_path, paths, stage_dir, source_identity, progress
        )
    if progress:
        progress(0.01, "открытие исходного файла")
    raw = read_cloud(source_path, max_points=MAX_INGEST_POINTS, progress=progress)
    if len(raw.xyz) == 0:
        raise ValueError("облако точек не содержит точек")

    if progress:
        progress(0.88, "расчёт габаритов и превью")
    bbox_min = raw.xyz.min(axis=0)
    bbox_max = raw.xyz.max(axis=0)
    origin = (bbox_min + bbox_max) / 2.0
    local = (raw.xyz - origin).astype(np.float32)
    colors = raw.rgb.astype(np.uint8, copy=False) if raw.rgb is not None else None
    intensity = raw.intensity.astype(np.float32, copy=False) if raw.intensity is not None else None

    stage_dir.mkdir(parents=True, exist_ok=True)
    staged_files: dict[str, Path] = {
        "positions": stage_dir / paths["positions"].name,
        "preview": stage_dir / paths["preview"].name,
        "meta": stage_dir / paths["meta"].name,
    }
    _save_npy_atomic(staged_files["positions"], local)
    if colors is not None:
        staged_files["colors"] = stage_dir / paths["colors"].name
        _save_npy_atomic(staged_files["colors"], colors)
    if intensity is not None:
        staged_files["intensity"] = stage_dir / paths["intensity"].name
        _save_npy_atomic(staged_files["intensity"], intensity)

    preview_arr, preview_count = build_preview(local, colors, intensity)
    tmp_preview = staged_files["preview"].with_suffix(".bin.tmp")
    preview_arr.tofile(tmp_preview)
    tmp_preview.replace(staged_files["preview"])

    source_count = int(raw.metadata.get("source_point_count") or len(raw.xyz))
    decimated = bool(raw.metadata.get("decimated") or len(local) < source_count)
    warning = None
    if decimated:
        warning = (
            f"В источнике ~{source_count:,} точек, в проект загружено {len(local):,} "
            f"(S2B_MAX_INGEST_POINTS={MAX_INGEST_POINTS:,}). Увеличьте лимит или "
            "конвертируйте в LAS/E57 для работы в полном разрешении."
        )

    checksum = None
    try:
        if source_path.stat().st_size <= 2 * 1024 * 1024 * 1024:
            checksum = sha256_file(source_path)
    except Exception:
        checksum = None

    if _source_identity(source_path) != source_identity:
        _discard_incomplete_stage(stage_dir, paths)
        raise RuntimeError("source identity changed while cloud import was running")

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
        "source_identity": source_identity,
    }
    write_json_atomic(staged_files["meta"], metadata)

    cloud = {
        "point_count": source_count,
        "ingested_count": int(len(local)),
        "decimated": decimated,
        "size_bytes": int(source_path.stat().st_size),
        "sha256": checksum,
        "origin": [float(x) for x in origin],
        "bbox_min": [float(x) for x in bbox_min],
        "bbox_max": [float(x) for x in bbox_max],
        "has_color": colors is not None,
        "has_intensity": intensity is not None,
        "metadata": metadata,
    }
    result = {
        "cloud_id": cloud_id,
        "point_count": source_count,
        "ingested_count": int(len(local)),
        "preview_count": preview_count,
        "decimated": decimated,
        "warning": warning,
    }
    files = {
        key: {"name": staged.name, **_file_record(staged)}
        for key, staged in staged_files.items()
    }
    manifest = {
        "version": INGEST_CHECKPOINT_VERSION,
        "cloud_id": cloud_id,
        "source_identity": source_identity,
        "files": files,
        "cloud": cloud,
        "result": result,
    }
    write_json_atomic(stage_dir / "manifest.json", manifest)
    return _finalize_checkpoint(project_id, cloud_id, paths, stage_dir, manifest, progress)


def cloud_meta(cloud_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM clouds WHERE id = ?", (cloud_id,))
    if not row:
        raise KeyError(cloud_id)
    try:
        return json.loads(row.get("metadata_json") or "{}")
    except Exception:
        return {}
