"""Conservative fitting of rectangular section evidence in an XY point slice.

The result is a review proposal. It never mutates source geometry or assigns a
catalog type. Explicit dimensions may complete an incomplete corner, but the
completed edges are marked as inferred in the returned evidence.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from itertools import permutations
from typing import Any

import numpy as np
from skimage.measure import LineModelND, ransac


class _CircleModel:
    """Small RANSAC model avoiding version-sensitive scikit-image APIs."""

    def __init__(self) -> None:
        self.center: np.ndarray | None = None
        self.radius: float | None = None

    @classmethod
    def from_estimate(cls, points: np.ndarray) -> _CircleModel | None:
        model = cls()
        return model if model.estimate(points) else None

    def estimate(self, points: np.ndarray) -> bool:
        points = np.asarray(points, dtype=np.float64)
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3:
            return False
        matrix = np.column_stack((2 * points[:, 0], 2 * points[:, 1], np.ones(len(points))))
        target = np.sum(points * points, axis=1)
        try:
            coefficients, _, rank, _ = np.linalg.lstsq(matrix, target, rcond=None)
        except np.linalg.LinAlgError:
            return False
        if rank < 3:
            return False
        center = coefficients[:2]
        radius_squared = float(coefficients[2] + center @ center)
        if not math.isfinite(radius_squared) or radius_squared <= 0:
            return False
        self.center = center
        self.radius = math.sqrt(radius_squared)
        return True

    def residuals(self, points: np.ndarray) -> np.ndarray:
        if self.center is None or self.radius is None:
            return np.full(len(points), np.inf)
        return np.abs(np.linalg.norm(np.asarray(points) - self.center, axis=1) - self.radius)


def _unit(vector: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if length == 0:
        raise ValueError("degenerate line")
    return vector / length


def _angle(a: np.ndarray, b: np.ndarray) -> float:
    return math.acos(float(np.clip(abs(np.dot(a, b)), -1.0, 1.0)))


def _intersection(a: dict[str, Any], b: dict[str, Any]) -> np.ndarray | None:
    matrix = np.column_stack((a["direction"], -b["direction"]))
    determinant = float(np.linalg.det(matrix))
    if abs(determinant) < 1e-8:
        return None
    parameters = np.linalg.solve(matrix, b["origin"] - a["origin"])
    return a["origin"] + parameters[0] * a["direction"]


def _extract_faces(points: np.ndarray, tolerance: float, max_faces: int) -> list[dict[str, Any]]:
    """Extract long, separated line segments reproducibly, retaining raw indices."""
    # Stable sorting makes RANSAC independent of the caller's point ordering.
    order = np.lexsort((points[:, 1], points[:, 0]))
    sorted_points = points[order]
    voxel = max(tolerance * 0.5, 1e-5)
    keys = np.rint(sorted_points / voxel).astype(np.int64)
    starts = np.r_[True, np.any(keys[1:] != keys[:-1], axis=1)]
    group = np.cumsum(starts) - 1
    unique = np.zeros((int(group[-1]) + 1, 2), dtype=np.float64)
    counts = np.bincount(group)
    np.add.at(unique, group, sorted_points)
    unique /= counts[:, None]
    source_indices = [order[group == i] for i in range(len(unique))]

    remaining = np.ones(len(unique), dtype=bool)
    faces: list[dict[str, Any]] = []
    gap_limit = max(10 * tolerance, 0.04)
    min_span = max(0.08, 12 * tolerance)
    for face_number in range(max_faces):
        active = np.flatnonzero(remaining)
        if len(active) < 20:
            break
        sample = unique[active]
        model, inliers = ransac(
            sample,
            LineModelND,
            min_samples=2,
            residual_threshold=tolerance,
            max_trials=256,
            stop_probability=0.995,
            rng=np.random.default_rng(1729 + face_number),
        )
        if model is None or inliers is None or int(inliers.sum()) < 20:
            break
        robust = LineModelND.from_estimate(sample[inliers])
        direction = _unit(np.asarray(robust.direction, dtype=float))
        origin = np.asarray(robust.origin, dtype=float)
        distances = np.abs((sample - origin)[:, 0] * direction[1] - (sample - origin)[:, 1] * direction[0])
        inlier_local = np.flatnonzero(distances <= tolerance)
        if len(inlier_local) < 20:
            break
        projections = (sample[inlier_local] - origin) @ direction
        sorted_local = np.argsort(projections, kind="stable")
        sorted_projection = projections[sorted_local]
        cuts = np.flatnonzero(np.diff(sorted_projection) > gap_limit) + 1
        segments = np.split(sorted_local, cuts)
        segment = max(segments, key=lambda s: (float(np.ptp(projections[s])), len(s)))
        if len(segment) < 20:
            # Remove the failed line consensus so another orientation can be tried.
            remaining[active[inlier_local]] = False
            continue
        selected = inlier_local[segment]
        span = float(np.ptp(projections[segment]))
        remaining[active[selected]] = False
        if span < min_span:
            continue
        fitted_points = sample[selected]
        fitted_line = LineModelND.from_estimate(fitted_points)
        direction = _unit(np.asarray(fitted_line.direction, dtype=float))
        origin = np.asarray(fitted_line.origin, dtype=float)
        scalar = (fitted_points - origin) @ direction
        low, high = float(scalar.min()), float(scalar.max())
        residuals = np.abs((fitted_points - origin)[:, 0] * direction[1] - (fitted_points - origin)[:, 1] * direction[0])
        raw = np.concatenate([source_indices[int(active[i])] for i in selected]).astype(int)
        faces.append({
            "origin": origin,
            "direction": direction,
            "start": origin + low * direction,
            "end": origin + high * direction,
            "span_m": high - low,
            "support": len(raw),
            "rmse_m": float(np.sqrt(np.mean(residuals**2))),
            "p95_residual_m": float(np.quantile(residuals, .95)),
            "input_point_indices": sorted(set(raw.tolist())),
            "span_kind": "observed_span_lower_bound",
        })
    return faces


def _public_face(face: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "face_id": f"F{index + 1}",
        "start_world_m": face["start"].tolist(),
        "end_world_m": face["end"].tolist(),
        "direction_xy": face["direction"].tolist(),
        "observed_span_m": face["span_m"],
        "span_kind": face["span_kind"],
        "support_count": face["support"],
        "rmse_m": face["rmse_m"],
        "p95_residual_m": face["p95_residual_m"],
        "input_point_indices": face["input_point_indices"],
    }


def _edge_observation_coverage(
    corners: Sequence[Sequence[float]],
    faces: Sequence[dict[str, Any]],
    *,
    line_distance_tolerance_m: float,
) -> list[dict[str, Any]]:
    """Measure how much of each proposed edge overlaps observed face segments.

    This is geometric segment coverage, not an engineering confidence score or
    a claim that the region between sampled returns is continuously visible.
    """
    polygon = np.asarray(corners, dtype=np.float64)
    evidence: list[dict[str, Any]] = []
    for edge_index, start in enumerate(polygon):
        end = polygon[(edge_index + 1) % len(polygon)]
        vector = end - start
        length = float(np.linalg.norm(vector))
        if length <= 0:
            evidence.append({"edge_index": edge_index, "length_m": length,
                             "observed_span_m": 0.0, "unobserved_m": 0.0,
                             "coverage_fraction": 0.0, "unobserved_fraction": 1.0,
                             "source_face_ids": [], "evidence": "invalid_edge"})
            continue
        direction = vector / length
        intervals: list[tuple[float, float, str]] = []
        for face_index, face in enumerate(faces):
            if abs(_angle(direction, np.asarray(face["direction"], dtype=np.float64))) > math.radians(3):
                continue
            origin = np.asarray(face["origin"], dtype=np.float64)
            delta = origin - start
            line_offset = abs(float(direction[0] * delta[1] - direction[1] * delta[0]))
            if line_offset > line_distance_tolerance_m:
                continue
            face_start = float(np.dot(np.asarray(face["start"]) - start, direction))
            face_end = float(np.dot(np.asarray(face["end"]) - start, direction))
            low = max(0.0, min(face_start, face_end))
            high = min(length, max(face_start, face_end))
            if high > low:
                intervals.append((low, high, f"F{face_index + 1}"))

        merged: list[list[float]] = []
        for low, high, _ in sorted(intervals):
            if not merged or low > merged[-1][1]:
                merged.append([low, high])
            else:
                merged[-1][1] = max(merged[-1][1], high)
        observed_span = min(length, sum(high - low for low, high in merged))
        coverage = min(1.0, max(0.0, observed_span / length))
        source_ids = sorted({face_id for _, _, face_id in intervals})
        evidence.append({
            "edge_index": edge_index,
            "length_m": length,
            "observed_span_m": observed_span,
            "unobserved_m": max(0.0, length - observed_span),
            "coverage_fraction": coverage,
            "unobserved_fraction": max(0.0, 1.0 - coverage),
            "source_face_ids": source_ids,
            "evidence": "observed" if coverage > 0 else "no_observed_points",
        })
    return evidence


def _same_section_hypothesis(
    first: Mapping[str, Any], second: Mapping[str, Any], *, tolerance_m: float,
) -> bool:
    """Match one rectangle despite corner start order and fit noise."""
    first_sides = sorted(float(value) for value in first.get("side_lengths_m", []))
    second_sides = sorted(float(value) for value in second.get("side_lengths_m", []))
    if len(first_sides) != 2 or len(second_sides) != 2:
        return False
    if any(abs(a - b) > tolerance_m for a, b in zip(first_sides, second_sides)):
        return False
    first_corners = np.asarray(first.get("corners_world_m"), dtype=np.float64)
    second_corners = np.asarray(second.get("corners_world_m"), dtype=np.float64)
    if first_corners.shape != (4, 2) or second_corners.shape != (4, 2):
        return False
    distances = np.linalg.norm(first_corners[:, None, :] - second_corners[None, :, :], axis=2)
    indices = np.arange(4)
    return any(
        np.all(distances[indices, order] <= tolerance_m)
        for order in permutations(range(4))
    )


def fit_circular_section(
    points_xy: np.ndarray,
    *,
    distance_tolerance_m: float = 0.004,
) -> dict[str, Any] | None:
    """Return a review-only circle candidate for a sufficiently observed ring.

    Partial arcs deliberately return ``None``: they do not establish a closed
    circular section. Coverage and residual limits are algorithm filters, not
    engineering tolerances.
    """
    points = np.asarray(points_xy, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise ValueError("points_xy must be a finite N×2 array")
    if not math.isfinite(distance_tolerance_m) or distance_tolerance_m <= 0:
        raise ValueError("distance_tolerance_m must be finite and positive")
    if len(points) < 30:
        return None

    center = points.mean(axis=0)
    local = points - center
    order = np.lexsort((local[:, 1], local[:, 0]))
    model, inliers = ransac(
        local[order],
        _CircleModel,
        min_samples=3,
        residual_threshold=distance_tolerance_m,
        max_trials=512,
        stop_probability=0.995,
        rng=np.random.default_rng(271828),
    )
    if model is None or inliers is None or int(inliers.sum()) < 30:
        return None

    # Refit using the consensus set and re-evaluate against the complete input.
    refined = _CircleModel.from_estimate(local[order][inliers])
    if refined is None:
        return None
    residuals = np.asarray(refined.residuals(local), dtype=np.float64)
    selected = np.flatnonzero(residuals <= distance_tolerance_m)
    if len(selected) < 30 or len(selected) / len(points) < 0.70:
        return None
    final = _CircleModel.from_estimate(local[selected])
    if final is None:
        return None
    assert final.center is not None and final.radius is not None
    local_center = final.center
    radius = final.radius
    final_residuals = np.asarray(final.residuals(local[selected]), dtype=np.float64)
    angles = np.mod(np.arctan2(local[selected, 1] - local_center[1], local[selected, 0] - local_center[0]), 2 * math.pi)
    occupied = np.bincount(np.floor(angles / (2 * math.pi) * 48).astype(int).clip(0, 47), minlength=48) > 0
    empty = ~occupied
    max_empty_bins = 48 if empty.all() else 0
    current_gap = 0
    for is_empty in np.r_[empty, empty]:
        current_gap = current_gap + 1 if is_empty else 0
        max_empty_bins = max(max_empty_bins, min(current_gap, 48))
    coverage = float(occupied.mean())
    if radius <= 0.02 or coverage < 0.70 or max_empty_bins > 12:
        return None

    return {
        "shape": "circle",
        "status": "candidate",
        "center_xy_m": (local_center + center).tolist(),
        "radius_m": radius,
        "diameter_m": 2 * radius,
        "support_count": int(len(selected)),
        "support_fraction": float(len(selected) / len(points)),
        "angular_coverage_fraction": coverage,
        "max_unobserved_arc_degrees": float(max_empty_bins * 360 / 48),
        "rmse_m": float(np.sqrt(np.mean(final_residuals**2))),
        "p95_radial_residual_m": float(np.quantile(final_residuals, 0.95)),
        "input_point_indices": selected.tolist(),
        "review_required": True,
        "engineering_status": "not_assessed",
        "tolerance_status": "provisional_algorithm_filter",
    }


def fit_built_up_i_section(
    points_xy: np.ndarray,
    *,
    distance_tolerance_m: float = 0.004,
    max_faces: int = 16,
) -> dict[str, Any] | None:
    """Measure a fully observed I-shaped outline as a review-only hypothesis.

    The detector requires four parallel coordinate levels in each of two
    orthogonal directions and the expected flange/web edge connectivity. It
    reports only dimensions supported by those observed line segments; partial
    or cluttered outlines remain unknown. This is not a steel catalogue type.
    """
    points = np.asarray(points_xy, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise ValueError("points_xy must be a finite N×2 array")
    if not math.isfinite(distance_tolerance_m) or distance_tolerance_m <= 0:
        raise ValueError("distance_tolerance_m must be finite and positive")
    if not isinstance(max_faces, int) or max_faces < 12:
        raise ValueError("max_faces must be an integer of at least 12")
    if len(points) < 60:
        return None

    center = points.mean(axis=0)
    faces = _extract_faces(points - center, distance_tolerance_m, max_faces)
    if len(faces) < 12:
        return None
    for face in faces:
        for key in ("origin", "start", "end"):
            face[key] = face[key] + center

    coordinate_tolerance = max(3 * distance_tolerance_m, 0.006)
    interval_tolerance = max(5 * distance_tolerance_m, 0.015)

    def merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
        merged: list[list[float]] = []
        for low, high in sorted(intervals):
            if not merged or low > merged[-1][1] + coordinate_tolerance:
                merged.append([low, high])
            else:
                merged[-1][1] = max(merged[-1][1], high)
        return [(low, high) for low, high in merged]

    def matches(actual: list[tuple[float, float]], expected: list[tuple[float, float]]) -> bool:
        if len(actual) != len(expected):
            return False
        return all(
            abs(a0 - e0) <= interval_tolerance and abs(a1 - e1) <= interval_tolerance
            for (a0, a1), (e0, e1) in zip(actual, expected)
        )

    def line_groups(
        direction: np.ndarray, normal: np.ndarray,
    ) -> tuple[list[tuple[float, list[tuple[float, float]], list[int]]],
               list[tuple[float, list[tuple[float, float]], list[int]]]]:
        parallel: list[dict[str, Any]] = []
        perpendicular: list[dict[str, Any]] = []
        for face in faces:
            face_direction = np.asarray(face["direction"], dtype=np.float64)
            is_parallel = _angle(face_direction, direction) <= math.radians(3)
            is_perpendicular = _angle(face_direction, normal) <= math.radians(3)
            if not is_parallel and not is_perpendicular:
                continue
            origin = np.asarray(face["origin"], dtype=np.float64)
            if is_parallel:
                coordinate = float(np.dot(origin, normal))
                start, end, axis = face["start"], face["end"], direction
                group_list = parallel
            else:
                coordinate = float(np.dot(origin, direction))
                start, end, axis = face["start"], face["end"], normal
                group_list = perpendicular
            interval = sorted((float(np.dot(start, axis)), float(np.dot(end, axis))))
            group = next((item for item in group_list
                          if abs(item["coordinate"] - coordinate) <= coordinate_tolerance), None)
            if group is None:
                group = {"coordinate": coordinate, "intervals": [], "indices": []}
                group_list.append(group)
            group["intervals"].append(tuple(interval))
            group["indices"].extend(face["input_point_indices"])

        def finalized(groups: list[dict[str, Any]]) -> list[tuple[float, list[tuple[float, float]], list[int]]]:
            return sorted((
                float(group["coordinate"]), merge_intervals(group["intervals"]),
                sorted(set(group["indices"])),
            ) for group in groups)

        return finalized(parallel), finalized(perpendicular)

    # Try each observed line orientation. Equivalent axis swaps are collapsed
    # by returning the first complete, strongest consensus.
    tested: set[tuple[int, int]] = set()
    for seed in sorted(faces, key=lambda face: (-face["span_m"], -face["support"])):
        direction = _unit(np.asarray(seed["direction"], dtype=np.float64))
        if direction[0] < 0 or (abs(direction[0]) < 1e-10 and direction[1] < 0):
            direction = -direction
        direction_key = tuple(np.rint(direction * 1000).astype(int))
        if direction_key in tested:
            continue
        tested.add(direction_key)
        normal = np.array([-direction[1], direction[0]], dtype=np.float64)
        parallel, perpendicular = line_groups(direction, normal)
        if len(parallel) != 4 or len(perpendicular) != 4:
            continue
        v = [item[0] for item in parallel]
        u = [item[0] for item in perpendicular]
        if min(u[1] - u[0], u[2] - u[1], u[3] - u[2],
               v[1] - v[0], v[2] - v[1], v[3] - v[2]) <= coordinate_tolerance:
            continue

        expected_parallel = [
            [(u[0], u[3])],
            [(u[0], u[1]), (u[2], u[3])],
            [(u[0], u[1]), (u[2], u[3])],
            [(u[0], u[3])],
        ]
        expected_perpendicular = [
            [(v[0], v[1]), (v[2], v[3])],
            [(v[1], v[2])],
            [(v[1], v[2])],
            [(v[0], v[1]), (v[2], v[3])],
        ]
        if not all(matches(actual[1], expected)
                   for actual, expected in zip(parallel, expected_parallel)):
            continue
        if not all(matches(actual[1], expected)
                   for actual, expected in zip(perpendicular, expected_perpendicular)):
            continue

        source_indices = sorted({
            point_index
            for group in [*parallel, *perpendicular]
            for point_index in group[2]
        })
        return {
            "shape": "built_up_i",
            "status": "candidate",
            "envelope_side_lengths_m": [float(u[3] - u[0]), float(v[3] - v[0])],
            "web_thickness_m": float(u[2] - u[1]),
            "flange_thicknesses_m": [float(v[1] - v[0]), float(v[3] - v[2])],
            "centerline_axes_xy": [direction.tolist(), normal.tolist()],
            "support_count": len(source_indices),
            "input_point_indices": source_indices,
            "review_required": True,
            "engineering_status": "not_assessed",
            "tolerance_status": "provisional_algorithm_filter",
        }
    return None


def fit_rectangular_section(
    points_xy: np.ndarray,
    *,
    known_sides_m: tuple[float, float] | None = None,
    distance_tolerance_m: float = 0.004,
    max_faces: int = 8,
) -> dict[str, Any]:
    """Fit observed rectangular faces and return conservative review hypotheses.

    ``known_sides_m`` is an explicit user-provided measurement. It is only used
    to construct candidate missing edges and is echoed as the source of those
    dimensions. No incomplete observed span is silently promoted to a full side.
    """
    points = np.asarray(points_xy, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2 or not np.isfinite(points).all():
        raise ValueError("points_xy must be a finite N×2 array")
    if not math.isfinite(distance_tolerance_m) or distance_tolerance_m <= 0:
        raise ValueError("distance_tolerance_m must be finite and positive")
    if not isinstance(max_faces, int) or max_faces < 1:
        raise ValueError("max_faces must be a positive integer")
    if known_sides_m is not None:
        if len(known_sides_m) != 2 or any(not math.isfinite(float(v)) or float(v) <= 0 for v in known_sides_m):
            raise ValueError("known_sides_m must contain two finite positive lengths")
        known = tuple(sorted(float(v) for v in known_sides_m))
    else:
        known = None

    center = points.mean(axis=0)
    faces = _extract_faces(points - center, distance_tolerance_m, max_faces)
    for face in faces:
        for key in ("origin", "start", "end"):
            face[key] = face[key] + center

    angle_tol = math.radians(3)
    corner_tol = max(0.025, 4 * distance_tolerance_m)
    if known is not None:
        # Explicit dimensions can close small scan gaps at a corner. Keep the
        # extrapolation bounded relative to the smaller entered side.
        corner_tol = max(corner_tol, 0.15 * min(known))
    candidates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    open_corners: list[dict[str, Any]] = []
    for i, first in enumerate(faces):
        for j in range(i + 1, len(faces)):
            second = faces[j]
            if abs(_angle(first["direction"], second["direction"]) - math.pi / 2) > angle_tol:
                continue
            corner = _intersection(first, second)
            if corner is None:
                continue
            endpoint_distances = [
                min(np.linalg.norm(corner - face["start"]), np.linalg.norm(corner - face["end"]))
                for face in (first, second)
            ]
            if any(distance > corner_tol for distance in endpoint_distances):
                continue
            outward: list[np.ndarray] = []
            for face in (first, second):
                outward.append(_unit((face["end"] if np.linalg.norm(corner-face["start"]) < np.linalg.norm(corner-face["end"]) else face["start"]) - corner))
            if known is None:
                open_corners.append({
                    "world_m": corner.tolist(),
                    "face_ids": [f"F{i + 1}", f"F{j + 1}"],
                    "observed_spans_m": [first["span_m"], second["span_m"]],
                })
                continue
            for length_u, length_v in (known, tuple(reversed(known))):
                lengths = (length_u, length_v)
                if any(face["span_m"] > length + max(2 * distance_tolerance_m, .01) for face, length in zip((first, second), lengths)):
                    continue
                # If the measured spans both identify a side uniquely, enforce that mapping.
                if abs(known[0] - known[1]) > 2 * distance_tolerance_m:
                    matches = [abs(first["span_m"] - length_u) <= max(3 * distance_tolerance_m, .01), abs(second["span_m"] - length_v) <= max(3 * distance_tolerance_m, .01)]
                    if any(matches) and not all(matches):
                        continue
                corners = [corner, corner + outward[0] * length_u,
                           corner + outward[0] * length_u + outward[1] * length_v,
                           corner + outward[1] * length_v]
                candidates.append({
                    "side_lengths_m": [length_u, length_v],
                    "corners_world_m": [p.tolist() for p in corners],
                    "observed_edge_count": 2,
                    "inferred_edge_count": 2,
                    "edge_evidence": ["observed", "inferred", "inferred", "observed"],
                    "dimension_source": "explicit_input",
                    "inferred": True,
                    "review_required": True,
                    "shape_interpretation": "outer_envelope_only",
                    "source_face_ids": [f"F{i + 1}", f"F{j + 1}"],
                    "corner_angle_degrees": 90.0,
                })

    # Four measured sides establish a single envelope only when the four line
    # segments form two parallel pairs and all four intersections close.
    if known is None and len(faces) == 4:
        parallel_pairs = [(i, j) for i in range(4) for j in range(i + 1, 4)
                          if _angle(faces[i]["direction"], faces[j]["direction"]) <= angle_tol]
        for first_pair in parallel_pairs:
            remaining_ids = [i for i in range(4) if i not in first_pair]
            if len(remaining_ids) != 2 or tuple(remaining_ids) not in parallel_pairs:
                continue
            group_u, group_v = first_pair, tuple(remaining_ids)
            if abs(_angle(faces[group_u[0]]["direction"], faces[group_v[0]]["direction"]) - math.pi / 2) > angle_tol:
                continue
            intersections = [_intersection(faces[i], faces[j]) for i in group_u for j in group_v]
            if any(point is None for point in intersections):
                continue
            polygon = np.asarray(intersections)
            centroid = polygon.mean(axis=0)
            order = np.argsort(np.arctan2(polygon[:, 1] - centroid[1], polygon[:, 0] - centroid[0]))
            polygon = polygon[order]
            edge_lengths = np.linalg.norm(np.roll(polygon, -1, axis=0) - polygon, axis=1)
            if min(edge_lengths) <= 0:
                continue
            if abs(edge_lengths[0] - edge_lengths[2]) > max(.025, .08 * edge_lengths[0]) or abs(edge_lengths[1] - edge_lengths[3]) > max(.025, .08 * edge_lengths[1]):
                continue
            measured_spans = [faces[i]["span_m"] for i in range(4)]
            if any(a > b + max(3 * distance_tolerance_m, .01) or b - a > max(.03, .08*b)
                   for a, b in zip(sorted(measured_spans), sorted(edge_lengths))):
                continue
            dimensions = [float((edge_lengths[0] + edge_lengths[2]) / 2), float((edge_lengths[1] + edge_lengths[3]) / 2)]
            candidates.append({
                "side_lengths_m": dimensions,
                "corners_world_m": polygon.tolist(),
                "observed_edge_count": 4,
                "inferred_edge_count": 0,
                "edge_evidence": ["observed"] * 4,
                "dimension_source": "observed_faces",
                "inferred": False,
                "review_required": True,
                "shape_interpretation": "outer_envelope_only",
                "source_face_ids": [f"F{i + 1}" for i in range(4)],
                "corner_angle_degrees": 90.0,
            })
            open_corners = []
            break

    if known is not None:
        # Face spans are lower bounds: an occluded face shorter than an
        # explicitly measured side is consistent with that side. Only a
        # clearly longer observed span contradicts the entered dimensions.
        observed = [face["span_m"] for face in faces]
        if len(observed) >= 4:
            observed_sorted = sorted(observed, reverse=True)
            expected_sorted = sorted(known * 2, reverse=True)
            side_tolerance = max(3 * distance_tolerance_m, .015)
            if any(
                observed_span > expected_side + side_tolerance
                for observed_span, expected_side in zip(observed_sorted[:4], expected_sorted)
            ):
                conflicts.append({"kind": "observed_dimensions_disagree", "observed_face_spans_m": observed_sorted[:4], "explicit_sides_m": list(known)})

    # Deduplicate hypotheses that arise from extracting the same two faces twice.
    unique_candidates: list[dict[str, Any]] = []
    hypothesis_tolerance = max(.003, distance_tolerance_m)
    for candidate in candidates:
        candidate["edge_observation_coverage"] = _edge_observation_coverage(
            candidate["corners_world_m"], faces,
            line_distance_tolerance_m=max(.025, 4 * distance_tolerance_m),
        )
        match = next(
            (existing for existing in unique_candidates
             if _same_section_hypothesis(existing, candidate, tolerance_m=hypothesis_tolerance)),
            None,
        )
        if match is None:
            unique_candidates.append(candidate)
        else:
            match["source_face_ids"] = sorted(
                set(match.get("source_face_ids", [])) | set(candidate.get("source_face_ids", []))
            )
    if conflicts and not unique_candidates:
        status = "unknown"
    elif unique_candidates:
        status = "proposed" if len(unique_candidates) == 1 else "ambiguous"
    elif open_corners:
        status = "open_section"
    else:
        status = "unknown"
    return {
        "status": status,
        "hypotheses": unique_candidates,
        "observed_faces": [_public_face(face, i) for i, face in enumerate(faces)],
        "open_corners": open_corners,
        "dimension_conflicts": conflicts,
        "review_required": True,
        "engineering_status": "not_assessed",
        "tolerance_status": "provisional_algorithm_parameter",
        "input_point_count": len(points),
    }


def fit_column_section_series(
    section_slices: Sequence[Mapping[str, Any]],
    *,
    known_sides_m: tuple[float, float] | None = None,
    distance_tolerance_m: float = 0.004,
) -> dict[str, Any]:
    """Fit independent height slices without interpolating through missing data.

    Each input slice contains ``z_m`` and finite ``points_xy``; optional
    ``source_point_ids`` map the local point order back to the source cloud.
    Dimensions are reported at each observed height and as raw ranges only.
    Those ranges are descriptive; this function does not apply an engineering
    tolerance, infer a catalog type, or confirm the geometry.
    """
    if not isinstance(section_slices, Sequence) or isinstance(section_slices, (str, bytes)):
        raise ValueError("section_slices must be a sequence of mappings")
    if not math.isfinite(float(distance_tolerance_m)) or distance_tolerance_m <= 0:
        raise ValueError("distance_tolerance_m must be finite and positive")
    if known_sides_m is not None and (
        len(known_sides_m) != 2
        or any(not math.isfinite(float(value)) or float(value) <= 0 for value in known_sides_m)
    ):
        raise ValueError("known_sides_m must contain two finite positive lengths")

    prepared: list[tuple[float, np.ndarray, list[int], str]] = []
    seen_z: set[float] = set()
    for item in section_slices:
        if not isinstance(item, Mapping):
            raise ValueError("each section slice must be a mapping")
        try:
            z_m = float(item["z_m"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("each section slice requires a finite z_m") from exc
        if not math.isfinite(z_m):
            raise ValueError("each section slice requires a finite z_m")
        if z_m in seen_z:
            raise ValueError("section slices require unique z_m values")
        seen_z.add(z_m)

        points = np.asarray(item.get("points_xy"), dtype=np.float64)
        if points.size == 0:
            points = np.empty((0, 2), dtype=np.float64)
        elif points.ndim == 1 and points.shape == (2,):
            points = points.reshape((1, 2))
        if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
            raise ValueError("points_xy must be a finite N×2 array")

        raw_ids = item.get("source_point_ids")
        if raw_ids is None:
            source_ids = list(range(len(points)))
            source_scope = "slice_local"
        else:
            if not isinstance(raw_ids, Sequence) or isinstance(raw_ids, (str, bytes)):
                raise ValueError("source_point_ids must be a sequence of integers")
            try:
                source_ids = [int(value) for value in raw_ids]
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("source_point_ids must be a sequence of integers") from exc
            if (len(source_ids) != len(points)
                    or len(set(source_ids)) != len(source_ids)
                    or any(converted != original for converted, original in zip(source_ids, raw_ids))):
                raise ValueError("source_point_ids length must match points_xy and IDs must be unique")
            source_scope = "source_rows"
        prepared.append((z_m, points, source_ids, source_scope))

    slices: list[dict[str, Any]] = []
    dimensions_by_height: list[tuple[float, tuple[float, float]]] = []
    shape_measurements: list[dict[str, Any]] = []
    built_up_measurements: list[dict[str, Any]] = []
    shape_by_height: list[tuple[float, str, tuple[float, ...]] | None] = []
    for z_m, points, source_ids, source_scope in sorted(prepared, key=lambda entry: entry[0]):
        if len(points) < 2:
            fit = {
                "status": "unknown", "hypotheses": [], "observed_faces": [],
                "open_corners": [], "dimension_conflicts": [], "review_required": True,
                "engineering_status": "not_assessed", "tolerance_status": "not_assessed",
                "input_point_count": len(points),
            }
        else:
            fit = fit_rectangular_section(
                points, known_sides_m=known_sides_m,
                distance_tolerance_m=distance_tolerance_m,
            )
        circle = fit_circular_section(points, distance_tolerance_m=distance_tolerance_m) if len(points) >= 30 else None
        shape_hypotheses = [circle] if circle is not None else []
        for hypothesis in shape_hypotheses:
            hypothesis["source_point_ids"] = sorted(source_ids[index] for index in hypothesis["input_point_indices"])
        built_up = fit_built_up_i_section(points, distance_tolerance_m=distance_tolerance_m) if len(points) >= 60 else None
        built_up_hypotheses = [built_up] if built_up is not None else []
        for hypothesis in built_up_hypotheses:
            hypothesis["source_point_ids"] = sorted(source_ids[index] for index in hypothesis["input_point_indices"])
        fit["shape_hypotheses"] = shape_hypotheses
        fit["built_up_hypotheses"] = built_up_hypotheses
        fit["shape_status"] = (
            "ambiguous" if len(shape_hypotheses) + len(built_up_hypotheses) > 1
            else "candidate" if shape_hypotheses or built_up_hypotheses or len(fit["hypotheses"]) == 1
            else "unknown"
        )

        face_ids: dict[str, list[int]] = {}
        for face in fit["observed_faces"]:
            mapped = [source_ids[index] for index in face["input_point_indices"]]
            face["source_point_ids"] = sorted(set(mapped))
            face_ids[face["face_id"]] = face["source_point_ids"]
        for hypothesis in fit["hypotheses"]:
            hypothesis["source_point_ids"] = sorted({
                point_id
                for face_id in hypothesis.get("source_face_ids", [])
                for point_id in face_ids.get(face_id, [])
            })
        if len(fit["hypotheses"]) == 1:
            dimensions = tuple(sorted(float(value) for value in fit["hypotheses"][0]["side_lengths_m"]))
            dimensions_by_height.append((z_m, dimensions))
            shape_measurements.append({"z_m": z_m, "shape": "rectangular_envelope", "side_lengths_m": list(dimensions)})
            shape_by_height.append((z_m, "rectangular_envelope", dimensions))
        elif len(fit["shape_hypotheses"]) == 1:
            hypothesis = fit["shape_hypotheses"][0]
            diameter = float(hypothesis["diameter_m"])
            shape_measurements.append({
                "z_m": z_m,
                "shape": "circle",
                "diameter_m": diameter,
                "center_xy_m": hypothesis["center_xy_m"],
            })
            shape_by_height.append((z_m, "circle", (diameter,)))
        elif len(built_up_hypotheses) == 1:
            hypothesis = built_up_hypotheses[0]
            measurement = {
                "z_m": z_m,
                "shape": "built_up_i",
                "envelope_side_lengths_m": hypothesis["envelope_side_lengths_m"],
                "web_thickness_m": hypothesis["web_thickness_m"],
                "flange_thicknesses_m": hypothesis["flange_thicknesses_m"],
                "centerline_axes_xy": hypothesis["centerline_axes_xy"],
            }
            shape_measurements.append(measurement)
            built_up_measurements.append(measurement)
            shape_by_height.append((
                z_m, "built_up_i", tuple(float(value) for value in (
                    *hypothesis["envelope_side_lengths_m"],
                    hypothesis["web_thickness_m"],
                    *hypothesis["flange_thicknesses_m"],
                )),
            ))
        else:
            shape_by_height.append(None)
        slices.append({
            **fit,
            "z_m": z_m,
            "source_point_ids": source_ids,
            "source_id_scope": source_scope,
        })

    ranges: dict[str, dict[str, float] | None] = {"short_side": None, "long_side": None}
    if dimensions_by_height:
        labels = ("short_side", "long_side")
        for index, label in enumerate(labels):
            values = [dimensions[index] for _, dimensions in dimensions_by_height]
            low, high = min(values), max(values)
            ranges[label] = {"min_m": low, "max_m": high, "range_m": high - low}
    if len(dimensions_by_height) < 2:
        variation = "insufficient"
    elif len(dimensions_by_height) != len(slices):
        variation = "incomplete"
    elif any(ranges[key]["range_m"] > 1e-9 for key in ranges):
        variation = "observed_variation"
    else:
        variation = "no_variation_observed"

    circle_diameters = [item["diameter_m"] for item in shape_measurements if item["shape"] == "circle"]
    if circle_diameters:
        low, high = min(circle_diameters), max(circle_diameters)
        circle_range: dict[str, float] | None = {"min_m": low, "max_m": high, "range_m": high - low}
    else:
        circle_range = None
    complete_shapes = [item for item in shape_by_height if item is not None]
    if len(complete_shapes) < 2:
        shape_variation = "insufficient"
    elif len(complete_shapes) != len(slices):
        shape_variation = "incomplete"
    elif len({item[1] for item in complete_shapes}) > 1:
        shape_variation = "observed_variation"
    elif any(
        max(item[2][index] for item in complete_shapes) - min(item[2][index] for item in complete_shapes) > 1e-9
        for index in range(len(complete_shapes[0][2]))
    ):
        shape_variation = "observed_variation"
    else:
        shape_variation = "no_variation_observed"

    return {
        "status": "review_required",
        "section_slices": slices,
        "dimensions_by_height_m": [
            {"z_m": z_m, "side_lengths_m": list(dimensions)}
            for z_m, dimensions in dimensions_by_height
        ],
        "dimension_ranges_m": ranges,
        "profile_variation_status": variation,
        "shape_measurements_by_height_m": shape_measurements,
        "built_up_profile_measurements_by_height_m": built_up_measurements,
        "shape_diameter_range_m": circle_range,
        "shape_variation_status": shape_variation,
        "engineering_status": "not_assessed",
        "review_required": True,
    }
