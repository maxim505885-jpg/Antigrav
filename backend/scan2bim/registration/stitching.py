"""Point cloud stitching (registration) module for multi-station scans.

Provides:
- Robust Iterative Closest Point (ICP) using SVD / Kabsch algorithm and cKDTree.
- SE(3) Transformation matrix calculation.
- ReCap-compatible registration manifest and unified point cloud export.
- Batch merging of multiple RCS/PLY scans into unified positions.npy with meta.json.
"""
from __future__ import annotations

import hashlib
import json
import logging
from threading import Lock
from pathlib import Path
from typing import Any, Mapping
import numpy as np
from scipy.spatial import cKDTree

logger = logging.getLogger(__name__)
_OPEN3D_FGR_RANDOM_LOCK = Lock()


def validate_full_resolution_station(
    station_id: str,
    source_point_count: int | None,
    stored_point_count: int,
    *,
    complete: bool,
    decimated: bool | None = None,
) -> None:
    """Fail closed when a station cannot be shown complete at full resolution."""
    if decimated is True:
        raise ValueError(f"{station_id} source is decimated")
    if complete is not True:
        raise ValueError(f"{station_id} source stream is incomplete")
    if not isinstance(stored_point_count, int) or stored_point_count <= 0:
        raise ValueError(f"{station_id} stored point count must be a positive integer")
    if source_point_count is None:
        raise ValueError(f"{station_id} source point count is missing")
    if not isinstance(source_point_count, int) or source_point_count <= 0:
        raise ValueError(f"{station_id} source point count must be a positive integer")
    if source_point_count != stored_point_count:
        raise ValueError(
            f"{station_id} is incomplete: source has {source_point_count} points, "
            f"but only {stored_point_count} are stored"
        )


def validate_unified_cloud_cache(
    meta: Mapping[str, Any],
    *,
    expected_point_count: int,
    actual_point_count: int,
    expected_station_inputs: Mapping[str, Any],
    expected_registration_matrix: np.ndarray,
    actual_file_sha256: str,
) -> None:
    """Reject cached merged points unless inputs, transform and bytes still match."""
    if meta.get("unified_merge") is not True:
        raise ValueError("cached point cloud is not marked as a unified merge")
    if (
        actual_point_count != expected_point_count
        or meta.get("source_point_count") != expected_point_count
        or meta.get("stored_point_count") != expected_point_count
    ):
        raise ValueError("cached unified point cloud point count does not match current stations")
    if not actual_file_sha256 or meta.get("checksum_sha256") != actual_file_sha256:
        raise ValueError("cached unified point cloud checksum does not match its bytes")
    if meta.get("station_input_fingerprints") != dict(expected_station_inputs):
        raise ValueError("cached unified point cloud station inputs do not match current sources")
    expected_row_ranges = [
        {
            "station_id": station_id,
            "source_row_start": inputs["unified_row_start"],
            "source_row_end_exclusive": inputs["unified_row_end_exclusive"],
            "source_row_count": inputs["stored_point_count"],
            "source_row_index_base": 0,
        }
        for station_id, inputs in expected_station_inputs.items()
        if "unified_row_start" in inputs and "unified_row_end_exclusive" in inputs
    ]
    if expected_row_ranges and meta.get("station_row_ranges") != expected_row_ranges:
        raise ValueError("cached unified point cloud source-row ranges do not match current station order")
    try:
        cached_matrix = np.asarray(meta.get("registration_matrix_station_02"), dtype=np.float64)
        expected_matrix = np.asarray(expected_registration_matrix, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("cached unified point cloud registration matrix is invalid") from exc
    if (
        cached_matrix.shape != (4, 4)
        or expected_matrix.shape != (4, 4)
        or not np.isfinite(cached_matrix).all()
        or not np.isfinite(expected_matrix).all()
        or not np.allclose(cached_matrix, expected_matrix, rtol=0.0, atol=1e-10)
    ):
        raise ValueError("cached unified point cloud registration matrix does not match current ICP")


def write_centered_unified_positions(
    stations: list[Mapping[str, Any]],
    output_path: str | Path,
    *,
    chunk_size: int = 1_000_000,
) -> dict[str, Any]:
    """Write local float32 coordinates without rounding large world coordinates first.

    Each station may provide a 4x4 matrix and a separate world-space origin.
    Two bounded-memory passes calculate world bounds and then write coordinates
    relative to the shared center. All transforms and subtraction happen in float64.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")

    prepared: list[tuple[Any, np.ndarray, np.ndarray, int]] = []
    row_ranges: list[dict[str, Any]] = []
    station_ids: set[str] = set()
    total_count = 0
    for index, station in enumerate(stations):
        points = station.get("points")
        shape = getattr(points, "shape", None)
        if shape is None or len(shape) != 2 or shape[1] != 3 or shape[0] <= 0:
            raise ValueError(f"station {index + 1} points must be a non-empty Nx3 array")
        matrix = np.asarray(station.get("matrix_4x4", np.eye(4)), dtype=np.float64)
        offset = np.asarray(station.get("origin", [0.0, 0.0, 0.0]), dtype=np.float64)
        if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
            raise ValueError(f"station {index + 1} transform must be a finite 4x4 matrix")
        if offset.shape != (3,) or not np.isfinite(offset).all():
            raise ValueError(f"station {index + 1} origin must be a finite 3D vector")
        station_id = str(station.get("id") or station.get("station_id") or f"station_{index + 1}").strip()
        if not station_id or station_id in station_ids:
            raise ValueError("station IDs must be non-empty and unique for source-row mapping")
        station_ids.add(station_id)
        prepared.append((points, matrix[:3, :3], matrix[:3, 3] + offset, int(shape[0])))
        row_ranges.append({
            "station_id": station_id,
            "source_row_start": total_count,
            "source_row_end_exclusive": total_count + int(shape[0]),
            "source_row_count": int(shape[0]),
            "source_row_index_base": 0,
        })
        total_count += int(shape[0])
    if not prepared:
        raise ValueError("at least one station is required")

    world_min = np.full(3, np.inf, dtype=np.float64)
    world_max = np.full(3, -np.inf, dtype=np.float64)
    for points, rotation, translation, count in prepared:
        for start in range(0, count, chunk_size):
            source = np.asarray(points[start:start + chunk_size], dtype=np.float64)
            if not np.isfinite(source).all():
                raise ValueError("station point coordinates must be finite")
            world = source @ rotation.T + translation
            world_min = np.minimum(world_min, world.min(axis=0))
            world_max = np.maximum(world_max, world.max(axis=0))

    origin = world_min / 2.0 + world_max / 2.0
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    from numpy.lib.format import open_memmap

    local_positions = open_memmap(output, mode="w+", dtype=np.float32, shape=(total_count, 3))
    cursor = 0
    for points, rotation, translation, count in prepared:
        for start in range(0, count, chunk_size):
            end = min(start + chunk_size, count)
            source = np.asarray(points[start:end], dtype=np.float64)
            local = source @ rotation.T + translation - origin
            if not np.isfinite(local).all() or np.any(np.abs(local) > np.finfo(np.float32).max):
                raise ValueError("centered station coordinates cannot be represented as float32")
            local_positions[cursor:cursor + end - start] = local.astype(np.float32)
            cursor += end - start
    local_positions.flush()
    del local_positions
    return {
        "total_points": total_count,
        "origin": origin,
        "world_min": world_min,
        "world_max": world_max,
        "station_row_ranges": row_ranges,
    }


def kabsch_fit(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Compute optimal rotation matrix R and translation t using Kabsch algorithm (SVD).

    Minimizes || R * source + t - target ||^2.
    """
    centroid_src = np.mean(source, axis=0)
    centroid_dst = np.mean(target, axis=0)

    p = source - centroid_src
    q = target - centroid_dst

    h = p.T @ q
    u, s, vt = np.linalg.svd(h)
    r = vt.T @ u.T

    # Reflection correction
    if np.linalg.det(r) < 0:
        vt[-1, :] *= -1
        r = vt.T @ u.T

    t = centroid_dst - r @ centroid_src
    return r, t


def convert_local_transform_to_world(
    local_transform: np.ndarray,
    source_origin: np.ndarray,
    target_origin: np.ndarray,
) -> np.ndarray:
    """Convert source-local → target-local to source-world → target-world.

    Stored/displayed points are relative to each cloud's saved world origin:
    ``world = local + origin``. The rotation is unchanged and translation is
    ``t_world = t_local + target_origin - R @ source_origin``.
    """
    transform = np.asarray(local_transform, dtype=np.float64)
    source = np.asarray(source_origin, dtype=np.float64)
    target = np.asarray(target_origin, dtype=np.float64)
    if transform.shape != (4, 4) or not np.isfinite(transform).all():
        raise ValueError("local transform must be a finite 4×4 matrix")
    if source.shape != (3,) or target.shape != (3,) or not np.isfinite(source).all() or not np.isfinite(target).all():
        raise ValueError("source and target origins must be finite 3D vectors")
    if not np.allclose(transform[3], [0.0, 0.0, 0.0, 1.0], atol=1e-10):
        raise ValueError("local transform must be an affine 4×4 matrix")

    world = transform.copy()
    world[:3, 3] += target - transform[:3, :3] @ source
    return world


def compute_pairwise_svd_alignment(
    source_points: np.ndarray,
    target_points: np.ndarray,
) -> dict[str, Any]:
    """Compute rigid 6-DOF transformation from user-selected matching point pairs.

    Requires at least 3 non-collinear corresponding point pairs:
    source_points[i] corresponds to target_points[i].

    Returns:
    - matrix_4x4: SE(3) transformation matrix (4x4)
    - rotation_3x3: 3x3 rotation matrix
    - translation: 3-vector translation
    - residuals_m: list of Euclidean distances per pair after transformation (in meters)
    - residuals_mm: list of Euclidean distances per pair after transformation (in mm)
    - rmse_mm: root-mean-square error across all pairs (in mm)
    - max_error_mm: maximum residual across all pairs (in mm)
    """
    src = np.asarray(source_points, dtype=np.float64)
    dst = np.asarray(target_points, dtype=np.float64)

    if src.ndim != 2 or src.shape[1] != 3:
        raise ValueError("source_points must be an N×3 array")
    if dst.ndim != 2 or dst.shape[1] != 3:
        raise ValueError("target_points must be an N×3 array")
    if len(src) != len(dst):
        raise ValueError(f"Point pair count mismatch: source has {len(src)} points, target has {len(dst)} points")
    if len(src) < 3:
        raise ValueError(f"At least 3 point pairs are required for 3D rigid alignment, got {len(src)}")

    if not np.isfinite(src).all() or not np.isfinite(dst).all():
        raise ValueError("Point coordinates must be finite numbers")

    # Check for collinearity / degeneracy (rank < 2 in centered coordinates)
    src_centered = src - np.mean(src, axis=0)
    if np.linalg.matrix_rank(src_centered) < 2:
        raise ValueError("Source points are collinear or degenerate; cannot determine 3D orientation")

    dst_centered = dst - np.mean(dst, axis=0)
    if np.linalg.matrix_rank(dst_centered) < 2:
        raise ValueError("Target points are collinear or degenerate; cannot determine 3D orientation")

    r, t = kabsch_fit(src, dst)

    # Transform source points
    transformed_src = (r @ src.T).T + t

    # Compute per-pair residuals
    diffs = transformed_src - dst
    residuals_m = np.linalg.norm(diffs, axis=1)
    residuals_mm = residuals_m * 1000.0
    rmse_mm = float(np.sqrt(np.mean(residuals_mm ** 2)))
    max_error_mm = float(np.max(residuals_mm))

    mat_4x4 = np.eye(4, dtype=np.float64)
    mat_4x4[:3, :3] = r
    mat_4x4[:3, 3] = t

    return {
        "matrix_4x4": mat_4x4.tolist(),
        "rotation_3x3": r.tolist(),
        "translation": t.tolist(),
        "residuals_m": residuals_m.tolist(),
        "residuals_mm": residuals_mm.tolist(),
        "rmse_mm": round(rmse_mm, 4),
        "max_error_mm": round(max_error_mm, 4),
        "pairs_count": len(src),
    }


def _sample_registration_indices(
    point_count: int,
    max_sample_points: int,
    *,
    seed: int,
) -> np.ndarray:
    """Choose a reproducible sample without aliasing a regular source-row stride."""
    if point_count < 0:
        raise ValueError("point_count must be non-negative")
    if max_sample_points < 1:
        raise ValueError("max_sample_points must be positive")
    count = min(point_count, max_sample_points)
    if count == point_count:
        return np.arange(point_count, dtype=np.int64)
    rng = np.random.default_rng(seed)
    if count * 4 >= point_count:
        # This branch is bounded by at most four times the requested sample size.
        return np.sort(rng.choice(point_count, size=count, replace=False).astype(np.int64))

    # Floyd's algorithm stores only the requested sample, even for hundreds of
    # millions of source rows.
    selected: set[int] = set()
    for upper in range(point_count - count, point_count):
        candidate = int(rng.integers(upper + 1))
        selected.add(upper if candidate in selected else candidate)
    return np.fromiter(sorted(selected), dtype=np.int64, count=count)


def _validate_finite_points_in_chunks(points: np.ndarray, label: str) -> None:
    """Bound temporary validation memory when the input is a full-resolution mmap."""
    chunk_rows = 1_000_000
    for start in range(0, len(points), chunk_rows):
        try:
            finite = np.isfinite(points[start : start + chunk_rows]).all()
        except TypeError as exc:
            raise ValueError(f"{label}_points must be numeric") from exc
        if not finite:
            raise ValueError(f"{label}_points must contain only finite values")


def global_fgr_icp(
    source_points: np.ndarray,
    target_points: np.ndarray,
    *,
    evaluation_source_points: np.ndarray | None = None,
    evaluation_target_points: np.ndarray | None = None,
    max_sample_points: int = 100_000,
    voxel_size_m: float = 0.5,
    max_correspondence_distance_m: float = 0.15,
    max_iterations: int = 80,
    sample_seed: int = 42,
) -> dict[str, Any]:
    """Return a read-only FGR + point-to-plane ICP transform candidate.

    Fit metrics describe the samples used to estimate the transform. Optional
    evaluation samples are disjoint at the caller and are only scored after
    fitting; they are not surveyed controls or physical accuracy measurements.
    This function never applies or persists a transformation.
    """
    source_raw = np.asarray(source_points)
    target_raw = np.asarray(target_points)
    for label, points in (("source", source_raw), ("target", target_raw)):
        if points.ndim != 2 or points.shape[1] != 3:
            raise ValueError(f"{label}_points must be an N×3 array")
        if len(points) < 100:
            raise ValueError(f"{label}_points must contain at least 100 points")
        _validate_finite_points_in_chunks(points, label)
    if (evaluation_source_points is None) != (evaluation_target_points is None):
        raise ValueError("evaluation source and target points must be provided together")
    evaluation_source_raw = None
    evaluation_target_raw = None
    if evaluation_source_points is not None and evaluation_target_points is not None:
        evaluation_source_raw = np.asarray(evaluation_source_points)
        evaluation_target_raw = np.asarray(evaluation_target_points)
        for label, points in (
            ("evaluation_source", evaluation_source_raw),
            ("evaluation_target", evaluation_target_raw),
        ):
            if points.ndim != 2 or points.shape[1] != 3:
                raise ValueError(f"{label}_points must be an N×3 array")
            if len(points) < 100:
                raise ValueError(f"{label}_points must contain at least 100 points")
            _validate_finite_points_in_chunks(points, label)
    if not isinstance(max_sample_points, int) or max_sample_points < 100:
        raise ValueError("max_sample_points must be an integer of at least 100")
    if not np.isfinite(voxel_size_m) or voxel_size_m <= 0:
        raise ValueError("voxel_size_m must be finite and positive")
    if not np.isfinite(max_correspondence_distance_m) or max_correspondence_distance_m <= 0:
        raise ValueError("max_correspondence_distance_m must be finite and positive")
    if not isinstance(max_iterations, int) or max_iterations < 1:
        raise ValueError("max_iterations must be a positive integer")
    if not isinstance(sample_seed, int) or sample_seed < 0 or sample_seed >= 2**31:
        raise ValueError("sample_seed must be an integer in [0, 2^31)")

    source_indices = _sample_registration_indices(
        len(source_raw), max_sample_points, seed=sample_seed
    )
    target_indices = _sample_registration_indices(
        len(target_raw), max_sample_points, seed=sample_seed + 1
    )
    source = np.asarray(source_raw[source_indices], dtype=np.float64)
    target = np.asarray(target_raw[target_indices], dtype=np.float64)
    try:
        import open3d as o3d
    except ImportError as exc:
        raise RuntimeError("Open3D is required for global FGR registration") from exc

    source_cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(source))
    target_cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(target))
    source_down = source_cloud.voxel_down_sample(voxel_size_m)
    target_down = target_cloud.voxel_down_sample(voxel_size_m)
    if len(source_down.points) < 50 or len(target_down.points) < 50:
        raise ValueError("Too few spatial samples remain for global registration")

    normal_radius = max(voxel_size_m * 0.75, 0.1)
    feature_radius = voxel_size_m * 5.0
    normal_search = o3d.geometry.KDTreeSearchParamHybrid(radius=normal_radius, max_nn=40)
    feature_search = o3d.geometry.KDTreeSearchParamHybrid(radius=feature_radius, max_nn=100)
    for cloud in (source_down, target_down):
        cloud.estimate_normals(normal_search)
    source_features = o3d.pipelines.registration.compute_fpfh_feature(source_down, feature_search)
    target_features = o3d.pipelines.registration.compute_fpfh_feature(target_down, feature_search)
    fgr_options = o3d.pipelines.registration.FastGlobalRegistrationOption(
        maximum_correspondence_distance=voxel_size_m * 1.5,
        iteration_number=128,
        maximum_tuple_count=1000,
    )
    # Open3D FGR uses a process-global RNG; seed and serialize registration calls.
    with _OPEN3D_FGR_RANDOM_LOCK:
        o3d.utility.random.seed(sample_seed)
        coarse = o3d.pipelines.registration.registration_fgr_based_on_feature_matching(
            source_down, target_down, source_features, target_features, fgr_options
        )
    initial = np.asarray(coarse.transformation, dtype=np.float64)
    if (
        initial.shape != (4, 4)
        or not np.isfinite(initial).all()
        or coarse.fitness <= 0
        or not np.allclose(initial[3], [0.0, 0.0, 0.0, 1.0], atol=1e-8)
        or not np.allclose(initial[:3, :3].T @ initial[:3, :3], np.eye(3), atol=1e-3)
        or not np.isclose(np.linalg.det(initial[:3, :3]), 1.0, atol=1e-3)
    ):
        raise ValueError("Global feature matching did not produce a valid rigid candidate")

    target_cloud.estimate_normals(normal_search)
    refined = o3d.pipelines.registration.registration_icp(
        source_cloud,
        target_cloud,
        max_correspondence_distance_m,
        initial,
        o3d.pipelines.registration.TransformationEstimationPointToPlane(),
        o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=max_iterations),
    )
    matrix = np.asarray(refined.transformation, dtype=np.float64)
    if (
        matrix.shape != (4, 4)
        or not np.isfinite(matrix).all()
        or not np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0], atol=1e-8)
        or not np.allclose(matrix[:3, :3].T @ matrix[:3, :3], np.eye(3), atol=1e-3)
        or not np.isclose(np.linalg.det(matrix[:3, :3]), 1.0, atol=1e-3)
    ):
        raise ValueError("Point-to-plane ICP returned an invalid rigid candidate")

    inlier_count = len(refined.correspondence_set)
    holdout = None
    if evaluation_source_raw is not None and evaluation_target_raw is not None:
        evaluation_source = np.asarray(evaluation_source_raw, dtype=np.float64)
        evaluation_target = np.asarray(evaluation_target_raw, dtype=np.float64)
        evaluation_source_cloud = o3d.geometry.PointCloud(
            o3d.utility.Vector3dVector(evaluation_source)
        )
        evaluation_target_cloud = o3d.geometry.PointCloud(
            o3d.utility.Vector3dVector(evaluation_target)
        )
        evaluated = o3d.pipelines.registration.evaluate_registration(
            evaluation_source_cloud,
            evaluation_target_cloud,
            max_correspondence_distance_m,
            matrix,
        )
        holdout_count = len(evaluated.correspondence_set)
        reverse_evaluated = o3d.pipelines.registration.evaluate_registration(
            evaluation_target_cloud,
            evaluation_source_cloud,
            max_correspondence_distance_m,
            np.linalg.inv(matrix),
        )
        reverse_holdout_count = len(reverse_evaluated.correspondence_set)
        holdout = {
            "status": "evaluated",
            "rmse_mm": (
                float(evaluated.inlier_rmse * 1000.0) if holdout_count else None
            ),
            "inlier_count": holdout_count,
            "source_sample_count": len(evaluation_source),
            "target_sample_count": len(evaluation_target),
            "inlier_fraction": float(holdout_count / len(evaluation_source)),
            "is_disjoint_from_fit": True,
            "reverse": {
                "status": "evaluated",
                "rmse_mm": (
                    round(float(reverse_evaluated.inlier_rmse * 1000.0), 9)
                    if reverse_holdout_count else None
                ),
                "inlier_count": reverse_holdout_count,
                "source_sample_count": len(evaluation_target),
                "target_sample_count": len(evaluation_source),
                "inlier_fraction": float(reverse_holdout_count / len(evaluation_target)),
                "is_disjoint_from_fit": True,
            },
        }
    return {
        "status": "candidate",
        "accuracy_status": "not_measured",
        "independent_control_count": 0,
        "fit_residuals_are_independent": False,
        "holdout": holdout or {
            "status": "not_available",
            "rmse_mm": None,
            "inlier_count": 0,
            "source_sample_count": 0,
            "target_sample_count": 0,
            "inlier_fraction": None,
            "is_disjoint_from_fit": False,
            "reverse": {
                "status": "not_available",
                "rmse_mm": None,
                "inlier_count": 0,
                "source_sample_count": 0,
                "target_sample_count": 0,
                "inlier_fraction": None,
                "is_disjoint_from_fit": False,
            },
        },
        "method": "open3d_fgr_point_to_plane_icp",
        "matrix_4x4": matrix.tolist(),
        "rotation_3x3": matrix[:3, :3].tolist(),
        "translation": matrix[:3, 3].tolist(),
        "rmse_mm": float(refined.inlier_rmse * 1000.0) if inlier_count else None,
        "inlier_count": inlier_count,
        "source_sample_count": len(source),
        "target_sample_count": len(target),
        "inlier_fraction": float(inlier_count / len(source)),
        "iterations": None,
        "iteration_limit": max_iterations,
        "sample_method": "seeded_random_without_replacement",
        "sample_seed": sample_seed,
        "open3d_seed": sample_seed,
        "converged": None,
        "optimizer_convergence": "not_exposed_by_open3d_result",
        "global_fgr_fitness": float(coarse.fitness),
        "global_fgr_rmse_mm": float(coarse.inlier_rmse * 1000.0) if coarse.fitness > 0 else None,
        "voxel_size_m": float(voxel_size_m),
        "max_correspondence_distance_m": float(max_correspondence_distance_m),
    }


def rigid_icp(
    source_points: np.ndarray,
    target_points: np.ndarray,
    max_iterations: int = 50,
    tolerance_m: float = 1e-4,
    max_correspondence_distance_m: float = 0.5,
    sample_size: int = 10000,
    random_seed: int | None = 0,
    initial_t4x4: np.ndarray | None = None,
) -> dict[str, Any]:
    """Align source point cloud to target point cloud.

    Returns:
    - R: 3x3 rotation matrix
    - t: 3-vector translation
    - transformation_4x4: SE(3) matrix
    - rmse_mm: root mean square error in millimeters
    - converged: bool
    """
    source = np.asarray(source_points)
    target = np.asarray(target_points)
    if source.ndim != 2 or source.shape[1] != 3:
        raise ValueError("source_points must be an N×3 array")
    if target.ndim != 2 or target.shape[1] != 3:
        raise ValueError("target_points must be an N×3 array")
    if len(source) < 10 or len(target) < 10:
        raise ValueError("source_points and target_points must each contain at least 10 points")
    if not isinstance(sample_size, int) or sample_size < 10:
        raise ValueError("sample_size must be an integer of at least 10")
    if not isinstance(max_iterations, int) or max_iterations < 1:
        raise ValueError("max_iterations must be a positive integer")
    if not np.isfinite(tolerance_m) or tolerance_m <= 0:
        raise ValueError("tolerance_m must be finite and positive")
    if not np.isfinite(max_correspondence_distance_m) or max_correspondence_distance_m <= 0:
        raise ValueError("max_correspondence_distance_m must be finite and positive")

    initial = None
    if initial_t4x4 is not None:
        initial = np.asarray(initial_t4x4, dtype=np.float64)
        if initial.shape != (4, 4) or not np.isfinite(initial).all():
            raise ValueError("initial_t4x4 must be a finite 4×4 matrix")
        if not np.allclose(initial[3], [0.0, 0.0, 0.0, 1.0], atol=1e-8):
            raise ValueError("initial_t4x4 must be an affine rigid transform")
        rotation = initial[:3, :3]
        if (
            not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-3)
            or not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-3)
        ):
            raise ValueError("initial_t4x4 rotation must be orthonormal with determinant +1")

    # Fixed-seed sampling without replacement keeps large-cloud registration
    # bounded and makes each run auditable. Returned indices refer to the
    # caller's input arrays; callers can map them back to persisted source rows.
    rng = np.random.default_rng(random_seed)
    source_sample_indices = (
        np.sort(rng.choice(len(source), size=sample_size, replace=False))
        if len(source) > sample_size else np.arange(len(source), dtype=np.int64)
    )
    target_sample_count = min(len(target), sample_size * 2)
    target_sample_indices = (
        np.sort(rng.choice(len(target), size=target_sample_count, replace=False))
        if len(target) > target_sample_count else np.arange(len(target), dtype=np.int64)
    )
    src = np.asarray(source[source_sample_indices], dtype=np.float64).copy()
    tgt = np.asarray(target[target_sample_indices], dtype=np.float64)
    if not np.isfinite(src).all() or not np.isfinite(tgt).all():
        raise ValueError("sampled source_points and target_points must contain only finite values")

    tree = cKDTree(tgt)
    if initial is None:
        current_r = np.eye(3, dtype=np.float64)
        # Remove bulk translation before nearest-neighbour matching when no
        # measured/manual or algorithmic initial pose is available.
        current_t = np.mean(tgt, axis=0) - np.mean(src, axis=0)
    else:
        # A supplied pose is already an informed initialization. Re-centering
        # here would silently overwrite its translation and can move a valid
        # tie-point fit away from the actual overlap.
        current_r = initial[:3, :3].copy()
        current_t = initial[:3, 3].copy()
    prev_rmse = float("inf")

    converged = False
    iteration = 0
    for iteration in range(max_iterations):
        transformed_src = (current_r @ src.T).T + current_t
        distances, indices = tree.query(transformed_src, k=1)

        # Filter out points beyond max correspondence distance (outliers)
        valid = distances < max_correspondence_distance_m
        if np.sum(valid) < 10:
            break

        step_r, step_t = kabsch_fit(transformed_src[valid], tgt[indices[valid]])

        current_r = step_r @ current_r
        current_t = step_r @ current_t + step_t

        transformed_src = (current_r @ src.T).T + current_t
        updated_distances, _ = tree.query(transformed_src, k=1)
        updated_valid = updated_distances < max_correspondence_distance_m
        if np.sum(updated_valid) < 10:
            break

        rmse = float(np.sqrt(np.mean(updated_distances[updated_valid] ** 2)))
        rotation_step = float(
            np.arccos(np.clip((np.trace(step_r) - 1.0) / 2.0, -1.0, 1.0))
        )
        translation_step = float(np.linalg.norm(step_t))
        if abs(prev_rmse - rmse) < tolerance_m or (
            rotation_step < tolerance_m and translation_step < tolerance_m
        ):
            converged = True
            break
        prev_rmse = rmse

    t4x4 = np.eye(4, dtype=np.float64)
    t4x4[:3, :3] = current_r
    t4x4[:3, 3] = current_t

    final_points = (current_r @ src.T).T + current_t
    final_distances, _ = tree.query(final_points, k=1)
    final_valid = final_distances < max_correspondence_distance_m
    inlier_count = int(np.count_nonzero(final_valid))
    inlier_fraction = float(inlier_count / len(src))
    final_rmse = (
        None
        if not np.any(final_valid)
        else round(float(np.sqrt(np.mean(final_distances[final_valid] ** 2)) * 1000.0), 3)
    )

    return {
        "rotation": current_r.tolist(),
        "translation": current_t.tolist(),
        "matrix_4x4": t4x4.tolist(),
        "rmse_mm": final_rmse,
        "inlier_count": inlier_count,
        "source_sample_count": int(len(src)),
        "target_sample_count": int(len(tgt)),
        "inlier_fraction": round(inlier_fraction, 6),
        "iterations": iteration + 1,
        "converged": converged,
        "source_sample_indices": source_sample_indices.tolist(),
        "target_sample_indices": target_sample_indices.tolist(),
    }


def create_recap_registration_project(
    stations: list[dict[str, Any]],
    project_name: str,
    output_path: Path,
) -> Path:
    """Write SCAN registration metadata; this does not create or verify an RCP project."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    station_ids = [
        str(s.get("id") or s.get("station_id") or f"station_{idx + 1}").strip()
        for idx, s in enumerate(stations)
    ]
    if any(not station_id for station_id in station_ids) or len(set(station_ids)) != len(station_ids):
        raise ValueError("station IDs must be non-empty and unique in a registration manifest")

    manifest = {
        "version": "1.0",
        "format": "SCAN station-registration manifest",
        "status": "metadata_only",
        "recap_project_generated": False,
        "registration_verified": False,
        "notice": "This JSON records station poses only; it is not an Autodesk ReCap RCP/RCS project.",
        "project_name": project_name,
        "station_count": len(stations),
        "stations": [
            {
                "station_id": s.get("id") or s.get("station_id") or f"station_{idx+1}",
                "file_path": str(s.get("path", "")),
                "point_count": int(s.get("point_count", 0)),
                "source_row_start": s.get("source_row_start"),
                "source_row_end_exclusive": s.get("source_row_end_exclusive"),
                "source_row_index_base": 0,
                "matrix_4x4": s.get("matrix_4x4", np.eye(4).tolist()),
                "rmse_mm": (
                    float(s["rmse_mm"]) if s.get("rmse_mm") is not None else None
                ),
            }
            for idx, s in enumerate(stations)
        ],
    }
    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def export_stitched_cloud(
    stations_data: list[dict[str, Any]],
    output_path: Path,
) -> Path:
    """Apply SE(3) transformation to all stations and save unified point cloud (PLY format)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    all_points = []
    all_colors = []

    for st in stations_data:
        pts = np.asarray(st["points"], dtype=np.float64)
        mat = np.asarray(st.get("matrix_4x4", np.eye(4)), dtype=np.float64)

        r = mat[:3, :3]
        t = mat[:3, 3] + np.asarray(st.get("origin", [0.0, 0.0, 0.0]), dtype=np.float64)
        transformed_pts = (r @ pts.T).T + t
        all_points.append(transformed_pts)

        if "colors" in st and st["colors"] is not None and len(st["colors"]) == len(pts):
            all_colors.append(np.asarray(st["colors"], dtype=np.uint8))
        else:
            all_colors.append(np.full((len(pts), 3), 200, dtype=np.uint8))

    merged_pts = np.vstack(all_points)
    merged_cols = np.vstack(all_colors)

    header = f"""ply
format binary_little_endian 1.0
element vertex {len(merged_pts)}
property double x
property double y
property double z
property uchar red
property uchar green
property uchar blue
end_header
"""
    with open(output_path, "wb") as f:
        f.write(header.encode("ascii"))
        vertex_dtype = np.dtype([
            ("x", "<f8"), ("y", "<f8"), ("z", "<f8"),
            ("red", "u1"), ("green", "u1"), ("blue", "u1"),
        ])
        vertex_data = np.empty(len(merged_pts), dtype=vertex_dtype)
        vertex_data["x"] = merged_pts[:, 0]
        vertex_data["y"] = merged_pts[:, 1]
        vertex_data["z"] = merged_pts[:, 2]
        vertex_data["red"] = merged_cols[:, 0]
        vertex_data["green"] = merged_cols[:, 1]
        vertex_data["blue"] = merged_cols[:, 2]
        f.write(vertex_data.tobytes())

    return output_path


def merge_and_save_unified_cloud(
    stations: list[dict[str, Any]],
    output_dir: str | Path,
    project_title: str = "Сводное облако цеха (1.rcs + 2.rcs)",
    export_ply: bool = False,
) -> dict[str, Any]:
    """Merge multiple scan stations into a unified dataset with positions.npy and meta.json.

    Each station in `stations` contains:
    - 'id' or 'name': str
    - 'points': np.ndarray (Nx3)
    - 'matrix_4x4': optional 4x4 SE(3) transformation matrix (defaults to identity)
    - 'path': optional str / Path

    Returns dict with paths to positions.npy, meta.json, registration_manifest.json, and point count.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    transformed_clouds = []
    total_count = 0
    station_meta = []
    station_ids: set[str] = set()

    for idx, st in enumerate(stations):
        pts = np.asarray(st["points"], dtype=np.float64)
        mat = np.asarray(st.get("matrix_4x4", np.eye(4)), dtype=np.float64)

        r = mat[:3, :3]
        t = mat[:3, 3] + np.asarray(st.get("origin", [0.0, 0.0, 0.0]), dtype=np.float64)
        transformed_pts = (r @ pts.T).T + t
        transformed_clouds.append(transformed_pts)
        station_id = str(st.get("id") or st.get("name") or f"station_{idx+1}").strip()
        if not station_id or station_id in station_ids:
            raise ValueError("station IDs must be non-empty and unique for source-row mapping")
        station_ids.add(station_id)
        row_start = total_count
        total_count += len(transformed_pts)

        station_meta.append({
            "station_id": station_id,
            "path": str(st.get("path", "")),
            "point_count": len(pts),
            "source_row_count": len(pts),
            "source_row_start": row_start,
            "source_row_end_exclusive": total_count,
            "matrix_4x4": mat.tolist(),
            "rmse_mm": st.get("rmse_mm"),
        })

    merged_world = np.vstack(transformed_clouds)

    # Compute global world bounding box
    world_min = merged_world.min(axis=0).astype(np.float64)
    world_max = merged_world.max(axis=0).astype(np.float64)
    origin = world_min / 2.0 + world_max / 2.0

    # Local coordinates centered around origin
    local_positions = (merged_world - origin).astype(np.float32)
    local_min = local_positions.min(axis=0).astype(np.float64)
    local_max = local_positions.max(axis=0).astype(np.float64)

    # Save positions.npy
    positions_file = out_path / "positions.npy"
    np.save(positions_file, local_positions)

    # Compute SHA-256
    hasher = hashlib.sha256()
    with open(positions_file, "rb") as f:
        while chunk := f.read(4 * 1024 * 1024):
            hasher.update(chunk)
    sha256_hash = hasher.hexdigest()

    meta = {
        "reader": "multi_scan_unified_stitcher",
        "name": project_title,
        "source_point_count": total_count,
        "stored_point_count": total_count,
        "origin": origin.tolist(),
        "bbox_min": (local_min + origin).tolist(),
        "bbox_max": (local_max + origin).tolist(),
        "checksum_sha256": sha256_hash,
        "station_count": len(stations),
        "station_row_ranges": [
            {
                "station_id": item["station_id"],
                "source_row_start": item["source_row_start"],
                "source_row_end_exclusive": item["source_row_end_exclusive"],
                "source_row_count": item["source_row_count"],
                "source_row_index_base": 0,
            }
            for item in station_meta
        ],
        "unified_merge": True,
    }
    meta_file = out_path / "meta.json"
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # Registration manifest
    manifest_file = out_path / "registration_manifest.json"
    create_recap_registration_project(station_meta, project_title, manifest_file)

    ply_path = None
    if export_ply:
        ply_file = out_path / "unified_cloud.ply"
        export_stitched_cloud([{"points": merged_world}], ply_file)
        ply_path = str(ply_file)

    return {
        "status": "success",
        "positions_file": str(positions_file),
        "meta_file": str(meta_file),
        "manifest_file": str(manifest_file),
        "ply_file": ply_path,
        "total_points": total_count,
        "origin": origin.tolist(),
        "world_bounds": {"min": world_min.tolist(), "max": world_max.tolist()},
    }
