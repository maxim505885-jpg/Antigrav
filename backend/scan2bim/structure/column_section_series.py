"""Join conservative column surface tracks to source-linked section series."""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from .section_fitting import fit_column_section_series


_CANDIDATE_EDGES = {"u+", "u-", "v+", "v-"}
_REVIEWABLE_TRACK_STATES = {"candidate_track", "weak_candidate_track"}


def fit_column_track_sections(
    candidate_geometry: Mapping[str, Any],
    surface_tracks: Sequence[Mapping[str, Any]],
    xyz_world_m: np.ndarray,
    source_point_ids: np.ndarray,
    *,
    vertical_bin_m: float = 0.25,
    known_sides_m: tuple[float, float] | None = None,
    distance_tolerance_m: float = 0.004,
) -> dict[str, Any]:
    """Fit candidate-track points at every height bin, retaining provenance.

    The source-point array must use the same ID domain as each track's
    ``source_point_indices``. Unassigned surfaces are recorded and excluded.
    Empty height bins remain explicit unknown slices. The result is a review
    diagnostic only; it does not confirm a face, column, or catalog type.
    """
    if not isinstance(candidate_geometry, Mapping):
        raise ValueError("candidate_geometry must be a mapping")
    center = np.asarray(candidate_geometry.get("center"), dtype=np.float64)
    sizes = candidate_geometry.get("sizes")
    if center.shape != (3,) or not np.isfinite(center).all() or not isinstance(sizes, Mapping):
        raise ValueError("candidate geometry requires a finite center and sizes")
    try:
        length, thickness, height = (float(sizes[key]) for key in ("length", "thickness", "height"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("candidate geometry requires numeric positive sizes") from exc
    if not all(math.isfinite(value) and value > 0 for value in (length, thickness, height)):
        raise ValueError("candidate dimensions must be finite and positive")
    if not math.isfinite(float(vertical_bin_m)) or vertical_bin_m <= 0:
        raise ValueError("vertical_bin_m must be finite and positive")
    if not isinstance(surface_tracks, Sequence) or isinstance(surface_tracks, (str, bytes)):
        raise ValueError("surface_tracks must be a sequence")

    xyz = np.asarray(xyz_world_m, dtype=np.float64)
    row_ids = np.asarray(source_point_ids)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.isfinite(xyz).all():
        raise ValueError("xyz_world_m must be a finite N×3 array")
    if row_ids.shape != (len(xyz),) or not np.issubdtype(row_ids.dtype, np.integer):
        raise ValueError("source_point_ids must be an integer array matching xyz_world_m")
    row_ids = row_ids.astype(np.int64, copy=False)
    if len(np.unique(row_ids)) != len(row_ids):
        raise ValueError("source rows must be unique")

    accepted: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    seen_track_ids: set[str] = set()
    for track in surface_tracks:
        if not isinstance(track, Mapping):
            raise ValueError("each surface track must be a mapping")
        track_id = str(track.get("track_id", ""))
        if not track_id or track_id in seen_track_ids:
            raise ValueError("surface track IDs must be nonempty and unique")
        seen_track_ids.add(track_id)
        edge_id = track.get("candidate_edge_id")
        track_status = str(track.get("track_status", "unknown"))
        if edge_id not in _CANDIDATE_EDGES or track_status not in _REVIEWABLE_TRACK_STATES:
            excluded.append({"track_id": track_id, "reason": "no_supported_candidate_edge"})
            continue
        values = track.get("source_point_indices", [])
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise ValueError(f"track {track_id} source_point_indices must be a sequence")
        try:
            track_rows = [int(value) for value in values]
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"track {track_id} source point IDs must be integers") from exc
        if any(converted != original for converted, original in zip(track_rows, values)):
            raise ValueError(f"track {track_id} source point IDs must be integers")
        accepted.append({
            "track_id": track_id,
            "edge_id": str(edge_id),
            "track_status": track_status,
            "rows": sorted(set(track_rows)),
        })

    if not accepted:
        z_min, z_max = center[2] - height / 2, center[2] + height / 2
        empty_slices: list[dict[str, Any]] = []
        empty_bins: list[dict[str, Any]] = []
        for bin_id in range(math.floor(z_min / vertical_bin_m), math.ceil(z_max / vertical_bin_m)):
            lower = max(z_min, bin_id * vertical_bin_m)
            upper = min(z_max, (bin_id + 1) * vertical_bin_m)
            if upper <= lower:
                continue
            z_m = (lower + upper) / 2
            empty_slices.append({"z_m": z_m, "points_xy": np.empty((0, 2)), "source_point_ids": []})
            empty_bins.append({"bin_id": bin_id, "z_m": z_m, "source_point_count": 0, "track_evidence": []})
        series = fit_column_section_series(
            empty_slices, known_sides_m=known_sides_m,
            distance_tolerance_m=distance_tolerance_m,
        )
        for section in series["section_slices"]:
            section["track_evidence"] = []
            section["track_ids"] = []
        return {
            "schema": "scan.column-track-section-series/1",
            "candidate_id": candidate_geometry.get("id"),
            "candidate_track_count": 0,
            "excluded_tracks": excluded,
            "vertical_bin_m": float(vertical_bin_m),
            "height_bins": empty_bins,
            "section_series": series,
            "engineering_status": "not_assessed",
            "catalog_assignment": "none",
            "confirmed": False,
            "review_required": True,
            "source_geometry_modified": False,
        }

    sorted_order = np.argsort(row_ids, kind="stable")
    sorted_rows = row_ids[sorted_order]
    row_membership: dict[int, set[str]] = {}
    for track in accepted:
        requested = np.asarray(track["rows"], dtype=np.int64)
        if not len(requested):
            continue
        positions = np.searchsorted(sorted_rows, requested)
        found = positions < len(sorted_rows)
        found[found] &= sorted_rows[positions[found]] == requested[found]
        if not found.all():
            raise ValueError(f"track {track['track_id']} references missing source rows")
        local_indices = sorted_order[positions]
        z_min, z_max = center[2] - height / 2, center[2] + height / 2
        in_height = (xyz[local_indices, 2] >= z_min) & (xyz[local_indices, 2] <= z_max)
        for local_index, source_id in zip(local_indices[in_height], requested[in_height]):
            row_membership.setdefault(int(source_id), set()).add(track["track_id"])

    z_min, z_max = center[2] - height / 2, center[2] + height / 2
    first_bin = math.floor(z_min / vertical_bin_m)
    last_bin = math.ceil(z_max / vertical_bin_m)
    bins: list[dict[str, Any]] = []
    section_slices: list[dict[str, Any]] = []
    track_by_id = {track["track_id"]: track for track in accepted}
    for bin_id in range(first_bin, last_bin):
        lower = max(z_min, bin_id * vertical_bin_m)
        upper = min(z_max, (bin_id + 1) * vertical_bin_m)
        if upper <= lower:
            continue
        # Resolve rows by stable source ID; duplicate track membership is
        # collapsed for fitting but remains visible in track_evidence below.
        source_ids: list[int] = []
        evidence_rows: dict[str, set[int]] = {}
        for source_id, track_ids in row_membership.items():
            position = int(np.searchsorted(sorted_rows, source_id))
            local_index = int(sorted_order[position])
            z = float(xyz[local_index, 2])
            in_bin = lower <= z < upper or (upper == z_max and z == upper)
            if not in_bin:
                continue
            source_ids.append(source_id)
            for track_id in track_ids:
                evidence_rows.setdefault(track_id, set()).add(source_id)
        source_ids.sort()
        positions = np.searchsorted(sorted_rows, np.asarray(source_ids, dtype=np.int64))
        local_indices = sorted_order[positions]
        track_evidence = [
            {
                "track_id": track_id,
                "edge_id": track_by_id[track_id]["edge_id"],
                "track_status": track_by_id[track_id]["track_status"],
                "source_point_count": len(point_ids),
            }
            for track_id, point_ids in sorted(evidence_rows.items())
        ]
        bins.append({
            "bin_id": bin_id,
            "z_m": (lower + upper) / 2,
            "source_point_count": len(source_ids),
            "track_evidence": track_evidence,
        })
        section_slices.append({
            "z_m": (lower + upper) / 2,
            "points_xy": xyz[local_indices, :2],
            "source_point_ids": source_ids,
        })

    series = fit_column_section_series(
        section_slices, known_sides_m=known_sides_m,
        distance_tolerance_m=distance_tolerance_m,
    )
    by_z = {item["z_m"]: item for item in bins}
    for section in series["section_slices"]:
        evidence = by_z[section["z_m"]]["track_evidence"]
        section["track_evidence"] = evidence
        section["track_ids"] = [item["track_id"] for item in evidence]
    return {
        "schema": "scan.column-track-section-series/1",
        "candidate_id": candidate_geometry.get("id"),
        "candidate_track_count": len(accepted),
        "excluded_tracks": excluded,
        "vertical_bin_m": float(vertical_bin_m),
        "height_bins": bins,
        "section_series": series,
        "engineering_status": "not_assessed",
        "catalog_assignment": "none",
        "confirmed": False,
        "review_required": True,
        "source_geometry_modified": False,
    }
