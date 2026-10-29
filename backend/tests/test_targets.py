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


def test_dense_target_detection_bounds_redundant_local_fits(monkeypatch):
    rng = np.random.default_rng(42)
    plane = rng.uniform([0.0, 0.0], [2.0, 2.0], size=(20_000, 2))
    plane = np.column_stack([plane, 0.5 + rng.normal(0.0, 0.001, len(plane))])
    dense_patch = rng.uniform([0.95, 0.95, 0.475], [1.05, 1.05, 0.525], size=(10_000, 3))
    cloud = np.vstack([plane, dense_patch])
    observed_fit_sizes = []

    def reject_candidate(points, **kwargs):
        observed_fit_sizes.append(len(points))
        return None

    monkeypatch.setattr("scan2bim.registration.targets.fit_sphere_ransac", reject_candidate)

    targets = detect_spherical_targets(
        cloud, expected_radius_m=0.0725, max_candidates=12
    )

    assert targets == []
    assert 0 < len(observed_fit_sizes) <= 12
    assert max(observed_fit_sizes) == 2_048


def test_detect_spherical_targets_rejects_planar_surface_arcs():
    rng = np.random.default_rng(20261027)
    xy = rng.uniform(-0.2, 0.2, size=(20_000, 2))
    plane = np.column_stack((xy, rng.normal(0.0, 0.0003, size=len(xy))))

    targets = detect_spherical_targets(plane, expected_radius_m=0.0725)

    assert targets == []


def test_detect_spherical_targets_keeps_occluded_60_degree_cap():
    rng = np.random.default_rng(20261031)
    center = np.array([1.0, 2.0, 1.5])
    radius = 0.0725
    cap_angle = np.deg2rad(60.0)
    phi = rng.uniform(0.0, 2.0 * np.pi, 1_000)
    cos_theta = rng.uniform(np.cos(cap_angle), 1.0, len(phi))
    sin_theta = np.sqrt(1.0 - cos_theta**2)
    directions = np.column_stack((
        sin_theta * np.cos(phi),
        sin_theta * np.sin(phi),
        cos_theta,
    ))
    sphere = center + radius * directions + rng.normal(0.0, 0.0005, (len(phi), 3))

    targets = detect_spherical_targets(sphere, expected_radius_m=radius)

    assert targets
    best = min(targets, key=lambda item: np.linalg.norm(np.asarray(item["center"]) - center))
    assert np.linalg.norm(np.asarray(best["center"]) - center) < 0.005
    assert best["surface_coverage_ratio"] >= 0.10


def test_detect_spherical_targets_rejects_cylindrical_surface():
    rng = np.random.default_rng(20261029)
    center = np.array([1.0, 2.0, 1.5])
    radius = 0.0725
    angle = rng.uniform(0.0, 2.0 * np.pi, 20_000)
    z = rng.uniform(-0.025, 0.025, len(angle))
    cylinder = np.column_stack((
        center[0] + radius * np.cos(angle),
        center[1] + radius * np.sin(angle),
        center[2] + z,
    ))
    cylinder += rng.normal(0.0, 0.0003, cylinder.shape)

    targets = detect_spherical_targets(cylinder, expected_radius_m=radius)

    assert targets == []


def test_detect_spherical_targets_keeps_visible_hemisphere_candidate():
    rng = np.random.default_rng(20261028)
    center = np.array([1.0, 2.0, 1.5])
    radius = 0.0725
    phi = rng.uniform(0.0, 2.0 * np.pi, 500)
    cos_theta = rng.uniform(0.0, 1.0, 500)
    sin_theta = np.sqrt(1.0 - cos_theta**2)
    directions = np.column_stack((
        sin_theta * np.cos(phi),
        sin_theta * np.sin(phi),
        cos_theta,
    ))
    sphere = center + radius * directions + rng.normal(0.0, 0.0005, (500, 3))

    targets = detect_spherical_targets(sphere, expected_radius_m=radius)

    assert targets
    best = min(targets, key=lambda item: np.linalg.norm(np.asarray(item["center"]) - center))
    assert np.linalg.norm(np.asarray(best["center"]) - center) < 0.005
    assert best["surface_coverage_ratio"] >= 0.15
