"""Tests for high-precision geodetic target detection and sphere fitting."""
import numpy as np
import pytest
from scan2bim.registration.targets import fit_sphere_ransac, detect_spherical_targets


def test_fit_sphere_ransac_accurate_synthetic():
    # Generate 500 points on a 145mm survey sphere (radius 0.0725m) at center (2.5, 3.0, 1.2)
    center_true = np.array([2.5, 3.0, 1.2])
    radius_true = 0.0725

    rng = np.random.default_rng(123)
    phi = rng.uniform(0, 2 * np.pi, 500)
    costheta = rng.uniform(-1, 1, 500)
    theta = np.arccos(costheta)

    x = radius_true * np.sin(theta) * np.cos(phi)
    y = radius_true * np.sin(theta) * np.sin(phi)
    z = radius_true * np.cos(theta)

    sphere_pts = np.column_stack([x, y, z]) + center_true
    # Add 0.5mm Gaussian noise
    sphere_pts += rng.normal(0, 0.0005, sphere_pts.shape)

    # Add 100 outlier background points
    outliers = rng.uniform([2.0, 2.5, 0.8], [3.0, 3.5, 1.6], (100, 3))
    all_pts = np.vstack([sphere_pts, outliers])

    result = fit_sphere_ransac(all_pts, target_radius_m=0.0725)
    assert result is not None
    assert result["target_type"] == "sphere"
    assert result["inlier_count"] >= 450

    # Sub-millimeter accuracy verification:
    estimated_center = np.array(result["center"])
    error_center_mm = np.linalg.norm(estimated_center - center_true) * 1000.0
    assert error_center_mm < 1.0  # Center recovered to within 1mm

    error_radius_mm = abs(result["radius_m"] - radius_true) * 1000.0
    assert error_radius_mm < 1.0  # Radius within 1mm

    assert result["rmse_mm"] < 1.5


def test_detect_spherical_targets_multiple():
    rng = np.random.default_rng(42)
    centers = [
        np.array([1.0, 2.0, 1.5]),
        np.array([4.0, 5.0, 1.5]),
    ]
    radius = 0.0725

    points_list = []
    for c in centers:
        phi = rng.uniform(0, 2 * np.pi, 300)
        costheta = rng.uniform(-1, 1, 300)
        theta = np.arccos(costheta)
        pts = np.column_stack([
            radius * np.sin(theta) * np.cos(phi),
            radius * np.sin(theta) * np.sin(phi),
            radius * np.cos(theta),
        ]) + c + rng.normal(0, 0.0005, (300, 3))
        points_list.append(pts)

    # Add random ground clutter
    clutter = rng.uniform([0, 0, 0], [6, 6, 2], (500, 3))
    points_list.append(clutter)

    cloud = np.vstack(points_list)

    targets = detect_spherical_targets(cloud, expected_radius_m=0.0725)
    assert len(targets) == 2

    found_coords = [t["center"] for t in targets]
    for c in centers:
        closest = min(np.linalg.norm(np.array(fc) - c) for fc in found_coords)
        assert closest < 0.005  # Within 5mm of expected center
