from __future__ import annotations

import json
import io
import uuid
from pathlib import Path

import pytest
import ezdxf

from scan2bim import db as database


@pytest.fixture
def api_data(client, monkeypatch):
    path = Path.cwd() / f".column_type_api_{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setattr(database, "DB_PATH", path)
    database.init_db()
    now = database.utcnow()
    projects = {name: f"project-{uuid.uuid4().hex}" for name in ("a", "b")}
    clouds = {name: f"cloud-{uuid.uuid4().hex}" for name in ("a", "b")}
    with database.db() as con:
        for key in ("a", "b"):
            con.execute(
                "INSERT INTO projects (id,name,created_at,updated_at) VALUES (?,?,?,?)",
                (projects[key], key, now, now),
            )
            con.execute(
                "INSERT INTO clouds (id,project_id,name,source_path,source_format,sha256,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (clouds[key], projects[key], key, "derived-test.e57", "e57", key * 64, now, now),
            )
        elements = {
            "a1": (projects["a"], clouds["a"], 0.5, 0.4),
            "a2": (projects["a"], clouds["a"], 0.5, 0.4),
            "a3": (projects["a"], clouds["a"], 0.7, 0.5),
            "b1": (projects["b"], clouds["b"], 0.5, 0.4),
        }
        for key, (project_id, cloud_id, length, thickness) in elements.items():
            geometry = {
                "kind": "oriented_box", "center": [float(len(key)), 0.0, 0.0],
                "sizes": {"length": length, "thickness": thickness, "height": 5.0},
                "rotation_z": 0.0,
            }
            con.execute(
                "INSERT INTO elements (id,project_id,cloud_id,class_name,geometry_json,bbox_json,"
                "dimensions_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    f"column-{key}", project_id, cloud_id, "column", json.dumps(geometry),
                    "{}", json.dumps({"column_type": "solid", "section_coverage": 0.9}), now, now,
                ),
            )
        con.execute(
            "INSERT INTO elements (id,project_id,cloud_id,class_name,geometry_json,bbox_json,"
            "dimensions_json,source,review_status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                "column-invalidated", projects["a"], clouds["a"], "column",
                json.dumps({"kind": "oriented_box", "center": [9.0, 0.0, 0.0],
                            "sizes": {"length": 0.5, "thickness": 0.4, "height": 5.0}, "rotation_z": 0.0}),
                "{}", "{}", "invalidated_synthetic_ground_truth", "invalidated", now, now,
            ),
        )
    yield {"projects": projects, "clouds": clouds}
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


def test_cloud_column_types_returns_proposals_and_project_catalog(client, api_data):
    response = client.get(f"/api/v1/clouds/{api_data['clouds']['a']}/column-types")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["tolerance_status"] == "provisional"
    assert len(payload["proposals"]) == 2
    repeated = next(item for item in payload["proposals"] if len(item["member_element_ids"]) == 2)
    assert repeated["status"] == "proposed"
    assert repeated["representative_sides_m"] == {"long": 0.5, "short": 0.4}
    assert repeated["evidence_summary"]["member_count"] == 2
    assert payload["confirmed_types"] == []


def test_manual_column_annotations_are_independent_versioned_and_exportable(client, api_data):
    cloud_id = api_data["clouds"]["a"]
    before = database.one("SELECT geometry_json, review_status FROM elements WHERE id='column-a1'")
    initial = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations")

    assert initial.status_code == 200, initial.text
    dataset = initial.json()
    assert dataset["schema"] == "scan.column-type-reference/1"
    assert len(dataset["annotations"]) == 3
    assert all(row["state"] == "pending" and row["sides_m"] is None for row in dataset["annotations"])
    row = {
        "source_snapshot_sha256": dataset["source_snapshot_sha256"],
        "annotator": "reviewer-a", "state": "labeled", "physical_instance_id": "C-01",
        "type_label": "K1", "shape_label": "rectangular_solid", "structural_role": "column",
        "sides_m": {"long": 0.5, "short": 0.4}, "measurement_source": "manual_cloud",
        "z_measurements": [{"z_m": 1.0, "sides_m": {"long": 0.5, "short": 0.4}}],
        "visible_faces": ["u+", "v+"], "hidden_faces": ["u-", "v-"],
        "confidence": 0.8, "reason_unknown": "", "note": "dimensions checked in two sections",
    }
    saved = client.post(f"/api/v1/clouds/{cloud_id}/column-annotations/column-a1", json=row)

    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1
    row["sides_m"] = {"long": 0.51, "short": 0.4}
    row["z_measurements"].append({"z_m": 4.0, "sides_m": {"long": 0.51, "short": 0.4}})
    second = client.post(f"/api/v1/clouds/{cloud_id}/column-annotations/column-a1", json=row)
    assert second.status_code == 200, second.text
    assert second.json()["revision"] == 2

    current = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations").json()
    exported = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations/export").json()
    source_model = client.get(f"/api/v1/clouds/{cloud_id}/bim?format=json").json()
    current_row = next(item for item in current["annotations"] if item["element_id"] == "column-a1")
    assert current_row["sides_m"] == {"long": 0.51, "short": 0.4}
    assert [item["revision"] for item in current["history"]] == [1, 2]
    assert exported["schema"] == "scan.column-type-reference/1"
    exported_row = next(item for item in exported["annotations"] if item["element_id"] == "column-a1")
    assert exported_row["sides_m"] == {"long": 0.51, "short": 0.4}
    assert exported_row["note"] == "dimensions checked in two sections"
    assert exported["source_cloud_manifest"] == source_model["source"]["snapshot_manifest"]
    from scan2bim.structure.column_annotations import column_snapshot_sha256
    reference_ids = {item["element_id"] for item in dataset["annotations"]}
    reference_elements = [item for item in source_model["elements"] if item["id"] in reference_ids]
    assert column_snapshot_sha256(reference_elements, source_model["source"]["snapshot_manifest"]) == exported["source_snapshot_sha256"]
    after = database.one("SELECT geometry_json, review_status FROM elements WHERE id='column-a1'")
    assert after == before


def test_invalidated_synthetic_columns_are_never_reference_annotations(client, api_data):
    cloud_id = api_data["clouds"]["a"]

    dataset = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations")
    assert dataset.status_code == 200, dataset.text
    assert {item["element_id"] for item in dataset.json()["annotations"]} == {
        "column-a1", "column-a2", "column-a3",
    }

    payload = {
        "source_snapshot_sha256": dataset.json()["source_snapshot_sha256"],
        "annotator": "reviewer-a", "state": "unknown", "physical_instance_id": None,
        "type_label": None, "sides_m": None, "measurement_source": None, "z_measurements": [],
        "visible_faces": [], "hidden_faces": [], "confidence": None,
        "reason_unknown": "synthetic row", "note": "must not become reference data",
    }
    saved = client.post(
        f"/api/v1/clouds/{cloud_id}/column-annotations/column-invalidated", json=payload,
    )
    exported = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations/export")
    database.execute(
        "INSERT INTO column_annotations "
        "(id,project_id,cloud_id,source_snapshot_sha256,element_id,revision,payload_json,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        ("archived-invalidated", api_data["projects"]["a"], cloud_id, "old-snapshot",
         "column-invalidated", 1, json.dumps({"state": "labeled", "type_label": "SYNTHETIC"}),
         database.utcnow()),
    )
    history = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations/history")

    assert saved.status_code == 404
    assert exported.status_code == 200, exported.text
    assert {item["element_id"] for item in exported.json()["annotations"]} == {
        "column-a1", "column-a2", "column-a3",
    }
    assert history.status_code == 200
    assert all(item["element_id"] != "column-invalidated" for item in history.json()["history"])


def test_column_annotation_rejects_duplicate_physical_ids_and_preserves_history(client, api_data):
    cloud_id = api_data["clouds"]["a"]
    dataset = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations").json()
    common = {
        "source_snapshot_sha256": dataset["source_snapshot_sha256"], "annotator": "reviewer-a",
        "state": "labeled", "physical_instance_id": "C-01", "type_label": "K1",
        "sides_m": None, "measurement_source": None, "z_measurements": [],
        "visible_faces": [], "hidden_faces": [], "confidence": 0.9,
        "reason_unknown": "", "note": "",
    }
    first = client.post(f"/api/v1/clouds/{cloud_id}/column-annotations/column-a1", json=common)
    duplicate = client.post(f"/api/v1/clouds/{cloud_id}/column-annotations/column-a2", json=common)

    assert first.status_code == 200, first.text
    assert duplicate.status_code == 409
    state = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations").json()
    assert len(state["history"]) == 1


def test_column_annotation_unknown_requires_reason_and_stale_snapshot_conflicts(client, api_data):
    cloud_id = api_data["clouds"]["a"]
    dataset = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations").json()
    body = {"source_snapshot_sha256": dataset["source_snapshot_sha256"], "annotator": "reviewer-a",
            "state": "unknown", "physical_instance_id": None, "type_label": None,
            "sides_m": None, "measurement_source": None, "z_measurements": [],
            "visible_faces": [], "hidden_faces": [], "confidence": None,
            "reason_unknown": "", "note": ""}
    missing_reason = client.post(f"/api/v1/clouds/{cloud_id}/column-annotations/column-a1", json=body)
    assert missing_reason.status_code == 422
    body["reason_unknown"] = "occluded by adjacent equipment"
    saved = client.post(f"/api/v1/clouds/{cloud_id}/column-annotations/column-a1", json=body)
    assert saved.status_code == 200, saved.text

    geometry = json.loads(database.one("SELECT geometry_json FROM elements WHERE id='column-a1'")["geometry_json"])
    geometry["center"][0] += 0.01
    database.execute("UPDATE elements SET geometry_json=? WHERE id='column-a1'", (json.dumps(geometry),))
    stale = client.post(f"/api/v1/clouds/{cloud_id}/column-annotations/column-a1", json=body)
    assert stale.status_code == 409
    current = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations").json()
    archived = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations/history").json()
    assert current["history"] == []
    assert len(archived["history"]) == 1
    assert archived["history"][0]["source_snapshot_sha256"] == dataset["source_snapshot_sha256"]


def test_column_annotation_snapshot_is_project_scoped(client, api_data):
    cloud_a, cloud_b = api_data["clouds"]["a"], api_data["clouds"]["b"]
    first = client.get(f"/api/v1/clouds/{cloud_a}/column-annotations").json()
    second = client.get(f"/api/v1/clouds/{cloud_b}/column-annotations").json()
    assert first["project_id"] != second["project_id"]
    assert first["dataset_id"] != second["dataset_id"]


def test_column_annotation_snapshot_rejects_changed_source_cloud_hash(client, api_data):
    cloud_id = api_data["clouds"]["a"]
    dataset = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations").json()
    database.execute("UPDATE clouds SET sha256='changed-source-digest' WHERE id=?", (cloud_id,))
    body = {"source_snapshot_sha256": dataset["source_snapshot_sha256"], "annotator": "reviewer-a",
            "state": "unknown", "physical_instance_id": None, "type_label": None,
            "sides_m": None, "measurement_source": None, "z_measurements": [],
            "visible_faces": [], "hidden_faces": [], "confidence": None,
            "reason_unknown": "no usable returns", "note": ""}

    stale = client.post(f"/api/v1/clouds/{cloud_id}/column-annotations/column-a1", json=body)

    assert stale.status_code == 409


def test_column_annotation_rechecks_snapshot_when_geometry_changes_during_save(client, api_data, monkeypatch):
    import importlib

    api_module = importlib.import_module("scan2bim.api.app")
    cloud_id = api_data["clouds"]["a"]
    dataset = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations").json()
    body = {"source_snapshot_sha256": dataset["source_snapshot_sha256"], "annotator": "reviewer-a",
            "state": "unknown", "physical_instance_id": None, "type_label": None,
            "sides_m": None, "measurement_source": None, "z_measurements": [],
            "visible_faces": [], "hidden_faces": [], "confidence": None,
            "reason_unknown": "occluded", "note": ""}
    original = api_module.column_snapshot_sha256
    mutated = False

    def change_after_snapshot(elements, cloud):
        nonlocal mutated
        digest = original(elements, cloud)
        if not mutated:
            mutated = True
            geometry = json.loads(database.one("SELECT geometry_json FROM elements WHERE id='column-a1'")["geometry_json"])
            geometry["center"][0] += 0.02
            database.execute("UPDATE elements SET geometry_json=? WHERE id='column-a1'", (json.dumps(geometry),))
        return digest

    monkeypatch.setattr(api_module, "column_snapshot_sha256", change_after_snapshot)

    stale = client.post(f"/api/v1/clouds/{cloud_id}/column-annotations/column-a1", json=body)

    assert stale.status_code == 409
    history = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations/history").json()
    assert history["history"] == []


def test_concurrent_column_annotation_saves_get_distinct_revisions(client, api_data):
    from concurrent.futures import ThreadPoolExecutor

    cloud_id = api_data["clouds"]["a"]
    dataset = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations").json()
    body = {"source_snapshot_sha256": dataset["source_snapshot_sha256"], "annotator": "reviewer-a",
            "state": "unknown", "physical_instance_id": None, "type_label": None,
            "sides_m": None, "measurement_source": None, "z_measurements": [],
            "visible_faces": [], "hidden_faces": [], "confidence": None,
            "reason_unknown": "partially occluded", "note": "parallel save"}

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.post, f"/api/v1/clouds/{cloud_id}/column-annotations/column-a1", json=body)
                   for _ in range(2)]
        responses = [future.result() for future in futures]

    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json()["revision"] for response in responses) == [1, 2]
    history = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations/history").json()
    assert [row["revision"] for row in history["history"]] == [1, 2]


def test_column_annotation_reappears_after_candidate_is_deleted_and_reimported(client, api_data):
    cloud_id = api_data["clouds"]["a"]
    dataset = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations").json()
    body = {"source_snapshot_sha256": dataset["source_snapshot_sha256"], "annotator": "reviewer-a",
            "state": "unknown", "physical_instance_id": None, "type_label": None,
            "sides_m": None, "measurement_source": None, "z_measurements": [],
            "visible_faces": [], "hidden_faces": [], "confidence": None,
            "reason_unknown": "candidate needs another review", "note": "retain manual knowledge"}

    saved = client.post(f"/api/v1/clouds/{cloud_id}/column-annotations/column-a1", json=body)
    assert saved.status_code == 200, saved.text
    original_element = database.one("SELECT * FROM elements WHERE id='column-a1'")

    database.execute("DELETE FROM elements WHERE id='column-a1'")
    without_candidate = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations").json()
    archived = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations/history").json()
    assert without_candidate["source_snapshot_sha256"] != dataset["source_snapshot_sha256"]
    assert without_candidate["history"] == []
    assert len(archived["history"]) == 1

    columns = list(original_element)
    placeholders = ",".join("?" for _ in columns)
    database.execute(
        f"INSERT INTO elements ({','.join(columns)}) VALUES ({placeholders})",
        tuple(original_element[column] for column in columns),
    )

    restored = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations").json()
    restored_row = next(row for row in restored["annotations"] if row["element_id"] == "column-a1")
    assert restored["source_snapshot_sha256"] == dataset["source_snapshot_sha256"]
    assert restored_row["state"] == "unknown"
    assert restored_row["reason_unknown"] == "candidate needs another review"
    assert restored["history"][0]["revision"] == 1


def test_column_annotation_rejects_invalid_dimension_order_without_creating_revision(client, api_data):
    cloud_id = api_data["clouds"]["a"]
    dataset = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations").json()
    body = {"source_snapshot_sha256": dataset["source_snapshot_sha256"], "annotator": "reviewer-a",
            "state": "labeled", "physical_instance_id": "C-01", "type_label": "K1",
            "sides_m": {"long": 0.3, "short": 0.4}, "measurement_source": "manual_cloud",
            "z_measurements": [], "visible_faces": [], "hidden_faces": [],
            "confidence": 0.8, "reason_unknown": "", "note": ""}

    invalid = client.post(f"/api/v1/clouds/{cloud_id}/column-annotations/column-a1", json=body)

    assert invalid.status_code == 422
    assert client.get(f"/api/v1/clouds/{cloud_id}/column-annotations").json()["history"] == []


def test_algorithm_suggested_annotation_rows_keep_structured_point_provenance_and_require_review(client, api_data):
    cloud_id = api_data["clouds"]["a"]
    dataset = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations").json()
    body = {
        "source_snapshot_sha256": dataset["source_snapshot_sha256"],
        "annotator": "reviewer-a", "state": "labeled", "physical_instance_id": "C-01",
        "type_label": "K1", "shape_label": "rectangular_solid", "structural_role": "column",
        "sides_m": None, "measurement_source": "manual_cloud",
        "algorithm_suggestions_verified": False,
        "z_measurements": [{
            "z_m": 2.0, "sides_m": {"long": 0.5, "short": 0.4}, "note": "checked in cloud",
            "source_provenance": {
                "source_point_row_id_count": 25, "source_point_row_id_sample": [1, 2, 3],
                "source_index_space": "derived_positions_row_index/1", "analysis_algorithm": "surface_tracks-v1",
            },
        }],
        "visible_faces": ["u+", "u-", "v+", "v-"], "hidden_faces": [],
        "confidence": 0.9, "reason_unknown": "", "note": "",
    }
    endpoint = f"/api/v1/clouds/{cloud_id}/column-annotations/column-a1"

    unverified = client.post(endpoint, json=body)
    assert unverified.status_code == 422
    assert client.get(f"/api/v1/clouds/{cloud_id}/column-annotations").json()["history"] == []

    body["algorithm_suggestions_verified"] = True
    saved = client.post(endpoint, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["algorithm_suggestions_verified"] is True
    assert saved.json()["z_measurements"][0]["source_provenance"]["source_point_row_id_count"] == 25
    assert saved.json()["z_measurements"][0]["source_provenance"]["source_point_row_id_sample"] == [1, 2, 3]
    assert saved.json()["z_measurements"][0]["source_provenance"]["source_index_space"] == "derived_positions_row_index/1"

    exported = client.get(f"/api/v1/clouds/{cloud_id}/column-annotations/export").json()
    exported_row = next(item for item in exported["annotations"] if item["element_id"] == "column-a1")
    assert exported_row["algorithm_suggestions_verified"] is True
    assert exported_row["z_measurements"][0]["source_provenance"]["source_point_row_id_sample"] == [1, 2, 3]

    import copy
    malformed = copy.deepcopy(body)
    malformed["z_measurements"][0]["source_provenance"]["source_point_row_id_sample"] = [-1]
    invalid = client.post(endpoint, json=malformed)
    assert invalid.status_code == 422
    assert len(client.get(f"/api/v1/clouds/{cloud_id}/column-annotations").json()["history"]) == 1


def test_confirm_requires_current_cloud_proposal_and_is_idempotent(client, api_data):
    cloud_id = api_data["clouds"]["a"]
    proposals = client.get(f"/api/v1/clouds/{cloud_id}/column-types").json()["proposals"]
    repeated = next(item for item in proposals if len(item["member_element_ids"]) == 2)
    body = {"cloud_id": cloud_id, "mark": "К7", "engineer": "reviewer", "note": "checked"}

    first = client.post(f"/api/v1/column-types/{repeated['proposal_key']}/confirm", json=body)
    second = client.post(f"/api/v1/column-types/{repeated['proposal_key']}/confirm", json=body)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["changed"] is False
    confirmed = client.get(f"/api/v1/clouds/{cloud_id}/column-types").json()
    assert confirmed["confirmed_types"][0]["mark"] == "К7"
    assert confirmed["proposals"]


def test_assign_validates_project_and_undo_restores_previous_membership(client, api_data):
    cloud_a, cloud_b = api_data["clouds"]["a"], api_data["clouds"]["b"]
    proposal_a = client.get(f"/api/v1/clouds/{cloud_a}/column-types").json()["proposals"][0]
    type_a = client.post(
        f"/api/v1/column-types/{proposal_a['proposal_key']}/confirm",
        json={"cloud_id": cloud_a},
    ).json()
    proposal_b = client.get(f"/api/v1/clouds/{cloud_b}/column-types").json()["proposals"][0]
    type_b = client.post(
        f"/api/v1/column-types/{proposal_b['proposal_key']}/confirm",
        json={"cloud_id": cloud_b},
    ).json()

    cross_project = client.post(
        "/api/v1/elements/column-a3/column-type", json={"type_id": type_b["id"]}
    )
    assigned = client.post(
        "/api/v1/elements/column-a3/column-type", json={"type_id": type_a["id"]}
    )
    undone = client.post(
        f"/api/v1/column-types/actions/{assigned.json()['action_id']}/undo", json={}
    )
    unknown = client.post(
        "/api/v1/elements/missing/column-type", json={"type_id": type_a["id"]}
    )

    assert cross_project.status_code == 409
    assert assigned.status_code == 200, assigned.text
    assert undone.status_code == 200, undone.text
    assert undone.json()["status"] == "undone"
    assert unknown.status_code == 404


def test_unknown_cloud_and_stale_proposal_are_not_confirmed(client, api_data):
    missing_cloud = client.get("/api/v1/clouds/missing/column-types")
    stale = client.post(
        "/api/v1/column-types/stale-proposal/confirm",
        json={"cloud_id": api_data["clouds"]["a"]},
    )

    assert missing_cloud.status_code == 404
    assert stale.status_code == 404


def test_rejected_group_stays_hidden_until_undo_without_rejecting_columns(client, api_data):
    cloud_id = api_data["clouds"]["a"]
    proposal = client.get(f"/api/v1/clouds/{cloud_id}/column-types").json()["proposals"][0]
    rejection = client.post(
        f"/api/v1/column-types/{proposal['proposal_key']}/reject",
        json={"cloud_id": cloud_id, "note": "section mismatch"},
    )
    assert rejection.status_code == 200, rejection.text
    refreshed = client.get(f"/api/v1/clouds/{cloud_id}/column-types").json()
    assert all(item["proposal_key"] != proposal["proposal_key"] for item in refreshed["proposals"])
    assert refreshed["rejected_proposals"][0]["proposal"]["proposal_key"] == proposal["proposal_key"]
    assert database.one("SELECT review_status FROM elements WHERE id='column-a1'")["review_status"] == "unreviewed"
    undone = client.post(f"/api/v1/column-types/actions/{rejection.json()['action_id']}/undo", json={})
    assert undone.status_code == 200, undone.text
    restored = client.get(f"/api/v1/clouds/{cloud_id}/column-types").json()
    assert any(item["proposal_key"] == proposal["proposal_key"] for item in restored["proposals"])


def test_plan_exports_use_current_confirmed_catalog_and_label_other_groups_as_proposals(client, api_data):
    cloud_id = api_data["clouds"]["a"]
    proposals = client.get(f"/api/v1/clouds/{cloud_id}/column-types").json()["proposals"]
    repeated = next(item for item in proposals if len(item["member_element_ids"]) == 2)
    confirmed = client.post(f"/api/v1/column-types/{repeated['proposal_key']}/confirm",
        json={"cloud_id": cloud_id, "mark": "К7"})
    assert confirmed.status_code == 200
    response = client.get(f"/api/v1/clouds/{cloud_id}/structural-plan.dxf?type=columns&issue=draft")
    assert response.status_code == 200, response.text
    # Match readfile's universal-newline handling for a Windows HTTP payload.
    doc = ezdxf.read(io.StringIO(response.text, newline=None))
    texts = [entity.dxf.text for entity in doc.modelspace().query("TEXT")]
    assert texts
    assert texts.count("К7") >= 2
    assert "К7-2" in texts
    assert "ПРЕДЛОЖЕНИЕ" in texts
    assert "column-a1" in texts and "column-a2" in texts
    pdf = client.get(f"/api/v1/clouds/{cloud_id}/structural-plan.pdf?type=columns&issue=draft")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")


def test_cleared_type_member_returns_as_an_unassigned_proposal(client, api_data):
    cloud_id = api_data["clouds"]["a"]
    proposals = client.get(f"/api/v1/clouds/{cloud_id}/column-types").json()["proposals"]
    repeated = next(item for item in proposals if len(item["member_element_ids"]) == 2)
    confirmed = client.post(f"/api/v1/column-types/{repeated['proposal_key']}/confirm", json={"cloud_id": cloud_id})
    assert confirmed.status_code == 200
    assert client.post("/api/v1/elements/column-a1/column-type", json={"type_id": None}).status_code == 200
    refreshed = client.get(f"/api/v1/clouds/{cloud_id}/column-types").json()
    returned = next((item for item in refreshed["proposals"] if item["member_element_ids"] == ["column-a1"]), None)
    assert returned is not None
    assert refreshed["confirmed_types"][0]["member_element_ids"] == ["column-a2"]
    separate = client.post(f"/api/v1/column-types/{returned['proposal_key']}/confirm",
        json={"cloud_id": cloud_id, "mark": "К2"})
    assert separate.status_code == 200, separate.text
    final = client.get(f"/api/v1/clouds/{cloud_id}/column-types").json()
    assert len(final["confirmed_types"]) == 2
    # A fully cleared type may be explicitly reconfirmed without creating a duplicate.
    client.post("/api/v1/elements/column-a1/column-type", json={"type_id": None})
    unassigned = client.get(f"/api/v1/clouds/{cloud_id}/column-types").json()["proposals"]
    same = next(item for item in unassigned if item["member_element_ids"] == ["column-a1"])
    restored = client.post(f"/api/v1/column-types/{same['proposal_key']}/confirm", json={"cloud_id": cloud_id})
    assert restored.status_code == 200, restored.text
    assert restored.json()["id"] == separate.json()["id"]
    assert restored.json()["changed"] is True


def test_pdf_export_forwards_scale_and_reports_fragment_limit(client, api_data, monkeypatch):
    import importlib
    module = importlib.import_module("scan2bim.api.app")
    received = []
    def limited_export(*args, **kwargs):
        received.append(kwargs.get("scale"))
        raise ValueError("PDF plan exceeds 200 fragments")
    monkeypatch.setattr(module, "export_structural_plan_pdf", limited_export)
    url = f"/api/v1/clouds/{api_data['clouds']['a']}/structural-plan.pdf"
    response = client.get(url + "?scale=200")
    assert response.status_code == 400
    assert "200 fragments" in response.json()["detail"]
    assert received == [200]
    assert client.get(url + "?scale=0").status_code == 422


def test_project_catalog_reuse_crosses_clouds_but_never_assigns_automatically(client, api_data):
    source_cloud = api_data["clouds"]["a"]
    proposal = next(p for p in client.get(f"/api/v1/clouds/{source_cloud}/column-types").json()["proposals"]
        if len(p["member_element_ids"]) == 2)
    confirmed = client.post(f"/api/v1/column-types/{proposal['proposal_key']}/confirm",
        json={"cloud_id": source_cloud, "mark": "К1"}).json()
    cloud_id = f"new-{uuid.uuid4().hex}"
    now = database.utcnow()
    with database.db() as con:
        con.execute("INSERT INTO clouds (id,project_id,name,source_path,source_format,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
            (cloud_id, api_data["projects"]["a"], "second scan", "synthetic.ply", "ply", now, now))
        con.execute("INSERT INTO elements (id,project_id,cloud_id,class_name,geometry_json,bbox_json,dimensions_json,created_at,updated_at) "
            "SELECT 'new-column',project_id,?,class_name,geometry_json,bbox_json,dimensions_json,created_at,updated_at FROM elements WHERE id='column-a1'", (cloud_id,))
    before = database.one("SELECT * FROM elements WHERE id='new-column'")
    url = f"/api/v1/clouds/{cloud_id}/column-types"
    payload = client.get(url).json()
    reuse = payload["catalog_reuse"]["suggestions"][0]
    assert reuse["status"] == "match" and reuse["review_required"] is True
    assert reuse["matches"][0]["type_id"] == confirmed["id"]
    assert reuse["matches"][0]["source_cloud_ids"] == [source_cloud]
    confirmed_type = next(item for item in payload["confirmed_types"] if item["id"] == confirmed["id"])
    assert confirmed_type["prototype"]["source_cloud_fingerprints"] == {source_cloud: "a" * 64}
    assert database.one("SELECT * FROM elements WHERE id='new-column'") == before
    assert database.one("SELECT * FROM column_type_assignments WHERE element_id='new-column'") is None
    with database.db() as con:
        con.execute("UPDATE clouds SET sha256=? WHERE id=?", ("f" * 64, source_cloud))
    changed_source = client.get(url).json()["catalog_reuse"]
    assert changed_source["suggestions"][0]["matches"] == []
    assert "source_cloud_changed" in changed_source["catalog_issues"][0]["reasons"]
    with database.db() as con:
        con.execute("UPDATE clouds SET sha256=? WHERE id=?", ("a" * 64, source_cloud))
    foreign = client.get(f"/api/v1/clouds/{api_data['clouds']['b']}/column-types").json()
    assert foreign["catalog_reuse"]["suggestions"][0]["matches"] == []
    with database.db() as con:
        con.execute("UPDATE elements SET review_status='rejected' WHERE id='column-a1'")
    stale = client.get(url).json()["catalog_reuse"]
    assert stale["suggestions"][0]["matches"] == []
    assert stale["catalog_issues"][0]["type_id"] == confirmed["id"]
