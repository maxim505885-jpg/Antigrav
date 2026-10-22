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
