import pytest
from scan2bim.api.app import app

def test_desktop_status(client):
    res = client.get("/api/v1/desktop/status")
    assert res.status_code == 200
    data = res.json()
    assert "platform" in data
    assert "autocad_available" in data
    assert "recap_available" in data
    # On this machine, both AutoCAD 2026 and ReCap are installed
    assert data["autocad_available"] is True
    assert data["recap_available"] is True

def test_open_explorer_not_found(client):
    res = client.post("/api/v1/desktop/open-explorer", json={"path": "C:\\non_existent_folder_12345"})
    assert res.status_code == 404
