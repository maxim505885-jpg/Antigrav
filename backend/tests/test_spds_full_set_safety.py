from scan2bim.cad.spds_full_set import align_elements_to_grid


def test_alignment_does_not_invent_grid_when_no_columns_are_known():
    result = align_elements_to_grid([])

    assert result["elements"] == []
    assert result["x_bays"] == []
    assert result["y_spans"] == []
    assert result["building_length"] is None
    assert result["building_width"] is None
    assert result["grid_status"] == "insufficient_data"


def test_alignment_keeps_single_column_location_without_inventing_building_extent():
    source = [{"id": "c1", "class_name": "column", "geometry": {"center": [12.0, 34.0, 5.0]}}]

    result = align_elements_to_grid(source)

    assert result["x_bays"] == [0.0]
    assert result["y_spans"] == [0.0]
    assert result["building_length"] is None
    assert result["building_width"] is None
    assert result["grid_status"] == "insufficient_data"
    assert source[0]["geometry"]["center"] == [12.0, 34.0, 5.0]


def test_alignment_records_invertible_transform_and_does_not_snap_observed_bays():
    import numpy as np

    source = [
        {"id": f"c{i}", "class_name": "column", "geometry": {"center": point}}
        for i, point in enumerate(([100.0, 200.0, 5.0], [106.2, 201.0, 5.0], [112.0, 202.0, 5.0]))
    ]
    original = [element["geometry"]["center"][:] for element in source]

    result = align_elements_to_grid(source)
    transform = np.asarray(result["source_to_sheet_4x4"], dtype=float)
    inverse = np.linalg.inv(transform)

    assert result["x_bays"][0] == 0.0
    assert any(abs(value / 6.0 - round(value / 6.0)) > 0.01 for value in result["x_bays"][1:])
    for source_point, aligned in zip(original, result["elements"]):
        world = np.asarray([*source_point, 1.0])
        sheet = transform @ world
        roundtrip = inverse @ sheet
        assert np.allclose(sheet[:3], aligned["geometry"]["center"], atol=1e-9)
        assert np.allclose(roundtrip[:3], source_point, atol=1e-9)
    assert [element["geometry"]["center"] for element in source] == original


def test_alignment_accepts_two_dimensional_bbox_without_fabricating_elevation():
    source = [{"id": "c1", "class_name": "column", "bbox": {"min": [2.0, 4.0], "max": [6.0, 8.0]}}]

    result = align_elements_to_grid(source)

    aligned = result["elements"][0]
    assert aligned["grid_pos"] == (0.0, 0.0)
    assert "geometry" not in aligned
    assert result["building_length"] is None
    assert result["grid_status"] == "insufficient_data"


def test_roof_sheet_does_not_fabricate_trusses_when_grid_is_missing(tmp_path):
    import ezdxf

    from scan2bim.cad.spds_full_set import generate_sheet_4_roof_structure

    out = tmp_path / "roof.dxf"
    generate_sheet_4_roof_structure(
        {"elements": [], "x_bays": [], "y_spans": []}, out, tmp_path / "roof.pdf"
    )

    doc = ezdxf.readfile(out)
    assert not [entity for entity in doc.modelspace().query("LINE")
                if entity.dxf.layer == "SPDS-BRACES"]
    assert any("ФЕРМЫ И СВЯЗИ НЕ ПОДТВЕРЖДЕНЫ" in (entity.dxf.text or "")
               for entity in doc.modelspace().query("TEXT"))


def test_deviation_sheet_is_unknown_without_independent_axes_or_tolerance(tmp_path):
    import ezdxf

    from scan2bim.cad.spds_full_set import generate_sheet_5_executive_deviation_scheme

    out = tmp_path / "deviations.dxf"
    generate_sheet_5_executive_deviation_scheme(
        align_elements_to_grid([]), out, tmp_path / "deviations.pdf"
    )
    doc = ezdxf.readfile(out)
    notes = " ".join(entity.dxf.text or "" for entity in doc.modelspace().query("TEXT"))

    assert "НЕ ОЦЕНЕНО" in notes
    assert "допуск не задан" in notes
    assert "в пределах допустимых строительных норм" not in notes
