"""Tests for Registration API endpoints: Target detection and Bundle Adjustment."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from scan2bim.api.app import app
from scan2bim.db import execute, init_db, new_id, utcnow
from scan2bim.storage import ensure_cloud_dir, cloud_paths


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_db = tmp_path / "test_reg_api.sqlite3"
    monkeypatch.setenv("S2B_DB_PATH", str(test_db))
    monkeypatch.setenv("S2B_DATA_DIR", str(tmp_path))
    from scan2bim import config
    config.DB_PATH = test_db
    config.DATA_DIR = tmp_path
    init_db()
    return TestClient(app)


def test_bundle_adjustment_api(client):
    req_payload = {
        "station_ids": ["ST_01", "ST_02"],
        "constraints": [
            {
                "from_id": "ST_01",
                "to_id": "ST_02",
                "matrix_4x4": [
                    [1, 0, 0, 5.0],
                    [0, 1, 0, 0.0],
                    [0, 0, 1, 0.0],
                    [0, 0, 0, 1.0],
                ],
                "weight": 1.0,
            }
        ],
        "fixed_station_id": "ST_01",
    }
    resp = client.post("/api/v1/registration/bundle-adjustment", json=req_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["success"] is True
    assert "optimized_poses" in data
    assert "ST_01" in data["optimized_poses"]
    assert "ST_02" in data["optimized_poses"]


def test_detect_targets_api(client, tmp_path):
    project_id = new_id()
    cloud_id = new_id()

    now = utcnow()
    execute(
        "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (project_id, "Test Prj", now, now),
    )
    execute(
        "INSERT INTO clouds (id, project_id, name, source_path, source_format, status, point_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (cloud_id, project_id, "Cloud Target", "/tmp/fake.ply", "ply", "ready", 500, now, now),
    )

    ensure_cloud_dir(project_id, cloud_id)
    paths = cloud_paths(project_id, cloud_id)

    # 300 points on sphere of r=0.0725
    center = np.array([1.0, 1.0, 1.0])
    radius = 0.0725
    phi = np.linspace(0, 2 * np.pi, 300)
    costheta = np.linspace(-1, 1, 300)
    theta = np.arccos(costheta)
    pts = np.column_stack([
        radius * np.sin(theta) * np.cos(phi),
        radius * np.sin(theta) * np.sin(phi),
        radius * np.cos(theta),
    ]) + center

    np.save(paths["positions"], pts.astype(np.float32))

    resp = client.post(
        "/api/v1/registration/detect-targets",
        json={"cloud_id": cloud_id, "expected_radius_m": 0.0725, "sample_points": 500},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["targets_found"] >= 1
    assert data["targets"][0]["target_type"] == "sphere"
