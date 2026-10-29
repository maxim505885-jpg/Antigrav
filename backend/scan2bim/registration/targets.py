"""Candidate extraction utilities for survey targets.

Sphere candidates are generated from raw point clouds. Their physical identity
and field accuracy require independent validation; no product-level accuracy
claim is made by this module.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping
import numpy as np
from scipy.spatial import cKDTree
from scipy.optimize import least_squares

logger = logging.getLogger(__name__)


def fit_sphere_ransac(
    points: np.ndarray,
    target_radius_m: float = 0.0725,  # Standard 145mm survey sphere (radius 72.5mm)
    radius_tolerance_m: float = 0.005,
    distance_threshold_m: float = 0.003,
    max_iterations: int = 1000,
    min_inliers: int = 30,
    refine_leastsquares: bool = True,
) -> dict[str, Any] | None:
    """Robustly fit a sphere of known or variable radius using RANSAC.

    Parameters:
    - points: Nx3 array of point positions in meters.
    - target_radius_m: Expected target sphere radius (e.g. 0.0725 for 145mm sphere,
                       0.050 for 100mm, 0.100 for 200mm sphere).
    - radius_tolerance_m: Permissible tolerance on radius.
    - distance_threshold_m: Inlier distance threshold from sphere surface.
    - max_iterations: Maximum RANSAC trials.
    - min_inliers: Minimum number of inliers required to declare a target valid.
    - refine_leastsquares: Whether to run Levenberg-Marquardt non-linear refinement on inliers.

    Returns:
    - dict with center, estimated_radius, inlier_count, rmse_mm, quality_score, or None.
    """
    pts = np.asarray(points, dtype=np.float64)
    n = len(pts)
    if n < min_inliers:
        return None

    best_inliers = None
    best_center = None
    best_radius = target_radius_m
    max_inlier_count = 0

    rng = np.random.default_rng(42)

    for _ in range(max_iterations):
        sample_idx = rng.choice(n, size=4, replace=False)
        p = pts[sample_idx]

        # 4 points define a sphere: |p_i - c|^2 = r^2
        # 2*(p_i - p_1) . c = |p_i|^2 - |p_1|^2 for i = 2, 3, 4
        a = 2.0 * (p[1:] - p[0])
        b = np.sum(p[1:] ** 2, axis=1) - np.sum(p[0] ** 2)

        try:
            center = np.linalg.solve(a, b)
        except np.linalg.LinAlgError:
            continue

        radius = np.linalg.norm(p[0] - center)
        if abs(radius - target_radius_m) > radius_tolerance_m:
            continue

        dists = np.abs(np.linalg.norm(pts - center, axis=1) - radius)
        inlier_mask = dists < distance_threshold_m
        inlier_count = int(np.sum(inlier_mask))

        if inlier_count > max_inlier_count:
            max_inlier_count = inlier_count
            best_inliers = inlier_mask
            best_center = center
            best_radius = radius

    if best_inliers is None or max_inlier_count < min_inliers:
        return None

    inlier_pts = pts[best_inliers]

    if refine_leastsquares:
        # Objective: minimize (||p - c|| - r)^2
        def residuals(params: np.ndarray) -> np.ndarray:
            c = params[:3]
            r = params[3]
            return np.linalg.norm(inlier_pts - c, axis=1) - r

        init_params = np.append(best_center, best_radius)
        bounds = (
            np.append(best_center - 0.05, target_radius_m - radius_tolerance_m),
            np.append(best_center + 0.05, target_radius_m + radius_tolerance_m),
        )
        res = least_squares(residuals, init_params, bounds=bounds, method="trf")
        if res.success:
            best_center = res.x[:3]
            best_radius = float(res.x[3])

    # Final residuals
    final_dists = np.abs(np.linalg.norm(inlier_pts - best_center, axis=1) - best_radius)
    rmse_mm = float(np.sqrt(np.mean(final_dists ** 2)) * 1000.0)

    return {
        "target_type": "sphere",
        "center": best_center.tolist(),
        "radius_m": float(best_radius),
        "diameter_mm": float(best_radius * 2000.0),
        "inlier_count": int(len(inlier_pts)),
        "total_candidate_points": int(n),
        "inlier_ratio": float(len(inlier_pts) / n),
        "rmse_mm": rmse_mm,
        "quality_score": float(max(0.0, 1.0 - (rmse_mm / (distance_threshold_m * 1000.0)))),
    }


MIN_SPHERE_SURFACE_COVERAGE_RATIO = 0.10


def _sphere_surface_coverage_ratio(
    points: np.ndarray,
    center: np.ndarray,
    radius_m: float,
    distance_threshold_m: float,
) -> float:
    """Measure 3D angular spread of points that fit a sphere surface.

    A planar arc can have a small radial residual for a large fitted sphere.
    Eigenvalue spread of the unit directions distinguishes that near-1D/2D
    surface arc from a sphere with useful visible angular coverage.
    """
    offsets = np.asarray(points, dtype=np.float64) - np.asarray(center, dtype=np.float64)
    distances = np.linalg.norm(offsets, axis=1)
    inliers = np.abs(distances - radius_m) <= distance_threshold_m
    if int(np.count_nonzero(inliers)) < 4:
        return 0.0

    directions = offsets[inliers] / distances[inliers, None]
    eigenvalues = np.linalg.eigvalsh(np.cov(directions, rowvar=False))
    largest = float(eigenvalues[-1])
    if not np.isfinite(eigenvalues).all() or largest <= 1e-12:
        return 0.0
    return float(max(0.0, float(eigenvalues[0])) / largest)


def detect_spherical_targets(
    points: np.ndarray,
    expected_radius_m: float = 0.0725,
    voxel_size_m: float = 0.04,
    search_radius_m: float = 0.15,
    min_points_per_cluster: int = 50,
    max_candidates: int = 64,
    max_fit_points: int = 2048,
) -> list[dict[str, Any]]:
    """Return potential sphere candidates; independently validate centers before use.

    1. Voxel grid downsampling to find candidate clusters.
    2. Local neighborhood extraction.
    3. High-precision sphere fit on each cluster.
    4. Non-maximum suppression and deduplication.
    """
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < min_points_per_cluster:
        return []

    tree = cKDTree(pts)

    # Coarse candidate centers by density
    mins = np.min(pts, axis=0)
    grid_coords = np.floor((pts - mins) / voxel_size_m).astype(np.int64)

    # Unique voxels with count
    unique_voxels, counts = np.unique(grid_coords, axis=0, return_counts=True)
    dense_mask = counts >= 5
    dense_voxels = unique_voxels[dense_mask]
    dense_counts = counts[dense_mask]

    # A dense scan may contain thousands of occupied voxels around the same
    # surface. Visit strongest, spatially separated seeds first so one target
    # or wall patch does not trigger thousands of redundant local fits.
    candidate_centers: list[np.ndarray] = []
    candidate_spacing_m = max(voxel_size_m, expected_radius_m * 1.5)
    spacing_cells = candidate_spacing_m / voxel_size_m
    cell_radius = int(np.ceil(spacing_cells))
    neighbor_offsets = [
        (dx, dy, dz)
        for dx in range(-cell_radius, cell_radius + 1)
        for dy in range(-cell_radius, cell_radius + 1)
        for dz in range(-cell_radius, cell_radius + 1)
        if dx * dx + dy * dy + dz * dz < spacing_cells * spacing_cells
    ]
    selected_voxel_keys: set[tuple[int, int, int]] = set()
    for voxel_index in np.argsort(-dense_counts, kind="stable"):
        voxel = dense_voxels[voxel_index]
        key = (int(voxel[0]), int(voxel[1]), int(voxel[2]))
        if any(
            (key[0] + dx, key[1] + dy, key[2] + dz) in selected_voxel_keys
            for dx, dy, dz in neighbor_offsets
        ):
            continue
        selected_voxel_keys.add(key)
        candidate_centers.append(mins + (voxel + 0.5) * voxel_size_m)
        if len(candidate_centers) >= max_candidates:
            break

    found_targets: list[dict[str, Any]] = []

    for v_center in candidate_centers:
        neighbor_indices = tree.query_ball_point(
            v_center, search_radius_m, return_sorted=True
        )
        if len(neighbor_indices) < min_points_per_cluster:
            continue

        if len(neighbor_indices) > max_fit_points:
            sample_indices = np.linspace(
                0, len(neighbor_indices) - 1, num=max_fit_points, dtype=np.int64
            )
            neighbor_indices = np.asarray(neighbor_indices, dtype=np.int64)[sample_indices]
        cluster_pts = pts[neighbor_indices]
        fit = fit_sphere_ransac(
            cluster_pts,
            target_radius_m=expected_radius_m,
            radius_tolerance_m=0.008,
            distance_threshold_m=0.003,
            max_iterations=200,
            min_inliers=30,
        )

        if fit and fit["rmse_mm"] < 4.0:
            surface_coverage = _sphere_surface_coverage_ratio(
                cluster_pts,
                np.asarray(fit["center"], dtype=np.float64),
                float(fit["radius_m"]),
                distance_threshold_m=0.003,
            )
            fit["surface_coverage_ratio"] = surface_coverage
            if surface_coverage < MIN_SPHERE_SURFACE_COVERAGE_RATIO:
                continue

            # Check duplicate against existing found targets
            c_new = np.array(fit["center"])
            is_dup = False
            for existing in found_targets:
                c_old = np.array(existing["center"])
                if np.linalg.norm(c_new - c_old) < (expected_radius_m * 1.5):
                    # Keep the one with better RMSE
                    if fit["rmse_mm"] < existing["rmse_mm"]:
                        existing.update(fit)
                    is_dup = True
                    break
            if not is_dup:
                found_targets.append(fit)

    # Assign ordered IDs
    for idx, t in enumerate(found_targets):
        t["id"] = f"SPHERE_{idx + 1:02d}"

    return sorted(found_targets, key=lambda x: x["rmse_mm"])
