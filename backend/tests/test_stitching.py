import numpy as np
import json
from scan2bim.registration.stitching import (
    rigid_icp,
    kabsch_fit,
    create_recap_registration_project,
    merge_and_save_unified_cloud,
)


def test_kabsch_fit_exact():
    # Known translation and 90 deg rotation around Z
    pts = np.array([
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [2.0, 3.0, 1.0],
    ])
    r_true = np.array([
        [0.0, -1.0, 0.0],
        [1.0,  0.0, 0.0],
        [0.0,  0.0, 1.0],
    ])
    t_true = np.array([5.0, -2.0, 3.0])

    target = (r_true @ pts.T).T + t_true

    r_est, t_est = kabsch_fit(pts, target)
    np.testing.assert_allclose(r_est, r_true, atol=1e-6)
    np.testing.assert_allclose(t_est, t_true, atol=1e-6)


def test_rigid_icp_convergence(tmp_path):
    np.random.seed(42)
    base_cloud = np.random.uniform(-10, 10, size=(1000, 3))

    # Small displacement
    theta = np.deg2rad(2.0)
    r_true = np.array([
        [np.cos(theta), -np.sin(theta), 0.0],
        [np.sin(theta),  np.cos(theta), 0.0],
        [0.0,            0.0,           1.0],
    ])
    t_true = np.array([0.05, -0.03, 0.02])

    source_cloud = (r_true @ base_cloud.T).T + t_true

    result = rigid_icp(source_cloud, base_cloud, max_iterations=30, tolerance_m=1e-5)
    assert result["converged"] is True
    assert result["iterations"] > 1  # a real convergence check cannot stop on the first update
    assert result["rmse_mm"] < 5.0  # sub-5mm precision

    # Test ReCap manifest creation
    stations = [
        {"id": "station_01", "path": "scan1.e57", "point_count": 1000, "matrix_4x4": np.eye(4).tolist()},
        {"id": "station_02", "path": "scan2.e57", "point_count": 1000, "matrix_4x4": result["matrix_4x4"], "rmse_mm": result["rmse_mm"]},
    ]
    manifest_path = tmp_path / "recap_project.json"
    create_recap_registration_project(stations, "Цех 1.rcs", manifest_path)
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["format"] == "SCAN station-registration manifest"
    assert manifest["recap_project_generated"] is False
    assert manifest["registration_verified"] is False


def test_rigid_icp_reports_missing_residual_when_no_correspondences():
    source = np.tile(np.array([[-10.0, 0.0, 0.0], [10.0, 0.0, 0.0]]), (10, 1))
    target = np.tile(np.array([[0.0, -10.0, 0.0], [0.0, 10.0, 0.0]]), (10, 1))

    result = rigid_icp(source, target, max_iterations=10)

    assert result["converged"] is False
    assert result["rmse_mm"] is None


def test_merge_and_save_unified_cloud(tmp_path):
    pts1 = np.array([[10.0, 20.0, 1.0], [12.0, 22.0, 2.0]], dtype=np.float32)
    pts2 = np.array([[30.0, 40.0, 3.0], [32.0, 42.0, 4.0]], dtype=np.float32)

    stations = [
        {"name": "Scan_1", "points": pts1, "matrix_4x4": np.eye(4).tolist()},
        {"name": "Scan_2", "points": pts2, "matrix_4x4": np.eye(4).tolist()},
    ]

    out_dir = tmp_path / "unified_test"
    res = merge_and_save_unified_cloud(stations, out_dir, project_title="Test Merged Cloud", export_ply=True)

    assert res["status"] == "success"
    assert res["total_points"] == 4
    assert (out_dir / "positions.npy").exists()
    assert (out_dir / "meta.json").exists()
    assert (out_dir / "registration_manifest.json").exists()
    assert (out_dir / "unified_cloud.ply").exists()

    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["stored_point_count"] == 4
    assert meta["unified_merge"] is True

    # Check bounds consistency for pipeline _load_geometry
    positions = np.load(out_dir / "positions.npy")
    origin = np.array(meta["origin"])
    bbox_min = np.array(meta["bbox_min"])
    bbox_max = np.array(meta["bbox_max"])
    np.testing.assert_allclose(bbox_min - origin, positions.min(axis=0), atol=1e-3)
    np.testing.assert_allclose(bbox_max - origin, positions.max(axis=0), atol=1e-3)
