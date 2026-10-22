from __future__ import annotations

import importlib
from pathlib import Path
import time

import numpy as np
import pytest

from scan2bim import ingest
from scan2bim.demo import write_room_ply
from scan2bim.db import execute, new_id, one, utcnow
from scan2bim.formats import RawCloud
from scan2bim.jobs import JobCancelled, create_job, get_job, update_job
from scan2bim.storage import cloud_paths


def test_ingest_resumes_finalization_from_a_complete_checkpoint(client, tmp_path, monkeypatch):
    source = tmp_path / "synthetic-source.xyz"
    source.write_text("synthetic test source", encoding="utf-8")
    project = client.post("/api/v1/projects", json={"name": "restart test"}).json()
    project_id = project["id"]
    cloud_id = new_id()
    now = utcnow()
    execute(
        """INSERT INTO clouds
        (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (cloud_id, project_id, "synthetic", str(source), "xyz", source.stat().st_size, "processing", now, now),
    )
    xyz = np.array([[10.0, 20.0, 1.0], [11.0, 22.0, 3.0], [12.0, 21.0, 2.0]])
    rgb = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]], dtype=np.uint8)
    raw = RawCloud(xyz, rgb, metadata={"reader": "synthetic-test", "source_point_count": 3})
    monkeypatch.setattr(ingest, "read_cloud", lambda *args, **kwargs: raw)

    def interrupt_after_checkpoint(_value, message):
        if message == "checkpoint ready; finalizing":
            raise JobCancelled("simulated restart after durable checkpoint")

    with pytest.raises(JobCancelled):
        ingest.ingest_cloud(project_id, cloud_id, source, progress=interrupt_after_checkpoint)

    paths = cloud_paths(project_id, cloud_id)
    checkpoint = paths["dir"] / ".ingest-stage" / "manifest.json"
    assert checkpoint.exists(), "complete stage manifest must survive interruption"

    def source_must_not_be_reopened(*_args, **_kwargs):
        pytest.fail("restart reopened the source although a complete checkpoint exists")

    monkeypatch.setattr(ingest, "read_cloud", source_must_not_be_reopened)
    result = ingest.ingest_cloud(project_id, cloud_id, source)

    assert result["ingested_count"] == 3
    np.testing.assert_array_equal(np.load(paths["positions"]), (xyz - xyz.mean(axis=0)).astype(np.float32))
    np.testing.assert_array_equal(np.load(paths["colors"]), rgb)
    assert paths["preview"].stat().st_size == result["preview_count"] * ingest.PREVIEW_DTYPE.itemsize
    assert one("SELECT status FROM clouds WHERE id = ?", (cloud_id,))["status"] == "ready"
    assert not checkpoint.parent.exists(), "committed stage should be cleaned after database finalization"


def test_cancelled_import_can_resume_from_checkpoint_without_rereading_source(client, tmp_path, monkeypatch):
    api_module = importlib.import_module("scan2bim.api.app")
    source = tmp_path / "resume-room.ply"
    write_room_ply(source, spacing=3.0)
    project = client.post("/api/v1/projects", json={"name": "resume import"}).json()
    real_ingest = api_module.ingest_cloud

    def cancel_after_checkpoint(project_id, cloud_id, source_path, progress):
        def cancel(value, message):
            if message == "checkpoint ready; finalizing":
                raise JobCancelled("test cancellation after checkpoint")
            progress(value, message)

        return real_ingest(project_id, cloud_id, source_path, progress=cancel)

    monkeypatch.setattr(api_module, "ingest_cloud", cancel_after_checkpoint)
    response = client.post(
        f"/api/v1/projects/{project['id']}/clouds/import-path",
        json={"path": str(source)},
    )
    assert response.status_code == 200, response.text
    cloud = response.json()
    job_id = cloud["import_job_id"]

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        cloud = client.get(f"/api/v1/clouds/{cloud['id']}").json()
        if cloud["status"] == "cancelled":
            break
        time.sleep(0.01)
    assert cloud["status"] == "cancelled"

    monkeypatch.setattr(api_module, "ingest_cloud", real_ingest)
    monkeypatch.setattr(ingest, "read_cloud", lambda *_args, **_kwargs: pytest.fail("source was reread"))
    resumed = client.post(f"/api/v1/clouds/{cloud['id']}/resume")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["import_job_id"] != job_id

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        cloud = client.get(f"/api/v1/clouds/{cloud['id']}").json()
        if cloud["status"] in {"ready", "failed"}:
            break
        time.sleep(0.01)
    assert cloud["status"] == "ready", cloud.get("error")


def test_restart_marks_interrupted_cloud_import_resumable_without_reading_source(client, tmp_path, monkeypatch):
    api_module = importlib.import_module("scan2bim.api.app")
    source = tmp_path / "interrupted-source.xyz"
    source.write_text("not opened during recovery", encoding="utf-8")
    project = client.post("/api/v1/projects", json={"name": "startup recovery"}).json()
    cloud_id = new_id()
    now = utcnow()
    execute(
        """INSERT INTO clouds
        (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (cloud_id, project["id"], "interrupted", str(source), "xyz", source.stat().st_size, "processing", now, now),
    )
    job_id = create_job("ingest", project["id"], cloud_id, "interrupted")
    update_job(job_id, status="running", message="reading")
    monkeypatch.setattr(ingest, "read_cloud", lambda *_args, **_kwargs: pytest.fail("startup read a source"))

    api_module._mark_interrupted_imports()

    cloud = client.get(f"/api/v1/clouds/{cloud_id}").json()
    assert cloud["status"] == "failed"
    assert "Возобновить" in cloud["error"]
    assert get_job(job_id)["status"] == "failed"


def test_changed_source_cannot_be_silently_imported_under_an_old_checkpoint(client, tmp_path, monkeypatch):
    source = tmp_path / "mutable-source.xyz"
    source.write_text("original source", encoding="utf-8")
    original_stat = source.stat()
    project = client.post("/api/v1/projects", json={"name": "changed checkpoint source"}).json()
    cloud_id = new_id()
    now = utcnow()
    execute(
        """INSERT INTO clouds
        (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (cloud_id, project["id"], "mutable", str(source), "xyz", source.stat().st_size, "processing", now, now),
    )
    xyz = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    monkeypatch.setattr(ingest, "read_cloud", lambda *_args, **_kwargs: RawCloud(xyz))

    def interrupt_after_checkpoint(_value, message):
        if message == "checkpoint ready; finalizing":
            raise JobCancelled("preserve checkpoint")

    with pytest.raises(JobCancelled):
        ingest.ingest_cloud(project["id"], cloud_id, source, progress=interrupt_after_checkpoint)
    checkpoint = cloud_paths(project["id"], cloud_id)["dir"] / ".ingest-stage" / "manifest.json"
    assert checkpoint.exists()
    source.write_text("changed source!", encoding="utf-8")
    import os
    os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    def must_not_reimport(*_args, **_kwargs):
        pytest.fail("changed source was silently read under the existing cloud ID")

    monkeypatch.setattr(ingest, "read_cloud", must_not_reimport)
    with pytest.raises(ValueError, match="content SHA-256 differs"):
        ingest.ingest_cloud(project["id"], cloud_id, source)
    assert checkpoint.exists(), "changed-source checkpoint is retained for diagnosis"


def test_same_size_same_mtime_source_replacement_during_import_is_rejected(client, tmp_path, monkeypatch):
    source = tmp_path / "same-stat-source.xyz"
    source.write_bytes(b"original points!\n")
    original_stat = source.stat()
    project = client.post("/api/v1/projects", json={"name": "source integrity"}).json()
    cloud_id = new_id()
    now = utcnow()
    execute(
        """INSERT INTO clouds
        (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (cloud_id, project["id"], "mutable", str(source), "xyz", original_stat.st_size, "processing", now, now),
    )

    def replace_source_during_read(*_args, **_kwargs):
        source.write_bytes(b"changed points!!\n")
        import os
        os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        return RawCloud(np.array([[1.0, 2.0, 3.0]]))

    monkeypatch.setattr(ingest, "read_cloud", replace_source_during_read)

    with pytest.raises(RuntimeError, match="source content changed"):
        ingest.ingest_cloud(project["id"], cloud_id, source)

    row = one("SELECT status,sha256 FROM clouds WHERE id=?", (cloud_id,))
    assert row["status"] == "processing"
    assert row["sha256"] is None
    assert not cloud_paths(project["id"], cloud_id)["positions"].exists()
