import pytest
from pathlib import Path
from scan2bim.api.app import app

def test_desktop_status(client):
    res = client.get("/api/v1/desktop/status")
    assert res.status_code == 200
    data = res.json()
    assert "platform" in data
    assert "autocad_available" in data
    assert "recap_available" in data
    assert "revit_available" in data
    # On this machine, AutoCAD 2026, ReCap and Revit 2027 are installed
    assert data["autocad_available"] is True
    assert data["recap_available"] is True
    assert data["revit_available"] is True

def test_open_explorer_not_found(client):
    res = client.post("/api/v1/desktop/open-explorer", json={"path": "C:\\non_existent_folder_12345"})
    assert res.status_code == 404

def test_compile_dwg_api(client):
    target_dxf = Path("data/output/single_pass_release/spds_album/01_plan_kolonn_SPDS.dxf").resolve()
    if target_dxf.is_file():
        res = client.post("/api/v1/desktop/compile-dwg", json={"path": str(target_dxf)})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert "dwg_path" in data
        assert Path(data["dwg_path"]).is_file()
