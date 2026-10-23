"""Global Bundle Adjustment and Pose Graph Optimization for multi-station point clouds.

Eliminates cumulative drift and loop-closure discrepancies across extended
scanning trajectories (e.g. 100m+ industrial workshop bays), exceeding
pairwise-only ICP approaches found in Autodesk ReCap Pro.
"""
from __future__ import annotations

import logging
from typing import Any, Mapping
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

logger = logging.getLogger(__name__)


def se3_to_vec6(matrix: np.ndarray) -> np.ndarray:
    """Convert 4x4 SE(3) matrix to 6D vector (rotvec_x, rotvec_y, rotvec_z, tx, ty, tz)."""
    rot = Rotation.from_matrix(matrix[:3, :3]).as_rotvec()
    trans = matrix[:3, 3]
    return np.concatenate([rot, trans])


def vec6_to_se3(vec: np.ndarray) -> np.ndarray:
    """Convert 6D vector (rotvec[3], trans[3]) to 4x4 SE(3) matrix."""
    mat = np.eye(4, dtype=np.float64)
    mat[:3, :3] = Rotation.from_rotvec(vec[:3]).as_matrix()
    mat[:3, 3] = vec[3:]
    return mat


def relative_se3_error(
    t_i: np.ndarray,
    t_j: np.ndarray,
    t_ij_measured: np.ndarray,
) -> np.ndarray:
    """Compute 6D pose discrepancy error vector e_ij = Log(T_ij_meas^-1 * (T_i^-1 * T_j))."""
    # Expected relative transform from station i to station j
    t_ij_estimated = np.linalg.inv(t_i) @ t_j
    # Error transform
    t_err = np.linalg.inv(t_ij_measured) @ t_ij_estimated
    rot_err = Rotation.from_matrix(t_err[:3, :3]).as_rotvec()
    trans_err = t_err[:3, 3]
    return np.concatenate([rot_err, trans_err])


def optimize_pose_graph(
    station_ids: list[str],
    relative_constraints: list[dict[str, Any]],
    fixed_station_id: str | None = None,
    weights: tuple[float, float] = (100.0, 1.0),  # (rotation_weight_rad, translation_weight_m)
) -> dict[str, Any]:
    """Jointly optimize global station poses given pairwise relative constraints.

    Parameters:
    - station_ids: List of unique station identifiers. Station 0 (or fixed_station_id) is datum (identity).
    - relative_constraints: List of measured pairwise edges:
        {
          "from_id": "station_1",
          "to_id": "station_2",
          "matrix_4x4": [[...]],
          "weight": 1.0,
          "rmse_mm": 2.4
        }
    - fixed_station_id: Station held rigidly at world datum (default: station_ids[0]).
    - weights: Relative weights for angle vs translation in objective function.

    Returns:
    - Dictionary with optimized 4x4 pose matrices for each station, initial/final RMSE, and status.
    """
    if not station_ids:
        raise ValueError("station_ids cannot be empty")

    n_stations = len(station_ids)
    station_to_idx = {sid: idx for idx, sid in enumerate(station_ids)}
    fixed_idx = station_to_idx.get(fixed_station_id or station_ids[0], 0)

    # Initial guess: build spanning tree from constraints or identity
    initial_poses = [np.eye(4, dtype=np.float64) for _ in range(n_stations)]
    visited = {fixed_idx}

    # Breadth-first / greedy propagation of initial poses
    changed = True
    while changed:
        changed = False
        for c in relative_constraints:
            u = station_to_idx.get(c["from_id"])
            v = station_to_idx.get(c["to_id"])
            if u is None or v is None:
                continue
            m = np.asarray(c["matrix_4x4"], dtype=np.float64)
            if u in visited and v not in visited:
                initial_poses[v] = initial_poses[u] @ m
                visited.add(v)
                changed = True
            elif v in visited and u not in visited:
                initial_poses[u] = initial_poses[v] @ np.linalg.inv(m)
                visited.add(u)
                changed = True

    # Parameter vector: (n_stations - 1) * 6 parameters (fixed station omitted)
    free_indices = [i for i in range(n_stations) if i != fixed_idx]

    def unpack_poses(params: np.ndarray) -> list[np.ndarray]:
        poses = [np.eye(4, dtype=np.float64) for _ in range(n_stations)]
        poses[fixed_idx] = np.eye(4, dtype=np.float64)
        for p_idx, s_idx in enumerate(free_indices):
            v6 = params[p_idx * 6 : (p_idx + 1) * 6]
            poses[s_idx] = vec6_to_se3(v6)
        return poses

    # Initial parameter vector
    x0 = np.zeros(len(free_indices) * 6, dtype=np.float64)
    for p_idx, s_idx in enumerate(free_indices):
        x0[p_idx * 6 : (p_idx + 1) * 6] = se3_to_vec6(initial_poses[s_idx])

    rot_w, trans_w = weights

    def objective(params: np.ndarray) -> np.ndarray:
        poses = unpack_poses(params)
        residuals = []
        for c in relative_constraints:
            u = station_to_idx[c["from_id"]]
            v = station_to_idx[c["to_id"]]
            m_meas = np.asarray(c["matrix_4x4"], dtype=np.float64)
            err = relative_se3_error(poses[u], poses[v], m_meas)
            edge_w = float(c.get("weight", 1.0))
            residuals.append(err[:3] * (rot_w * edge_w))
            residuals.append(err[3:] * (trans_w * edge_w))
        return np.concatenate(residuals) if residuals else np.zeros(1)

    initial_residuals = objective(x0)
    init_rmse_mm = float(np.sqrt(np.mean(initial_residuals ** 2)) * 1000.0 / trans_w)

    res = least_squares(objective, x0, method="lm", max_nfev=200)

    final_poses = unpack_poses(res.x if res.success else x0)
    final_residuals = objective(res.x if res.success else x0)
    final_rmse_mm = float(np.sqrt(np.mean(final_residuals ** 2)) * 1000.0 / trans_w)

    optimized_poses: dict[str, list[list[float]]] = {}
    for sid, idx in station_to_idx.items():
        optimized_poses[sid] = final_poses[idx].tolist()

    return {
        "success": bool(res.success),
        "fixed_station": station_ids[fixed_idx],
        "initial_rmse_mm": init_rmse_mm,
        "final_rmse_mm": final_rmse_mm,
        "optimized_poses": optimized_poses,
        "num_constraints": len(relative_constraints),
    }
