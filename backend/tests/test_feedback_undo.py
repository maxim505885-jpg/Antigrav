from __future__ import annotations

from conftest import wait_cloud, wait_job
from scan2bim.db import execute


def _recognized_demo(client):
    demo = client.post("/api/v1/demo")
    assert demo.status_code == 200, demo.text
    cloud = wait_cloud(client, demo.json()["cloud"]["id"])
    assert cloud["status"] == "ready", cloud
    job = client.post(f"/api/v1/clouds/{cloud['id']}/recognize")
    assert job.status_code == 200, job.text
    assert wait_job(client, job.json()["id"])["status"] == "succeeded"
    return cloud, client.get(f"/api/v1/clouds/{cloud['id']}/elements").json()


def test_undo_confirm_restores_review_state_and_is_recorded(client):
    cloud, elements = _recognized_demo(client)
    element = elements[0]
    confirmed = client.post(
        f"/api/v1/elements/{element['id']}/feedback", json={"action": "confirm"}
    )
    assert confirmed.status_code == 200
    feedback_id = confirmed.json()["feedback_id"]
    assert client.get(f"/api/v1/elements/{element['id']}/history").json()[0]["can_undo"] is True
    assert confirmed.json()["sample"]["id"]

    undone = client.post(f"/api/v1/elements/{element['id']}/history/{feedback_id}/undo")
    assert undone.status_code == 200, undone.text
    current = next(item for item in client.get(f"/api/v1/clouds/{cloud['id']}/elements").json() if item["id"] == element["id"])
    assert current["review_status"] == "unreviewed"
    history = client.get(f"/api/v1/elements/{element['id']}/history").json()
    assert [item["action"] for item in history] == ["confirm", "undo"]
    assert history[-1]["after"]["undo_of"] == feedback_id
    assert history[-1]["can_undo"] is False
    samples = client.get(f"/api/v1/projects/{cloud['project_id']}/samples").json()
    sample = next(item for item in samples if item["id"] == confirmed.json()["sample"]["id"])
    assert sample["source"] == "undone"
    reconfirmed = client.post(f"/api/v1/elements/{element['id']}/feedback", json={"action": "confirm"})
    assert reconfirmed.status_code == 200, reconfirmed.text
    assert reconfirmed.json()["sample"]["id"] != sample["id"]
    samples = client.get(f"/api/v1/projects/{cloud['project_id']}/samples").json()
    assert sum(item["element_id"] == element["id"] and item["source"] != "undone" for item in samples) == 1
    assert client.post(f"/api/v1/elements/{element['id']}/history/{feedback_id}/undo").status_code == 409


def test_inferred_boundary_edit_is_not_added_as_a_training_sample(client):
    cloud, elements = _recognized_demo(client)
    element = next(item for item in elements if item["class_name"] == "column")
    response = client.post(
        f"/api/v1/elements/{element['id']}/feedback",
        json={"action": "adjust_boundary", "geometry": element["geometry"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["element"]["inferred"] is True
    assert response.json()["sample"] is None
    samples = client.get(f"/api/v1/projects/{cloud['project_id']}/samples").json()
    assert all(sample["element_id"] != element["id"] for sample in samples)


def test_invalidated_synthetic_element_cannot_be_reviewed_or_sampled(client):
    cloud, elements = _recognized_demo(client)
    element = next(item for item in elements if not item["inferred"])
    confirmed = client.post(
        f"/api/v1/elements/{element['id']}/feedback", json={"action": "confirm"}
    )
    assert confirmed.status_code == 200 and confirmed.json()["sample"]
    execute(
        "UPDATE elements SET source='invalidated_synthetic_ground_truth', inferred=1, measured=0 WHERE id=?",
        (element["id"],),
    )
    execute(
        "UPDATE training_samples SET source='invalidated_synthetic_ground_truth' WHERE element_id=?",
        (element["id"],),
    )

    review = client.post(f"/api/v1/elements/{element['id']}/feedback", json={"action": "confirm"})
    sample = client.post(
        f"/api/v1/projects/{cloud['project_id']}/samples", json={"element_id": element["id"]}
    )

    assert review.status_code == 400
    assert "invalidated synthetic ground truth" in review.json()["detail"]
    assert sample.status_code == 409
    model_status = client.get(f"/api/v1/projects/{cloud['project_id']}/model-status")
    assert model_status.status_code == 200
    assert model_status.json()["samples"] == 0


def test_explicit_training_sample_requires_review_and_is_idempotent(client):
    cloud, elements = _recognized_demo(client)
    element = next(item for item in elements if item["class_name"] == "column")
    endpoint = f"/api/v1/projects/{cloud['project_id']}/samples"

    unreviewed = client.post(endpoint, json={"element_id": element["id"]})
    assert unreviewed.status_code == 409

    confirmed = client.post(f"/api/v1/elements/{element['id']}/feedback", json={"action": "confirm"})
    assert confirmed.status_code == 200, confirmed.text
    first = client.post(endpoint, json={"element_id": element["id"]})
    second = client.post(endpoint, json={"element_id": element["id"]})
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"] == confirmed.json()["sample"]["id"]

    wrong_label = client.post(endpoint, json={"element_id": element["id"], "class_name": "wall"})
    assert wrong_label.status_code == 409


def test_reclassify_replaces_training_label_and_undo_restores_previous_sample(client):
    cloud, elements = _recognized_demo(client)
    element = next(item for item in elements if item["class_name"] == "column" and not item["inferred"])
    confirmed = client.post(f"/api/v1/elements/{element['id']}/feedback", json={"action": "confirm"})
    assert confirmed.status_code == 200 and confirmed.json()["sample"]
    old_sample_id = confirmed.json()["sample"]["id"]

    corrected = client.post(
        f"/api/v1/elements/{element['id']}/feedback",
        json={"action": "reclassify", "class_name": "wall", "engineer": "reviewer"},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["sample"] and corrected.json()["sample"]["class_name"] == "wall"
    samples = client.get(f"/api/v1/projects/{cloud['project_id']}/samples").json()
    assert next(item for item in samples if item["id"] == old_sample_id)["source"] == "undone"

    undo = client.post(
        f"/api/v1/elements/{element['id']}/history/{corrected.json()['feedback_id']}/undo"
    )
    assert undo.status_code == 200, undo.text
    samples = client.get(f"/api/v1/projects/{cloud['project_id']}/samples").json()
    assert next(item for item in samples if item["id"] == old_sample_id)["source"] == "engineer"
    assert next(item for item in samples if item["id"] == corrected.json()["sample"]["id"])["source"] == "undone"


def test_undo_split_restores_parent_and_keeps_children_as_rejected_history(client):
    cloud, elements = _recognized_demo(client)
    parent = next(item for item in elements if item["class_name"] == "column")
    split_at = sum(parent["bbox"][axis][0] for axis in ("min", "max")) / 2
    split = client.post(
        f"/api/v1/elements/{parent['id']}/feedback",
        json={"action": "split", "axis": "x", "value": split_at},
    )
    assert split.status_code == 200, split.text
    children = split.json()["children"]
    feedback_id = split.json()["feedback_id"]

    undone = client.post(f"/api/v1/elements/{parent['id']}/history/{feedback_id}/undo")
    assert undone.status_code == 200, undone.text
    current = client.get(f"/api/v1/clouds/{cloud['id']}/elements").json()
    restored_parent = next(item for item in current if item["id"] == parent["id"])
    assert restored_parent["review_status"] == parent["review_status"]
    restored_children = {item["id"]: item for item in undone.json()["restored"]}
    for child in children:
        archived = next(item for item in current if item["id"] == child["id"])
        assert archived["review_status"] == "rejected"
        assert restored_children[child["id"]]["metadata"]["undone_split"] == feedback_id


def test_undo_merge_restores_both_source_elements(client):
    cloud, elements = _recognized_demo(client)
    walls = [item for item in elements if item["class_name"] == "wall"][:2]
    before = {item["id"]: item for item in walls}
    merged = client.post(
        f"/api/v1/elements/{walls[0]['id']}/feedback",
        json={"action": "merge", "other_element_id": walls[1]["id"]},
    )
    assert merged.status_code == 200, merged.text
    feedback_id = merged.json()["feedback_id"]

    undone = client.post(f"/api/v1/elements/{walls[0]['id']}/history/{feedback_id}/undo")
    assert undone.status_code == 200, undone.text
    current = {item["id"]: item for item in client.get(f"/api/v1/clouds/{cloud['id']}/elements").json()}
    for element_id, original in before.items():
        assert current[element_id]["review_status"] == original["review_status"]
        assert current[element_id]["geometry"] == original["geometry"]


def test_undo_merge_refuses_to_overwrite_a_fragment_changed_after_merge(client):
    _, elements = _recognized_demo(client)
    walls = [item for item in elements if item["class_name"] == "wall"][:2]
    merged = client.post(
        f"/api/v1/elements/{walls[0]['id']}/feedback",
        json={"action": "merge", "other_element_id": walls[1]["id"]},
    )
    feedback_id = merged.json()["feedback_id"]
    changed = client.post(f"/api/v1/elements/{walls[1]['id']}/feedback", json={"action": "confirm"})
    assert changed.status_code == 200
    undone = client.post(f"/api/v1/elements/{walls[0]['id']}/history/{feedback_id}/undo")
    assert undone.status_code == 409
