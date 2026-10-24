from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from scan2bim import db as database
from scan2bim.schemas import RecognitionEvaluationRequest


@pytest.fixture
def recognition_data(client, monkeypatch):
    path = Path.cwd() / f".recognition_eval_{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setattr(database, "DB_PATH", path)
    database.init_db()
    now = database.utcnow()
    project_id, cloud_id = "eval-project", "eval-cloud"
    with database.db() as con:
        con.execute(
            "INSERT INTO projects (id,name,created_at,updated_at) VALUES (?,?,?,?)",
            (project_id, "evaluation", now, now),
        )
        con.execute(
            "INSERT INTO clouds (id,project_id,name,source_path,source_format,sha256,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (cloud_id, project_id, "evaluation", "derived-test.e57", "e57", "a" * 64, now, now),
        )
        candidates = [
            ("column-valid", {"min": [-1, -1, -1], "max": [1, 1, 1]}, [0, 0, 0]),
            ("column-flat", {"min": [3, -1, -1], "max": [3, 1, 1]}, [3, 0, 0]),
        ]
        for element_id, bbox, center in candidates:
            geometry = {
                "kind": "oriented_box", "center": center,
                "sizes": {"length": 2.0, "thickness": 2.0, "height": 2.0},
                "rotation_z": 0.0,
            }
            con.execute(
                "INSERT INTO elements (id,project_id,cloud_id,class_name,geometry_json,bbox_json,"
                "dimensions_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (element_id, project_id, cloud_id, "column", json.dumps(geometry),
                 json.dumps(bbox), "{}", now, now),
            )
    yield {"cloud_id": cloud_id}
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


def reference_box(instance_id, bbox):
    return {"physical_instance_id": instance_id, "class_name": "column", "bbox": bbox}


def test_recognition_reference_schema_rejects_role_incompatible_with_class():
    request = {
        "source_snapshot_sha256": "a" * 64,
        "reference_set_id": "independent-01",
        "reference_origin": "independent_manual",
        "reference_kind": "field_measurement",
        "annotator": "engineer",
        "reference_elements": [{
            "physical_instance_id": "C-01", "class_name": "column", "role_label": "crane_girder",
            "bbox": {"min": [0, 0, 0], "max": [1, 1, 1]},
        }],
    }

    with pytest.raises(ValueError, match="incompatible"):
        RecognitionEvaluationRequest.model_validate(request)


def test_recognition_reference_schema_accepts_crane_girder_beam_role():
    request = {
        "source_snapshot_sha256": "a" * 64,
        "reference_set_id": "independent-02",
        "reference_origin": "independent_manual",
        "reference_kind": "field_measurement",
        "annotator": "engineer",
        "reference_elements": [{
            "physical_instance_id": "KG-01", "class_name": "beam", "role_label": "crane_girder",
            "bbox": {"min": [0, 0, 0], "max": [1, 1, 1]},
        }],
    }

    assert RecognitionEvaluationRequest.model_validate(request).reference_elements[0].role_label == "crane_girder"


def test_cloud_recognition_evaluation_counts_missed_physical_and_unscorable_candidates(client, recognition_data):
    cloud_id = recognition_data["cloud_id"]
    snapshot = client.get(f"/api/v1/clouds/{cloud_id}/element-annotations").json()["source_snapshot_sha256"]
    exact_box = {"min": [-1, -1, -1], "max": [1, 1, 1]}
    missed_box = {"min": [9, 9, 9], "max": [11, 11, 11]}
    response = client.post(f"/api/v1/clouds/{cloud_id}/recognition-evaluation", json={
        "source_snapshot_sha256": snapshot,
        "reference_set_id": "pilot-holdout-01",
        "reference_origin": "independent_manual",
        "reference_kind": "field_measurement",
        "annotator": "engineer",
        "iou_threshold": 0.5,
        "reference_elements": [
            reference_box("C-01", exact_box),
            reference_box("C-02", missed_box),
        ],
    })

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["reference_element_count"] == 2
    assert report["total_detected_candidates"] == 2
    assert report["unscorable_detection_geometry_count"] == 1
    assert report["unscorable_detection_ids"] == ["column-flat"]
    assert report["per_class"]["column"]["true_positives"] == 1
    assert report["per_class"]["column"]["false_positives"] == 1
    assert report["per_class"]["column"]["false_negatives"] == 1
    assert report["overall_precision"] == 0.5
    assert report["overall_recall"] == 0.5
    assert report["holdout_status"] == "not_verified"
    assert report["missed_reference_elements_counted_as_false_negatives"] is True
    assert database.one("SELECT COUNT(*) AS count FROM element_annotations")["count"] == 0


def test_cloud_recognition_evaluation_uses_member_centerline_for_flat_candidate_bbox(client, recognition_data):
    cloud_id = recognition_data["cloud_id"]
    now = database.utcnow()
    geometry = {"kind": "member", "p0": [1.0, 0.5, 0.2], "p1": [3.0, 0.5, 2.8]}
    with database.db() as con:
        con.execute(
            "INSERT INTO elements (id,project_id,cloud_id,class_name,geometry_json,bbox_json,"
            "dimensions_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("brace-axis", "eval-project", cloud_id, "brace", json.dumps(geometry),
             json.dumps({"min": [1, 0.5, 0.2], "max": [3, 0.5, 2.8]}), "{}", now, now),
        )
    snapshot = client.get(f"/api/v1/clouds/{cloud_id}/element-annotations").json()["source_snapshot_sha256"]
    references = [
        reference_box("C-01", {"min": [-1, -1, -1], "max": [1, 1, 1]}),
        reference_box("C-02", {"min": [9, 9, 9], "max": [11, 11, 11]}),
        {"physical_instance_id": "BR-01", "class_name": "brace",
         "bbox": {"min": [0, 0, 0], "max": [4, 1, 3]}},
    ]
    response = client.post(f"/api/v1/clouds/{cloud_id}/recognition-evaluation", json={
        "source_snapshot_sha256": snapshot,
        "reference_set_id": "pilot-centerline-01",
        "reference_origin": "independent_manual",
        "reference_kind": "field_measurement",
        "annotator": "engineer",
        "reference_elements": references,
    })

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["centerline_extent_match_count"] == 1
    assert report["mean_matched_centerline_extent_iou"] is not None
    assert report["mean_matched_iou"] == 1.0
    assert report["per_class"]["brace"]["true_positives"] == 1
    assert report["per_class"]["brace"]["centerline_extent_match_count"] == 1
    assert report["unscorable_detection_geometry_count"] == 2


def test_cloud_recognition_evaluation_reports_crane_girder_role_separately(client, recognition_data):
    cloud_id = recognition_data["cloud_id"]
    now = database.utcnow()
    bbox = {"min": [-1, -0.5, -0.5], "max": [1, 0.5, 0.5]}
    geometry = {
        "kind": "oriented_box", "center": [0, 0, 0],
        "sizes": {"length": 2.0, "thickness": 1.0, "height": 1.0},
        "rotation_z": 0.0,
    }
    with database.db() as con:
        con.execute(
            "INSERT INTO elements (id,project_id,cloud_id,class_name,geometry_json,bbox_json,"
            "dimensions_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("girder-detection", "eval-project", cloud_id, "beam", json.dumps(geometry),
             json.dumps(bbox), json.dumps({"role": "crane_girder"}), now, now),
        )
    snapshot = client.get(f"/api/v1/clouds/{cloud_id}/element-annotations").json()["source_snapshot_sha256"]
    response = client.post(f"/api/v1/clouds/{cloud_id}/recognition-evaluation", json={
        "source_snapshot_sha256": snapshot,
        "reference_set_id": "pilot-role-01",
        "reference_origin": "independent_manual",
        "reference_kind": "field_measurement",
        "annotator": "engineer",
        "reference_elements": [{
            "physical_instance_id": "KG-01", "class_name": "beam", "role_label": "crane_girder", "bbox": bbox,
        }],
    })

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["per_class"]["beam"]["true_positives"] == 1
    assert report["role_metrics"]["evaluated_reference_count"] == 1
    assert report["role_metrics"]["correct_count"] == 1
    assert report["role_metrics"]["precision"] == report["role_metrics"]["recall"] == 1.0
    assert report["role_metrics"]["per_role"]["crane_girder"]["true_positives"] == 1


def test_cloud_recognition_evaluation_rejects_stale_candidate_snapshot(client, recognition_data):
    response = client.post(f"/api/v1/clouds/{recognition_data['cloud_id']}/recognition-evaluation", json={
        "source_snapshot_sha256": "0" * 64,
        "reference_set_id": "pilot-holdout-01",
        "reference_origin": "independent_manual",
        "reference_kind": "field_measurement",
        "annotator": "engineer",
        "reference_elements": [reference_box("C-01", {"min": [0, 0, 0], "max": [1, 1, 1]})],
    })

    assert response.status_code == 409
    assert "snapshot changed" in response.json()["detail"]


def test_cloud_recognition_evaluation_rejects_duplicate_physical_ids(client, recognition_data):
    cloud_id = recognition_data["cloud_id"]
    snapshot = client.get(f"/api/v1/clouds/{cloud_id}/element-annotations").json()["source_snapshot_sha256"]
    reference = reference_box("C-01", {"min": [0, 0, 0], "max": [1, 1, 1]})
    response = client.post(f"/api/v1/clouds/{cloud_id}/recognition-evaluation", json={
        "source_snapshot_sha256": snapshot,
        "reference_set_id": "pilot-holdout-01",
        "reference_origin": "independent_manual",
        "reference_kind": "field_measurement",
        "annotator": "engineer",
        "reference_elements": [reference, reference],
    })

    assert response.status_code == 422
    assert "physical_instance_id values must be unique" in response.json()["detail"]


def test_cloud_recognition_evaluation_rejects_blank_provenance_and_physical_ids(client, recognition_data):
    cloud_id = recognition_data["cloud_id"]
    snapshot = client.get(f"/api/v1/clouds/{cloud_id}/element-annotations").json()["source_snapshot_sha256"]
    body = {
        "source_snapshot_sha256": snapshot,
        "reference_set_id": "pilot-holdout-01",
        "reference_origin": "independent_manual",
        "reference_kind": "field_measurement",
        "annotator": "   ",
        "reference_elements": [reference_box("C-01", {"min": [0, 0, 0], "max": [1, 1, 1]})],
    }
    response = client.post(f"/api/v1/clouds/{cloud_id}/recognition-evaluation", json=body)
    assert response.status_code == 422

    body["annotator"] = "engineer"
    body["reference_elements"] = [reference_box("   ", {"min": [0, 0, 0], "max": [1, 1, 1]})]
    response = client.post(f"/api/v1/clouds/{cloud_id}/recognition-evaluation", json=body)
    assert response.status_code == 422
