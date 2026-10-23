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
    try:
        rotation_z = float(candidate_geometry.get("rotation_z", 0.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("candidate rotation_z must be finite") from exc
    if not math.isfinite(rotation_z):
        raise ValueError("candidate rotation_z must be finite")
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
    z_min, z_max = center[2] - height / 2, center[2] + height / 2
    delta_xy = xyz[:, :2] - center[:2]
    cosine, sine = math.cos(rotation_z), math.sin(rotation_z)
    local_u = cosine * delta_xy[:, 0] + sine * delta_xy[:, 1]
    local_v = -sine * delta_xy[:, 0] + cosine * delta_xy[:, 1]
    crop_margin = max(4 * float(distance_tolerance_m), 0.015)
    in_candidate_crop = (
        (np.abs(local_u) <= length / 2 + crop_margin)
        & (np.abs(local_v) <= thickness / 2 + crop_margin)
        & (xyz[:, 2] >= z_min)
        & (xyz[:, 2] <= z_max)
    )

    def built_up_points_for_bin(lower: float, upper: float) -> tuple[np.ndarray, list[int]]:
        in_bin = in_candidate_crop & (xyz[:, 2] >= lower) & (
            (xyz[:, 2] < upper) | ((upper == z_max) & (xyz[:, 2] <= upper))
        )
        local_indices = np.flatnonzero(in_bin)
        source_order = np.argsort(row_ids[local_indices], kind="stable")
        local_indices = local_indices[source_order]
        return xyz[local_indices, :2], row_ids[local_indices].tolist()

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
        empty_slices: list[dict[str, Any]] = []
        empty_bins: list[dict[str, Any]] = []
        for bin_id in range(math.floor(z_min / vertical_bin_m), math.ceil(z_max / vertical_bin_m)):
            lower = max(z_min, bin_id * vertical_bin_m)
            upper = min(z_max, (bin_id + 1) * vertical_bin_m)
            if upper <= lower:
                continue
            z_m = (lower + upper) / 2
            candidate_xy, candidate_rows = built_up_points_for_bin(lower, upper)
            empty_slices.append({
                "z_m": z_m,
                "points_xy": np.empty((0, 2)),
                "source_point_ids": [],
                "built_up_points_xy": candidate_xy,
                "built_up_source_point_ids": candidate_rows,
            })
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
    first_bin = math.floor(z_min / vertical_bin_m)
    last_bin = math.ceil(z_max / vertical_bin_m)
    track_local_parts: list[np.ndarray] = []
    track_id_parts: list[np.ndarray] = []
    for track_index, track in enumerate(accepted):
        requested = np.asarray(track["rows"], dtype=np.int64)
        if not len(requested):
            continue
        positions = np.searchsorted(sorted_rows, requested)
        found = positions < len(sorted_rows)
        found[found] &= sorted_rows[positions[found]] == requested[found]
        if not found.all():
            raise ValueError(f"track {track['track_id']} references missing source rows")
        local_indices = sorted_order[positions]
        in_height = (xyz[local_indices, 2] >= z_min) & (xyz[local_indices, 2] <= z_max)
        selected = local_indices[in_height]
        if len(selected):
            track_local_parts.append(selected)
            track_id_parts.append(np.full(len(selected), track_index, dtype=np.int32))

    if track_local_parts:
        association_local = np.concatenate(track_local_parts)
        association_track = np.concatenate(track_id_parts)
        association_order = np.lexsort((association_track, association_local))
        association_local = association_local[association_order]
        association_track = association_track[association_order]
        unique_local, association_counts = np.unique(association_local, return_counts=True)
    else:
        association_local = np.empty(0, dtype=np.int64)
        association_track = np.empty(0, dtype=np.int32)
        unique_local = np.empty(0, dtype=np.int64)
        association_counts = np.empty(0, dtype=np.int64)

    # Use the same clipped bin boundaries as the section loop. Searching the
    # boundary array preserves exact boundary behavior (including z_max in the
    # final slice) without rescanning every point once for every height bin.
    bin_ids = np.arange(first_bin, last_bin, dtype=np.int64)
    bin_lowers = np.maximum(z_min, bin_ids * vertical_bin_m)
    unique_z = xyz[unique_local, 2]
    bin_offsets = np.searchsorted(bin_lowers, unique_z, side="right") - 1
    unique_bins = bin_ids[bin_offsets]
    unique_bins[unique_z == z_max] = bin_ids[-1]
    association_unique = np.repeat(np.arange(len(unique_local), dtype=np.int64), association_counts)
    association_bins = unique_bins[association_unique]
    row_order = np.argsort(unique_bins, kind="stable")
    sorted_row_bins = unique_bins[row_order]
    association_bin_order = np.argsort(association_bins, kind="stable")
    sorted_association_bins = association_bins[association_bin_order]

    bins: list[dict[str, Any]] = []
    section_slices: list[dict[str, Any]] = []
    for bin_id in range(first_bin, last_bin):
        lower = max(z_min, bin_id * vertical_bin_m)
        upper = min(z_max, (bin_id + 1) * vertical_bin_m)
        if upper <= lower:
            continue
        row_begin = int(np.searchsorted(sorted_row_bins, bin_id, side="left"))
        row_end = int(np.searchsorted(sorted_row_bins, bin_id, side="right"))
        local_indices = unique_local[row_order[row_begin:row_end]]
        source_ids_array = row_ids[local_indices]
        source_order = np.argsort(source_ids_array, kind="stable")
        source_ids = source_ids_array[source_order].tolist()
        local_indices = local_indices[source_order]

        association_begin = int(np.searchsorted(sorted_association_bins, bin_id, side="left"))
        association_end = int(np.searchsorted(sorted_association_bins, bin_id, side="right"))
        track_counts = np.bincount(
            association_track[association_bin_order[association_begin:association_end]],
            minlength=len(accepted),
        )
        track_evidence = [
            {
                "track_id": accepted[index]["track_id"],
                "edge_id": accepted[index]["edge_id"],
                "track_status": accepted[index]["track_status"],
                "source_point_count": int(track_counts[index]),
            }
            for index in sorted(range(len(accepted)), key=lambda value: accepted[value]["track_id"])
            if track_counts[index] > 0
        ]
        bins.append({
            "bin_id": bin_id,
            "z_m": (lower + upper) / 2,
            "source_point_count": len(local_indices),
            "track_evidence": track_evidence,
        })
        built_up_xy, built_up_source_ids = built_up_points_for_bin(lower, upper)
        section_slices.append({
            "z_m": (lower + upper) / 2,
            "points_xy": xyz[local_indices, :2],
            "source_point_ids": source_ids,
            "built_up_points_xy": built_up_xy,
            "built_up_source_point_ids": built_up_source_ids,
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
