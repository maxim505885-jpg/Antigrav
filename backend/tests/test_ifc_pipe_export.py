import pytest
from pathlib import Path
import ifcopenshell

from scan2bim.bim.ifc import export_ifc


def test_export_ifc_pipe_segment(tmp_path):
    model = {
        "project": {"name": "MEP IFC Test"},
        "levels": [{"name": "Этаж 1", "elevation": 0.0}],
        "elements": [
            {
                "id": "pipe-001-element",
                "class_name": "pipe",
                "confidence": 0.92,
                "measured": True,
                "inferred": False,
                "review_status": "unreviewed",
                "geometry": {
                    "start_point": [0.0, 0.0, 3.0],
                    "end_point": [10.0, 0.0, 3.0],
                    "radius_m": 0.1,
                    "diameter_mm": 200.0,
                    "length_m": 10.0,
                },
                "bbox": {"min": [-0.1, -0.1, 2.9], "max": [10.1, 0.1, 3.1]},
                "dimensions": {"diameter_mm": 200.0, "length_m": 10.0},
                "metadata": {"system_type": "Piping"},
            }
        ]
    }

    out_file = tmp_path / "test_mep.ifc"
    res = export_ifc(model, out_file)
    assert res.exists()

    ifc = ifcopenshell.open(str(res))
    pipes = ifc.by_type("IfcPipeSegment")
    assert len(pipes) == 1
    pipe = pipes[0]
    assert "Pipe pipe-001" in pipe.Name
    assert pipe.PredefinedType == "RIGIDSEGMENT"

    # Verify Pset_ScanToBIM exists
    psets = [rel.RelatingPropertyDefinition for rel in pipe.IsDefinedBy if hasattr(rel, "RelatingPropertyDefinition")]
    pset_names = [p.Name for p in psets if p.is_a("IfcPropertySet")]
    assert "Pset_ScanToBIM" in pset_names
