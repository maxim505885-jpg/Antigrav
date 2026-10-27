import os
import subprocess
import sys
from importlib import import_module
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

api_app = import_module("scan2bim.api.app")
from scan2bim.api.app import app
from scan2bim.server import require_api_key_for_remote_bind


@pytest.mark.parametrize("host", ["127.0.0.1", "127.42.0.7", "::1", "[::1]", "localhost"])
def test_loopback_bind_does_not_require_api_key(host: str):
    require_api_key_for_remote_bind(host, "")


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "::", "scan-host"])
def test_non_loopback_bind_requires_api_key(host: str):
    with pytest.raises(ValueError, match="S2B_API_KEY"):
        require_api_key_for_remote_bind(host, "")


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "::"])
def test_non_loopback_bind_is_allowed_when_api_key_is_configured(host: str):
    require_api_key_for_remote_bind(host, "configured-secret")


def test_whitespace_api_key_does_not_unlock_remote_bind():
    with pytest.raises(ValueError, match="S2B_API_KEY"):
        require_api_key_for_remote_bind("0.0.0.0", "  \t ")


def test_supported_cli_rejects_remote_bind_before_starting_uvicorn():
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.pop("S2B_API_KEY", None)
    result = subprocess.run(
        [sys.executable, str(repo_root / "backend" / "run.py"), "--host", "0.0.0.0", "--port", "0"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert "S2B_API_KEY must be configured" in result.stderr


def test_remote_api_client_is_rejected_when_no_api_key_is_configured(monkeypatch):
    monkeypatch.setattr(api_app, "API_KEY", "")
    with TestClient(app, client=("192.0.2.10", 12345)) as client:
        response = client.get("/api/v1/projects")
    assert response.status_code == 401


def test_loopback_api_client_remains_available_without_api_key(monkeypatch):
    monkeypatch.setattr(api_app, "API_KEY", "")
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        response = client.get("/api/v1/projects")
    assert response.status_code == 200


def test_remote_api_client_can_use_configured_api_key(monkeypatch):
    monkeypatch.setattr(api_app, "API_KEY", "test-secret")
    with TestClient(app, client=("192.0.2.10", 12345)) as client:
        response = client.get("/api/v1/projects", headers={"X-API-Key": "test-secret"})
    assert response.status_code == 200


def test_forwarded_loopback_header_does_not_authorize_remote_client(monkeypatch):
    monkeypatch.setattr(api_app, "API_KEY", "")
    with TestClient(app, client=("192.0.2.10", 12345)) as client:
        response = client.get(
            "/api/v1/projects",
            headers={"X-Forwarded-For": "127.0.0.1"},
        )
    assert response.status_code == 401
