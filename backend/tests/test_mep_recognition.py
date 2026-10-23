import math
import numpy as np
import pytest

from scan2bim.recognition.mep import fit_cylinder_ransac, detect_pipe_network


def test_fit_cylinder_ransac_synthetic():
    # Generate points on a horizontal cylinder along X axis
    # Radius = 0.1m (200mm diameter), length = 4.0m
    n_points = 500
    theta = np.random.uniform(0, 2 * np.pi, n_points)
    x = np.random.uniform(0, 4.0, n_points)
    r = 0.10
    y = r * np.cos(theta)
    z = r * np.sin(theta) + 2.0  # Center at Z = 2.0m

    # Add small noise (1mm)
    noise = np.random.normal(0, 0.001, (n_points, 3))
    pts = np.column_stack([x, y, z]) + noise

    res = fit_cylinder_ransac(pts, max_iterations=150)
    assert res is not None
    assert math.isclose(res["diameter_mm"], 200.0, abs_tol=15.0)
    assert math.isclose(res["length_m"], 4.0, abs_tol=0.3)
    assert res["inlier_count"] > 300
    assert abs(res["axis_direction"][0]) > 0.9  # Strongly aligned with X


def test_detect_pipe_network_multiple_runs():
    # Pipe 1 along X
    t1 = np.linspace(0, 2 * np.pi, 200)
    x1 = np.linspace(0, 3, 200)
    p1 = np.column_stack([x1, 0.05 * np.cos(t1), 0.05 * np.sin(t1) + 3.0])

    # Pipe 2 along Y
    t2 = np.linspace(0, 2 * np.pi, 200)
    y2 = np.linspace(0, 3, 200)
    p2 = np.column_stack([0.05 * np.cos(t2) + 5.0, y2, 0.05 * np.sin(t2) + 3.0])

    all_pts = np.vstack([p1, p2])
    pipes = detect_pipe_network(all_pts, min_segment_points=25)
    assert len(pipes) >= 1
    assert pipes[0].diameter_mm > 0
    assert pipes[0].length_m > 0
