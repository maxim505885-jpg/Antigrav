import pytest
from pathlib import Path
import numpy as np

from scan2bim.db import execute, new_id, utcnow
from scan2bim.storage import cloud_paths


def test_registration_flow_success(client, tmp_path):
    project = client.post("/api/v1/projects", json={"name": "Registration test"}).json()
    project_id = project["id"]
    
    # Cloud 1
    c1_id = new_id()
    now = utcnow()
    execute(
        """INSERT INTO clouds (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (c1_id, project_id, "Cloud 1", "c1.ply", "ply", 1000, "ready", now, now)
    )
    p1 = cloud_paths(project_id, c1_id)
    p1["positions"].parent.mkdir(parents=True, exist_ok=True)
    pts1 = np.random.normal(0, 5, size=(100, 3)).astype(np.float64)
    np.save(p1["positions"], pts1)

    # Cloud 2 (shifted Cloud 1)
    c2_id = new_id()
    execute(
        """INSERT INTO clouds (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (c2_id, project_id, "Cloud 2", "c2.ply", "ply", 1000, "ready", now, now)
    )
    p2 = cloud_paths(project_id, c2_id)
    p2["positions"].parent.mkdir(parents=True, exist_ok=True)
    pts2 = pts1 + np.array([1.0, 0.5, -0.2])
    np.save(p2["positions"], pts2)

    # Match via ICP
    res = client.post("/api/v1/registration/match", json={
        "source_cloud_id": c1_id,
        "target_cloud_id": c2_id,
        "sample_points": 100,
        "max_iterations": 20
    })
    assert res.status_code == 200
    data = res.json()
    assert "matrix_4x4" in data
    assert "rmse_mm" in data
    assert data["rmse_mm"] >= 0
    assert len(data["source_sample_row_ids"]) == len(set(data["source_sample_row_ids"])) == 100
    assert len(data["target_sample_row_ids"]) == len(set(data["target_sample_row_ids"])) == 100
    assert set(data["source_sample_row_ids"]) == set(range(100))
    assert set(data["target_sample_row_ids"]) == set(range(100))

    sampled = client.post("/api/v1/registration/match", json={
        "source_cloud_id": c1_id,
        "target_cloud_id": c2_id,
        "sample_points": 20,
        "max_iterations": 20,
        "random_seed": 91,
    })
    assert sampled.status_code == 200
    sampled_data = sampled.json()
    expected_rows = np.linspace(0, 99, 20, dtype=np.int64).tolist()
    assert sampled_data["source_sample_row_ids"] == expected_rows
    assert sampled_data["target_sample_row_ids"] == expected_rows

    # Export PLY and ReCap
    stations = [
        {"points": pts1.tolist(), "matrix_4x4": np.eye(4).tolist()},
        {"points": pts2.tolist(), "matrix_4x4": data["matrix_4x4"]}
    ]
    res_ply = client.post("/api/v1/registration/export-ply", json={
        "project_name": "test_unified",
        "stations": stations
    })
    assert res_ply.status_code == 200
    assert Path(res_ply.json()["output_path"]).exists()

    res_rc = client.post("/api/v1/registration/export-recap", json={
        "project_name": "test_unified",
        "stations": stations
    })
    assert res_rc.status_code == 200
    assert Path(res_rc.json()["output_path"]).exists()


def test_registration_rejects_clouds_below_icp_minimum(client):
    project = client.post("/api/v1/projects", json={"name": "Small registration test"}).json()
    cloud_id = new_id()
    now = utcnow()
    execute(
        """INSERT INTO clouds (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (cloud_id, project["id"], "Small cloud", "small.ply", "ply", 100, "ready", now, now),
    )
    point_path = cloud_paths(project["id"], cloud_id)["positions"]
    point_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(point_path, np.zeros((9, 3), dtype=np.float64))

    response = client.post("/api/v1/registration/match", json={
        "source_cloud_id": cloud_id,
        "target_cloud_id": cloud_id,
        "sample_points": 10,
    })

    assert response.status_code == 400
    assert "не менее 10 точек" in response.json()["detail"]
