from pathlib import Path

import ezdxf

from scan2bim.cad.dxf import export_elements_dxf


def test_oriented_box_uses_center_as_geometric_center(tmp_path: Path):
    out = export_elements_dxf([{
        "id": "beam-1",
        "class_name": "beam",
        "geometry": {
            "kind": "oriented_box",
            "center": [10.0, 20.0, 8.0],
            "sizes": {"length": 6.0, "thickness": 0.4, "height": 2.0},
        },
    }], tmp_path / "centered-beam.dxf")

    doc = ezdxf.readfile(out)
    vertices = [vertex.dxf.location for polyline in doc.modelspace().query("POLYLINE") for vertex in polyline.vertices]
    z_values = [point.z for point in vertices]
    assert z_values
    assert min(z_values) == 7.0
    assert max(z_values) == 9.0


def test_brace_member_exports_world_centerline_on_brace_layer(tmp_path: Path):
    out = export_elements_dxf([{
        "id": "brace-1",
        "class_name": "brace",
        "geometry": {"kind": "member", "p0": [-1.0, 2.0, 3.0], "p1": [4.0, 6.0, 8.0], "section_m": 0.12},
    }], tmp_path / "brace.dxf")

    doc = ezdxf.readfile(out)
    lines = [line for line in doc.modelspace().query("LINE") if line.dxf.layer == "S2B-BRACES"]
    assert len(lines) == 1
    assert tuple(lines[0].dxf.start) == (-1.0, 2.0, 3.0)
    assert tuple(lines[0].dxf.end) == (4.0, 6.0, 8.0)
