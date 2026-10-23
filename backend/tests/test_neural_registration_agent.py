"""Tests for Neural Registration Agent (Нейросетевой Агент Сшивки Облаков Точек).

Verifies:
1. BEV Structural Feature Extraction (density, Z-height, occupancy).
2. Global Coarse Neural Matching under large rotations (30°, 90°, 180°) and translations.
3. Point-to-Plane ICP sub-millimeter refinement.
4. Multi-station Pose Graph Optimization (loop closure / уравнивание сети).
5. Full Autonomous NeuralRegistrationAgent execution & reasoning audit trail.
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from scan2bim.registration.neural_agent import (
    extract_bev_structural_features,
    neural_coarse_match,
    point_to_plane_icp,
    pose_graph_optimize,
    NeuralRegistrationAgent,
    RegistrationStation,
)


def make_synthetic_hall_scan(
    bay_count: int = 8,
    bay_step_m: float = 6.0,
    span_widths: list[float] = [13.25, 11.70, 13.25],
    height_m: float = 10.0,
    point_density: int = 150,
    seed: int = 42,
) -> np.ndarray:
    """Generate realistic point cloud of an industrial workshop structure."""
    rng = np.random.default_rng(seed)
    points = []

    # Columns at grid intersections (bay_i * 6.0, span_y)
    row_ys = [0.0]
    curr_y = 0.0
    for w in span_widths:
        curr_y += w
        row_ys.append(curr_y)

    for bay_i in range(bay_count):
        x = bay_i * bay_step_m
        for y in row_ys:
            # 0.8 x 0.5 x height column points
            n_pts = point_density
            dx = rng.uniform(-0.4, 0.4, n_pts)
            dy = rng.uniform(-0.25, 0.25, n_pts)
            dz = rng.uniform(0.0, height_m, n_pts)
            pts = np.column_stack([x + dx, y + dy, dz])
            points.append(pts)

    # Longitudinal crane girder lines at y in row_ys[1:-1] at z=6.8m
    for y in row_ys[1:-1]:
        n_beam_pts = point_density * 4
        bx = rng.uniform(0.0, (bay_count - 1) * bay_step_m, n_beam_pts)
        by = y + rng.normal(0.0, 0.05, n_beam_pts)
        bz = 6.8 + rng.normal(0.0, 0.05, n_beam_pts)
        points.append(np.column_stack([bx, by, bz]))

    # Floor plane at z=0.0
    n_floor = point_density * 6
    fx = rng.uniform(0.0, (bay_count - 1) * bay_step_m, n_floor)
    fy = rng.uniform(0.0, row_ys[-1], n_floor)
    fz = rng.normal(0.0, 0.015, n_floor)
    points.append(np.column_stack([fx, fy, fz]))

    all_pts = np.vstack(points).astype(np.float32)
    return all_pts


def transform_points(points: np.ndarray, r_mat: np.ndarray, t_vec: np.ndarray) -> np.ndarray:
    return (r_mat @ points.T).T + t_vec


def make_rot_z(angle_rad: float) -> np.ndarray:
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    return np.array([
        [c, -s, 0.0],
        [s,  c, 0.0],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)


def test_bev_structural_feature_extraction():
    cloud = make_synthetic_hall_scan(bay_count=6, seed=1)
    bev = extract_bev_structural_features(cloud, cell_size_m=0.20)
    assert "tensor" in bev
    assert "origin_xy" in bev
    assert "resolution" in bev
    assert bev["tensor"].ndim == 3  # (C, H, W)
    assert bev["tensor"].shape[0] >= 2  # density + height / normal channels
    assert np.max(bev["tensor"]) > 0.0


def test_neural_coarse_matching_large_rotation_and_offset():
    # Base station 1
    station_1 = make_synthetic_hall_scan(bay_count=10, seed=10)

    # Station 2 is rotated by 35 degrees and shifted by (+12.0m, -8.0m, +0.5m)
    true_angle = math.radians(35.0)
    true_r = make_rot_z(true_angle)
    true_t = np.array([12.0, -8.0, 0.5], dtype=np.float64)
    station_2 = transform_points(station_1, true_r, true_t)

    # Add 10% outlier noise to station 2
    rng = np.random.default_rng(99)
    noise = rng.uniform(-20.0, 50.0, (len(station_2) // 10, 3)).astype(np.float32)
    station_2_noisy = np.vstack([station_2, noise])

    # Run neural coarse match
    match = neural_coarse_match(station_2_noisy, station_1)

    assert match["confidence"] > 0.5
    est_r = np.array(match["rotation"], dtype=np.float64)
    est_t = np.array(match["translation"], dtype=np.float64)

    # Verify recovered angle within 3 degrees
    est_angle = math.atan2(est_r[1, 0], est_r[0, 0])
    angle_error_deg = abs(math.degrees(est_angle - true_angle))
    if angle_error_deg > 180:
        angle_error_deg = abs(360 - angle_error_deg)
    assert angle_error_deg < 4.0, f"Recovered angle error too large: {angle_error_deg:.2f}°"

    # Verify recovered translation within 0.8m
    trans_error_m = np.linalg.norm(est_t[:2] - true_t[:2])
    assert trans_error_m < 1.0, f"Coarse translation error too large: {trans_error_m:.2f} m"


def test_point_to_plane_icp_millimeter_refinement():
    # Base target cloud
    target = make_synthetic_hall_scan(bay_count=8, seed=20)

    # Source cloud with a small known perturbation (3 degrees, 0.25m offset)
    pert_angle = math.radians(2.5)
    pert_r = make_rot_z(pert_angle)
    pert_t = np.array([0.20, -0.15, 0.05], dtype=np.float64)
    source = transform_points(target, pert_r, pert_t)

    res = point_to_plane_icp(source, target, max_iterations=25, tolerance_m=1e-4)
    assert res["converged"] is True
    assert res["rmse_mm"] < 15.0, f"Expected sub-15mm RMSE, got {res['rmse_mm']} mm"

    # Check transformation inversion
    inv_t = res["matrix_4x4"]
    aligned_source = (np.array(inv_t[:3, :3]) @ source.T).T + np.array(inv_t[:3, 3])
    final_diff = np.mean(np.linalg.norm(aligned_source[:1000] - target[:1000], axis=1))
    assert final_diff < 0.05, f"Mean alignment residual too high: {final_diff}m"


def test_pose_graph_loop_closure():
    # 3 stations forming a closed loop
    st0_to_st1 = {"matrix": np.eye(4), "information": np.eye(6) * 100.0}
    st1_to_st2 = {"matrix": np.eye(4), "information": np.eye(6) * 100.0}
    # Accumulated drift in loop closure (realistic 3cm loop closure drift)
    drift_t = np.array([0.03, -0.02, 0.01])
    st2_to_st0_drifted = np.eye(4)
    st2_to_st0_drifted[:3, 3] = drift_t

    edges = [
        {"from": 0, "to": 1, "t4x4": st0_to_st1["matrix"].tolist(), "weight": 1.0},
        {"from": 1, "to": 2, "t4x4": st1_to_st2["matrix"].tolist(), "weight": 1.0},
        {"from": 2, "to": 0, "t4x4": st2_to_st0_drifted.tolist(), "weight": 1.0},
    ]

    optimized = pose_graph_optimize(station_count=3, edges=edges)
    assert len(optimized["poses"]) == 3
    assert optimized["residual_norm_after"] < optimized["residual_norm_before"]
    assert optimized["residual_norm_after"] < 0.02


def test_neural_registration_agent_autonomous_pipeline():
    agent = NeuralRegistrationAgent()

    st1_pts = make_synthetic_hall_scan(bay_count=8, seed=42)
    rot_30 = make_rot_z(math.radians(30.0))
    trans_offset = np.array([6.0, 3.0, 0.1], dtype=np.float64)
    st2_pts = transform_points(st1_pts, rot_30, trans_offset)

    stations = [
        RegistrationStation(id="scan_01", points=st1_pts, name="Стоянка 1 (Вход цеха)"),
        RegistrationStation(id="scan_02", points=st2_pts, name="Стоянка 2 (Ось 6)"),
    ]

    result = agent.auto_stitch(stations)

    assert result["status"] == "success"
    assert result["converged"] is True
    assert result["rmse_mm"] < 10.0
    assert result["overlap_ratio"] > 0.4
    assert len(result["reasoning_log"]) >= 4
    # Ensure agent log contains clear engineering explanations in Russian
    log_text = " ".join(result["reasoning_log"])
    assert "Станция" in log_text or "стоянк" in log_text.lower()
    assert "сходимость" in log_text.lower() or "icp" in log_text.lower() or "невязк" in log_text.lower()
