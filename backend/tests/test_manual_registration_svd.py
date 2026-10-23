import pytest
import numpy as np

from scan2bim.db import execute, new_id, utcnow
from scan2bim.storage import cloud_paths
from scan2bim.registration.stitching import compute_pairwise_svd_alignment


def test_compute_pairwise_svd_alignment_exact_transform():
    # 4 non-coplanar points
    src = np.array([
        [0.0, 0.0, 0.0],
        [5.0, 0.0, 0.0],
        [0.0, 4.0, 0.0],
        [0.0, 0.0, 3.0],
    ])
    # Rotate 90 degrees around Z, translate by (10, 20, 5)
    # [x, y, z] -> [-y + 10, x + 20, z + 5]
    dst = np.array([
        [10.0, 20.0, 5.0],
        [10.0, 25.0, 5.0],
        [6.0, 20.0, 5.0],
        [10.0, 20.0, 8.0],
    ])

    res = compute_pairwise_svd_alignment(src, dst)
    assert res["pairs_count"] == 4
    assert res["rmse_mm"] < 0.01
    assert res["max_error_mm"] < 0.01
    for r in res["residuals_mm"]:
        assert r < 0.01

    mat = np.array(res["matrix_4x4"])
    expected_r = np.array([
        [0.0, -1.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0],
    ])
    assert np.allclose(mat[:3, :3], expected_r, atol=1e-5)
    assert np.allclose(mat[:3, 3], [10.0, 20.0, 5.0], atol=1e-5)


def test_compute_pairwise_svd_alignment_validation_errors():
    # Less than 3 points
    with pytest.raises(ValueError, match="At least 3 point pairs"):
        compute_pairwise_svd_alignment(np.zeros((2, 3)), np.zeros((2, 3)))

    # Collinear points
    src_collinear = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [2.0, 0.0, 0.0],
    ])
    with pytest.raises(ValueError, match="collinear or degenerate"):
        compute_pairwise_svd_alignment(src_collinear, src_collinear + 1.0)


def test_pair_align_endpoint(client):
    proj = client.post("/api/v1/projects", json={"name": "Pair Align Test"}).json()
    p_id = proj["id"]

    now = utcnow()
    c1_id = new_id()
    c2_id = new_id()

    execute(
        """INSERT INTO clouds (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (c1_id, p_id, "Cloud 1", "c1.ply", "ply", 100, "ready", now, now)
    )
    execute(
        """INSERT INTO clouds (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (c2_id, p_id, "Cloud 2", "c2.ply", "ply", 100, "ready", now, now)
    )

    pairs = [
        {"source_point": [0.0, 0.0, 0.0], "target_point": [2.0, 3.0, 4.0], "label": "Point A"},
        {"source_point": [10.0, 0.0, 0.0], "target_point": [12.0, 3.0, 4.0], "label": "Point B"},
        {"source_point": [0.0, 10.0, 0.0], "target_point": [2.0, 13.0, 4.0], "label": "Point C"},
        {"source_point": [0.0, 0.0, 10.0], "target_point": [2.0, 3.0, 14.0], "label": "Point D"},
    ]

    res = client.post("/api/v1/registration/pair-align", json={
        "source_cloud_id": c1_id,
        "target_cloud_id": c2_id,
        "pairs": pairs,
        "apply_icp_refinement": False,
    })

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["pairs_count"] == 4
    assert data["rmse_mm"] < 0.01
    assert len(data["pair_details"]) == 4
    assert data["pair_details"][0]["label"] == "Point A"
    assert data["pair_details"][0]["residual_mm"] < 0.01
