"""Associate observed vertical planes with candidate OBB faces for review.

These geometric thresholds are association settings, not engineering tolerances.
The result is evidence for a human reviewer; it never confirms a column or type.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np


def _finite_vector(value: Any, size: int, name: str) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float64)
    if vector.shape != (size,) or not np.isfinite(vector).all():
        raise ValueError(f"{name} must contain {size} finite numbers")
    return vector


def _longest_run(values: list[int]) -> int:
    longest = current = 0
    previous: int | None = None
    for value in sorted(set(values)):
        current = current + 1 if previous is not None and value == previous + 1 else 1
        longest = max(longest, current)
        previous = value
    return longest


def associate_surfaces_to_column(
    candidate_geometry: Mapping[str, Any],
    surface_result: Mapping[str, Any],
    *,
    max_normal_deviation_degrees: float = 8.0,
    max_boundary_offset_m: float = 0.10,
    min_edge_overlap_fraction: float = 0.20,
    min_vertical_support_fraction: float = 0.25,
    vertical_bin_m: float = 0.25,
) -> dict[str, Any]:
    """Match observed plane strips to nearby faces of one oriented candidate box.

    A match means only that an observed plane is geometrically compatible with
    a candidate face. Walls, cladding, beams, and scan artifacts can still
    produce compatible matches, so ownership and structural role remain unknown.
    """
    center = _finite_vector(candidate_geometry.get("center"), 3, "candidate center")
    sizes = candidate_geometry.get("sizes")
    if not isinstance(sizes, Mapping):
        raise ValueError("candidate sizes are required")
    try:
        length, thickness, height = (float(sizes[key]) for key in ("length", "thickness", "height"))
        angle = float(candidate_geometry.get("rotation_z", 0.0))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("candidate sizes and rotation must be numeric") from exc
    settings = (max_normal_deviation_degrees, max_boundary_offset_m,
                min_edge_overlap_fraction, min_vertical_support_fraction, vertical_bin_m)
    if not all(math.isfinite(float(value)) for value in settings):
        raise ValueError("association settings must be finite")
    if min(length, thickness, height) <= 0 or not math.isfinite(angle):
        raise ValueError("candidate dimensions must be positive and rotation finite")
    if not 0 < max_normal_deviation_degrees < 45 or max_boundary_offset_m < 0:
        raise ValueError("invalid orientation or boundary association setting")
    if not 0 < min_edge_overlap_fraction <= 1 or not 0 < min_vertical_support_fraction <= 1 or vertical_bin_m <= 0:
        raise ValueError("invalid overlap or vertical support setting")

    u = np.array([math.cos(angle), math.sin(angle)], dtype=np.float64)
    v = np.array([-math.sin(angle), math.cos(angle)], dtype=np.float64)
    half_length, half_thickness = length / 2, thickness / 2
    z_min, z_max = center[2] - height / 2, center[2] + height / 2
    box_z_bins = set(range(math.floor(z_min / vertical_bin_m), math.ceil(z_max / vertical_bin_m)))
    edges = (
        ("u+", u, float(np.dot(u, center[:2]) + half_length), v, half_thickness),
        ("u-", u, float(np.dot(u, center[:2]) - half_length), v, half_thickness),
        ("v+", v, float(np.dot(v, center[:2]) + half_thickness), -u, half_length),
        ("v-", v, float(np.dot(v, center[:2]) - half_thickness), -u, half_length),
    )

    surfaces = surface_result.get("surfaces", [])
    if not isinstance(surfaces, (list, tuple)):
        raise ValueError("surface_result.surfaces must be a list")
    associations: list[dict[str, Any]] = []
    for surface in surfaces:
        if not isinstance(surface, Mapping):
            raise ValueError("each surface observation must be a mapping")
        normal = _finite_vector(surface.get("normal_xy"), 2, "surface normal")
        normal_norm = float(np.linalg.norm(normal))
        if normal_norm <= 1e-12:
            raise ValueError("surface normal must be non-zero")
        normal /= normal_norm
        offset = float(surface.get("line_offset_m", math.nan))
        anchor = _finite_vector(surface.get("line_anchor_xy_world_m"), 2, "surface anchor")
        span_bounds = _finite_vector(surface.get("line_span_bounds_from_anchor_m"), 2, "surface span bounds")
        z_bounds = _finite_vector(surface.get("z_bounds_world_m"), 2, "surface z bounds")
        if not np.isfinite(offset) or span_bounds[1] <= span_bounds[0] or z_bounds[1] < z_bounds[0]:
            raise ValueError("surface line or height bounds are invalid")

        occupied_bins = surface.get("occupied_z_bin_ids")
        if isinstance(occupied_bins, (list, tuple)) and occupied_bins:
            overlapping_bins = [int(value) for value in occupied_bins if int(value) in box_z_bins]
            continuous_height = min(_longest_run(overlapping_bins) * vertical_bin_m, height)
        else:
            z_overlap = max(0.0, min(z_max, z_bounds[1]) - max(z_min, z_bounds[0]))
            reported_continuous = float(surface.get("longest_consecutive_vertical_span_m", z_bounds[1] - z_bounds[0]))
            continuous_height = min(z_overlap, max(0.0, reported_continuous))
        vertical_fraction = continuous_height / height

        tangent = np.array([-normal[1], normal[0]], dtype=np.float64)
        observed_endpoints = np.stack((anchor + tangent * span_bounds[0], anchor + tangent * span_bounds[1]))

        edge_measurements: list[dict[str, Any]] = []
        for edge_id, edge_normal, edge_offset, edge_tangent, half_span in edges:
            dot = float(np.dot(normal, edge_normal))
            normal_deviation = math.degrees(math.acos(float(np.clip(abs(dot), -1.0, 1.0))))
            aligned_offset = offset if dot >= 0 else -offset
            boundary_distance = abs(aligned_offset - edge_offset)
            projected = observed_endpoints @ edge_tangent
            observed_low, observed_high = float(projected.min()), float(projected.max())
            edge_center = float(np.dot(edge_tangent, center[:2]))
            edge_low, edge_high = edge_center - half_span, edge_center + half_span
            overlap = max(0.0, min(observed_high, edge_high) - max(observed_low, edge_low))
            candidate_edge_coverage = overlap / max(2 * half_span, 1e-12)
            observed_span_inside_fraction = overlap / max(observed_high - observed_low, 1e-12)
            edge_measurements.append({
                "candidate_edge_id": edge_id,
                "normal_deviation_degrees": normal_deviation,
                "boundary_offset_m": boundary_distance,
                "observed_edge_coverage_fraction": float(candidate_edge_coverage),
                "observed_span_inside_fraction": float(observed_span_inside_fraction),
                "normal_matches": normal_deviation <= max_normal_deviation_degrees,
                "boundary_matches": boundary_distance <= max_boundary_offset_m,
                "span_matches": candidate_edge_coverage >= min_edge_overlap_fraction,
            })

        geometrically_compatible = [item for item in edge_measurements
                                    if item["normal_matches"] and item["boundary_matches"] and item["span_matches"]]
        result: dict[str, Any] = {
            "plane_id": str(surface.get("plane_id", "")),
            "candidate_edge_id": None,
            "association_status": "outside_candidate_boundary",
            "potential_candidate_edges": sorted(item["candidate_edge_id"] for item in geometrically_compatible),
            "candidate_edges": [],
            "continuous_vertical_support_m": continuous_height,
            "vertical_support_fraction": float(vertical_fraction),
            "review_required": True,
        }
        if not edge_measurements:
            result["association_status"] = "no_candidate_edges"
        else:
            best = min(edge_measurements, key=lambda item: (
                item["normal_deviation_degrees"] / max_normal_deviation_degrees
                + item["boundary_offset_m"] / max(max_boundary_offset_m, 1e-12)
                + 1 - item["observed_edge_coverage_fraction"]
            ))
            result.update({key: best[key] for key in (
                "normal_deviation_degrees", "boundary_offset_m",
                "observed_edge_coverage_fraction", "observed_span_inside_fraction")})
            if not geometrically_compatible:
                if not any(item["normal_matches"] for item in edge_measurements):
                    result["association_status"] = "orientation_mismatch"
                elif not any(item["boundary_matches"] and item["normal_matches"] for item in edge_measurements):
                    result["association_status"] = "outside_candidate_boundary"
                else:
                    result["association_status"] = "outside_candidate_span"
            elif vertical_fraction < min_vertical_support_fraction:
                result["association_status"] = "insufficient_vertical_support"
            elif len(geometrically_compatible) == 1:
                result["association_status"] = "candidate_face"
                result["candidate_edge_id"] = geometrically_compatible[0]["candidate_edge_id"]
                result["candidate_edges"] = [geometrically_compatible[0]["candidate_edge_id"]]
            elif len(geometrically_compatible) > 1:
                result["association_status"] = "ambiguous_candidate_face"
                result["candidate_edges"] = sorted(item["candidate_edge_id"] for item in geometrically_compatible)
        associations.append(result)

    assigned_edges = {item["candidate_edge_id"] for item in associations
                      if item["association_status"] == "candidate_face"}
    edge_count = len(assigned_edges)
    status = "four_candidate_faces" if edge_count == 4 else "partial_candidate_faces" if edge_count else "no_candidate_faces"
    return {
        "candidate_id": candidate_geometry.get("id"),
        "association_status": status,
        "candidate_edge_count": edge_count,
        "candidate_edges": sorted(assigned_edges),
        "surface_associations": associations,
        "structural_role": "unknown",
        "confirmed": False,
        "review_required": True,
        "engineering_status": "not_assessed",
        "association_settings": {
            "max_normal_deviation_degrees": max_normal_deviation_degrees,
            "max_boundary_offset_m": max_boundary_offset_m,
            "min_edge_overlap_fraction": min_edge_overlap_fraction,
            "min_vertical_support_fraction": min_vertical_support_fraction,
            "vertical_bin_m": vertical_bin_m,
            "settings_are_engineering_tolerances": False,
        },
    }


def cluster_column_surface_tracks(
    candidate_geometry: Mapping[str, Any],
    surface_result: Mapping[str, Any],
    association_result: Mapping[str, Any],
    *,
    max_track_normal_deviation_degrees: float = 5.0,
    max_track_boundary_delta_m: float = 0.04,
    min_track_span_overlap_fraction: float = 0.25,
    max_track_endpoint_gap_m: float = 0.05,
    vertical_bin_m: float = 0.25,
) -> list[dict[str, Any]]:
    """Cluster compatible observations into review-only, source-linked face tracks.

    Fragments merge only when they refer to one unambiguous candidate edge,
    share vertical occupancy, follow the same plane, overlap along the face,
    and remain inside its finite footprint. This intentionally leaves gaps as
    separate tracks; it does not imply ownership, continuity behind occlusion,
    structural role, or an engineering tolerance.
    """
    center = _finite_vector(candidate_geometry.get("center"), 3, "candidate center")
    sizes = candidate_geometry.get("sizes")
    if not isinstance(sizes, Mapping):
        raise ValueError("candidate sizes are required")
    try:
        length, thickness, height = (float(sizes[key]) for key in ("length", "thickness", "height"))
        angle = float(candidate_geometry.get("rotation_z", 0.0))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("candidate sizes and rotation must be numeric") from exc
    settings = (max_track_normal_deviation_degrees, max_track_boundary_delta_m,
                min_track_span_overlap_fraction, max_track_endpoint_gap_m, vertical_bin_m)
    if (not all(math.isfinite(float(value)) for value in settings)
            or min(length, thickness, height) <= 0 or not math.isfinite(angle)
            or not 0 < max_track_normal_deviation_degrees < 45
            or max_track_boundary_delta_m < 0
            or not 0 < min_track_span_overlap_fraction <= 1
            or max_track_endpoint_gap_m < 0
            or vertical_bin_m <= 0):
        raise ValueError("invalid track geometry or association setting")

    surfaces = surface_result.get("surfaces", [])
    associations = association_result.get("surface_associations", [])
    if not isinstance(surfaces, (list, tuple)) or not isinstance(associations, (list, tuple)):
        raise ValueError("surfaces and surface associations must be lists")
    association_by_id = {str(item.get("plane_id", "")): item for item in associations
                         if isinstance(item, Mapping)}
    if len(association_by_id) != len(associations):
        raise ValueError("surface association plane IDs must be unique")

    u = np.array([math.cos(angle), math.sin(angle)], dtype=np.float64)
    v = np.array([-math.sin(angle), math.cos(angle)], dtype=np.float64)
    edge_geometry = {
        "u+": (u, float(np.dot(u, center[:2]) + length / 2), v, length),
        "u-": (u, float(np.dot(u, center[:2]) - length / 2), v, length),
        "v+": (v, float(np.dot(v, center[:2]) + thickness / 2), -u, thickness),
        "v-": (v, float(np.dot(v, center[:2]) - thickness / 2), -u, thickness),
    }
    candidate_z_min, candidate_z_max = center[2] - height / 2, center[2] + height / 2
    candidate_bins = set(range(math.floor(candidate_z_min / vertical_bin_m),
                               math.ceil(candidate_z_max / vertical_bin_m)))
    observations: list[dict[str, Any]] = []
    for surface in surfaces:
        if not isinstance(surface, Mapping):
            raise ValueError("each surface observation must be a mapping")
        plane_id = str(surface.get("plane_id", ""))
        association = association_by_id.get(plane_id)
        if association is None:
            raise ValueError(f"surface {plane_id!r} has no matching association")
        exclusion_reasons: list[str] = []
        edge_id = association.get("candidate_edge_id")
        if association.get("association_status") == "insufficient_vertical_support":
            potential = association.get("potential_candidate_edges", [])
            edge_id = potential[0] if len(potential) == 1 else None
        if edge_id not in edge_geometry:
            exclusion_reasons.append(
                "association_" + str(association.get("association_status", "no_candidate_edge"))
            )
            edge_id = None

        normal = _finite_vector(surface.get("normal_xy"), 2, "surface normal")
        normal_norm = float(np.linalg.norm(normal))
        if normal_norm <= 1e-12:
            raise ValueError("surface normal must be non-zero")
        normal = normal / normal_norm
        offset = float(surface.get("line_offset_m", math.nan))
        anchor = _finite_vector(surface.get("line_anchor_xy_world_m"), 2, "surface anchor")
        span = _finite_vector(surface.get("line_span_bounds_from_anchor_m"), 2, "surface span bounds")
        if not math.isfinite(offset) or span[1] <= span[0]:
            raise ValueError("surface line bounds are invalid")
        tangent = _finite_vector(surface.get("line_direction_xy"), 2, "surface line direction")
        tangent_norm = float(np.linalg.norm(tangent))
        if tangent_norm <= 1e-12:
            raise ValueError("surface line direction must be non-zero")
        tangent /= tangent_norm
        endpoints = np.stack((anchor + tangent * span[0], anchor + tangent * span[1]))
        point_indices = surface.get("source_crop_row_ids", surface.get("input_point_indices", []))
        if not isinstance(point_indices, (list, tuple)):
            raise ValueError("surface point provenance must be a list")
        try:
            point_indices = sorted({int(value) for value in point_indices})
        except (TypeError, ValueError) as exc:
            raise ValueError("surface point provenance must contain integers") from exc

        edge_position = None
        vertical_bins = {int(value) for value in surface.get("occupied_z_bin_ids", [])}
        if not vertical_bins:
            z_bounds = _finite_vector(surface.get("z_bounds_world_m"), 2, "surface z bounds")
            if z_bounds[1] >= z_bounds[0]:
                vertical_bins = set(range(math.floor(z_bounds[0] / vertical_bin_m),
                                          math.ceil(z_bounds[1] / vertical_bin_m)))
        if not vertical_bins.intersection(candidate_bins):
            exclusion_reasons.append("outside_candidate_vertical_extent")
            edge_id = None
        if edge_id is not None:
            edge_normal, edge_offset, edge_tangent, edge_length = edge_geometry[edge_id]
            dot = float(np.dot(normal, edge_normal))
            deviation = math.degrees(math.acos(float(np.clip(abs(dot), -1.0, 1.0))))
            aligned_offset = offset if dot >= 0 else -offset
            boundary_delta = abs(aligned_offset - edge_offset)
            projected = endpoints @ edge_tangent
            edge_center = float(np.dot(edge_tangent, center[:2]))
            edge_low, edge_high = edge_center - edge_length / 2, edge_center + edge_length / 2
            if deviation > max_track_normal_deviation_degrees:
                exclusion_reasons.append("track_normal_deviation_exceeds_limit")
            if boundary_delta > max_track_boundary_delta_m:
                exclusion_reasons.append("track_boundary_delta_exceeds_limit")
            if projected.min() < edge_low - max_track_boundary_delta_m or projected.max() > edge_high + max_track_boundary_delta_m:
                exclusion_reasons.append("track_span_exceeds_candidate_face")
            if exclusion_reasons:
                edge_id = None
            else:
                edge_position = sorted((float(projected.min()), float(projected.max())))
        observations.append({
            "plane_id": plane_id,
            "edge_id": edge_id,
            "edge_position": edge_position,
            "normal": normal,
            "offset": offset,
            "vertical_bins": vertical_bins,
            "point_indices": point_indices,
            "association_status": str(association.get("association_status", "unknown")),
            "exclusion_reasons": exclusion_reasons,
        })

    parent = list(range(len(observations)))
    link_evidence: list[dict[str, Any]] = []

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        a, b = find(first), find(second)
        if a != b:
            parent[b] = a

    for i, first in enumerate(observations):
        if first["edge_id"] is None:
            continue
        edge_normal = edge_geometry[first["edge_id"]][0]
        for j in range(i + 1, len(observations)):
            second = observations[j]
            if second["edge_id"] != first["edge_id"]:
                continue
            normal_deviation = math.degrees(math.acos(float(np.clip(
                abs(np.dot(first["normal"], second["normal"])), -1.0, 1.0))))
            if normal_deviation > max_track_normal_deviation_degrees:
                continue
            first_offset = first["offset"] if np.dot(first["normal"], edge_normal) >= 0 else -first["offset"]
            second_offset = second["offset"] if np.dot(second["normal"], edge_normal) >= 0 else -second["offset"]
            if abs(first_offset - second_offset) > max_track_boundary_delta_m:
                continue
            shared_bins = first["vertical_bins"] & second["vertical_bins"]
            if not shared_bins:
                continue
            a0, a1 = first["edge_position"]
            b0, b1 = second["edge_position"]
            overlap = max(0.0, min(a1, b1) - max(a0, b0))
            shorter = min(a1 - a0, b1 - b0)
            overlap_fraction = overlap / max(shorter, 1e-12)
            endpoint_gap = max(0.0, max(a0, b0) - min(a1, b1))
            overlap_supported = overlap_fraction >= min_track_span_overlap_fraction
            endpoints_supported = 0 < endpoint_gap <= max_track_endpoint_gap_m
            if not overlap_supported and not endpoints_supported:
                continue
            union(i, j)
            link_evidence.append({
                "surface_ids": sorted((first["plane_id"], second["plane_id"])),
                "normal_deviation_degrees": normal_deviation,
                "boundary_delta_m": abs(first_offset - second_offset),
                "shared_vertical_bin_count": len(shared_bins),
                "span_overlap_fraction": overlap_fraction,
                "endpoint_gap_m": endpoint_gap,
                "overlap_supported": overlap_supported,
                "endpoints_supported": endpoints_supported,
            })

    groups: dict[int, list[dict[str, Any]]] = {}
    for index, observation in enumerate(observations):
        groups.setdefault(find(index), []).append(observation)
    links_by_root: dict[int, list[dict[str, Any]]] = {}
    for link in link_evidence:
        linked = [index for index, item in enumerate(observations)
                  if item["plane_id"] in link["surface_ids"]]
        if linked:
            links_by_root.setdefault(find(linked[0]), []).append(link)

    tracks = []
    for members in groups.values():
        bins = set().union(*(member["vertical_bins"] for member in members)) & candidate_bins
        support_m = min(len(bins) * vertical_bin_m, height)
        edges = {member["edge_id"] for member in members}
        edge_id = next(iter(edges)) if len(edges) == 1 else None
        track_status = "candidate_track" if edge_id is not None else "unassigned_surface_track"
        if any(member["association_status"] == "insufficient_vertical_support" for member in members):
            track_status = "weak_candidate_track" if edge_id is not None else track_status
        tracks.append({
            "track_id": "track:" + "+".join(sorted(member["plane_id"] for member in members)),
            "candidate_edge_id": edge_id,
            "surface_ids": sorted(member["plane_id"] for member in members),
            "source_point_indices": sorted({value for member in members for value in member["point_indices"]}),
            "vertical_support_m": support_m,
            "vertical_support_fraction": support_m / height,
            "occupied_z_bin_ids": sorted(bins),
            "association_statuses": sorted({member["association_status"] for member in members}),
            "track_status": track_status,
            "exclusion_reasons": sorted({reason for member in members for reason in member["exclusion_reasons"]}),
            "structural_role": "unknown",
            "confirmed": False,
            "review_required": True,
            "settings": {
                "max_track_normal_deviation_degrees": max_track_normal_deviation_degrees,
                "max_track_boundary_delta_m": max_track_boundary_delta_m,
                "min_track_span_overlap_fraction": min_track_span_overlap_fraction,
                "max_track_endpoint_gap_m": max_track_endpoint_gap_m,
                "vertical_bin_m": vertical_bin_m,
                "settings_are_engineering_tolerances": False,
            },
            "link_evidence": sorted(links_by_root.get(find(next(
                index for index, item in enumerate(observations)
                if item["plane_id"] == members[0]["plane_id"])), []),
                key=lambda item: item["surface_ids"]),
        })
    return sorted(tracks, key=lambda item: (item["candidate_edge_id"] or "~", item["track_id"]))
