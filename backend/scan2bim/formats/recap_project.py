"""Experimental XML draft writer. This does NOT produce an Autodesk RCP.

ReCap project schema and indexed support data are proprietary. A real project
requires linked RCS scan data in its support folder; this research draft is not
openable in ReCap.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping
import xml.dom.minidom
import xml.etree.ElementTree as ET
import numpy as np


def generate_recap_project_draft_xml(
    project_name: str,
    scans: list[Mapping[str, Any]],
    unit: str = "meter",
    coordinate_system: str = "Local",
) -> str:
    """Generate authentic Autodesk ReCap .rcp XML structure.
    
    Each scan entry in `scans` must contain:
    - `id`: unique scan identifier (e.g. 'scan_01')
    - `path`: relative or absolute path to .rcs file
    - `matrix_4x4`: 4x4 transformation matrix (numpy array or nested list)
    Optional:
    - `point_count`: integer point count
    - `name`: human readable name
    - `rmse_mm`: registration residual
    """
    root = ET.Element("ReCapProject", attrib={"version": "2.0", "generator": "SCAN AI Point Cloud Studio"})
    
    # Project properties
    props = ET.SubElement(root, "ProjectProperties")
    ET.SubElement(props, "Name").text = project_name
    ET.SubElement(props, "Unit").text = unit
    ET.SubElement(props, "TargetCoordinateSystem").text = coordinate_system
    ET.SubElement(props, "ScanCount").text = str(len(scans))
    
    # Scan group
    group = ET.SubElement(root, "ScanGroup", attrib={"id": "0", "name": "Registered Scans"})
    
    for idx, scan in enumerate(scans):
        scan_id = str(scan.get("id", f"scan_{idx + 1}"))
        scan_name = str(scan.get("name", scan_id))
        scan_path = str(scan.get("path", ""))
        point_count = scan.get("point_count", 0)
        
        # 4x4 matrix
        mat = np.asarray(scan.get("matrix_4x4", np.eye(4)), dtype=np.float64)
        if mat.shape != (4, 4):
            mat = np.eye(4)
        
        scan_elem = ET.SubElement(group, "Scan", attrib={
            "id": scan_id,
            "name": scan_name,
            "path": scan_path,
        })
        
        if point_count:
            ET.SubElement(scan_elem, "PointCount").text = str(int(point_count))
        
        if scan.get("rmse_mm") is not None:
            ET.SubElement(scan_elem, "RegistrationRmseMm").text = f"{float(scan['rmse_mm']):.4f}"
        
        # Formatted 4x4 matrix string in row-major order
        matrix_elem = ET.SubElement(scan_elem, "Matrix")
        lines = []
        for row in mat:
            lines.append(" ".join(f"{v:.10f}" for v in row))
        matrix_elem.text = "\n" + "\n".join(lines) + "\n"
        
        # Origin translation
        t_elem = ET.SubElement(scan_elem, "Translation")
        t_elem.text = f"{mat[0, 3]:.6f} {mat[1, 3]:.6f} {mat[2, 3]:.6f}"
    
    # Pretty-print XML
    raw_xml = ET.tostring(root, encoding="utf-8")
    parsed = xml.dom.minidom.parseString(raw_xml)
    return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")


def export_recap_project_draft_bundle(
    project_dir: Path,
    project_name: str,
    scans: list[Mapping[str, Any]],
    unit: str = "meter",
    coordinate_system: str = "Local",
) -> dict[str, Any]:
    """Generate complete ReCap project folder structure.
    
    Creates:
    - `<project_dir>/<project_name>.rcp`
    - `<project_dir>/<project_name> Support/`
    - `<project_dir>/<project_name> Support/manifest.json`
    """
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    
    rcp_path = project_dir / f"{project_name}.rcp-draft.xml"
    support_dir = project_dir / f"{project_name} Draft Support"
    support_dir.mkdir(parents=True, exist_ok=True)
    
    xml_content = generate_recap_project_draft_xml(
        project_name=project_name,
        scans=scans,
        unit=unit,
        coordinate_system=coordinate_system,
    )
    rcp_path.write_text(xml_content, encoding="utf-8")
    
    # Write JSON metadata into Support directory
    manifest = {
        "generator": "SCAN AI Point Cloud Studio",
        "format": "SCAN research draft; not an Autodesk ReCap project",
        "project_name": project_name,
        "rcp_file": rcp_path.name,
        "scans": [
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "path": str(s.get("path")),
                "point_count": s.get("point_count"),
                "rmse_mm": s.get("rmse_mm"),
                "matrix_4x4": (
                    np.asarray(s.get("matrix_4x4", np.eye(4)), dtype=float).tolist()
                ),
            }
            for s in scans
        ],
    }
    manifest_path = support_dir / "project_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    
    return {
        "status": "draft_only_not_openable_in_recap",
        "rcp_path": str(rcp_path),
        "support_dir": str(support_dir),
        "manifest_path": str(manifest_path),
        "scan_count": len(scans),
    }

export_recap_project_bundle = export_recap_project_draft_bundle
generate_recap_project_xml = generate_recap_project_draft_xml
