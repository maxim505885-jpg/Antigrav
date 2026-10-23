"""Tests for Global Pose Graph Optimization and Bundle Adjustment."""
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from scan2bim.registration.bundle_adjustment import optimize_pose_graph


def test_bundle_adjustment_triangle_loop_closure():
    """Verify that a 3-station closed loop with accumulated noise is perfectly distributed."""
    # True poses:
    # Station 0: (0, 0, 0)
    # Station 1: (10, 0, 0)
    # Station 2: (10, 10, 0)
    # And closing back to Station 0
    station_ids = ["ST_01", "ST_02", "ST_03"]

    t0 = np.eye(4)
    t1 = np.eye(4); t1[:3, 3] = [10.0, 0.0, 0.0]
    t2 = np.eye(4); t2[:3, 3] = [10.0, 10.0, 0.0]

    # Ground truth relative transforms:
    rel_0_1 = np.linalg.inv(t0) @ t1
    rel_1_2 = np.linalg.inv(t1) @ t2
    rel_2_0 = np.linalg.inv(t2) @ t0

    # Add small drift noise to loop closure edge (e.g. 50mm error in loop closure)
    noisy_rel_2_0 = rel_2_0.copy()
    noisy_rel_2_0[0, 3] += 0.050  # 50mm offset error

    constraints = [
        {"from_id": "ST_01", "to_id": "ST_02", "matrix_4x4": rel_0_1.tolist(), "weight": 1.0},
        {"from_id": "ST_02", "to_id": "ST_03", "matrix_4x4": rel_1_2.tolist(), "weight": 1.0},
        {"from_id": "ST_03", "to_id": "ST_01", "matrix_4x4": noisy_rel_2_0.tolist(), "weight": 1.0},
    ]

    result = optimize_pose_graph(station_ids, constraints, fixed_station_id="ST_01")
    assert result["success"] is True
    assert result["final_rmse_mm"] < result["initial_rmse_mm"]

    # In ST_01 datum, ST_01 must be pure identity
    st0_opt = np.array(result["optimized_poses"]["ST_01"])
    assert np.allclose(st0_opt, np.eye(4), atol=1e-5)

    # Error is distributed across all 3 stations rather than accumulating at loop closure
    st2_opt = np.array(result["optimized_poses"]["ST_02"])
    st3_opt = np.array(result["optimized_poses"]["ST_03"])

    assert 9.95 < st2_opt[0, 3] < 10.05
    assert 9.95 < st3_opt[1, 3] < 10.05
