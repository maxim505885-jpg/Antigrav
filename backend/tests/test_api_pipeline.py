"""Full route: upload/demo -> preview -> section -> DXF -> recognition -> IFC."""
from __future__ import annotations

import io
from pathlib import Path

import ezdxf
import numpy as np

from conftest import wait_cloud, wait_job


def _demo_cloud(client) -> tuple[dict, str]:
    response = client.post("/api/v1/demo")
    assert response.status_code == 200, response.text
    data = response.json()
    cloud = wait_cloud(client, data["cloud"]["id"])
    assert cloud["status"] == "ready", cloud
    return cloud, data["project"]["id"]


def test_full_pipeline(client):
    cloud, project_id = _demo_cloud(client)
    assert cloud["point_count"] > 10000
    assert cloud["preview_count"] > 0

    preview = client.get(f"/api/v1/clouds/{cloud['id']}/preview")
    assert preview.status_code == 200
    assert len(preview.content) == cloud["preview_count"] * 15

    section_response = client.post(
        f"/api/v1/clouds/{cloud['id']}/sections",
        json={"kind": "horizontal", "position": 1.5, "thickness": 0.2, "grid_res": 0.02},
    )
    assert section_response.status_code == 200, section_response.text
    section = section_response.json()
    assert section["result"]["polygons"]
    assert section["result"]["frame"]["kind"] == "horizontal"

    dxf_response = client.post(f"/api/v1/sections/{section['id']}/export?format=dxf&scale=50")
    assert dxf_response.status_code == 200
    assert b"SECTION" in dxf_response.content[:200]
    dxf_path = Path("data_test_export.dxf")
    dxf_path.write_bytes(dxf_response.content)
    try:
        doc = ezdxf.readfile(dxf_path)
    finally:
        dxf_path.unlink(missing_ok=True)
    assert len(list(doc.modelspace().query("LWPOLYLINE"))) >= 2
    assert len(list(doc.modelspace().query("DIMENSION"))) >= 2

    json_response = client.post(f"/api/v1/sections/{section['id']}/export?format=json")
    assert json_response.status_code == 200
    assert json_response.json()["frame"]["position_world"] == section["result"]["frame"]["position_world"]

    dwg_response = client.post(f"/api/v1/sections/{section['id']}/export?format=dwg")
    assert dwg_response.status_code == 409
    assert "Autodesk" in dwg_response.json()["detail"]["summary"]

    recognition = client.post(f"/api/v1/clouds/{cloud['id']}/recognize")
    assert recognition.status_code == 200
    job = wait_job(client, recognition.json()["id"])
    assert job["status"] == "succeeded", job.get("error")
    elements = client.get(f"/api/v1/clouds/{cloud['id']}/elements").json()
    classes = {item["class_name"] for item in elements}
    assert {"wall", "column", "slab"} <= classes
    assert len([e for e in elements if e["class_name"] == "wall"]) >= 4

    levels = client.get(f"/api/v1/clouds/{cloud['id']}/levels").json()
    assert len(levels) >= 2

    # Engineer confirms five elements -> labelled samples.
    for element in elements[:5]:
        response = client.post(
            f"/api/v1/elements/{element['id']}/feedback",
            json={"action": "confirm", "engineer": "test", "note": "checked"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["element"]["review_status"] == "confirmed"

    samples = client.get(f"/api/v1/projects/{project_id}/samples").json()
    assert len(samples) >= 5
    assert all(sample["features"] for sample in samples)

    train = client.post(
        f"/api/v1/projects/{project_id}/train",
        json={"name": "test-knn", "test_fraction": 0.3, "min_test_samples": 6, "min_macro_f1": 0.6},
    )
    assert train.status_code == 200, train.text
    model = train.json()
    assert model["status"] == "candidate"
    assert model["metrics"]["eligible_for_activation"] is False
    activation = client.post(f"/api/v1/models/{model['id']}/activate")
    assert activation.status_code == 409

    ifc_response = client.get(f"/api/v1/clouds/{cloud['id']}/bim?format=ifc")
    assert ifc_response.status_code == 200, ifc_response.text
    assert ifc_response.content[:7] == b"ISO-103"

    import ifcopenshell

    ifc_path = Path("data_test_export.ifc")
    ifc_path.write_bytes(ifc_response.content)
    try:
        ifc = ifcopenshell.open(ifc_path)
    finally:
        ifc_path.unlink(missing_ok=True)
    assert len(ifc.by_type("IfcWall")) >= 1
    assert len(ifc.by_type("IfcPropertySet")) >= 1

    clouds = client.get(f"/api/v1/projects/{project_id}/clouds").json()
    assert clouds and clouds[0]["id"] == cloud["id"]


def test_upload_and_rcs_guidance(client, tmp_path: Path):
    project = client.post("/api/v1/projects", json={"name": "Upload test"}).json()
    xyz = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
    payload = "\n".join(" ".join(f"{v:.3f}" for v in row) for row in xyz) + "\n"
    response = client.post(
        f"/api/v1/projects/{project['id']}/clouds/upload",
        files={"file": ("tiny.xyz", payload.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 200, response.text
    cloud = wait_cloud(client, response.json()["id"])
    assert cloud["status"] == "ready"
    assert cloud["point_count"] == 4

    # Guidance must always be available and must be honest about the format.
    guidance = client.get("/api/v1/formats/rcs").json()
    assert "steps" in guidance
    assert "proprietary" in guidance["summary"].lower()

    from scan2bim.formats.rcs_native import native_available

    rcs = tmp_path / "scan.rcs"
    rcs.write_bytes(b"ADOCT" + b"\x00" * 128)
    response = client.post(
        f"/api/v1/projects/{project['id']}/clouds/import-path",
        json={"path": str(rcs)},
    )
    if native_available()["dll_exists"]:
        # The import is accepted (the local ReCap DLL exists) but a fake
        # ADOCT file must FAIL INGEST with a real error, never a silent
        # success or an invented point cloud.
        assert response.status_code == 200, response.text
        cloud = wait_cloud(client, response.json()["id"])
        assert cloud["status"] == "failed"
        assert cloud.get("error"), "failed ingest must carry an error message"
    else:
        # No local ReCap: the documented conversion path must be enforced.
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "steps" in detail
        assert (
            "not" in detail["summary"].lower()
            or "proprietary" in detail["summary"].lower()
        )
