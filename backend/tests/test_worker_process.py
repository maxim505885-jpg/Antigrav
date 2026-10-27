from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scan2bim.config import DATA_DIR
from scan2bim.db import execute, one
from scan2bim.demo import write_room_ply
from scan2bim.jobs import claim_next_ingest_job, create_job, request_cancel, submit_ingest_task


def _worker_input_path(name: str) -> Path:
    path = DATA_DIR / "worker-test-inputs"
    path.mkdir(parents=True, exist_ok=True)
    return path / name


def test_external_worker_imports_cloud_in_a_separate_process(client, monkeypatch):
    monkeypatch.setenv("S2B_INGEST_MODE", "worker")
    source = _worker_input_path("external-worker-room.ply")
    write_room_ply(source, spacing=3.0)
    project = client.post("/api/v1/projects", json={"name": "external worker test"}).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/clouds/import-path",
        json={"path": str(source)},
    )
    assert response.status_code == 200, response.text
    cloud = response.json()
    job_id = cloud["import_job_id"]

    queued = one("SELECT status, task_payload_json FROM jobs WHERE id = ?", (job_id,))
    assert queued["status"] == "queued"
    assert json.loads(queued["task_payload_json"])["payload"]["cloud_id"] == cloud["id"]

    backend_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["S2B_INGEST_MODE"] = "worker"
    env["PYTHONPATH"] = str(backend_root) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "scan2bim.worker", "--once"],
        cwd=backend_root.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    job = client.get(f"/api/v1/jobs/{job_id}").json()
    updated_cloud = client.get(f"/api/v1/clouds/{cloud['id']}").json()
    assert job["status"] == "succeeded", job
    assert updated_cloud["status"] == "ready", updated_cloud
    assert updated_cloud["ingested_count"] == updated_cloud["point_count"]


def test_external_worker_runs_recognition_cleanup_and_export_in_a_separate_process(client, monkeypatch):
    monkeypatch.setenv("S2B_INGEST_MODE", "worker")
    source = _worker_input_path("external-worker-processing-room.ply")
    write_room_ply(source, spacing=3.0)
    project = client.post("/api/v1/projects", json={"name": "external worker processing"}).json()
    imported = client.post(
        f"/api/v1/projects/{project['id']}/clouds/import-path",
        json={"path": str(source)},
    )
    assert imported.status_code == 200, imported.text
    cloud = imported.json()
    backend_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["S2B_INGEST_MODE"] = "worker"
    env["PYTHONPATH"] = str(backend_root) + os.pathsep + env.get("PYTHONPATH", "")

    def run_worker_once():
        result = subprocess.run(
            [sys.executable, "-m", "scan2bim.worker", "--once"],
            cwd=backend_root.parent,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr or result.stdout

    run_worker_once()
    assert client.get(f"/api/v1/clouds/{cloud['id']}").json()["status"] == "ready"

    recognition_response = client.post(f"/api/v1/clouds/{cloud['id']}/recognize")
    assert recognition_response.status_code == 200, recognition_response.text
    recognition_job_id = recognition_response.json()["id"]
    recognition_task = json.loads(one(
        "SELECT task_payload_json FROM jobs WHERE id = ?", (recognition_job_id,)
    )["task_payload_json"])
    assert recognition_task["task_type"] == "recognition"
    run_worker_once()
    recognition_job = client.get(f"/api/v1/jobs/{recognition_job_id}").json()
    assert recognition_job["status"] == "succeeded", recognition_job

    cleanup_response = client.post(
        f"/api/v1/clouds/{cloud['id']}/cleanup",
        json={"method": "voxel", "voxel_m": 0.5, "voxel_mode": "centroid"},
    )
    assert cleanup_response.status_code == 200, cleanup_response.text
    cleanup_job_id = cleanup_response.json()["id"]
    cleanup_task = json.loads(one(
        "SELECT task_payload_json FROM jobs WHERE id = ?", (cleanup_job_id,)
    )["task_payload_json"])
    assert cleanup_task["task_type"] == "cleanup"
    run_worker_once()
    cleanup_job = client.get(f"/api/v1/jobs/{cleanup_job_id}").json()
    assert cleanup_job["status"] == "succeeded", cleanup_job
    derived_id = cleanup_job["result"]["derived_id"]
    derived = client.get(f"/api/v1/clouds/{cloud['id']}/derived").json()
    assert any(item["derived_id"] == derived_id for item in derived)

    export_response = client.post(
        f"/api/v1/clouds/{cloud['id']}/export",
        json={"format": "ply", "derived_id": derived_id, "verify": True},
    )
    assert export_response.status_code == 200, export_response.text
    export_job_id = export_response.json()["id"]
    export_task = json.loads(one(
        "SELECT task_payload_json FROM jobs WHERE id = ?", (export_job_id,)
    )["task_payload_json"])
    assert export_task["task_type"] == "cloud_export"
    run_worker_once()
    export_job = client.get(f"/api/v1/jobs/{export_job_id}").json()
    assert export_job["status"] == "succeeded", export_job
    exported = client.get(f"/api/v1/clouds/{cloud['id']}/exports").json()
    assert any(item["export_id"] == export_job["result"]["export_id"] for item in exported)


def test_api_startup_recovery_preserves_imports_owned_by_external_worker(client, monkeypatch):
    monkeypatch.setenv("S2B_INGEST_MODE", "worker")
    source = _worker_input_path("startup-recovery-room.ply")
    write_room_ply(source, spacing=3.0)
    project = client.post("/api/v1/projects", json={"name": "worker startup recovery"}).json()
    response = client.post(
        f"/api/v1/projects/{project['id']}/clouds/import-path",
        json={"path": str(source)},
    )
    assert response.status_code == 200, response.text
    cloud = response.json()

    from scan2bim.api.app import _mark_interrupted_imports, _mark_interrupted_jobs

    _mark_interrupted_imports()
    _mark_interrupted_jobs()

    assert one("SELECT status FROM clouds WHERE id = ?", (cloud["id"],))["status"] == "processing"
    assert one(
        "SELECT status FROM jobs WHERE id = ?", (cloud["import_job_id"],)
    )["status"] == "queued"
    execute("UPDATE jobs SET status = 'cancelled', message = 'test cleanup' WHERE id = ?", (cloud["import_job_id"],))
    execute("UPDATE clouds SET status = 'cancelled' WHERE id = ?", (cloud["id"],))


def test_worker_claim_is_exclusive_and_expired_lease_is_recoverable(monkeypatch):
    monkeypatch.setenv("S2B_INGEST_MODE", "worker")
    job_id = create_job("ingest", message="lease test")
    submit_ingest_task(job_id, "ingest", {"project_id": "p", "cloud_id": "c"})

    first = claim_next_ingest_job("worker-a", lease_seconds=30)
    assert first["id"] == job_id
    assert claim_next_ingest_job("worker-b", lease_seconds=30) is None

    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="seconds")
    execute("UPDATE jobs SET lease_expires_at = ? WHERE id = ?", (expired, job_id))
    reclaimed = claim_next_ingest_job("worker-b", lease_seconds=30)
    assert reclaimed["id"] == job_id
    assert reclaimed["worker_id"] == "worker-b"
    assert reclaimed["attempts"] == 2


def test_simultaneous_workers_cannot_claim_the_same_job(monkeypatch):
    monkeypatch.setenv("S2B_INGEST_MODE", "worker")
    job_id = create_job("ingest", message="simultaneous claim")
    submit_ingest_task(job_id, "ingest", {"project_id": "p", "cloud_id": "c"})
    start = threading.Barrier(3)

    def claim(worker_id: str):
        start.wait(timeout=5)
        return claim_next_ingest_job(worker_id, lease_seconds=30)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(claim, "worker-a"), pool.submit(claim, "worker-b")]
        start.wait(timeout=5)
        claims = [future.result(timeout=10) for future in futures]

    winners = [claim for claim in claims if claim is not None]
    assert len(winners) == 1
    assert winners[0]["id"] == job_id
    assert winners[0]["attempts"] == 1


def test_worker_marks_corrupt_persisted_task_failed_and_releases_lease(monkeypatch):
    monkeypatch.setenv("S2B_INGEST_MODE", "worker")
    job_id = create_job("recognition", message="corrupt payload")
    execute(
        "UPDATE jobs SET task_payload_json = ? WHERE id = ?",
        ("{not-json", job_id),
    )

    from scan2bim.worker import run_once

    assert run_once("worker-corrupt-payload") is True
    job = one(
        "SELECT status, worker_id, lease_expires_at, error FROM jobs WHERE id = ?",
        (job_id,),
    )
    assert job["status"] == "failed"
    assert job["worker_id"] is None
    assert job["lease_expires_at"] is None
    assert "JSONDecodeError" in job["error"]


@pytest.mark.parametrize(
    "payload_json",
    [
        "[]",
        '{"task_type":"recognition"}',
        '{"task_type":"recognition","payload":[]}',
    ],
)
def test_worker_marks_malformed_task_shape_failed_and_releases_lease(monkeypatch, payload_json):
    monkeypatch.setenv("S2B_INGEST_MODE", "worker")
    job_id = create_job("recognition", message="malformed payload shape")
    execute(
        "UPDATE jobs SET task_payload_json = ? WHERE id = ?",
        (payload_json, job_id),
    )

    from scan2bim.worker import run_once

    assert run_once("worker-malformed-payload") is True
    job = one(
        "SELECT status, worker_id, lease_expires_at, error FROM jobs WHERE id = ?",
        (job_id,),
    )
    assert job["status"] == "failed"
    assert job["worker_id"] is None
    assert job["lease_expires_at"] is None
    assert "ValueError" in job["error"]


def test_queued_external_import_can_be_cancelled_without_a_live_worker(monkeypatch):
    monkeypatch.setenv("S2B_INGEST_MODE", "worker")
    job_id = create_job("ingest", message="queued cancellation")
    submit_ingest_task(job_id, "ingest", {"project_id": "p", "cloud_id": "c"})

    assert request_cancel(job_id) is True
    job = one("SELECT status, cancel_requested FROM jobs WHERE id = ?", (job_id,))
    assert job == {"status": "cancelled", "cancel_requested": 1}
    assert claim_next_ingest_job("worker-a") is None


def test_existing_jobs_table_gets_additive_worker_migration(monkeypatch):
    from scan2bim import db as database

    migration_dir = DATA_DIR / "worker-test-migrations"
    migration_dir.mkdir(parents=True, exist_ok=True)
    path = migration_dir / f"legacy-scan-{uuid.uuid4().hex}.sqlite3"
    with sqlite3.connect(path) as con:
        con.execute(
            """CREATE TABLE jobs (
                id TEXT PRIMARY KEY, project_id TEXT, cloud_id TEXT, type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued', progress REAL NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '', result_json TEXT NOT NULL DEFAULT '{}',
                error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )"""
        )
    monkeypatch.setattr(database, "DB_PATH", path)

    database.init_db()

    with sqlite3.connect(path) as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info(jobs)")}
    assert {
        "task_payload_json",
        "worker_id",
        "lease_expires_at",
        "attempts",
        "cancel_requested",
    } <= columns
