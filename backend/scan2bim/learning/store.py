"""Storage of engineer-reviewed examples and their source points."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from ..db import dumps, execute, loads, new_id, one, rows, utcnow
from ..storage import cached_sha256_file, cloud_paths, project_dir
from .features import features_from_element

CHUNK = 2_000_000
MAX_SAMPLE_POINTS = 20000
MEMBER_AXIS_SOURCE_CORRIDOR_M = 0.55
MEMBER_AXIS_ENDPOINT_BUFFER_M = 0.35


def point_cloud_snapshot(
    cloud_id: str,
    positions_path: str | Path,
    point_count: int,
    origin: np.ndarray | list[float],
) -> dict[str, Any]:
    """Identify the exact stored position array and coordinate origin for row IDs."""
    if not isinstance(cloud_id, str) or not cloud_id.strip():
        raise ValueError("cloud_id must be a non-empty string")
    if isinstance(point_count, bool) or not isinstance(point_count, int) or point_count < 0:
        raise ValueError("point_count must be a non-negative integer")
    origin_values = np.asarray(origin, dtype=np.float64)
    if origin_values.shape != (3,) or not np.isfinite(origin_values).all():
        raise ValueError("origin must contain three finite coordinates")
    document = {
        "cloud_id": cloud_id,
        "point_count": point_count,
        "positions_sha256": cached_sha256_file(Path(positions_path)),
        "origin_m": [float(value) for value in origin_values],
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**document, "snapshot_id": hashlib.sha256(encoded).hexdigest()}


def element_bbox_coordinate_frame(element: dict[str, Any]) -> str:
    """Return the frame used by this persisted element's bbox.

    Older geometric recognizer rows stored positions relative to the cloud
    origin. The current recognizer emits source-cloud-world geometry, and now
    stamps that frame explicitly so mixed-age databases remain readable.
    """
    metadata = element.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    frame = metadata.get("bbox_coordinate_frame")
    if frame is not None:
        if not isinstance(frame, str) or frame not in {"cloud_local", "source_cloud_world"}:
            raise ValueError("unsupported bbox coordinate frame")
        return frame
    if element.get("source") in {"geometric", "structural_grid"}:
        return "cloud_local"
    return "source_cloud_world"


def _cloud(cloud_id: str) -> dict[str, Any]:
    cloud = one("SELECT * FROM clouds WHERE id = ?", (cloud_id,))
    if not cloud:
        raise ValueError(f"cloud {cloud_id} not found")
    return cloud


def current_point_cloud_snapshot(cloud_id: str) -> dict[str, Any]:
    cloud = _cloud(cloud_id)
    positions_path = cloud_paths(cloud["project_id"], cloud_id)["positions"]
    positions = np.load(positions_path, mmap_mode="r", allow_pickle=False)
    try:
        count = len(positions)
    finally:
        mmap = getattr(positions, "_mmap", None)
        if mmap is not None:
            mmap.close()
    origin = [cloud["origin_x"] or 0.0, cloud["origin_y"] or 0.0, cloud["origin_z"] or 0.0]
    return point_cloud_snapshot(cloud_id, positions_path, count, origin)


def validate_training_sample_source(cloud_id: str, element: dict[str, Any]) -> dict[str, Any]:
    """Require a review candidate's point evidence to describe the current cloud."""
    current = current_point_cloud_snapshot(cloud_id)
    metadata = element.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    saved = metadata.get("source_cloud_snapshot")
    if not isinstance(saved, dict):
        raise ValueError(
            "candidate has no source cloud snapshot; rerun recognition before creating training data"
        )
    if saved.get("cloud_id") != cloud_id or saved.get("snapshot_id") != current["snapshot_id"]:
        raise ValueError(
            "cloud snapshot changed after recognition; rerun recognition before creating training data"
        )
    evidence = inspect_source_point_alignment(
        cloud_id, element, element_bbox_coordinate_frame(element),
    )
    if evidence["status"] == "mismatch":
        raise ValueError(
            "source row IDs do not match the current cloud and candidate bbox; review or rerun recognition"
        )
    return current


def extract_element_points(
    cloud_id: str,
    bbox: dict[str, Any],
    limit: int = MAX_SAMPLE_POINTS,
    margin: float = 0.05,
    coordinate_frame: str = "source_cloud_world",
    degenerate_context_half_extent_m: float | None = None,
) -> np.ndarray:
    cloud = _cloud(cloud_id)
    paths = cloud_paths(cloud["project_id"], cloud_id)
    if not paths["positions"].exists():
        return np.empty((0, 3), dtype=np.float32)
    origin = np.array(
        [cloud["origin_x"] or 0.0, cloud["origin_y"] or 0.0, cloud["origin_z"] or 0.0],
        dtype=np.float64,
    )
    if not isinstance(coordinate_frame, str) or coordinate_frame not in {"cloud_local", "source_cloud_world"}:
        raise ValueError("unsupported element bbox coordinate frame")
    if degenerate_context_half_extent_m is not None and (
        not np.isfinite(degenerate_context_half_extent_m) or degenerate_context_half_extent_m <= 0
    ):
        raise ValueError("degenerate context half extent must be positive and finite")
    try:
        mn = np.array(bbox["min"], dtype=np.float64)
        mx = np.array(bbox["max"], dtype=np.float64)
        if mn.shape != (3,) or mx.shape != (3,) or not np.isfinite(mn).all() or not np.isfinite(mx).all():
            raise ValueError("bbox bounds must be finite 3D coordinates")
        if np.any(mn > mx):
            raise ValueError("bbox minimum exceeds maximum")
        if coordinate_frame == "source_cloud_world":
            mn -= origin
            mx -= origin
        if degenerate_context_half_extent_m is not None:
            center = (mn + mx) / 2
            half = (mx - mn) / 2
            half = np.where(half <= 1e-6, degenerate_context_half_extent_m, half)
            mn = center - half - margin
            mx = center + half + margin
        else:
            mn -= margin
            mx += margin
    except Exception:
        return np.empty((0, 3), dtype=np.float32)
    arr = np.load(paths["positions"], mmap_mode="r")
    parts: list[np.ndarray] = []
    found = 0
    for start in range(0, arr.shape[0], CHUNK):
        chunk = np.asarray(arr[start : start + CHUNK])
        mask = np.all(chunk >= mn, axis=1) & np.all(chunk <= mx, axis=1)
        if not np.any(mask):
            continue
        picked = chunk[mask]
        if len(picked) > limit:
            idx = np.random.default_rng(3).choice(len(picked), size=limit, replace=False)
            picked = picked[idx]
        parts.append(picked.astype(np.float32) + origin.astype(np.float32))
        found += len(picked)
        if found >= limit:
            break
    if not parts:
        return np.empty((0, 3), dtype=np.float32)
    points = np.concatenate(parts)
    if len(points) > limit:
        idx = np.random.default_rng(4).choice(len(points), size=limit, replace=False)
        points = points[idx]
    return points


def inspect_source_point_alignment(
    cloud_id: str,
    element: dict[str, Any],
    coordinate_frame: str,
    margin: float = 0.05,
    max_checked_ids: int = 20_000,
) -> dict[str, Any]:
    """Check whether persisted source row IDs still describe this cloud/bbox.

    This is a provenance integrity check, not an element-accuracy score. It is
    intentionally bounded because candidate metadata can contain many rows.
    """
    metadata = element.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    raw_ids = metadata.get("source_point_ids")
    index_space = metadata.get("source_point_id_space")
    if not isinstance(raw_ids, list) or not raw_ids:
        return {
            "status": "unverifiable",
            "reason": "missing_source_point_ids",
            "row_ids_count": len(raw_ids) if isinstance(raw_ids, list) else 0,
            "row_ids_valid_count": 0,
            "row_ids_within_bbox_count": 0,
            "row_ids_within_geometry_count": 0,
            "geometry_check": "unavailable",
            "row_ids_sampled": bool(metadata.get("source_point_ids_sampled")),
        }
    if index_space != "positions.npy row index":
        return {
            "status": "unverifiable",
            "reason": "unsupported_source_point_id_space",
            "row_ids_count": len(raw_ids),
            "row_ids_valid_count": 0,
            "row_ids_within_bbox_count": 0,
            "row_ids_within_geometry_count": 0,
            "geometry_check": "unavailable",
            "row_ids_sampled": bool(metadata.get("source_point_ids_sampled")),
        }
    if not isinstance(coordinate_frame, str) or coordinate_frame not in {"cloud_local", "source_cloud_world"}:
        raise ValueError("unsupported element bbox coordinate frame")
    try:
        if max_checked_ids <= 0:
            raise ValueError("max checked IDs must be positive")
        numeric_ids = np.asarray(raw_ids, dtype=np.float64).reshape(-1)
        if len(numeric_ids) > max_checked_ids:
            selection = np.linspace(0, len(numeric_ids) - 1, max_checked_ids, dtype=np.int64)
            numeric_ids = numeric_ids[selection]
        checked_count = len(numeric_ids)
        integer_ids = np.isfinite(numeric_ids) & (numeric_ids == np.floor(numeric_ids))
        candidate_ids = numeric_ids[integer_ids].astype(np.int64)
        cloud = _cloud(cloud_id)
        positions_path = cloud_paths(cloud["project_id"], cloud_id)["positions"]
        if not positions_path.exists():
            raise FileNotFoundError(positions_path)
        positions = np.load(positions_path, mmap_mode="r")
        origin = np.array(
            [cloud["origin_x"] or 0.0, cloud["origin_y"] or 0.0, cloud["origin_z"] or 0.0],
            dtype=np.float64,
        )
        saved_snapshot = metadata.get("source_cloud_snapshot")
        snapshot_matches: bool | None = None
        if saved_snapshot is not None:
            current_snapshot = point_cloud_snapshot(
                cloud_id,
                positions_path,
                len(positions),
                origin,
            )
            snapshot_matches = (
                isinstance(saved_snapshot, dict)
                and saved_snapshot.get("cloud_id") == cloud_id
                and saved_snapshot.get("snapshot_id") == current_snapshot["snapshot_id"]
            )
            if not snapshot_matches:
                return {
                    "status": "mismatch",
                    "reason": "source_cloud_snapshot_changed",
                    "row_ids_count": len(raw_ids),
                    "row_ids_checked_count": 0,
                    "row_ids_valid_count": 0,
                    "row_ids_within_bbox_count": 0,
                    "row_ids_within_geometry_count": 0,
                    "geometry_check": "unavailable",
                    "row_ids_sampled": bool(metadata.get("source_point_ids_sampled")),
                    "snapshot_matches": False,
                }
        valid_ids = candidate_ids[(candidate_ids >= 0) & (candidate_ids < len(positions))]
        if not len(valid_ids):
            valid_points = np.empty((0, 3), dtype=np.float64)
        else:
            valid_points = np.asarray(positions[valid_ids], dtype=np.float64)
        bbox = element.get("bbox") or {}
        mn = np.asarray(bbox["min"], dtype=np.float64)
        mx = np.asarray(bbox["max"], dtype=np.float64)
        if mn.shape != (3,) or mx.shape != (3,) or not np.isfinite(mn).all() or not np.isfinite(mx).all() or np.any(mn > mx):
            raise ValueError("invalid bbox")
        if coordinate_frame == "source_cloud_world":
            mn -= origin
            mx -= origin
        within_bbox = np.all((valid_points >= mn - margin) & (valid_points <= mx + margin), axis=1)
        within_bbox_count = int(within_bbox.sum())
        geometry = element.get("geometry")
        geometry = geometry if isinstance(geometry, dict) else {}
        geometry_check = "bbox"
        within_geometry = within_bbox
        if geometry.get("kind") == "member":
            p0 = np.asarray(geometry.get("p0"), dtype=np.float64)
            p1 = np.asarray(geometry.get("p1"), dtype=np.float64)
            if (p0.shape != (3,) or p1.shape != (3,) or not np.isfinite(p0).all()
                    or not np.isfinite(p1).all()):
                raise ValueError("invalid member axis geometry")
            axis = p1 - p0
            axis_length = float(np.linalg.norm(axis))
            if not math.isfinite(axis_length) or axis_length <= 1e-9:
                raise ValueError("member axis geometry must have positive length")
            measured_points = (
                valid_points + origin if coordinate_frame == "source_cloud_world"
                else valid_points
            )
            fractions = ((measured_points - p0) @ axis) / (axis_length * axis_length)
            closest = p0 + np.clip(fractions, 0.0, 1.0)[:, None] * axis
            distances = np.linalg.norm(measured_points - closest, axis=1)
            # This corridor covers the recognizer's section-slice selection,
            # including 0.45 m plane thickness, up to 0.20 m line offset, and
            # raster/Hough quantization. It is provenance support, not an
            # engineering tolerance or a fitted section size.
            within_geometry = (
                (fractions >= -MEMBER_AXIS_ENDPOINT_BUFFER_M / axis_length)
                & (fractions <= 1.0 + MEMBER_AXIS_ENDPOINT_BUFFER_M / axis_length)
                & (distances <= MEMBER_AXIS_SOURCE_CORRIDOR_M)
            )
            geometry_check = "member_axis"
        within_geometry_count = int(within_geometry.sum())
        valid_count = len(valid_ids)
        alignment_status = "consistent" if (
            checked_count > 0
            and valid_count / checked_count >= 0.95
            and within_geometry_count / valid_count >= 0.95
        ) else "mismatch"
        has_snapshot = snapshot_matches is True
        status = alignment_status if has_snapshot or alignment_status == "mismatch" else "unverifiable"
        reason = (
            (
                "source_point_ids_bbox_mismatch" if geometry_check == "bbox"
                else "source_point_ids_member_axis_mismatch"
            ) if alignment_status == "mismatch"
            else "missing_source_cloud_snapshot" if not has_snapshot
            else None
        )
        evidence = {
            "status": status,
            "row_ids_count": len(raw_ids),
            "row_ids_checked_count": checked_count,
            "row_ids_valid_count": valid_count,
            "row_ids_within_bbox_count": within_bbox_count,
            "row_ids_within_geometry_count": within_geometry_count,
            "geometry_check": geometry_check,
            "row_ids_sampled": bool(metadata.get("source_point_ids_sampled")),
        }
        if reason is not None:
            evidence["reason"] = reason
        if snapshot_matches is not None:
            evidence["snapshot_matches"] = snapshot_matches
        return evidence
    except (OSError, ValueError, TypeError, OverflowError):
        return {
            "status": "unverifiable",
            "reason": "source_point_evidence_could_not_be_read",
            "row_ids_count": len(raw_ids),
            "row_ids_valid_count": 0,
            "row_ids_within_bbox_count": 0,
            "row_ids_within_geometry_count": 0,
            "geometry_check": "unavailable",
            "row_ids_sampled": bool(metadata.get("source_point_ids_sampled")),
        }


def create_sample(
    project_id: str,
    cloud_id: str,
    element: dict[str, Any],
    class_name: str | None = None,
    split: str = "train",
    source: str = "engineer",
    element_id: str | None = None,
    physical_instance_id: str | None = None,
) -> dict[str, Any]:
    source_snapshot = validate_training_sample_source(cloud_id, element)
    sample_id = new_id()
    label = class_name or element.get("class_name") or "unknown"
    features = features_from_element(element)
    points_path = project_dir(project_id) / "training" / f"{sample_id}.npy"
    points_path.parent.mkdir(parents=True, exist_ok=True)
    points = extract_element_points(
        cloud_id,
        element.get("bbox") or {},
        coordinate_frame=element_bbox_coordinate_frame(element),
    )
    if not len(points):
        raise ValueError("no source points fall inside the reviewed element bbox")
    if current_point_cloud_snapshot(cloud_id)["snapshot_id"] != source_snapshot["snapshot_id"]:
        raise ValueError("cloud snapshot changed while collecting the training sample")
    np.save(points_path, points)
    execute(
        """
        INSERT INTO training_samples
        (id, project_id, cloud_id, element_id, class_name, physical_instance_id, source_snapshot_id,
         features_json, points_path, split, source, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            sample_id,
            project_id,
            cloud_id,
            element_id or element.get("id"),
            label,
            physical_instance_id,
            source_snapshot["snapshot_id"],
            dumps(features),
            str(points_path),
            split,
            source,
            utcnow(),
        ),
    )
    return {
        "id": sample_id,
        "project_id": project_id,
        "cloud_id": cloud_id,
        "element_id": element_id or element.get("id"),
        "class_name": label,
        "physical_instance_id": physical_instance_id,
        "source_snapshot_id": source_snapshot["snapshot_id"],
        "features": features,
        "split": split,
        "source": source,
        "point_count": int(len(points)),
        "created_at": utcnow(),
    }


def list_samples(project_id: str, split: str | None = None) -> list[dict[str, Any]]:
    if split:
        records = rows(
            "SELECT * FROM training_samples WHERE project_id = ? AND split = ? ORDER BY created_at DESC",
            (project_id, split),
        )
    else:
        records = rows(
            "SELECT * FROM training_samples WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,),
        )
    result = []
    for rec in records:
        rec = dict(rec)
        rec["features"] = loads(rec.get("features_json"), {})
        rec.pop("features_json", None)
        result.append(rec)
    return result


def samples_for_training(project_id: str) -> list[dict[str, Any]]:
    # Only explicit engineer-reviewed annotations can be used as labels. Keeping
    # this allowlist strict prevents imported, generated, or invalidated records
    # from silently entering a future training run.
    return [sample for sample in list_samples(project_id) if sample.get("source") == "engineer"]


def similar_samples(project_id: str, features: dict[str, float], k: int = 5) -> list[dict[str, Any]]:
    samples = [sample for sample in list_samples(project_id) if sample.get("source") == "engineer"]
    if not samples:
        return []
    names = list(features.keys())
    X = np.asarray(
        [[float(s["features"].get(name, 0.0)) for name in names] for s in samples],
        dtype=np.float64,
    )
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std < 1e-9] = 1.0
    v = (np.asarray([float(features.get(name, 0.0)) for name in names]) - mean) / std
    distances = np.linalg.norm((X - mean) / std - v, axis=1)
    order = np.argsort(distances)[:k]
    out = []
    for idx in order:
        sample = dict(samples[int(idx)])
        sample["distance"] = round(float(distances[int(idx)]), 5)
        sample["features"] = sample["features"]
        out.append(sample)
    return out
