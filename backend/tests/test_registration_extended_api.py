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


def test_export_recap_project_api(client, monkeypatch):
    from scan2bim.formats import recap_decap
    monkeypatch.setattr(recap_decap, "create_recap_project", lambda *_args: {
        "status": "created_by_autodesk_decap", "rcp_path": "test.rcp",
        "support_dir": "test Support", "linked_rcs_count": 1,
        "package_verified": True, "rcp_size_bytes": 256,
        "linked_rcs_size_bytes": 1024,
    })
    req_payload = {
        "project_name": "API_ReCap_Test",
        "stations": [
            {
                "id": "st1",
                "name": "Station 1",
                "path": "1.rcs",
                "point_count": 10000,
                "matrix_4x4": np.eye(4).tolist(),
                "rmse_mm": 1.2,
            }
        ],
    }
    resp = client.post("/api/v1/registration/export-rcp-project", json=req_payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "created_by_autodesk_decap"
    assert resp.json()["package_verified"] is True
    assert resp.json()["linked_rcs_size_bytes"] == 1024


def test_export_recap_project_api_does_not_fallback_to_xml_draft(client, monkeypatch):
    from scan2bim.formats import recap_decap
    monkeypatch.setattr(recap_decap, "create_recap_project",
                        lambda *_args: (_ for _ in ()).throw(RuntimeError("failed scans 1")))
    response = client.post("/api/v1/registration/export-rcp-project", json={
        "project_name": "failed", "stations": [{"path": "station.rcs"}],
    })
    assert response.status_code == 422
    assert "failed scans 1" in response.json()["detail"]
