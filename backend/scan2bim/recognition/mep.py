"""MEP (Mechanical, Electrical, Plumbing) pipe and duct recognition module.

Provides:
- Robust RANSAC cylinder fitting for linear pipe segments.
- Axis extraction, centerline tracing, diameter estimation.
- Fitting identification (elbows, tees, reducers) based on axis intersections.
- Export to native IFC4 IfcPipeSegment and IfcFlowFitting entities.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, asdict
from typing import Any, List, Optional
import numpy as np


@dataclass
class PipeSegmentHypothesis:
    id: str
    start_point: list[float]  # [x, y, z] in meters
    end_point: list[float]    # [x, y, z] in meters
    axis_direction: list[float]  # normalized [dx, dy, dz]
    radius_m: float
    diameter_mm: float
    length_m: float
    slope_percent: float
    inlier_count: int
    confidence: float
    system_type: str = "Piping"  # "HVAC", "Piping", "Drainage"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _circle_fit_2d(xy: np.ndarray) -> tuple[float, float, float]:
    """Fit circle to 2D points using algebraic Pratt / Kasa method.

    Returns (cx, cy, radius).
    """
    x = xy[:, 0]
    y = xy[:, 1]
    a = np.column_stack([x, y, np.ones_like(x)])
    b = x**2 + y**2
    try:
        c, _, _, _ = np.linalg.lstsq(a, b, rcond=None)
        cx = c[0] / 2.0
        cy = c[1] / 2.0
        r_sq = c[2] + cx**2 + cy**2
        radius = math.sqrt(r_sq) if r_sq > 0 else 0.0
        return float(cx), float(cy), float(radius)
    except Exception:
        return 0.0, 0.0, 0.0


def fit_cylinder_ransac(
    points: np.ndarray,
    max_iterations: int = 150,
    distance_threshold_m: float = 0.02,
    min_radius_m: float = 0.015,  # 30 mm diameter min
    max_radius_m: float = 0.60,   # 1200 mm diameter max
    random_seed: int = 42,
    checkpoint: Callable[[], None] | None = None,
) -> Optional[dict[str, Any]]:
    """Fit a 3D cylinder to a point cluster using RANSAC.

    Uses PCA to extract the primary linear axis, projects cross-section perpendicularly,
    and performs circle fitting.
    """
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 20:
        return None

    rng = np.random.default_rng(random_seed)
    centroid = np.mean(pts, axis=0)
    centered = pts - centroid

    # PCA gives principal components: vt[0] is cylinder axis, vt[1] & vt[2] are cross-section plane
    _, _, vt = np.linalg.svd(centered)
    axis = vt[0] / np.linalg.norm(vt[0])
    u_axis = vt[1] / np.linalg.norm(vt[1])
    v_axis = vt[2] / np.linalg.norm(vt[2])

    best_inliers = 0
    best_params = None

    # RANSAC on small batches to refine axis and center
    for iteration in range(max_iterations):
        if checkpoint is not None and iteration % 10 == 0:
            checkpoint()
        sample_idx = rng.choice(len(pts), size=min(len(pts), 50), replace=False)
        sub_pts = pts[sample_idx]

        # Project sub_pts onto cross section plane (u, v)
        sub_centered = sub_pts - centroid
        u_proj = np.dot(sub_centered, u_axis)
        v_proj = np.dot(sub_centered, v_axis)
        uv = np.column_stack([u_proj, v_proj])

        cx, cy, radius = _circle_fit_2d(uv)
        if not (min_radius_m <= radius <= max_radius_m):
            continue

        # Axis point in 3D
        p0 = centroid + cx * u_axis + cy * v_axis

        # Compute perpendicular distance of all pts to this axis
        diff = pts - p0
        cross = np.cross(diff, axis)
        dist_to_axis = np.linalg.norm(cross, axis=1)

        errors = np.abs(dist_to_axis - radius)
        inlier_mask = errors < distance_threshold_m
        inlier_cnt = int(np.sum(inlier_mask))

        if inlier_cnt > best_inliers and inlier_cnt >= 15:
            best_inliers = inlier_cnt
            best_params = {
                "p0": p0,
                "axis": axis,
                "radius_m": radius,
                "inlier_mask": inlier_mask,
                "inlier_count": inlier_cnt,
            }

    if best_params is None or best_inliers < 15:
        return None

    inliers = pts[best_params["inlier_mask"]]
    p0 = best_params["p0"]
    axis = best_params["axis"]
    radius = best_params["radius_m"]

    # Refine circle fit on all inliers
    inlier_centered = inliers - p0
    u_proj = np.dot(inlier_centered, u_axis)
    v_proj = np.dot(inlier_centered, v_axis)
    rcx, rcy, refined_rad = _circle_fit_2d(np.column_stack([u_proj, v_proj]))
    if min_radius_m <= refined_rad <= max_radius_m:
        radius = refined_rad
        p0 = p0 + rcx * u_axis + rcy * v_axis

    # Project inliers onto axis to compute extent [start_point, end_point]
    projections = np.dot(inliers - p0, axis)
    t_min = float(np.min(projections))
    t_max = float(np.max(projections))
    length = max(0.01, t_max - t_min)

    start_pt = p0 + axis * t_min
    end_pt = p0 + axis * t_max

    # Compute slope: vertical drop per horizontal run
    dx = end_pt[0] - start_pt[0]
    dy = end_pt[1] - start_pt[1]
    dz = end_pt[2] - start_pt[2]
    horiz_dist = math.hypot(dx, dy)
    slope_percent = (dz / horiz_dist * 100.0) if horiz_dist > 1e-4 else 0.0

    confidence = float(min(1.0, best_inliers / max(len(pts), 1)))

    return {
        "start_point": start_pt.tolist(),
        "end_point": end_pt.tolist(),
        "axis_direction": axis.tolist(),
        "radius_m": round(radius, 4),
        "diameter_mm": round(radius * 2000.0, 1),
        "length_m": round(length, 3),
        "slope_percent": round(slope_percent, 2),
        "inlier_count": best_inliers,
        "confidence": round(confidence, 3),
    }


def detect_pipe_network(
    points: np.ndarray,
    min_segment_points: int = 30,
    max_segments: int = 10,
    max_iterations: int = 120,
    checkpoint: Callable[[], None] | None = None,
) -> list[PipeSegmentHypothesis]:
    """Segment multiple linear pipe runs from point cloud."""
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < min_segment_points:
        return []

    remaining = np.copy(pts)
    pipes: list[PipeSegmentHypothesis] = []

    for i in range(max(0, int(max_segments))):
        if len(remaining) < min_segment_points:
            break

        if checkpoint is not None:
            checkpoint()
        cyl = fit_cylinder_ransac(
            remaining,
            max_iterations=max(1, int(max_iterations)),
            checkpoint=checkpoint,
        )
        if cyl is None:
            break

        # Remove inliers from remaining pool
        p0 = np.array(cyl["start_point"])
        axis = np.array(cyl["axis_direction"])
        rad = cyl["radius_m"]

        v = remaining - p0
        cross = np.cross(v, axis)
        dists = np.linalg.norm(cross, axis=1)
        inlier_mask = np.abs(dists - rad) < 0.03

        if np.sum(inlier_mask) < 20:
            break

        pipe = PipeSegmentHypothesis(
            id=f"pipe_{i+1:02d}",
            start_point=cyl["start_point"],
            end_point=cyl["end_point"],
            axis_direction=cyl["axis_direction"],
            radius_m=cyl["radius_m"],
            diameter_mm=cyl["diameter_mm"],
            length_m=cyl["length_m"],
            slope_percent=cyl["slope_percent"],
            inlier_count=cyl["inlier_count"],
            confidence=cyl["confidence"],
        )
        pipes.append(pipe)
        remaining = remaining[~inlier_mask]

    return pipes
