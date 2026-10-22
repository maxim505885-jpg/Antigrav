from pathlib import Path
import numpy as np
import json
import pytest

from scan2bim.registration.stitching import (
    kabsch_fit,
    rigid_icp,
    create_recap_registration_project,
    export_stitched_cloud,
)


def test_kabsch_fit_exact():
    # 3 points
    src = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64)
    # Translate by [5, 2, -1]
    t_true = np.array([5.0, 2.0, -1.0])
    dst = src + t_true
    r, t = kabsch_fit(src, dst)
    np.testing.assert_allclose(r, np.eye(3), atol=1e-5)
    np.testing.assert_allclose(t, t_true, atol=1e-5)


def test_rigid_icp_alignment():
    # Synthetic cube points
    np.random.seed(42)
    src = np.random.uniform(-5.0, 5.0, (500, 3))
    # Slight shift and rotation
    shift = np.array([0.2, -0.1, 0.05])
    target = src + shift

    result = rigid_icp(src, target, max_iterations=30, sample_size=500)
    assert result["converged"] is True
    assert result["rmse_mm"] < 5.0 # Sub-centimeter error


def test_export_stitched_cloud_and_recap(tmp_path):
    st1 = {
        "id": "station_01",
        "points": np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]], dtype=np.float32),
        "colors": np.array([[255, 0, 0], [0, 255, 0]], dtype=np.uint8),
        "matrix_4x4": np.eye(4).tolist(),
    }
    st2 = {
        "id": "station_02",
        "points": np.array([[2.0, 2.0, 2.0], [3.0, 3.0, 3.0]], dtype=np.float32),
        "colors": np.array([[0, 0, 255], [255, 255, 255]], dtype=np.uint8),
        "matrix_4x4": np.eye(4).tolist(),
    }

    out_ply = tmp_path / "stitched.ply"
    res_path = export_stitched_cloud([st1, st2], out_ply)
    assert res_path.exists()
    assert res_path.stat().st_size > 50

    out_recap = tmp_path / "recap_project.json"
    recap_proj = create_recap_registration_project([st1, st2], "Workshop Project", out_recap)
    assert recap_proj.exists()
    manifest = json.loads(recap_proj.read_text(encoding="utf-8"))
    assert manifest["station_count"] == 2
    assert manifest["stations"][0]["station_id"] == "station_01"
