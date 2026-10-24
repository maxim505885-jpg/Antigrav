from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from scan2bim.learning import store


@pytest.fixture
def point_cloud(tmp_path: Path, monkeypatch):
    positions = np.array(
        [[0.0, 0.0, 0.0], [0.55, 0.0, 1.0], [0.75, 0.0, 1.0], [2.0, 2.0, 2.0]],
        dtype=np.float32,
    )
    path = tmp_path / "positions.npy"
    np.save(path, positions)
    origin = np.array([10.0, 20.0, 30.0])
    monkeypatch.setattr(store, "_cloud", lambda cloud_id: {
        "id": cloud_id, "project_id": "pilot", "ingested_count": len(positions),
        "origin_x": origin[0], "origin_y": origin[1], "origin_z": origin[2],
    })
    monkeypatch.setattr(store, "cloud_paths", lambda _project_id, _cloud_id: {"positions": path})
    monkeypatch.setattr(store, "project_dir", lambda _project_id: tmp_path)
    inserts = []
    monkeypatch.setattr(store, "execute", lambda *args: inserts.append(args))
    return path, positions, origin, inserts, tmp_path


def _element(snapshot: dict, ids: list[int] | None = None) -> dict:
    metadata = {"bbox_coordinate_frame": "cloud_local"}
    if snapshot is not None:
        metadata["source_cloud_snapshot"] = snapshot
    if ids is not None:
        metadata.update({
            "source_point_ids": ids,
            "source_point_id_space": "positions.npy row index",
            "source_point_ids_sampled": False,
        })
    return {
        "id": "column-1", "class_name": "column", "source": "geometric",
        "geometry": {"kind": "oriented_box", "sizes": {"length": 0.55, "thickness": 0.1, "height": 1.0}},
        "bbox": {"min": [0.0, 0.0, 0.0], "max": [0.55, 0.0, 1.0]},
        "metadata": metadata,
    }


def test_training_sample_persists_the_point_cloud_snapshot_id(point_cloud):
    path, positions, origin, inserts, root = point_cloud
    snapshot = store.point_cloud_snapshot("cloud", path, len(positions), origin)

    sample = store.create_sample("pilot", "cloud", _element(snapshot, [0, 1]))

    assert sample["source_snapshot_id"] == snapshot["snapshot_id"]
    assert "source_snapshot_id" in inserts[0][0]
    assert snapshot["snapshot_id"] in inserts[0][1]
    saved = np.load(root / "training" / f"{sample['id']}.npy")
    np.testing.assert_allclose(saved, [origin, origin + [0.55, 0.0, 1.0]])


def test_sample_creation_rejects_a_candidate_from_a_different_cloud_snapshot(point_cloud):
    path, positions, origin, inserts, root = point_cloud
    old_snapshot = store.point_cloud_snapshot("cloud", path, len(positions), origin)
    element = _element(old_snapshot, [0, 1])
    np.save(path, positions + np.array([10.0, 0.0, 0.0], dtype=np.float32))

    with pytest.raises(ValueError, match="cloud snapshot changed"):
        store.create_sample("pilot", "cloud", element)

    assert inserts == []
    assert not (root / "training").exists()


def test_sample_creation_requires_a_snapshot_even_when_legacy_rows_match_bbox(point_cloud):
    path, positions, origin, inserts, root = point_cloud
    legacy_element = _element(None, [0, 1])

    with pytest.raises(ValueError, match="no source cloud snapshot"):
        store.create_sample("pilot", "cloud", legacy_element)

    assert inserts == []
    assert not (root / "training").exists()


def test_sample_creation_rejects_legacy_source_rows_outside_candidate_bbox(point_cloud):
    path, positions, origin, inserts, root = point_cloud
    current = store.point_cloud_snapshot("cloud", path, len(positions), origin)
    element = _element(current, [3])

    with pytest.raises(ValueError, match="source row IDs do not match"):
        store.create_sample("pilot", "cloud", element)

    assert inserts == []
    assert not (root / "training").exists()


def test_stale_cloud_cannot_become_a_training_label_through_the_api(client, monkeypatch):
    import importlib

    from conftest import wait_cloud, wait_job
    from scan2bim.storage import cloud_paths
    from scan2bim.recognition.geometric import DetectedElement, RecognitionResult

    project = client.post("/api/v1/projects", json={"name": "Snapshot training guard"}).json()
    points = "0 0 0\n0.55 0 1\n0.75 0 1\n2 2 2\n"
    uploaded = client.post(
        f"/api/v1/projects/{project['id']}/clouds/upload",
        files={"file": ("cloud.xyz", points.encode(), "text/plain")},
    )
    assert uploaded.status_code == 200, uploaded.text
    cloud = wait_cloud(client, uploaded.json()["id"])
    assert cloud["status"] == "ready", cloud.get("error")
    candidate = DetectedElement(
        class_name="column",
        geometry={"kind": "oriented_box", "center": [0.275, 0, 0.5],
                  "sizes": {"length": 0.55, "thickness": 0.1, "height": 1.0}},
        bbox={"min": [0, 0, 0], "max": [0.55, 0, 1]},
        confidence=0.8,
        measured=True,
        inferred=False,
        metadata={
            "source_point_ids": [0, 1],
            "source_point_id_space": "positions.npy row index",
            "source_point_ids_sampled": False,
        },
    )
    app_module = importlib.import_module("scan2bim.api.app")
    monkeypatch.setattr(
        app_module, "detect_structures",
        lambda _geom, _progress=None: RecognitionResult([candidate], [], [], {}),
    )
    job = client.post(f"/api/v1/clouds/{cloud['id']}/recognize")
    assert job.status_code == 200, job.text
    completed = wait_job(client, job.json()["id"])
    assert completed["status"] == "succeeded", completed.get("error")
    element = client.get(f"/api/v1/clouds/{cloud['id']}/elements").json()[0]

    paths = cloud_paths(project["id"], cloud["id"])
    array = np.load(paths["positions"], mmap_mode="r").copy()
    np.save(paths["positions"], array + np.array([10.0, 0.0, 0.0], dtype=np.float32))

    direct_review = client.patch(
        f"/api/v1/elements/{element['id']}", json={"review_status": "confirmed"},
    )
    assert direct_review.status_code == 409, direct_review.text
    assert client.get(f"/api/v1/clouds/{cloud['id']}/elements").json()[0]["review_status"] == "unreviewed"

    feedback = client.post(
        f"/api/v1/elements/{element['id']}/feedback", json={"action": "confirm"},
    )
    assert feedback.status_code == 200, feedback.text
    assert feedback.json()["sample"] is None
    assert "rerun recognition" in feedback.json()["training_sample_warning"]

    explicit_sample = client.post(
        f"/api/v1/projects/{project['id']}/samples",
        json={"element_id": element["id"], "class_name": "column"},
    )
    assert explicit_sample.status_code == 409, explicit_sample.text
