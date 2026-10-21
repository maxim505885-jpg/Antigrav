from __future__ import annotations

import threading
import time
from pathlib import Path

from scan2bim.jobs import create_job, get_job, request_cancel, submit
from scan2bim.demo import write_room_ply


def test_cancelling_running_job_stops_it_without_reporting_failure(client):
    del client  # initialize the isolated test database before inserting a job
    job_id = create_job("test", message="test cancellation")
    started = threading.Event()

    def work(progress):
        started.set()
        while True:
            progress(0.25, "reading chunk")
            time.sleep(0.005)

    submit(job_id, work)
    assert started.wait(2), "job worker did not start"
    assert request_cancel(job_id) is True

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = get_job(job_id)
        if job and job["status"] in {"cancelled", "failed", "succeeded"}:
            break
        time.sleep(0.005)

    job = get_job(job_id)
    assert job["status"] == "cancelled"
    assert job["error"] is None
    assert request_cancel(job_id) is False


def test_cancel_endpoint_requests_cancellation_for_running_job(client):
    job_id = create_job("test", message="API cancellation")
    started = threading.Event()

    def work(progress):
        started.set()
        while True:
            time.sleep(0.005)
            progress(0.25, "reading chunk")

    submit(job_id, work)
    assert started.wait(2), "job worker did not start"
    response = client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert response.status_code == 200, response.text
    assert response.json()["cancel_requested"] is True

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = get_job(job_id)
        if job and job["status"] == "cancelled":
            break
        time.sleep(0.005)
    assert get_job(job_id)["status"] == "cancelled"


def test_cloud_import_response_exposes_its_cancellable_job(client, tmp_path):
    source = Path(tmp_path) / "tiny-room.ply"
    write_room_ply(source, spacing=3.0)
    project_response = client.post("/api/v1/projects", json={"name": "import cancellation"})
    assert project_response.status_code == 200, project_response.text
    project_id = project_response.json()["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/clouds/import-path",
        json={"path": str(source)},
    )
    assert response.status_code == 200, response.text
    cloud = response.json()
    assert cloud["import_job_id"]
    job = client.get(f"/api/v1/jobs/{cloud['import_job_id']}").json()
    assert job["cloud_id"] == cloud["id"]
    assert job["type"] == "ingest"
