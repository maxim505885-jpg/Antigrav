import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from scan2bim.api.app import app
from scan2bim.db import execute, init_db, new_id, utcnow


@pytest.fixture
def client(tmp_path, monkeypatch):
    test_db = tmp_path / "station_registration.sqlite3"
    monkeypatch.setenv("S2B_DB_PATH", str(test_db))
    monkeypatch.setenv("S2B_DATA_DIR", str(tmp_path))
    from scan2bim import config

    config.DB_PATH = test_db
    config.DATA_DIR = tmp_path
    init_db()
    return TestClient(app)


def _insert_project_and_stations(*, status="ready", source_metadata=None):
    project_id = new_id()
    station_a, station_b = new_id(), new_id()
    now = utcnow()
    execute(
        "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (project_id, "Station registration", now, now),
    )
    for station_id, name, metadata in (
        (station_a, "RCP node — station A", source_metadata or {"recap_project": {"selected_node": {"node_id": "A"}}}),
        (station_b, "RCP node — station B", {"recap_project": {"selected_node": {"node_id": "B"}}}),
    ):
        execute(
            """INSERT INTO clouds
               (id, project_id, name, source_path, source_format, status, point_count,
                metadata_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'rcs', ?, 100, ?, ?, ?)""",
            (station_id, project_id, name, f"{station_id}.rcs", status,
             json.dumps(metadata), now, now),
        )
    return project_id, station_a, station_b


def _payload(station_a, station_b, tx=1.25):
    matrix = np.eye(4)
    matrix[0, 3] = tx
    return {
        "source_station_id": station_a,
        "target_station_id": station_b,
        "method": "manual_kabsch",
        "matrix_4x4": matrix.tolist(),
        "fit_rmse_mm": 2.5,
    }


def test_station_pair_is_saved_as_unverified_and_listed_idempotently(client):
    project_id, station_a, station_b = _insert_project_and_stations()

    response = client.post(
        f"/api/v1/projects/{project_id}/station-registrations",
        json=_payload(station_a, station_b),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "proposed"
    assert body["accuracy_status"] == "not_measured"
    assert body["source_station_identity"] == "rcp_node"
    assert body["item"]["source_station_name"] == "RCP node — station A"
    assert body["item"]["matrix_applied"] is False
    assert body["item"]["rcp_updated"] is False
    assert body["item"]["independent_control_count"] == 0
    assert body["item"]["acceptance_rmse_mm"] is None
    registration_id = body["item"]["id"]

    updated = client.post(
        f"/api/v1/projects/{project_id}/station-registrations",
        json=_payload(station_a, station_b, tx=2.0),
    )
    assert updated.status_code == 200
    assert updated.json()["item"]["id"] == registration_id
    assert updated.json()["item"]["matrix_4x4"][0][3] == 2.0

    listed = client.get(f"/api/v1/projects/{project_id}/station-registrations")
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1
    assert listed.json()["items"][0]["status"] == "proposed"


@pytest.mark.parametrize(
    ("request_patch", "expected_status"),
    [
        ({"target_station_id": "missing"}, 404),
        ({"source_station_id": "same"}, 422),
        ({"method": "unknown"}, 422),
        ({"matrix_4x4": [[2, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]}, 422),
    ],
)
def test_station_registration_rejects_invalid_or_unrelated_pair(client, request_patch, expected_status):
    project_id, station_a, station_b = _insert_project_and_stations()
    payload = _payload(station_a, station_b)
    if request_patch.get("source_station_id") == "same":
        request_patch["source_station_id"] = station_b
    payload.update(request_patch)
    response = client.post(
        f"/api/v1/projects/{project_id}/station-registrations",
        json=payload,
    )
    assert response.status_code == expected_status


def test_station_registration_requires_ready_single_station_records(client):
    project_id, station_a, station_b = _insert_project_and_stations(status="processing")
    response = client.post(
        f"/api/v1/projects/{project_id}/station-registrations",
        json=_payload(station_a, station_b),
    )
    assert response.status_code == 409

    project_id, station_a, station_b = _insert_project_and_stations(
        source_metadata={"station_row_ranges": [
            {"station_id": "S1", "source_row_start": 0, "source_row_end_exclusive": 50},
            {"station_id": "S2", "source_row_start": 50, "source_row_end_exclusive": 100},
        ]},
    )
    response = client.post(
        f"/api/v1/projects/{project_id}/station-registrations",
        json=_payload(station_a, station_b),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["station_count"] == 2


@pytest.mark.parametrize("route", ["/api/v1/registration/match", "/api/v1/registration/pair-align"])
def test_registration_calculation_rejects_aggregate_cloud_with_multiple_stations(client, route):
    project_id, station_a, station_b = _insert_project_and_stations(
        source_metadata={"station_row_ranges": [
            {"station_id": "S1", "source_row_start": 0, "source_row_end_exclusive": 50},
            {"station_id": "S2", "source_row_start": 50, "source_row_end_exclusive": 100},
        ]},
    )
    if route.endswith("/match"):
        payload = {"source_cloud_id": station_a, "target_cloud_id": station_b}
    else:
        payload = {
            "source_cloud_id": station_a,
            "target_cloud_id": station_b,
            "pairs": [
                {"source_point": [0, 0, 0], "target_point": [0, 0, 0]},
                {"source_point": [1, 0, 0], "target_point": [1, 0, 0]},
                {"source_point": [0, 1, 0], "target_point": [0, 1, 0]},
            ],
        }
    response = client.post(route, json=payload)
    assert response.status_code == 409
    assert response.json()["detail"]["station_count"] == 2
