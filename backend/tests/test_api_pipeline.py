"""Full route: upload/demo -> preview -> section -> DXF -> recognition -> IFC."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile

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


def _read_dxf(content: bytes):
    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as handle:
        path = Path(handle.name)
        handle.write(content)
    try:
        return ezdxf.readfile(path)
    finally:
        path.unlink(missing_ok=True)


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
    doc = _read_dxf(dxf_response.content)
    assert len(list(doc.modelspace().query("LWPOLYLINE"))) >= 2
    assert len(list(doc.modelspace().query("DIMENSION"))) >= 2

    json_response = client.post(f"/api/v1/sections/{section['id']}/export?format=json")
    assert json_response.status_code == 200
    assert json_response.json()["frame"]["position_world"] == section["result"]["frame"]["position_world"]

    from scan2bim.cad.dwg_compiler import find_accoreconsole, find_oda_converter

    dwg_response = client.post(f"/api/v1/sections/{section['id']}/export?format=dwg")
    if find_oda_converter() or find_accoreconsole():
        # A licensed converter is installed: DWG must be a real binary DWG.
        assert dwg_response.status_code == 200, dwg_response.text
        assert dwg_response.content[:4] == b"AC10"
    else:
        assert dwg_response.status_code == 409
        assert "конвертер" in dwg_response.json()["detail"]["summary"]

    recognition = client.post(f"/api/v1/clouds/{cloud['id']}/recognize")
    assert recognition.status_code == 200
    job = wait_job(client, recognition.json()["id"])
    assert job["status"] == "succeeded", job.get("error")
    elements = client.get(f"/api/v1/clouds/{cloud['id']}/elements").json()
    classes = {item["class_name"] for item in elements}
    assert {"wall", "column", "slab"} <= classes
    assert len([e for e in elements if e["class_name"] == "wall"]) >= 4

    bim_json = client.get(f"/api/v1/clouds/{cloud['id']}/bim?format=json")
    assert bim_json.status_code == 200, bim_json.text
    exchange = bim_json.json()
    assert exchange["units"] == "m"
    assert exchange["coordinate_frame"]["id"] == "source_cloud_world"
    source_element = next(item for item in elements if item["metadata"])
    exchanged_element = next(item for item in exchange["elements"] if item["id"] == source_element["id"])
    assert exchanged_element["metadata"] == source_element["metadata"]

    elements_dxf = client.get(f"/api/v1/clouds/{cloud['id']}/elements.dxf")
    assert elements_dxf.status_code == 200, elements_dxf.text
    elements_doc = _read_dxf(elements_dxf.content)
    dxf_provenance = []
    for entity in elements_doc.modelspace():
        if not entity.has_extension_dict:
            continue
        extension = entity.get_extension_dict()
        if "SCAN_PROVENANCE_V1" not in extension:
            continue
        chunks = [tag.value for tag in extension["SCAN_PROVENANCE_V1"].tags if tag.code == 1]
        assert chunks[0] == "scan2bim.dxf-provenance/1"
        dxf_provenance.append(json.loads("".join(chunks[1:])))
    dxf_element = next(item for item in dxf_provenance if item["id"] == source_element["id"])
    assert dxf_element["class_name"] == exchanged_element["class_name"]
    assert dxf_element["role"] == source_element["dimensions"].get("role", "")
    assert dxf_element["geometry"] == exchanged_element["geometry"]
    assert dxf_element["confidence"] == source_element["confidence"]
    assert dxf_element["measured"] == source_element["measured"]
    assert dxf_element["inferred"] == source_element["inferred"]
    assert dxf_element["review_status"] == source_element["review_status"]
    assert dxf_element["metadata"] == exchanged_element["metadata"]
    assert elements_doc.header["$INSUNITS"] == 6

    ifc_response = client.get(f"/api/v1/clouds/{cloud['id']}/bim?format=ifc")
    assert ifc_response.status_code == 200, ifc_response.text
    assert ifc_response.content[:7] == b"ISO-103"

    import ifcopenshell
    from ifcopenshell.util.element import get_psets

    ifc = ifcopenshell.file.from_string(ifc_response.content.decode("utf-8"))
    assert len(ifc.by_type("IfcWall")) >= 1
    assert len(ifc.by_type("IfcPropertySet")) >= 1
    ifc_provenance = next(
        get_psets(product)["Pset_ScanToBIM"]
        for product in ifc.by_type("IfcProduct")
        if "Pset_ScanToBIM" in get_psets(product)
        and get_psets(product)["Pset_ScanToBIM"]["ElementId"] == source_element["id"]
    )
    assert ifc_provenance["ClassName"] == exchanged_element["class_name"]
    assert ifc_provenance["Role"] == source_element["dimensions"].get("role", "")
    assert json.loads(ifc_provenance["GeometryJSON"]) == exchanged_element["geometry"]
    assert json.loads(ifc_provenance["DimensionsJSON"]) == source_element["dimensions"]
    assert ifc_provenance["Confidence"] == source_element["confidence"]
    assert ifc_provenance["Measured"] == source_element["measured"]
    assert ifc_provenance["Inferred"] == source_element["inferred"]
    assert ifc_provenance["ReviewStatus"] == source_element["review_status"]
    assert json.loads(ifc_provenance["MetadataJSON"]) == exchanged_element["metadata"]
    project_units = ifc.by_type("IfcProject")[0].UnitsInContext.Units
    length_units = [unit for unit in project_units if unit.UnitType == "LENGTHUNIT"]
    assert [(unit.Name, unit.Prefix) for unit in length_units] == [("METRE", None)]

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
    plan_doc = _read_dxf(structural_plan.content)
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
    final_doc = _read_dxf(default_final.content)
    assert not list(final_doc.modelspace().query('LWPOLYLINE[layer=="S2B-COLUMNS"]'))
    assert not structural_schedule_from_dxf(final_doc)["rows"]
    assert any("ФИНАЛЬНЫЙ ВЫПУСК" in entity.dxf.text for entity in final_doc.modelspace().query("TEXT"))

    structural_pdf = client.get(f"/api/v1/clouds/{cloud['id']}/structural-plan.pdf?type=columns")
    assert structural_pdf.status_code == 200, structural_pdf.text
    assert structural_pdf.headers["content-type"].startswith("application/pdf")
    assert structural_pdf.content.startswith(b"%PDF")

    levels = client.get(f"/api/v1/clouds/{cloud['id']}/levels").json()
    assert len(levels) >= 2

    # Only explicitly reviewed, non-inferred geometry can seed the learning set.
    reviewable_for_learning = [element for element in elements if not element["inferred"]][:5]
    assert len(reviewable_for_learning) >= 4
    for element in reviewable_for_learning:
        response = client.post(
            f"/api/v1/elements/{element['id']}/feedback",
            json={"action": "confirm", "engineer": "test", "note": "checked"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["element"]["review_status"] == "confirmed"

    reviewed_ids = {element["id"] for element in reviewable_for_learning}
    reviewed_plan = client.get(f"/api/v1/clouds/{cloud['id']}/structural-plan.dxf?type=columns")
    assert reviewed_plan.status_code == 200, reviewed_plan.text
    reviewed_doc = _read_dxf(reviewed_plan.content)
    reviewed_schedule = structural_schedule_from_dxf(reviewed_doc)["rows"]
    assert reviewed_schedule
    assert len({row[1] for row in reviewed_schedule}) == len(reviewed_schedule)
    assert all(row[1] in reviewed_ids and row[4] == "ПРОВЕРЕНО" for row in reviewed_schedule)

    history = client.get(f"/api/v1/elements/{reviewable_for_learning[0]['id']}/history")
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

    clouds = client.get(f"/api/v1/projects/{project_id}/clouds").json()
    assert clouds and clouds[0]["id"] == cloud["id"]


def test_upload_and_rcs_guidance(client, request):
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

    rcs = Path(tempfile.gettempdir()) / f"scan2bim-test-{id(client)}.rcs"
    rcs.write_bytes(b"ADOCT" + b"\x00" * 128)
    request.addfinalizer(lambda: rcs.unlink(missing_ok=True))
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
