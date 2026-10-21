import importlib

from scan2bim.recognition.geometric import DetectedElement, RecognitionResult

from conftest import wait_cloud, wait_job


def _candidate(center_x=2.0):
    return DetectedElement(
        class_name="column",
        geometry={
            "kind": "oriented_box",
            "center": [center_x, 2.0, 2.0],
            "sizes": {"length": 1.0, "thickness": 1.0, "height": 4.0},
        },
        bbox={
            "min": [center_x - 0.5, 1.5, 0.0],
            "max": [center_x + 0.5, 2.5, 4.0],
        },
        confidence=0.8,
    )


def _recognize(client, cloud_id):
    response = client.post(f"/api/v1/clouds/{cloud_id}/recognize")
    assert response.status_code == 200
    return wait_job(client, response.json()["id"])


def test_rerun_preserves_manual_review_and_surfaces_changed_overlap(client, monkeypatch):
    project = client.post("/api/v1/projects", json={"name": "Reconciliation test"}).json()
    points = "0 0 0\n1 0 0\n0 1 0\n0 0 1\n"
    response = client.post(
        f"/api/v1/projects/{project['id']}/clouds/upload",
        files={"file": ("tiny.xyz", points.encode(), "text/plain")},
    )
    assert response.status_code == 200
    cloud = wait_cloud(client, response.json()["id"])

    state = {"element": _candidate()}
    app_module = importlib.import_module("scan2bim.api.app")
    monkeypatch.setattr(
        app_module,
        "detect_structures",
        lambda geom, progress=None: RecognitionResult([state["element"]], [], [], {}),
    )

    first = _recognize(client, cloud["id"])
    assert first["status"] == "succeeded", first.get("error")
    original = client.get(f"/api/v1/clouds/{cloud['id']}/elements").json()[0]
    confirmed = client.post(
        f"/api/v1/elements/{original['id']}/feedback",
        json={"action": "confirm", "engineer": "test", "note": "manual review"},
    )
    assert confirmed.status_code == 200

    identical = _recognize(client, cloud["id"])
    assert identical["status"] == "succeeded", identical.get("error")
    elements = client.get(f"/api/v1/clouds/{cloud['id']}/elements").json()
    assert len(elements) == 1
    assert elements[0]["id"] == original["id"]
    assert elements[0]["review_status"] == "confirmed"
    assert identical["result"]["review_reconciliation"]["preserved_manual_element_ids"] == [original["id"]]

    state["element"] = _candidate(center_x=2.1)
    changed = _recognize(client, cloud["id"])
    assert changed["status"] == "succeeded", changed.get("error")
    elements = client.get(f"/api/v1/clouds/{cloud['id']}/elements").json()
    assert len(elements) == 2
    manual = next(item for item in elements if item["id"] == original["id"])
    candidate = next(item for item in elements if item["id"] != original["id"])
    assert manual["review_status"] == "confirmed"
    assert candidate["dimensions"]["review_conflict_with"] == [original["id"]]
    assert changed["result"]["review_reconciliation"]["conflicts"] == [
        {"candidate_id": candidate["id"], "protected_ids": [original["id"]]}
    ]
