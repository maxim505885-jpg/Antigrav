from pathlib import Path
import json
import ezdxf
import pytest

from scan2bim.cad.spds_full_set import (
    align_elements_to_grid,
    generate_sheet_1_columns_plan,
    generate_sheet_2_crane_plan,
    generate_sheet_3_transverse_section,
    generate_sheet_4_roof_structure,
    generate_full_spds_album,
)


@pytest.fixture
def sample_workshop_elements():
    """Create a minimal set of elements representing the industrial workshop."""
    elements = []
    # 2 rows of 10 columns along 9.81 deg skewed line
    angle_rad = 0.1785 # ~10.23 deg
    import math
    ca, sa = math.cos(angle_rad), math.sin(angle_rad)

    # Bays at step 6.0m, spans at 30.0m
    for bay_i in range(12):
        u = bay_i * 6.0
        for span_j, row_lbl in enumerate(["A", "B", "C"]):
            v = span_j * 30.0
            # Rotate into cloud coordinates
            x = u * ca - v * sa - 20.0
            y = u * sa + v * ca + 40.0
            elements.append({
                "id": f"col_{bay_i}_{span_j}",
                "class_name": "column",
                "geometry": {
                    "kind": "oriented_box",
                    "center": [x, y, 3.5],
                    "sizes": {"length": 0.8, "thickness": 0.5, "height": 9.5},
                    "rotation_z": angle_rad,
                },
                "bbox": {"min": [x - 0.4, y - 0.25, -1.0], "max": [x + 0.4, y + 0.25, 9.5]},
                "dimensions": {"length_m": 0.8, "thickness_m": 0.5, "height_m": 9.5},
            })

    # Add sample crane girders
    for span_j in [0, 1]:
        v = span_j * 30.0 + 0.75
        for bay_i in range(0, 12, 2):
            u = bay_i * 6.0 + 6.0
            x = u * ca - v * sa - 20.0
            y = u * sa + v * ca + 40.0
            elements.append({
                "id": f"beam_{bay_i}_{span_j}",
                "class_name": "beam",
                "geometry": {
                    "kind": "oriented_box",
                    "center": [x, y, 6.2],
                    "sizes": {"length": 12.0, "thickness": 0.3, "height": 0.6},
                    "rotation_z": angle_rad,
                },
                "bbox": {"min": [x - 6.0, y - 0.15, 5.9], "max": [x + 6.0, y + 0.15, 6.5]},
                "dimensions": {"role": "crane_girder", "length_m": 12.0, "height_m": 0.6},
            })

    # Add sample trusses
    for bay_i in range(12):
        u = bay_i * 6.0
        for span_j in [0, 1]:
            v = span_j * 30.0 + 15.0
            x = u * ca - v * sa - 20.0
            y = u * sa + v * ca + 40.0
            elements.append({
                "id": f"truss_{bay_i}_{span_j}",
                "class_name": "truss",
                "geometry": {
                    "kind": "oriented_box",
                    "center": [x, y, 10.7],
                    "sizes": {"length": 30.0, "thickness": 0.4, "height": 2.5},
                    "rotation_z": angle_rad + math.pi / 2,
                },
                "bbox": {"min": [x - 0.2, y - 15.0, 9.5], "max": [x + 0.2, y + 15.0, 12.0]},
                "dimensions": {"span_m": 30.0, "height_m": 2.5, "top_chord_z": 12.0, "bottom_chord_z": 9.5},
            })

    return elements


def test_align_elements_to_grid(sample_workshop_elements):
    aligned_data = align_elements_to_grid(sample_workshop_elements)
    assert "elements" in aligned_data
    assert "x_bays" in aligned_data
    assert "y_spans" in aligned_data
    assert len(aligned_data["x_bays"]) >= 10
    assert len(aligned_data["y_spans"]) == 3
    # Check that Y coordinates of rows are now nearly constant
    y_vals = [el["grid_pos"][1] for el in aligned_data["elements"] if el["class_name"] == "column"]
    # Check 3 distinct rows
    unique_rows = sorted(set(round(y / 5.0) * 5 for y in y_vals))
    assert len(unique_rows) == 3


def test_generate_sheet_1_columns_plan(tmp_path, sample_workshop_elements):
    out_dxf = tmp_path / "sheet_1_columns.dxf"
    out_pdf = tmp_path / "sheet_1_columns.pdf"
    aligned = align_elements_to_grid(sample_workshop_elements)
    res = generate_sheet_1_columns_plan(aligned, out_dxf, out_pdf)
    assert out_dxf.exists()
    assert out_dxf.stat().st_size > 1000
    assert out_pdf.exists()
    assert out_pdf.stat().st_size > 1000

    # Verify DXF contents
    doc = ezdxf.readfile(str(out_dxf))
    assert "SPDS-FRAME" in doc.layers
    assert "SPDS-COLUMNS" in doc.layers
    assert "SPDS-AXES" in doc.layers


def test_generate_sheet_2_crane_plan(tmp_path, sample_workshop_elements):
    out_dxf = tmp_path / "sheet_2_crane.dxf"
    out_pdf = tmp_path / "sheet_2_crane.pdf"
    aligned = align_elements_to_grid(sample_workshop_elements)
    res = generate_sheet_2_crane_plan(aligned, out_dxf, out_pdf)
    assert out_dxf.exists()
    assert out_pdf.exists()


def test_generate_sheet_3_transverse_section(tmp_path, sample_workshop_elements):
    out_dxf = tmp_path / "sheet_3_section.dxf"
    out_pdf = tmp_path / "sheet_3_section.pdf"
    aligned = align_elements_to_grid(sample_workshop_elements)
    res = generate_sheet_3_transverse_section(aligned, out_dxf, out_pdf)
    assert out_dxf.exists()
    assert out_pdf.exists()


def test_generate_sheet_4_roof_structure(tmp_path, sample_workshop_elements):
    out_dxf = tmp_path / "sheet_4_roof.dxf"
    out_pdf = tmp_path / "sheet_4_roof.pdf"
    aligned = align_elements_to_grid(sample_workshop_elements)
    res = generate_sheet_4_roof_structure(aligned, out_dxf, out_pdf)
    assert out_dxf.exists()
    assert out_pdf.exists()


def test_generate_full_spds_album(tmp_path, sample_workshop_elements):
    out_dir = tmp_path / "spds_album"
    album_manifest = generate_full_spds_album(sample_workshop_elements, out_dir)
    assert len(album_manifest["sheets"]) == 4
    for sheet in album_manifest["sheets"]:
        assert Path(sheet["dxf_path"]).exists()
        assert Path(sheet["pdf_path"]).exists()
    assert Path(album_manifest["album_pdf_path"]).exists()
