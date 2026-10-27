"""Test environment: isolated data directory and shared API client."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Ensure OpenBLAS and OpenMP use bounded threads on Windows to prevent memory exhaustion
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
if not os.environ.get("S2B_DATA_DIR"):
    os.environ["S2B_DATA_DIR"] = tempfile.mkdtemp(prefix="s2b_test_")

import pytest  # noqa: E402
import fastapi.testclient as fastapi_testclient  # noqa: E402

_TestClient = fastapi_testclient.TestClient


class LoopbackTestClient(_TestClient):
    """Model the desktop app's normal loopback client in API tests."""

    def __init__(self, *args, client=("127.0.0.1", 8000), **kwargs):
        super().__init__(*args, client=client, **kwargs)


fastapi_testclient.TestClient = LoopbackTestClient
TestClient = LoopbackTestClient

from scan2bim.api.app import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


def wait_job(client: TestClient, job_id: str, timeout: float = 120.0) -> dict:
    import time

    start = time.time()
    while time.time() - start < timeout:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in {"succeeded", "failed"}:
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish")


def wait_cloud(client: TestClient, cloud_id: str, timeout: float = 120.0) -> dict:
    import time

    start = time.time()
    while time.time() - start < timeout:
        cloud = client.get(f"/api/v1/clouds/{cloud_id}").json()
        if cloud["status"] in {"ready", "failed"}:
            return cloud
        time.sleep(0.2)
    raise AssertionError(f"cloud {cloud_id} did not finish")
