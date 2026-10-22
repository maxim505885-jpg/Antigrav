"""Ingestion: read a source cloud, store an immutable copy of derived arrays.

Source files are never modified. Positions are stored as float32 relative to a
per-cloud origin (the bbox centre) to keep viewer precision; the origin is saved
in metadata and can be added back to obtain world coordinates.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

import numpy as np

from .config import MAX_INGEST_POINTS, MAX_PREVIEW_POINTS
from .db import dumps, execute, one, utcnow
from .formats import read_cloud
from .formats.readers import (
    e57_stream_info, iter_e57_chunks, iter_las_chunks, iter_pcd_chunks, iter_ply_chunks,
    iter_text_chunks, las_stream_info,
)
from .formats.rcs_native import extract_rcs_native, native_available
from .storage import cloud_paths, sha256_file, write_json_atomic

PREVIEW_DTYPE = np.dtype(
    [("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")]
)
INGEST_CHECKPOINT_VERSION = 1
POINT_STREAM_CHUNK_POINTS = 500_000
TEXT_STREAM_CHUNK_POINTS = POINT_STREAM_CHUNK_POINTS
MIN_INGEST_DISK_RESERVE_BYTES = int(os.environ.get("S2B_INGEST_DISK_RESERVE_BYTES", str(1024**3)))


class CheckpointSourceChanged(ValueError):
    """The source no longer matches the source for a complete ingest checkpoint."""


def _save_npy_atomic(path: Path, array: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # np.save appends .npy when the suffix differs, so keep .npy at the end.
    tmp = path.with_name(path.name + ".tmp.npy")
    np.save(tmp, array)
    tmp.replace(path)


def _sha256_array(array: np.ndarray) -> str:
    return hashlib.sha256(memoryview(np.ascontiguousarray(array))).hexdigest()


def _fsync_path(path: Path) -> None:
    with path.open("r+b") as fh:
        fh.flush()
        os.fsync(fh.fileno())


def _write_json_durable(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8") as fh:
            json.dump(value, fh, ensure_ascii=False, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


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
    target: int | None = None,
) -> tuple[Path, int]:
    """Write the interleaved binary preview and return (path, count)."""
    if target is None:
        target = MAX_PREVIEW_POINTS
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
        if not current_identity.get("missing"):
            stat_keys = ("path", "size_bytes", "mtime_ns")
            if any(current_identity.get(key) != identity.get(key) for key in stat_keys):
                raise CheckpointSourceChanged("source changed since ingest checkpoint: file identity differs")
            expected_sha256 = identity.get("sha256")
            if expected_sha256 and sha256_file(source_path) != expected_sha256:
                raise CheckpointSourceChanged("source changed since ingest checkpoint: content SHA-256 differs")
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
    stage_dir: Path, paths: dict[str, Path], *, preserve_raw_stream: bool = False,
    preserve_e57_stream: bool = False, preserve_las_stream: bool = False,
    preserve_text_stream: bool = False, preserve_pcd_stream: bool = False,
    preserve_ply_stream: bool = False,
) -> None:
    checkpoint_name = (
        "e57-write-checkpoint.json" if preserve_e57_stream else
        "las-write-checkpoint.json" if preserve_las_stream else
        "pcd-write-checkpoint.json" if preserve_pcd_stream else
        "ply-write-checkpoint.json" if preserve_ply_stream else
        "text-write-checkpoint.json" if preserve_text_stream else None
    )
    if checkpoint_name and (stage_dir / checkpoint_name).is_file():
        preserved = {checkpoint_name, paths["positions"].name}
        if paths["colors"].exists() or (stage_dir / paths["colors"].name).exists():
            preserved.add(paths["colors"].name)
        if paths["intensity"].exists() or (stage_dir / paths["intensity"].name).exists():
            preserved.add(paths["intensity"].name)
        for child in stage_dir.iterdir():
            if child.name in preserved:
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
    elif preserve_raw_stream and (stage_dir / "raw").is_dir():
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

    checksum = raw["reader"].get("source_sha256")
    try:
        if checksum is None and source_path.stat().st_size <= 2 * 1024 * 1024 * 1024:
            checksum = sha256_file(source_path)
        if checksum is None:
            raise RuntimeError("full-resolution RCS stream has no source content hash")
        verified_checksum = sha256_file(source_path)
    except OSError as exc:
        _discard_incomplete_stage(stage_dir, paths)
        raise RuntimeError(f"could not verify source content after RCS import: {exc}") from exc
    if verified_checksum != checksum:
        _discard_incomplete_stage(stage_dir, paths)
        raise RuntimeError("source content changed while full-resolution RCS import was running")
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
        "source_identity": {**source_identity, "sha256": checksum},
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
        "source_identity": {**source_identity, "sha256": checksum},
        "files": files,
        "cloud": cloud,
        "result": result,
    }
    write_json_atomic(stage_dir / "manifest.json", manifest)
    return _finalize_checkpoint(project_id, cloud_id, paths, stage_dir, manifest, progress)


def _ingest_full_e57_stream(
    project_id: str,
    cloud_id: str,
    source_path: Path,
    paths: dict[str, Path],
    stage_dir: Path,
    source_identity: dict[str, Any],
    progress=None,
) -> dict[str, Any]:
    """Ingest full-resolution E57 with bounded point buffers and disk-backed arrays.

    Two sequential passes measure bounds and fill disk-backed arrays. If the
    write pass is interrupted, checksummed output blocks survive and the reader
    replays the committed input prefix (pye57 seek is unavailable) before it
    appends new blocks.
    """
    checksum = sha256_file(source_path)
    info = e57_stream_info(source_path)
    source_count = int(info["source_point_count"])
    if source_count <= 0:
        raise ValueError("E57 stream contains no points")
    chunk_points = 500_000

    bbox_min = np.full(3, np.inf, dtype=np.float64)
    bbox_max = np.full(3, -np.inf, dtype=np.float64)
    valid_count = 0
    bounds_progress = (
        (lambda fraction, message: progress(0.05 + 0.45 * fraction, message))
        if progress else None
    )
    for xyz, rgb, intensity in iter_e57_chunks(
        source_path, chunk_points=chunk_points, progress=bounds_progress
    ):
        if info["has_color"] != (rgb is not None):
            raise RuntimeError("E57 color fields changed between scan headers and point stream")
        if info["has_intensity"] != (intensity is not None):
            raise RuntimeError("E57 intensity fields changed between scan headers and point stream")
        if len(xyz):
            bbox_min = np.minimum(bbox_min, xyz.min(axis=0))
            bbox_max = np.maximum(bbox_max, xyz.max(axis=0))
            valid_count += len(xyz)
    if valid_count <= 0:
        raise ValueError("E57 stream contains no finite points")

    derived_bytes = valid_count * (3 * np.dtype("<f4").itemsize)
    if info["has_color"]:
        derived_bytes += valid_count * 3 * np.dtype("u1").itemsize
    if info["has_intensity"]:
        derived_bytes += valid_count * np.dtype("<f4").itemsize
    preview_bytes = min(valid_count, MAX_PREVIEW_POINTS) * PREVIEW_DTYPE.itemsize
    required_free = derived_bytes + preview_bytes + MIN_INGEST_DISK_RESERVE_BYTES
    free_bytes = shutil.disk_usage(paths["dir"]).free
    if free_bytes < required_free:
        raise OSError(
            "not enough free disk space to finalize full-resolution E57 import: "
            f"need about {required_free:,} free bytes including reserve, have {free_bytes:,}"
        )

    origin = (bbox_min + bbox_max) / 2.0
    stage_dir.mkdir(parents=True, exist_ok=True)
    staged_files: dict[str, Path] = {
        "positions": stage_dir / paths["positions"].name,
        "preview": stage_dir / paths["preview"].name,
        "meta": stage_dir / paths["meta"].name,
    }
    if info["has_color"]:
        staged_files["colors"] = stage_dir / paths["colors"].name
    if info["has_intensity"]:
        staged_files["intensity"] = stage_dir / paths["intensity"].name

    checkpoint_path = stage_dir / "e57-write-checkpoint.json"
    checkpoint_identity = {**source_identity, "sha256": checksum}
    checkpoint = None
    if checkpoint_path.is_file():
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"E57 write checkpoint is unreadable: {exc}") from exc
        expected = {
            "version": 1, "cloud_id": cloud_id, "source_identity": checkpoint_identity,
            "source_point_count": source_count, "valid_point_count": valid_count,
            "bbox_min": bbox_min.tolist(), "bbox_max": bbox_max.tolist(), "origin": origin.tolist(),
            "has_color": bool(info["has_color"]), "has_intensity": bool(info["has_intensity"]),
        }
        if any(checkpoint.get(key) != value for key, value in expected.items()):
            raise CheckpointSourceChanged("E57 source or measured bounds changed since write checkpoint")

    positions = colors = intensity_values = None
    out_start = int(checkpoint.get("committed_points", 0)) if checkpoint else 0
    try:
        mode = "r+" if checkpoint else "w+"
        positions = (
            np.load(staged_files["positions"], mmap_mode="r+") if checkpoint else
            np.lib.format.open_memmap(
                staged_files["positions"], mode="w+", dtype="<f4", shape=(valid_count, 3)
            )
        )
        colors = (
            np.load(staged_files["colors"], mmap_mode="r+") if checkpoint and info["has_color"] else
            np.lib.format.open_memmap(
                staged_files["colors"], mode=mode, dtype="u1", shape=(valid_count, 3)
            ) if info["has_color"] else None
        )
        intensity_values = (
            np.load(staged_files["intensity"], mmap_mode="r+") if checkpoint and info["has_intensity"] else
            np.lib.format.open_memmap(
                staged_files["intensity"], mode=mode, dtype="<f4", shape=(valid_count,)
            ) if info["has_intensity"] else None
        )
        if positions.shape != (valid_count, 3) or positions.dtype != np.dtype("<f4"):
            raise RuntimeError("E57 positions checkpoint has an invalid array shape or dtype")
        if colors is not None and (colors.shape != (valid_count, 3) or colors.dtype != np.dtype("u1")):
            raise RuntimeError("E57 colors checkpoint has an invalid array shape or dtype")
        if intensity_values is not None and (
            intensity_values.shape != (valid_count,) or intensity_values.dtype != np.dtype("<f4")
        ):
            raise RuntimeError("E57 intensity checkpoint has an invalid array shape or dtype")
        blocks = list(checkpoint.get("blocks", [])) if checkpoint else []
        if checkpoint:
            verified_end = 0
            for block in blocks:
                start, end = int(block["start"]), int(block["end"])
                if start != verified_end or end <= start or end > out_start:
                    raise RuntimeError("E57 checkpoint block ranges are inconsistent")
                arrays = {"positions": positions[start:end]}
                if colors is not None:
                    arrays["colors"] = colors[start:end]
                if intensity_values is not None:
                    arrays["intensity"] = intensity_values[start:end]
                if {key: _sha256_array(value) for key, value in arrays.items()} != block.get("sha256"):
                    raise RuntimeError("E57 checkpoint block checksum does not match stored arrays")
                verified_end = end
            if verified_end != out_start or out_start > valid_count:
                raise RuntimeError("E57 committed point count does not match verified blocks")

        skipped = out_start
        for xyz, rgb, intensity in iter_e57_chunks(source_path, chunk_points=chunk_points):
            if info["has_color"] != (rgb is not None):
                raise RuntimeError("E57 color fields changed between point stream passes")
            if info["has_intensity"] != (intensity is not None):
                raise RuntimeError("E57 intensity fields changed between point stream passes")
            count = len(xyz)
            if skipped:
                consumed = min(skipped, count)
                xyz = xyz[consumed:]
                rgb = rgb[consumed:] if rgb is not None else None
                intensity = intensity[consumed:] if intensity is not None else None
                skipped -= consumed
                count = len(xyz)
            if count:
                out_end = out_start + count
                if out_end > valid_count:
                    raise RuntimeError("E57 point count increased between bounds and write passes")
                positions[out_start:out_end] = (xyz - origin).astype(np.float32)
                if colors is not None and rgb is not None:
                    colors[out_start:out_end] = rgb
                if intensity_values is not None and intensity is not None:
                    intensity_values[out_start:out_end] = intensity
                positions.flush()
                if colors is not None:
                    colors.flush()
                if intensity_values is not None:
                    intensity_values.flush()
                for staged in staged_files.values():
                    if staged in {staged_files["positions"], staged_files.get("colors"),
                                  staged_files.get("intensity")} and staged.exists():
                        _fsync_path(staged)
                arrays = {"positions": positions[out_start:out_end]}
                if colors is not None:
                    arrays["colors"] = colors[out_start:out_end]
                if intensity_values is not None:
                    arrays["intensity"] = intensity_values[out_start:out_end]
                blocks.append({
                    "start": out_start, "end": out_end,
                    "sha256": {key: _sha256_array(value) for key, value in arrays.items()},
                })
                out_start = out_end
                state = {
                    "version": 1, "cloud_id": cloud_id, "source_identity": checkpoint_identity,
                    "source_point_count": source_count, "valid_point_count": valid_count,
                    "bbox_min": bbox_min.tolist(), "bbox_max": bbox_max.tolist(), "origin": origin.tolist(),
                    "has_color": bool(info["has_color"]), "has_intensity": bool(info["has_intensity"]),
                    "committed_points": out_start, "blocks": blocks,
                }
                _write_json_durable(checkpoint_path, state)
            if progress:
                progress(0.58 + 0.30 * (out_start / valid_count), "writing full-resolution E57 memmaps")
        if skipped:
            raise RuntimeError("E57 stream ended before the committed output prefix")
        if out_start != valid_count:
            raise RuntimeError("E57 point count changed between bounds and write passes")
        positions.flush()
        if colors is not None:
            colors.flush()
        if intensity_values is not None:
            intensity_values.flush()
    finally:
        if positions is not None:
            positions._mmap.close()
        if colors is not None:
            colors._mmap.close()
        if intensity_values is not None:
            intensity_values._mmap.close()

    if _source_identity(source_path) != source_identity or sha256_file(source_path) != checksum:
        _discard_incomplete_stage(stage_dir, paths)
        raise RuntimeError("source content changed while full-resolution E57 import was running")

    positions = np.load(staged_files["positions"], mmap_mode="r")
    colors = np.load(staged_files["colors"], mmap_mode="r") if "colors" in staged_files else None
    intensity_values = np.load(staged_files["intensity"], mmap_mode="r") if "intensity" in staged_files else None
    try:
        preview_arr, preview_count = build_preview(positions, colors, intensity_values)
        preview_tmp = staged_files["preview"].with_suffix(".bin.tmp")
        preview_arr.tofile(preview_tmp)
        preview_tmp.replace(staged_files["preview"])
    finally:
        positions._mmap.close()
        if colors is not None:
            colors._mmap.close()
        if intensity_values is not None:
            intensity_values._mmap.close()

    metadata = {
        **info,
        "origin": [float(value) for value in origin],
        "bbox_min": [float(value) for value in bbox_min],
        "bbox_max": [float(value) for value in bbox_max],
        "preview_count": preview_count,
        "preview_stride_bytes": PREVIEW_DTYPE.itemsize,
        "stored_point_count": valid_count,
        "decimated": False,
        "dropped_non_finite": source_count - valid_count,
        "warning": None,
        "has_color": bool(info["has_color"]),
        "has_intensity": bool(info["has_intensity"]),
        "bounded_memory": True,
        "stream_chunk_points": chunk_points,
        "restart_policy": "replay_committed_prefix_then_continue",
        "crash_safe": True,
        "source_unchanged": True,
        "checksum_sha256": checksum,
        "source_identity": {**source_identity, "sha256": checksum},
    }
    write_json_atomic(staged_files["meta"], metadata)
    cloud = {
        "point_count": source_count,
        "ingested_count": valid_count,
        "decimated": False,
        "size_bytes": int(source_identity["size_bytes"]),
        "sha256": checksum,
        "origin": [float(value) for value in origin],
        "bbox_min": [float(value) for value in bbox_min],
        "bbox_max": [float(value) for value in bbox_max],
        "has_color": bool(info["has_color"]),
        "has_intensity": bool(info["has_intensity"]),
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
    files = {key: {"name": staged.name, **_file_record(staged)} for key, staged in staged_files.items()}
    manifest = {
        "version": INGEST_CHECKPOINT_VERSION,
        "cloud_id": cloud_id,
        "source_identity": {**source_identity, "sha256": checksum},
        "files": files,
        "cloud": cloud,
        "result": result,
    }
    write_json_atomic(stage_dir / "manifest.json", manifest)
    return _finalize_checkpoint(project_id, cloud_id, paths, stage_dir, manifest, progress)


def _ingest_full_las_stream(
    project_id: str,
    cloud_id: str,
    source_path: Path,
    paths: dict[str, Path],
    stage_dir: Path,
    source_identity: dict[str, Any],
    progress=None,
) -> dict[str, Any]:
    """Import full-resolution LAS/LAZ in bounded chunks into disk-backed arrays."""
    checksum = sha256_file(source_path)
    info = las_stream_info(source_path)
    source_count = int(info["source_point_count"])
    if source_count <= 0:
        raise ValueError("LAS/LAZ stream contains no points")
    chunk_points = 500_000

    bbox_min = np.full(3, np.inf, dtype=np.float64)
    bbox_max = np.full(3, -np.inf, dtype=np.float64)
    valid_count = 0
    bounds_progress = (
        (lambda fraction, message: progress(0.05 + 0.45 * fraction, message))
        if progress else None
    )
    for xyz, rgb, intensity in iter_las_chunks(
        source_path, chunk_points=chunk_points, progress=bounds_progress
    ):
        if info["has_color"] != (rgb is not None):
            raise RuntimeError("LAS/LAZ color dimensions changed during bounds pass")
        if info["has_intensity"] != (intensity is not None):
            raise RuntimeError("LAS/LAZ intensity dimension changed during bounds pass")
        if len(xyz):
            bbox_min = np.minimum(bbox_min, xyz.min(axis=0))
            bbox_max = np.maximum(bbox_max, xyz.max(axis=0))
            valid_count += len(xyz)
    if valid_count <= 0:
        raise ValueError("LAS/LAZ stream contains no finite points")

    derived_bytes = valid_count * (3 * np.dtype("<f4").itemsize)
    if info["has_color"]:
        derived_bytes += valid_count * 3 * np.dtype("u1").itemsize
    if info["has_intensity"]:
        derived_bytes += valid_count * np.dtype("<f4").itemsize
    preview_bytes = min(valid_count, MAX_PREVIEW_POINTS) * PREVIEW_DTYPE.itemsize
    required_free = derived_bytes + preview_bytes + MIN_INGEST_DISK_RESERVE_BYTES
    free_bytes = shutil.disk_usage(paths["dir"]).free
    if free_bytes < required_free:
        raise OSError(
            "not enough free disk space to finalize full-resolution LAS/LAZ import: "
            f"need about {required_free:,} free bytes including reserve, have {free_bytes:,}"
        )

    origin = (bbox_min + bbox_max) / 2.0
    stage_dir.mkdir(parents=True, exist_ok=True)
    staged_files: dict[str, Path] = {
        "positions": stage_dir / paths["positions"].name,
        "preview": stage_dir / paths["preview"].name,
        "meta": stage_dir / paths["meta"].name,
    }
    if info["has_color"]:
        staged_files["colors"] = stage_dir / paths["colors"].name
    if info["has_intensity"]:
        staged_files["intensity"] = stage_dir / paths["intensity"].name

    checkpoint_path = stage_dir / "las-write-checkpoint.json"
    checkpoint_identity = {**source_identity, "sha256": checksum}
    checkpoint = None
    if checkpoint_path.is_file():
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"LAS/LAZ write checkpoint is unreadable: {exc}") from exc
        expected = {
            "version": 1, "cloud_id": cloud_id, "source_identity": checkpoint_identity,
            "source_point_count": source_count, "valid_point_count": valid_count,
            "bbox_min": bbox_min.tolist(), "bbox_max": bbox_max.tolist(), "origin": origin.tolist(),
            "has_color": bool(info["has_color"]), "has_intensity": bool(info["has_intensity"]),
        }
        if any(checkpoint.get(key) != value for key, value in expected.items()):
            raise CheckpointSourceChanged("LAS/LAZ source or measured bounds changed since write checkpoint")

    positions = colors = intensity_values = None
    out_start = int(checkpoint.get("committed_points", 0)) if checkpoint else 0
    try:
        mode = "r+" if checkpoint else "w+"
        positions = (
            np.load(staged_files["positions"], mmap_mode="r+") if checkpoint else
            np.lib.format.open_memmap(
                staged_files["positions"], mode="w+", dtype="<f4", shape=(valid_count, 3)
            )
        )
        colors = (
            np.load(staged_files["colors"], mmap_mode="r+") if checkpoint and info["has_color"] else
            np.lib.format.open_memmap(
                staged_files["colors"], mode=mode, dtype="u1", shape=(valid_count, 3)
            ) if info["has_color"] else None
        )
        intensity_values = (
            np.load(staged_files["intensity"], mmap_mode="r+") if checkpoint and info["has_intensity"] else
            np.lib.format.open_memmap(
                staged_files["intensity"], mode=mode, dtype="<f4", shape=(valid_count,)
            ) if info["has_intensity"] else None
        )
        if positions.shape != (valid_count, 3) or positions.dtype != np.dtype("<f4"):
            raise RuntimeError("LAS/LAZ positions checkpoint has an invalid array shape or dtype")
        if colors is not None and (colors.shape != (valid_count, 3) or colors.dtype != np.dtype("u1")):
            raise RuntimeError("LAS/LAZ colors checkpoint has an invalid array shape or dtype")
        if intensity_values is not None and (
            intensity_values.shape != (valid_count,) or intensity_values.dtype != np.dtype("<f4")
        ):
            raise RuntimeError("LAS/LAZ intensity checkpoint has an invalid array shape or dtype")
        blocks = list(checkpoint.get("blocks", [])) if checkpoint else []
        if checkpoint:
            verified_end = 0
            for block in blocks:
                start, end = int(block["start"]), int(block["end"])
                if start != verified_end or end <= start or end > out_start:
                    raise RuntimeError("LAS/LAZ checkpoint block ranges are inconsistent")
                arrays = {"positions": positions[start:end]}
                if colors is not None:
                    arrays["colors"] = colors[start:end]
                if intensity_values is not None:
                    arrays["intensity"] = intensity_values[start:end]
                if {key: _sha256_array(value) for key, value in arrays.items()} != block.get("sha256"):
                    raise RuntimeError("LAS/LAZ checkpoint block checksum does not match stored arrays")
                verified_end = end
            if verified_end != out_start or out_start > valid_count:
                raise RuntimeError("LAS/LAZ committed point count does not match verified blocks")

        skipped = out_start
        for xyz, rgb, intensity in iter_las_chunks(source_path, chunk_points=chunk_points):
            if info["has_color"] != (rgb is not None):
                raise RuntimeError("LAS/LAZ color dimensions changed between stream passes")
            if info["has_intensity"] != (intensity is not None):
                raise RuntimeError("LAS/LAZ intensity dimension changed between stream passes")
            count = len(xyz)
            if skipped:
                consumed = min(skipped, count)
                xyz = xyz[consumed:]
                rgb = rgb[consumed:] if rgb is not None else None
                intensity = intensity[consumed:] if intensity is not None else None
                skipped -= consumed
                count = len(xyz)
            if count:
                out_end = out_start + count
                if out_end > valid_count:
                    raise RuntimeError("LAS/LAZ point count increased between stream passes")
                positions[out_start:out_end] = (xyz - origin).astype(np.float32)
                if colors is not None and rgb is not None:
                    colors[out_start:out_end] = rgb
                if intensity_values is not None and intensity is not None:
                    intensity_values[out_start:out_end] = intensity
                positions.flush()
                if colors is not None:
                    colors.flush()
                if intensity_values is not None:
                    intensity_values.flush()
                for key in ("positions", "colors", "intensity"):
                    staged = staged_files.get(key)
                    if staged is not None:
                        _fsync_path(staged)
                arrays = {"positions": positions[out_start:out_end]}
                if colors is not None:
                    arrays["colors"] = colors[out_start:out_end]
                if intensity_values is not None:
                    arrays["intensity"] = intensity_values[out_start:out_end]
                blocks.append({
                    "start": out_start, "end": out_end,
                    "sha256": {key: _sha256_array(value) for key, value in arrays.items()},
                })
                out_start = out_end
                state = {
                    "version": 1, "cloud_id": cloud_id, "source_identity": checkpoint_identity,
                    "source_point_count": source_count, "valid_point_count": valid_count,
                    "bbox_min": bbox_min.tolist(), "bbox_max": bbox_max.tolist(), "origin": origin.tolist(),
                    "has_color": bool(info["has_color"]), "has_intensity": bool(info["has_intensity"]),
                    "committed_points": out_start, "blocks": blocks,
                }
                _write_json_durable(checkpoint_path, state)
            if progress:
                progress(0.58 + 0.30 * (out_start / valid_count), "writing full-resolution LAS/LAZ memmaps")
        if skipped:
            raise RuntimeError("LAS/LAZ stream ended before the committed output prefix")
        if out_start != valid_count:
            raise RuntimeError("LAS/LAZ point count changed between bounds and write passes")
        positions.flush()
        if colors is not None:
            colors.flush()
        if intensity_values is not None:
            intensity_values.flush()
    finally:
        if positions is not None:
            positions._mmap.close()
        if colors is not None:
            colors._mmap.close()
        if intensity_values is not None:
            intensity_values._mmap.close()

    if _source_identity(source_path) != source_identity or sha256_file(source_path) != checksum:
        _discard_incomplete_stage(stage_dir, paths)
        raise RuntimeError("source content changed while full-resolution LAS/LAZ import was running")

    positions = np.load(staged_files["positions"], mmap_mode="r")
    colors = np.load(staged_files["colors"], mmap_mode="r") if "colors" in staged_files else None
    intensity_values = np.load(staged_files["intensity"], mmap_mode="r") if "intensity" in staged_files else None
    try:
        preview_arr, preview_count = build_preview(positions, colors, intensity_values)
        preview_tmp = staged_files["preview"].with_suffix(".bin.tmp")
        preview_arr.tofile(preview_tmp)
        preview_tmp.replace(staged_files["preview"])
    finally:
        positions._mmap.close()
        if colors is not None:
            colors._mmap.close()
        if intensity_values is not None:
            intensity_values._mmap.close()

    metadata = {
        **info,
        "origin": [float(value) for value in origin],
        "bbox_min": [float(value) for value in bbox_min],
        "bbox_max": [float(value) for value in bbox_max],
        "preview_count": preview_count,
        "preview_stride_bytes": PREVIEW_DTYPE.itemsize,
        "stored_point_count": valid_count,
        "decimated": False,
        "dropped_non_finite": source_count - valid_count,
        "warning": None,
        "has_color": bool(info["has_color"]),
        "has_intensity": bool(info["has_intensity"]),
        "bounded_memory": True,
        "stream_chunk_points": chunk_points,
        "restart_policy": "replay_committed_prefix_then_continue",
        "crash_safe": True,
        "source_unchanged": True,
        "checksum_sha256": checksum,
        "source_identity": {**source_identity, "sha256": checksum},
    }
    write_json_atomic(staged_files["meta"], metadata)
    cloud = {
        "point_count": source_count,
        "ingested_count": valid_count,
        "decimated": False,
        "size_bytes": int(source_identity["size_bytes"]),
        "sha256": checksum,
        "origin": [float(value) for value in origin],
        "bbox_min": [float(value) for value in bbox_min],
        "bbox_max": [float(value) for value in bbox_max],
        "has_color": bool(info["has_color"]),
        "has_intensity": bool(info["has_intensity"]),
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
    files = {key: {"name": staged.name, **_file_record(staged)} for key, staged in staged_files.items()}
    manifest = {
        "version": INGEST_CHECKPOINT_VERSION,
        "cloud_id": cloud_id,
        "source_identity": {**source_identity, "sha256": checksum},
        "files": files,
        "cloud": cloud,
        "result": result,
    }
    write_json_atomic(stage_dir / "manifest.json", manifest)
    return _finalize_checkpoint(project_id, cloud_id, paths, stage_dir, manifest, progress)


def _ingest_full_chunked_stream(
    project_id: str,
    cloud_id: str,
    source_path: Path,
    paths: dict[str, Path],
    stage_dir: Path,
    source_identity: dict[str, Any],
    source_format: str,
    reader_label: str,
    chunk_reader,
    progress=None,
) -> dict[str, Any]:
    """Import a sequential format in bounded, restartable memmap blocks."""
    checksum = sha256_file(source_path)
    fmt = source_format.lower().lstrip(".")
    text_format = fmt in {"xyz", "pts", "txt", "csv"}
    checkpoint_prefix = "text" if text_format else fmt
    progress_label = "text" if text_format else fmt.upper()

    bbox_min = np.full(3, np.inf, dtype=np.float64)
    bbox_max = np.full(3, -np.inf, dtype=np.float64)
    valid_count = 0
    source_count = 0
    if progress:
        progress(0.03, f"measuring full-resolution {progress_label} cloud")
    for xyz, _rgb, _intensity in chunk_reader(source_path, chunk_points=POINT_STREAM_CHUNK_POINTS):
        source_count += len(xyz)
        xyz = xyz[np.isfinite(xyz).all(axis=1)]
        if not len(xyz):
            continue
        bbox_min = np.minimum(bbox_min, xyz.min(axis=0))
        bbox_max = np.maximum(bbox_max, xyz.max(axis=0))
        valid_count += len(xyz)
    if valid_count <= 0:
        raise ValueError(f"{fmt.upper()} stream contains no finite points")
    if _source_identity(source_path) != source_identity or sha256_file(source_path) != checksum:
        raise RuntimeError(f"source content changed during full-resolution {fmt.upper()} bounds pass")

    # The second pass infers the same dimensions; determine flags from the first
    # non-empty block so allocation is driven by actual parsed columns.
    first = next(chunk_reader(source_path, chunk_points=POINT_STREAM_CHUNK_POINTS), None)
    if first is None:
        raise ValueError(f"{fmt.upper()} stream contains no finite points")
    has_color, has_intensity = first[1] is not None, first[2] is not None
    origin = (bbox_min + bbox_max) / 2.0
    derived_bytes = valid_count * 3 * np.dtype("<f4").itemsize
    if has_color:
        derived_bytes += valid_count * 3 * np.dtype("u1").itemsize
    if has_intensity:
        derived_bytes += valid_count * np.dtype("<f4").itemsize
    preview_bytes = min(valid_count, MAX_PREVIEW_POINTS) * PREVIEW_DTYPE.itemsize
    required_free = derived_bytes + preview_bytes + MIN_INGEST_DISK_RESERVE_BYTES
    free_bytes = shutil.disk_usage(paths["dir"]).free
    if free_bytes < required_free:
        raise OSError(
            f"not enough free disk space to finalize full-resolution {fmt.upper()} import: "
            f"need about {required_free:,} free bytes including reserve, have {free_bytes:,}"
        )

    stage_dir.mkdir(parents=True, exist_ok=True)
    staged_files: dict[str, Path] = {
        "positions": stage_dir / paths["positions"].name,
        "preview": stage_dir / paths["preview"].name,
        "meta": stage_dir / paths["meta"].name,
    }
    if has_color:
        staged_files["colors"] = stage_dir / paths["colors"].name
    if has_intensity:
        staged_files["intensity"] = stage_dir / paths["intensity"].name

    checkpoint_path = stage_dir / f"{checkpoint_prefix}-write-checkpoint.json"
    checkpoint_identity = {**source_identity, "sha256": checksum}
    checkpoint = None
    if checkpoint_path.is_file():
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"{fmt.upper()} write checkpoint is unreadable: {exc}") from exc
        expected = {
            "version": 1, "cloud_id": cloud_id, "source_identity": checkpoint_identity,
            "format": fmt, "source_point_count": source_count, "valid_point_count": valid_count,
            "bbox_min": bbox_min.tolist(), "bbox_max": bbox_max.tolist(), "origin": origin.tolist(),
            "has_color": has_color, "has_intensity": has_intensity,
        }
        if any(checkpoint.get(key) != value for key, value in expected.items()):
            raise CheckpointSourceChanged(f"{fmt.upper()} source or measured bounds changed since write checkpoint")

    positions = colors = intensity_values = None
    out_start = int(checkpoint.get("committed_points", 0)) if checkpoint else 0
    try:
        mode = "r+" if checkpoint else "w+"
        positions = (
            np.load(staged_files["positions"], mmap_mode="r+") if checkpoint else
            np.lib.format.open_memmap(staged_files["positions"], mode="w+", dtype="<f4", shape=(valid_count, 3))
        )
        colors = (
            np.load(staged_files["colors"], mmap_mode="r+") if checkpoint and has_color else
            np.lib.format.open_memmap(staged_files["colors"], mode=mode, dtype="u1", shape=(valid_count, 3))
            if has_color else None
        )
        intensity_values = (
            np.load(staged_files["intensity"], mmap_mode="r+") if checkpoint and has_intensity else
            np.lib.format.open_memmap(staged_files["intensity"], mode=mode, dtype="<f4", shape=(valid_count,))
            if has_intensity else None
        )
        if positions.shape != (valid_count, 3) or positions.dtype != np.dtype("<f4"):
            raise RuntimeError(f"{fmt.upper()} positions checkpoint has an invalid array shape or dtype")
        blocks = list(checkpoint.get("blocks", [])) if checkpoint else []
        if checkpoint:
            verified_end = 0
            for block in blocks:
                start, end = int(block["start"]), int(block["end"])
                if start != verified_end or end <= start or end > out_start:
                    raise RuntimeError(f"{fmt.upper()} checkpoint block ranges are inconsistent")
                arrays = {"positions": positions[start:end]}
                if colors is not None:
                    arrays["colors"] = colors[start:end]
                if intensity_values is not None:
                    arrays["intensity"] = intensity_values[start:end]
                if {key: _sha256_array(value) for key, value in arrays.items()} != block.get("sha256"):
                    raise RuntimeError(f"{fmt.upper()} checkpoint block checksum does not match stored arrays")
                verified_end = end
            if verified_end != out_start or out_start > valid_count:
                raise RuntimeError(f"{fmt.upper()} committed point count does not match verified blocks")

        skipped = out_start
        for xyz, rgb, intensity in chunk_reader(source_path, chunk_points=POINT_STREAM_CHUNK_POINTS):
            finite = np.isfinite(xyz).all(axis=1)
            xyz = xyz[finite]
            rgb = rgb[finite] if rgb is not None else None
            intensity = intensity[finite] if intensity is not None else None
            if not len(xyz):
                continue
            if (rgb is not None) != has_color or (intensity is not None) != has_intensity:
                raise RuntimeError(f"{fmt.upper()} attributes changed between stream passes")
            count = len(xyz)
            if skipped:
                consumed = min(skipped, count)
                xyz = xyz[consumed:]
                rgb = rgb[consumed:] if rgb is not None else None
                intensity = intensity[consumed:] if intensity is not None else None
                skipped -= consumed
                count = len(xyz)
            if count:
                out_end = out_start + count
                if out_end > valid_count:
                    raise RuntimeError(f"{fmt.upper()} point count increased between stream passes")
                positions[out_start:out_end] = (xyz - origin).astype(np.float32)
                if colors is not None:
                    colors[out_start:out_end] = rgb
                if intensity_values is not None:
                    intensity_values[out_start:out_end] = intensity
                for array in (positions, colors, intensity_values):
                    if array is not None:
                        array.flush()
                for key in ("positions", "colors", "intensity"):
                    staged = staged_files.get(key)
                    if staged is not None:
                        _fsync_path(staged)
                arrays = {"positions": positions[out_start:out_end]}
                if colors is not None:
                    arrays["colors"] = colors[out_start:out_end]
                if intensity_values is not None:
                    arrays["intensity"] = intensity_values[out_start:out_end]
                blocks.append({
                    "start": out_start, "end": out_end,
                    "sha256": {key: _sha256_array(value) for key, value in arrays.items()},
                })
                out_start = out_end
                _write_json_durable(checkpoint_path, {
                    "version": 1, "cloud_id": cloud_id, "source_identity": checkpoint_identity,
                    "format": fmt, "source_point_count": source_count, "valid_point_count": valid_count,
                    "bbox_min": bbox_min.tolist(), "bbox_max": bbox_max.tolist(), "origin": origin.tolist(),
                    "has_color": has_color, "has_intensity": has_intensity,
                    "committed_points": out_start, "blocks": blocks,
                })
            if progress:
                progress(0.58 + 0.30 * (out_start / valid_count), f"writing full-resolution {progress_label} memmaps")
        if skipped or out_start != valid_count:
            raise RuntimeError(f"{fmt.upper()} point count changed between bounds and write passes")
    finally:
        for array in (positions, colors, intensity_values):
            if array is not None:
                array._mmap.close()

    if _source_identity(source_path) != source_identity or sha256_file(source_path) != checksum:
        _discard_incomplete_stage(stage_dir, paths)
        raise RuntimeError(f"source content changed while full-resolution {fmt.upper()} import was running")

    positions = np.load(staged_files["positions"], mmap_mode="r")
    colors = np.load(staged_files["colors"], mmap_mode="r") if has_color else None
    intensity_values = np.load(staged_files["intensity"], mmap_mode="r") if has_intensity else None
    try:
        preview_arr, preview_count = build_preview(positions, colors, intensity_values)
        preview_tmp = staged_files["preview"].with_suffix(".bin.tmp")
        preview_arr.tofile(preview_tmp)
        preview_tmp.replace(staged_files["preview"])
    finally:
        for array in (positions, colors, intensity_values):
            if array is not None:
                array._mmap.close()

    metadata = {
        "reader": reader_label, "format": fmt, "source_point_count": source_count,
        "stored_point_count": valid_count, "preview_count": preview_count,
        "preview_stride_bytes": PREVIEW_DTYPE.itemsize, "origin": origin.tolist(),
        "bbox_min": bbox_min.tolist(), "bbox_max": bbox_max.tolist(),
        "has_color": has_color, "has_intensity": has_intensity,
        "decimated": False, "dropped_non_finite": source_count - valid_count, "bounded_memory": True,
        "stream_chunk_points": POINT_STREAM_CHUNK_POINTS,
        "restart_policy": "replay_committed_prefix_then_continue", "crash_safe": True,
        "source_unchanged": True, "checksum_sha256": checksum,
        "source_identity": checkpoint_identity,
    }
    write_json_atomic(staged_files["meta"], metadata)
    cloud = {
        "point_count": source_count, "ingested_count": valid_count, "decimated": False,
        "size_bytes": int(source_identity["size_bytes"]), "sha256": checksum,
        "origin": origin.tolist(), "bbox_min": bbox_min.tolist(), "bbox_max": bbox_max.tolist(),
        "has_color": has_color, "has_intensity": has_intensity, "metadata": metadata,
    }
    result = {
        "cloud_id": cloud_id, "point_count": source_count, "ingested_count": valid_count,
        "preview_count": preview_count, "decimated": False, "warning": None,
    }
    files = {key: {"name": staged.name, **_file_record(staged)} for key, staged in staged_files.items()}
    manifest = {
        "version": INGEST_CHECKPOINT_VERSION, "cloud_id": cloud_id,
        "source_identity": checkpoint_identity, "files": files, "cloud": cloud, "result": result,
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
    full_e57_stream = source_path.suffix.lower() == ".e57" and MAX_INGEST_POINTS == 0
    full_las_stream = source_path.suffix.lower() in {".las", ".laz"} and MAX_INGEST_POINTS == 0
    full_text_stream = source_path.suffix.lower() in {".pts", ".xyz", ".txt", ".csv"} and MAX_INGEST_POINTS == 0
    full_pcd_stream = source_path.suffix.lower() == ".pcd" and MAX_INGEST_POINTS == 0
    full_ply_stream = source_path.suffix.lower() == ".ply" and MAX_INGEST_POINTS == 0
    preserve_raw_stream = full_rcs_stream and (stage_dir / "raw" / "stream.json").is_file()
    preserve_e57_stream = full_e57_stream and (stage_dir / "e57-write-checkpoint.json").is_file()
    preserve_las_stream = full_las_stream and (stage_dir / "las-write-checkpoint.json").is_file()
    preserve_text_stream = full_text_stream and (stage_dir / "text-write-checkpoint.json").is_file()
    preserve_pcd_stream = full_pcd_stream and (stage_dir / "pcd-write-checkpoint.json").is_file()
    preserve_ply_stream = full_ply_stream and (stage_dir / "ply-write-checkpoint.json").is_file()
    if stage_dir.exists() or any(paths[key].exists() for key in ("positions", "colors", "intensity", "preview", "meta")):
        _discard_incomplete_stage(
            stage_dir, paths, preserve_raw_stream=preserve_raw_stream,
            preserve_e57_stream=preserve_e57_stream, preserve_las_stream=preserve_las_stream,
            preserve_text_stream=preserve_text_stream,
            preserve_pcd_stream=preserve_pcd_stream,
            preserve_ply_stream=preserve_ply_stream,
        )
    source_identity = _source_identity(source_path)
    if full_e57_stream:
        return _ingest_full_e57_stream(
            project_id, cloud_id, source_path, paths, stage_dir, source_identity, progress
        )
    if full_las_stream:
        return _ingest_full_las_stream(
            project_id, cloud_id, source_path, paths, stage_dir, source_identity, progress
        )
    if full_text_stream:
        source_format = source_path.suffix.lower().lstrip(".")
        return _ingest_full_chunked_stream(
            project_id, cloud_id, source_path, paths, stage_dir, source_identity,
            source_format, "pandas",
            lambda path, chunk_points: iter_text_chunks(
                path, source_format, chunk_points=chunk_points,
            ),
            progress,
        )
    if full_pcd_stream:
        return _ingest_full_chunked_stream(
            project_id, cloud_id, source_path, paths, stage_dir, source_identity,
            "pcd", "pcd", iter_pcd_chunks, progress,
        )
    if full_ply_stream:
        return _ingest_full_chunked_stream(
            project_id, cloud_id, source_path, paths, stage_dir, source_identity,
            "ply", "ply-chunk", iter_ply_chunks, progress,
        )
    if full_rcs_stream:
        return _ingest_full_rcs_stream(
            project_id, cloud_id, source_path, paths, stage_dir, source_identity, progress
        )
    if progress:
        progress(0.01, "открытие исходного файла")
    # Stat identity alone misses same-size/same-mtime replacement. Hash before
    # decode and again before committing, including sources larger than 2 GiB.
    source_checksum = sha256_file(source_path)
    source_identity = {**source_identity, "sha256": source_checksum}
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

    checksum = source_checksum
    stat_identity = {key: value for key, value in source_identity.items() if key != "sha256"}
    if _source_identity(source_path) != stat_identity or sha256_file(source_path) != source_checksum:
        _discard_incomplete_stage(stage_dir, paths)
        raise RuntimeError("source content changed while cloud import was running")

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
