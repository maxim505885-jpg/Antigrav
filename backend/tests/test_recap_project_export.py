"""Tests for Autodesk ReCap (.RCP) project generation and export."""
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np

from scan2bim.formats.recap_project import (
    generate_recap_project_draft_xml,
    export_recap_project_draft_bundle,
)


def test_generate_recap_project_draft_xml():
    scans = [
        {
            "id": "scan_01",
            "name": "Station 01",
            "path": "1.rcs",
            "point_count": 297873927,
            "matrix_4x4": np.eye(4),
            "rmse_mm": 0.0,
        },
        {
            "id": "scan_02",
            "name": "Station 02",
            "path": "2.rcs",
            "point_count": 576820490,
            "matrix_4x4": [
                [0.9998, -0.015, 0.005, 12.450],
                [0.015, 0.9998, -0.002, -3.120],
                [-0.005, 0.002, 0.9999, 0.045],
                [0.0, 0.0, 0.0, 1.0],
            ],
            "rmse_mm": 2.14,
        },
    ]

    xml_text = generate_recap_project_draft_xml(
        project_name="Workshop_Test",
        scans=scans,
        unit="meter",
    )

    root = ET.fromstring(xml_text)
    assert root.tag == "ReCapProject"
    assert root.attrib["version"] == "2.0"

    props = root.find("ProjectProperties")
    assert props is not None
    assert props.find("Name").text == "Workshop_Test"
    assert props.find("Unit").text == "meter"
    assert props.find("ScanCount").text == "2"

    group = root.find("ScanGroup")
    assert group is not None
    scan_elements = group.findall("Scan")
    assert len(scan_elements) == 2

    assert scan_elements[0].attrib["id"] == "scan_01"
    assert scan_elements[0].attrib["path"] == "1.rcs"
    assert scan_elements[0].find("PointCount").text == "297873927"

    assert scan_elements[1].attrib["id"] == "scan_02"
    assert scan_elements[1].attrib["path"] == "2.rcs"
    assert scan_elements[1].find("RegistrationRmseMm").text == "2.1400"
    assert "12.450" in scan_elements[1].find("Matrix").text


def test_export_recap_project_draft_bundle(tmp_path: Path):
    scans = [
        {
            "id": "s1",
            "path": "1.rcs",
            "point_count": 1000,
            "matrix_4x4": np.eye(4).tolist(),
        }
    ]

    res = export_recap_project_draft_bundle(
        project_dir=tmp_path,
        project_name="Industrial_Hall",
        scans=scans,
    )

    assert res["status"] == "draft_only_not_openable_in_recap"
    rcp_file = Path(res["rcp_path"])
    support_dir = Path(res["support_dir"])
    manifest = Path(res["manifest_path"])

    assert rcp_file.exists()
    assert rcp_file.name == "Industrial_Hall.rcp-draft.xml"
    assert support_dir.exists()
    assert support_dir.name == "Industrial_Hall Draft Support"
    assert manifest.exists()

    content = rcp_file.read_text(encoding="utf-8")
    assert "<ReCapProject" in content
    assert "Industrial_Hall" in content
