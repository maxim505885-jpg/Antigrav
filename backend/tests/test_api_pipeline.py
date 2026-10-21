"""Full route: upload/demo -> preview -> section -> DXF -> recognition -> IFC."""
from __future__ import annotations

import io
from pathlib import Path

import ezdxf
import numpy as np

from conftest import wait_cloud, wait_job
from scan2bim.cad.pdf import structural_schedule_from_dxf


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

    column = next(item for item in elements if item["class_name"] == "column")
    fit_response = client.post(
        f"/api/v1/elements/{column['id']}/section-fit",
        json={"slice_z_m": column["geometry"]["center"][2], "thickness_m": 0.2},
    )
    assert fit_response.status_code == 200, fit_response.text
    fit = fit_response.json()
    assert fit["algorithm"] == {"name": "fit_rectangular_section", "version": "1"}
    assert fit["parameters"]["thickness_m"] == 0.2
    assert fit["parameters"]["distance_tolerance_m"] == 0.004
    assert fit["source_rows"]["kind"] == "derived_cloud_zero_based_row_index"
    assert fit["source_rows"]["count"] == fit["point_count"]
    point_support = fit["point_support"]
    assert point_support["selected_point_count"] == fit["point_count"]
    assert point_support["unique_observed_face_point_count"] <= fit["point_count"]
    assert point_support["unassigned_point_count"] == (
        fit["point_count"] - point_support["unique_observed_face_point_count"]
    )
    if fit["point_count"]:
        assert point_support["observed_face_point_fraction"] == (
            point_support["unique_observed_face_point_count"] / fit["point_count"]
        )
    assert "не покрытие площади поверхности" in point_support["scope"]
    face_support_counts = [face["ingested_point_row_id_count"] for face in fit["observed_faces"]]
    if face_support_counts:
        assert point_support["unique_observed_face_point_count"] >= max(face_support_counts)
        assert point_support["unique_observed_face_point_count"] <= sum(face_support_counts)
    else:
        assert point_support["unique_observed_face_point_count"] == 0
    if fit["observed_faces"]:
        face = fit["observed_faces"][0]
        assert "p95_residual_m" in face
        assert "span_kind" in face
        assert "ingested_point_row_id_sample" in face

    structural_plan = client.get(f"/api/v1/clouds/{cloud['id']}/structural-plan.dxf?type=columns&issue=draft")
    assert structural_plan.status_code == 200, structural_plan.text
    plan_path = Path("data_test_structural_plan.dxf")
    plan_path.write_bytes(structural_plan.content)
    try:
        plan_doc = ezdxf.readfile(plan_path)
    finally:
        plan_path.unlink(missing_ok=True)
    assert len(list(plan_doc.modelspace().query('LWPOLYLINE[layer=="S2B-COLUMNS"]'))) >= 1
    assert any("ПЛАН КОЛОНН" in entity.dxf.text for entity in plan_doc.modelspace().query("TEXT"))
    assert any("ЧЕРНОВИК" in entity.dxf.text for entity in plan_doc.modelspace().query("TEXT"))
    draft_rows = structural_schedule_from_dxf(plan_doc)["rows"]
    expected_column_ids = {element["id"] for element in elements if element["class_name"] == "column"}
    assert {row[1] for row in draft_rows} == expected_column_ids
    assert len({row[1] for row in draft_rows}) == len(draft_rows)
    assert all(row[4] == "КАНДИДАТ" for row in draft_rows)

    default_final = client.get(f"/api/v1/clouds/{cloud['id']}/structural-plan.dxf?type=columns")
    assert default_final.status_code == 200, default_final.text
    final_path = Path("data_test_structural_plan_final.dxf")
    final_path.write_bytes(default_final.content)
    try:
        final_doc = ezdxf.readfile(final_path)
    finally:
        final_path.unlink(missing_ok=True)
    assert not list(final_doc.modelspace().query('LWPOLYLINE[layer=="S2B-COLUMNS"]'))
    assert not structural_schedule_from_dxf(final_doc)["rows"]
    assert any("ФИНАЛЬНЫЙ ВЫПУСК" in entity.dxf.text for entity in final_doc.modelspace().query("TEXT"))

    structural_pdf = client.get(f"/api/v1/clouds/{cloud['id']}/structural-plan.pdf?type=columns")
    assert structural_pdf.status_code == 200, structural_pdf.text
    assert structural_pdf.headers["content-type"].startswith("application/pdf")
    assert structural_pdf.content.startswith(b"%PDF")

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

    reviewed_ids = {element["id"] for element in elements[:5]}
    reviewed_plan = client.get(f"/api/v1/clouds/{cloud['id']}/structural-plan.dxf?type=columns")
    assert reviewed_plan.status_code == 200, reviewed_plan.text
    reviewed_path = Path("data_test_structural_plan_reviewed.dxf")
    reviewed_path.write_bytes(reviewed_plan.content)
    try:
        reviewed_doc = ezdxf.readfile(reviewed_path)
    finally:
        reviewed_path.unlink(missing_ok=True)
    reviewed_schedule = structural_schedule_from_dxf(reviewed_doc)["rows"]
    assert reviewed_schedule
    assert len({row[1] for row in reviewed_schedule}) == len(reviewed_schedule)
    assert all(row[1] in reviewed_ids and row[4] == "ПРОВЕРЕНО" for row in reviewed_schedule)

    history = client.get(f"/api/v1/elements/{elements[0]['id']}/history")
    assert history.status_code == 200, history.text
    assert len(history.json()) == 1
    assert history.json()[0]["action"] == "confirm"
    assert history.json()[0]["after"]["review_status"] == "confirmed"

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
