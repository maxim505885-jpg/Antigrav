"""API proof that two explicit sides complete a review-only column contour."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from conftest import wait_cloud
from scan2bim import db as database


def test_two_known_column_sides_complete_a_contour_without_saving_geometry(client):
    project = client.post("/api/v1/projects", json={"name": "Two-side column fit"}).json()

    heights = np.linspace(2.0, 4.0, 201)
    side_a = np.array([(x, 2.0, z) for z in heights for x in np.linspace(2.0, 2.5, 81)])
    side_b = np.array([(2.0, y, z) for z in heights for y in np.linspace(2.0, 2.4, 65)])
    xyz = np.concatenate((side_a, side_b))
    payload = "\n".join(" ".join(f"{value:.6f}" for value in row) for row in xyz) + "\n"
    imported = client.post(
        f"/api/v1/projects/{project['id']}/clouds/upload",
        files={"file": ("two-faces.xyz", payload.encode("ascii"), "text/plain")},
    )
    assert imported.status_code == 200, imported.text
    cloud = wait_cloud(client, imported.json()["id"])
    assert cloud["status"] == "ready", cloud

    element_id = "manual-column-candidate"
    geometry = {
        "kind": "oriented_box", "center": [2.25, 2.2, 3.0],
        "sizes": {"length": 0.5, "thickness": 0.4, "height": 2.0},
        "rotation_z": 0.0,
    }
    now = database.utcnow()
    database.execute(
        "INSERT INTO elements (id,project_id,cloud_id,class_name,geometry_json,bbox_json,"
        "confidence,confidence_kind,measured,inferred,source,review_status,dimensions_json,metadata_json,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (element_id, project["id"], cloud["id"], "column", json.dumps(geometry),
         json.dumps({"min": [2.0, 2.0, 2.0], "max": [2.5, 2.4, 4.0]}),
         0.5, "heuristic", 1, 0, "test", "unreviewed", "{}", "{}", now, now),
    )

    response = client.post(
        f"/api/v1/elements/{element_id}/section-fit",
        json={"slice_z_m": 3.0, "thickness_m": 0.1, "known_sides_m": [0.5, 0.4]},
    )
    assert response.status_code == 200, response.text
    result = response.json()

    assert result["status"] == "proposed"
    hypothesis = result["hypotheses"][0]
    assert sorted(hypothesis["side_lengths_m"]) == [0.4, 0.5]
    assert len(hypothesis["corners_world_m"]) == 4
    assert hypothesis["observed_edge_count"] == 2
    assert hypothesis["inferred_edge_count"] == 2
    assert hypothesis["dimension_source"] == "explicit_input"
    assert hypothesis["review_required"] is True
    assert result["persisted"] is False
    assert result["source_geometry_modified"] is False
    saved = database.one("SELECT geometry_json,review_status FROM elements WHERE id=?", (element_id,))
    assert json.loads(saved["geometry_json"]) == geometry
    assert saved["review_status"] == "unreviewed"

    batch_response = client.post(
        f"/api/v1/elements/{element_id}/section-fit-batch",
        json={"slice_z_values_m": [2.5, 3.0, 3.5], "thickness_m": 0.1, "known_sides_m": [0.5, 0.4]},
    )
    assert batch_response.status_code == 200, batch_response.text
    batch = batch_response.json()
    assert batch["element_id"] == element_id
    assert batch["algorithm"] == {"name": "fit_rectangular_section", "version": "1"}
    assert batch["slice_count"] == 3
    assert batch["review_required"] is True
    assert batch["persisted"] is False
    assert batch["source_geometry_modified"] is False
    assert [item["slice_z_m"] for item in batch["slices"]] == [2.5, 3.0, 3.5]
    assert all(item["source_rows"]["count"] == item["point_count"] for item in batch["slices"])
    assert batch["slices"][1]["hypotheses"] == result["hypotheses"]

    duplicate_height_response = client.post(
        f"/api/v1/elements/{element_id}/section-fit-batch",
        json={"slice_z_values_m": [3.0, 3.0, 3.5]},
    )
    assert duplicate_height_response.status_code == 422
    out_of_range_response = client.post(
        f"/api/v1/elements/{element_id}/section-fit-batch",
        json={"slice_z_values_m": [2.5, 3.0, 1_000_000_001]},
    )
    assert out_of_range_response.status_code == 422

    saved_after_batch = database.one("SELECT geometry_json,review_status FROM elements WHERE id=?", (element_id,))
    assert json.loads(saved_after_batch["geometry_json"]) == geometry
    assert saved_after_batch["review_status"] == "unreviewed"


def test_column_surface_track_analysis_returns_source_linked_review_evidence(client):
    project = client.post("/api/v1/projects", json={"name": "Column surface tracking"}).json()
    center = np.array([2.25, 2.2, 1.75])
    z_values = np.linspace(1.0, 2.5, 61)
    x_values = np.linspace(2.0, 2.5, 25)
    y_values = np.linspace(2.0, 2.4, 21)
    faces = [
        np.array([(x, y, z) for z in z_values for x in x_values])
        for y in (2.0, 2.4)
    ] + [
        np.array([(x, y, z) for z in z_values for y in y_values])
        for x in (2.0, 2.5)
    ]
    xyz = np.unique(np.concatenate(faces), axis=0)
    text = "\n".join(" ".join(f"{value:.6f}" for value in row) for row in xyz) + "\n"
    imported = client.post(
        f"/api/v1/projects/{project['id']}/clouds/upload",
        files={"file": ("column-faces.xyz", text.encode("ascii"), "text/plain")},
    )
    assert imported.status_code == 200, imported.text
    cloud = wait_cloud(client, imported.json()["id"])
    assert cloud["status"] == "ready", cloud

    element_id = "surface-track-column-candidate"
    geometry = {
        "kind": "oriented_box", "center": center.tolist(),
        "sizes": {"length": 0.5, "thickness": 0.4, "height": 1.5},
        "rotation_z": 0.0,
    }
    now = database.utcnow()
    database.execute(
        "INSERT INTO elements (id,project_id,cloud_id,class_name,geometry_json,bbox_json,"
        "confidence,confidence_kind,measured,inferred,source,review_status,dimensions_json,metadata_json,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (element_id, project["id"], cloud["id"], "column", json.dumps(geometry),
         json.dumps({"min": [2.0, 2.0, 1.0], "max": [2.5, 2.4, 2.5]}),
         0.5, "heuristic", 1, 0, "test", "unreviewed", "{}", "{}", now, now),
    )

    response = client.post(f"/api/v1/elements/{element_id}/surface-track-analysis")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["candidate_id"] == element_id
    assert report["cloud_id"] == cloud["id"]
    assert report["confirmed"] is False
    assert report["review_required"] is True
    assert report["source_geometry_modified"] is False
    assert report["input_points"]["count"] == len(xyz)
    assert report["surface_result"]["surfaces"]
    assert report["surface_association"]["candidate_edge_count"] == 4
    assert len(report["tracks"]) == 4
    track_statuses = {track["track_status"] for track in report["tracks"]}
    assert track_statuses & {"candidate_track", "weak_candidate_track"}
    assert "unassigned_surface_track" in track_statuses
    assert all(track["source_point_row_id_count"] > 0 for track in report["tracks"])
    assert all(track["source_point_row_id_sample"] for track in report["tracks"])
    assert len(report["section_series"]["section_slices"]) > 0
    assert report["section_series"]["review_required"] is True
    saved = database.one("SELECT geometry_json,review_status FROM elements WHERE id=?", (element_id,))
    assert json.loads(saved["geometry_json"]) == geometry
    assert saved["review_status"] == "unreviewed"
