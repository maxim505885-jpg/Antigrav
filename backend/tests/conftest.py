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
os.environ.setdefault("S2B_DATA_DIR", tempfile.mkdtemp(prefix="s2b_test_"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

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
