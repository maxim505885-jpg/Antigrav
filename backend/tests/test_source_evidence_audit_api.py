from __future__ import annotations

import importlib


def test_source_evidence_audit_returns_read_only_per_candidate_summary(client, monkeypatch):
    api = importlib.import_module("scan2bim.api.app")
    elements = [
        {"id": "member-a", "cloud_id": "cloud-a", "class_name": "beam", "review_status": "unreviewed", "metadata": {"source_cloud_snapshot": {"snapshot_id": "bound"}}},
        {"id": "member-b", "cloud_id": "cloud-a", "class_name": "brace", "review_status": "unreviewed", "metadata": {}},
        {"id": "member-c", "cloud_id": "cloud-a", "class_name": "column", "review_status": "approved", "metadata": {"source_cloud_snapshot": {"snapshot_id": "present"}}},
    ]
    evidence = {
        "member-a": {"status": "consistent", "snapshot_matches": True, "row_ids_count": 10, "row_ids_valid_count": 10},
        "member-b": {"status": "mismatch", "row_ids_count": 8, "row_ids_valid_count": 0},
        "member-c": {"status": "unverifiable", "row_ids_count": 0, "row_ids_valid_count": 0},
    }
    monkeypatch.setattr(api, "_cloud", lambda cloud_id: {"id": cloud_id, "status": "ready"})
    monkeypatch.setattr(api, "list_elements", lambda cloud_id: elements)
    monkeypatch.setattr(api, "element_bbox_coordinate_frame", lambda element: "cloud_local")
    monkeypatch.setattr(
        api,
        "inspect_source_point_alignment",
        lambda cloud_id, element, frame: evidence[element["id"]],
    )

    response = client.get("/api/v1/clouds/cloud-a/source-evidence-audit")

    assert response.status_code == 200
    assert response.json() == {
        "cloud_id": "cloud-a",
        "candidate_count": 3,
        "status_counts": {"consistent": 1, "mismatch": 1, "unverifiable": 1},
        "status_counts_by_class": {
            "beam": {"consistent": 1, "mismatch": 0, "unverifiable": 0},
            "brace": {"consistent": 0, "mismatch": 1, "unverifiable": 0},
            "column": {"consistent": 0, "mismatch": 0, "unverifiable": 1},
        },
        "source_snapshot_counts": {"current": 1, "missing": 1, "stale": 0, "unchecked": 1},
        "attention_count": 2,
        "accuracy_status": "not_measured",
        "candidates": [
            {"id": "member-b", "class_name": "brace", "review_status": "unreviewed", "evidence": evidence["member-b"]},
            {"id": "member-c", "class_name": "column", "review_status": "approved", "evidence": evidence["member-c"]},
        ],
    }


def test_source_evidence_audit_rejects_clouds_that_are_not_ready(client, monkeypatch):
    api = importlib.import_module("scan2bim.api.app")
    monkeypatch.setattr(api, "_cloud", lambda cloud_id: {"id": cloud_id, "status": "processing"})

    response = client.get("/api/v1/clouds/cloud-a/source-evidence-audit")

    assert response.status_code == 409
    assert response.json()["detail"] == "cloud is not ready (status: processing)"
