"""Extract vertical planar observations and their across-height persistence."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from skimage.measure import ransac


class _PlaneModel:
    """Minimal RANSAC-compatible orthogonal-distance plane model."""

    def __init__(self) -> None:
        self.origin: np.ndarray | None = None
        self.normal: np.ndarray | None = None

    @classmethod
    def from_estimate(cls, data: np.ndarray) -> "_PlaneModel":
        model = cls()
        model.estimate(data)
        return model

    def estimate(self, points: np.ndarray) -> bool:
        points = np.asarray(points, dtype=float)
        if points.ndim != 2 or points.shape[1] != 3 or len(points) < 3:
            return False
        origin = points.mean(axis=0)
        _, singular, vectors = np.linalg.svd(points - origin, full_matrices=False)
        if len(singular) < 2 or singular[-2] <= 1e-10:
            return False
        normal = vectors[-1]
        norm = float(np.linalg.norm(normal))
        if not math.isfinite(norm) or norm <= 1e-12:
            return False
        self.origin = origin
        self.normal = normal / norm
        return True

    def residuals(self, points: np.ndarray) -> np.ndarray:
        if self.origin is None or self.normal is None:
            raise ValueError("plane model has not been estimated")
        return np.abs((np.asarray(points, dtype=float) - self.origin) @ self.normal)


def _unit_xy(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-12 else vector


def extract_vertical_surfaces(
    points_xyz: np.ndarray,
    *,
    distance_tolerance_m: float = .015,
    voxel_m: float = .02,
    min_support: int = 30,
    min_vertical_span_m: float = .5,
    max_tilt_degrees: float = 8.0,
    max_planes: int = 8,
    max_trials: int = 192,
) -> dict[str, Any]:
    """Return supported vertical planes and near-right-angle face intersections.

    Output describes surfaces in the supplied cloud only. It does not decide
    whether points belong to a column, nor infer a structural role or type.
    ``input_point_indices`` always refer to the caller's array.
    """
    points = np.asarray(points_xyz, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 3 or not np.isfinite(points).all():
        raise ValueError("points_xyz must be a finite N×3 array")
    numeric = (distance_tolerance_m, voxel_m, min_vertical_span_m, max_tilt_degrees)
    if any(not math.isfinite(float(value)) for value in numeric) or distance_tolerance_m <= 0 or voxel_m <= 0 or min_vertical_span_m <= 0 or not 0 < max_tilt_degrees < 45:
        raise ValueError("invalid distance, voxel, height or tilt parameter")
    if not isinstance(min_support, int) or min_support < 3 or not isinstance(max_planes, int) or max_planes < 1 or not isinstance(max_trials, int) or max_trials < 1:
        raise ValueError("support and RANSAC limits must be positive integers")

    center = points.mean(axis=0)
    local_points = points - center
    order = np.lexsort((local_points[:, 2], local_points[:, 1], local_points[:, 0]))
    sorted_points = local_points[order]
    keys = np.rint(sorted_points / voxel_m).astype(np.int64)
    starts = np.r_[True, np.any(keys[1:] != keys[:-1], axis=1)]
    group = np.cumsum(starts) - 1
    unique = np.zeros((int(group[-1]) + 1, 3), dtype=np.float64)
    counts = np.bincount(group)
    np.add.at(unique, group, sorted_points)
    unique /= counts[:, None]
    source_indices = [order[group == i] for i in range(len(unique))]

    remaining = np.ones(len(unique), dtype=bool)
    planes: list[dict[str, Any]] = []
    for plane_number in range(max_planes):
        active = np.flatnonzero(remaining)
        if len(active) < min_support:
            break
        model, inliers = ransac(
            unique[active], _PlaneModel, min_samples=3,
            residual_threshold=distance_tolerance_m,
            max_trials=max_trials, stop_probability=.995,
            rng=np.random.default_rng(2718 + plane_number),
        )
        if model is None or inliers is None or int(inliers.sum()) < min_support:
            break
        consensus = unique[active[inliers]]
        refined = _PlaneModel()
        if not refined.estimate(consensus):
            remaining[active[inliers]] = False
            continue
        residuals = refined.residuals(unique[active])
        selected = np.flatnonzero(residuals <= distance_tolerance_m)
        if len(selected) < min_support:
            remaining[active[inliers]] = False
            continue
        chosen = active[selected]
        remaining[chosen] = False
        fitted = unique[chosen]
        refined.estimate(fitted)
        normal = np.asarray(refined.normal, dtype=float)
        if normal[2] < 0:
            normal = -normal
        world_origin = np.asarray(refined.origin) + center
        world_points = fitted + center
        support_ids = np.concatenate([source_indices[int(i)] for i in chosen]).astype(int)
        normal_xy = _unit_xy(normal[:2])
        horizontal_tangent = np.array([-normal_xy[1], normal_xy[0]])
        tangent_positions = (world_points[:, :2] - world_origin[:2]) @ horizontal_tangent
        z_values = world_points[:, 2]
        z_bin_size = .25
        z_bins = np.unique(np.floor(z_values / z_bin_size).astype(int))
        longest = run = 0
        previous = None
        for value in z_bins:
            run = run + 1 if previous is not None and value == previous + 1 else 1
            longest = max(longest, run)
            previous = int(value)
        residual_values = np.abs((fitted - refined.origin) @ normal)
        is_vertical = abs(float(normal[2])) <= math.sin(math.radians(max_tilt_degrees))
        z_span = float(np.ptp(z_values))
        tangent_span = float(np.ptp(tangent_positions))
        if is_vertical and z_span >= min_vertical_span_m and tangent_span >= .12:
            planes.append({
                "plane_id": f"V{len(planes) + 1}",
                "normal_xy": normal_xy.tolist(),
                "line_offset_m": float(np.dot(normal_xy, world_origin[:2])),
                "line_direction_xy": horizontal_tangent.tolist(),
                "line_anchor_xy_world_m": world_origin[:2].tolist(),
                "line_span_m": tangent_span,
                "line_span_bounds_from_anchor_m": [float(tangent_positions.min()), float(tangent_positions.max())],
                "z_bounds_world_m": [float(z_values.min()), float(z_values.max())],
                "vertical_span_m": z_span,
                "longest_consecutive_vertical_span_m": float(longest * z_bin_size),
                "occupied_z_bins_0_25m": int(len(z_bins)),
                "longest_consecutive_z_bins": int(longest),
                "occupied_z_bin_ids": z_bins.tolist(),
                "point_count": int(len(support_ids)),
                "rmse_m": float(np.sqrt(np.mean(residual_values**2))),
                "p95_residual_m": float(np.quantile(residual_values, .95)),
                "input_point_indices": sorted(set(support_ids.tolist())),
            })

    adjacent_pairs = []
    for i, first in enumerate(planes):
        n1 = np.asarray(first["normal_xy"])
        for second in planes[i + 1:]:
            n2 = np.asarray(second["normal_xy"])
            angle = math.degrees(math.acos(float(np.clip(abs(np.dot(n1, n2)), -1, 1))))
            if abs(angle - 90) > 8:
                continue
            shared_bins = sorted(set(first["occupied_z_bin_ids"]) & set(second["occupied_z_bin_ids"]))
            shared_runs: list[tuple[int, int]] = []
            if shared_bins:
                run_start = previous_bin = shared_bins[0]
                for bin_id in shared_bins[1:]:
                    if bin_id != previous_bin + 1:
                        shared_runs.append((run_start, previous_bin))
                        run_start = bin_id
                    previous_bin = bin_id
                shared_runs.append((run_start, previous_bin))
            if not shared_runs:
                continue
            run_start, run_end = max(shared_runs, key=lambda run: run[1] - run[0] + 1)
            shared_run_span = (run_end - run_start + 1) * .25
            if shared_run_span < min_vertical_span_m:
                continue
            z_low, z_high = run_start * .25, (run_end + 1) * .25
            matrix = np.stack((n1, n2))
            if abs(float(np.linalg.det(matrix))) < .05:
                continue
            corner = np.linalg.solve(matrix, np.array([first["line_offset_m"], second["line_offset_m"]]))
            tangent1 = np.asarray(first["line_direction_xy"])
            tangent2 = np.asarray(second["line_direction_xy"])
            coordinate1 = float(np.dot(corner - np.asarray(first["line_anchor_xy_world_m"]), tangent1))
            coordinate2 = float(np.dot(corner - np.asarray(second["line_anchor_xy_world_m"]), tangent2))
            span1 = first["line_span_bounds_from_anchor_m"]
            span2 = second["line_span_bounds_from_anchor_m"]
            if not (span1[0] - .05 <= coordinate1 <= span1[1] + .05 and span2[0] - .05 <= coordinate2 <= span2[1] + .05):
                continue
            endpoint_gaps = [min(abs(coordinate1 - span1[0]), abs(coordinate1 - span1[1])),
                             min(abs(coordinate2 - span2[0]), abs(coordinate2 - span2[1]))]
            adjacent_pairs.append({
                "face_ids": [first["plane_id"], second["plane_id"]],
                "corner_xy_world_m": corner.tolist(),
                "shared_z_bounds_world_m": [z_low, z_high],
                "shared_vertical_span_m": z_high - z_low,
                "shared_consecutive_vertical_span_m": shared_run_span,
                "normal_angle_degrees": angle,
                "intersection_to_each_observed_line_endpoint_m": endpoint_gaps,
                "corner_supported_by_both_observed_endpoints": bool(max(endpoint_gaps) <= .10),
                "review_required": True,
            })
    return {
        "status": "faces_found" if planes else "no_vertical_faces",
        "input_point_count": len(points),
        "unique_voxel_count": len(unique),
        "voxel_m": voxel_m,
        "surfaces": planes,
        "adjacent_face_pairs": adjacent_pairs,
        "review_required": True,
        "engineering_status": "not_assessed",
        "structural_role": "unknown",
    }
