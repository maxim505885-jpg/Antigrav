from pathlib import Path
import re

import ezdxf
import pytest

from scan2bim.cad.dxf import export_structural_plan_dxf
from scan2bim.cad.pdf import export_structural_plan_pdf


_DRAWING_ISSUE_TEST_DIR = Path(__file__).resolve().parents[2] / "data" / "validation" / "drawing-issue-tests"


def _drawing_issue_output(name: str) -> Path:
    _DRAWING_ISSUE_TEST_DIR.mkdir(parents=True, exist_ok=True)
    return _DRAWING_ISSUE_TEST_DIR / name


def test_confirmed_type_marks_keep_each_measured_rectangle_and_dimension_residual(tmp_path):
    elements = []
    for element_id, x, length, thickness, angle in (
        ("physical-a", 0, 0.5, 0.4, 0),
        ("physical-b", 6, 0.502, 0.398, 1.5707963267948966),
    ):
        elements.append({"id": element_id, "class_name": "column", "review_status": "unreviewed",
            "geometry": {"kind": "oriented_box", "center": [x, 0, 3],
                "sizes": {"length": length, "thickness": thickness, "height": 6}, "rotation_z": angle}})
    catalog = [{"id": "type-1", "mark": "К1", "status": "confirmed",
        "member_element_ids": ["physical-a", "physical-b"],
        "prototype": {"representative_sides_m": {"long": 0.5, "short": 0.4}}}]
    out = export_structural_plan_dxf(elements, tmp_path / "types.dxf", "columns", column_types=catalog)
    doc = ezdxf.readfile(out)
    footprints = list(doc.modelspace().query('LWPOLYLINE[layer=="S2B-COLUMNS"]'))
    assert len(footprints) == 2
    assert all(poly.closed and len(poly.get_points("xy")) == 4 for poly in footprints)
    second = list(footprints[1].get_points("xy"))
    assert max(x for x, _ in second) - min(x for x, _ in second) == pytest.approx(0.398)
    assert max(y for _, y in second) - min(y for _, y in second) == pytest.approx(0.502)
    texts = [entity.dxf.text for entity in doc.modelspace().query("TEXT")]
    assert texts.count("К1") >= 2
    assert "К1-2" in texts
    assert "physical-a" in texts and "physical-b" in texts
    assert "502.0 × 398.0" in texts
    assert "+2.0 / -2.0" in texts
    assert "КАНДИДАТ" in texts
    assert "ТИП ПОДТВ." in texts
    assert any("К1: 2 шт." in text for text in texts)
    assert not doc.audit().has_errors
    pdf = export_structural_plan_pdf(elements, tmp_path / "types.pdf", "columns", column_types=catalog)
    assert pdf.read_bytes().startswith(b"%PDF")


def test_proposed_type_is_explicitly_distinguished_from_confirmed_type(tmp_path):
    element = {"id": "candidate-a", "class_name": "column", "geometry": {
        "kind": "oriented_box", "center": [0, 0, 3], "rotation_z": 0,
        "sizes": {"length": 0.5, "thickness": 0.4, "height": 6}}}
    proposal = {"proposal_key": "group-1", "status": "proposed", "member_element_ids": ["candidate-a"],
        "representative_sides_m": {"long": 0.5, "short": 0.4}}
    out = export_structural_plan_dxf([element], tmp_path / "proposal.dxf", "columns", column_types=[proposal])
    texts = [entity.dxf.text for entity in ezdxf.readfile(out).modelspace().query("TEXT")]
    assert "ПРЕДЛОЖЕНИЕ" in texts
    assert "ТИП ПОДТВ." not in texts


def test_empty_column_plan_still_exports_a_valid_sheet(tmp_path):
    out = export_structural_plan_dxf([], tmp_path / "empty.dxf", "columns")
    assert not ezdxf.readfile(out).audit().has_errors


def test_dimension_labels_use_the_same_metre_units_as_model_geometry(tmp_path):
    element = {"id": "unit-test", "class_name": "column", "geometry": {
        "kind": "oriented_box", "center": [0, 0, 3], "rotation_z": 0,
        "sizes": {"length": 0.5, "thickness": 0.4, "height": 6}}}
    out = export_structural_plan_dxf([element], tmp_path / "units.dxf", "columns")
    doc = ezdxf.readfile(out)
    assert doc.header["$INSUNITS"] == 6
    assert doc.dimstyles.get("EZDXF").dxf.dimlfac == 1
    labels = [entity.plain_text() for dimension in doc.modelspace().query("DIMENSION")
        for entity in dimension.virtual_entities() if entity.dxftype() == "MTEXT"]
    assert sorted(float(label) for label in labels) == [0.4, 0.5]


def test_sparse_small_pdf_keeps_fixed_scale_instead_of_fitting_whole_model(tmp_path):
    elements = [{"id": f"sparse-{index}", "class_name": "column", "geometry": {
        "kind": "oriented_box", "center": [index * 70, 0, 3], "rotation_z": 0,
        "sizes": {"length": 0.5, "thickness": 0.4, "height": 6}}} for index in range(2)]
    out = export_structural_plan_pdf(elements, tmp_path / "sparse.pdf", "columns")
    assert len(re.findall(rb"/Type /Page\b", out.read_bytes())) >= 4
    with pytest.raises(ValueError, match="scale"):
        export_structural_plan_pdf(elements, tmp_path / "invalid.pdf", "columns", scale=0)


def test_fragment_does_not_render_a_dimension_with_missing_endpoints(tmp_path):
    from ezdxf import bbox
    from scan2bim.cad.pdf import plan_entity_in_window
    doc = ezdxf.new(setup=True)
    dim = doc.modelspace().add_linear_dim(base=(0, -2), p1=(0, 0), p2=(54.505, 0))
    dim.render()
    entity = dim.dimension
    bound = bbox.extents([entity])
    assert not plan_entity_in_window(entity, bound, (-1, 38, -5, 20))
    assert not plan_entity_in_window(entity, bound, (30, 70, -5, 20))
    assert plan_entity_in_window(entity, bound, (-10, 70, -10, 20))
    # Physical geometry crossing a seam still appears on both fragments.
    line = doc.modelspace().add_line((0, 0), (54.505, 0))
    assert plan_entity_in_window(line, bbox.extents([line]), (-1, 38, -5, 20))


def test_pdf_fragment_shows_its_visible_geometry_extent_when_overall_dimension_is_hidden(tmp_path, monkeypatch):
    from matplotlib.backends.backend_pdf import PdfPages

    saved_pages = []
    savefig = PdfPages.savefig

    def capture_page(pdf, figure, *args, **kwargs):
        saved_pages.append([text.get_text() for text in figure.texts])
        return savefig(pdf, figure, *args, **kwargs)

    monkeypatch.setattr(PdfPages, "savefig", capture_page)
    elements = [{"id": f"column-{index}", "class_name": "column", "geometry": {
        "kind": "oriented_box", "center": [index * 6.0, 0.0, 3.0], "rotation_z": 0,
        "sizes": {"length": 0.5, "thickness": 0.4, "height": 6.0}}}
        for index in range(3)]

    export_structural_plan_pdf(elements, tmp_path / "fragment-extents.pdf", "columns", scale=10)

    fragment_pages = [texts for texts in saved_pages if any(text.startswith("Фрагмент ") for text in texts)]
    extent_labels = [text for texts in fragment_pages for text in texts
        if text.startswith("Охват геометрии в окне")]
    assert fragment_pages
    assert len(extent_labels) == len(fragment_pages)
    assert any("ΔX=" in text and "ΔY=" in text for text in extent_labels)
    assert all("не цепочка осей" in text for text in extent_labels)


@pytest.mark.parametrize("scale", [50, 100, 200, 500])
def test_pdf_fragment_preserves_physical_print_scale(tmp_path, monkeypatch, scale):
    from scan2bim.cad import pdf as pdf_module
    from matplotlib.backends.backend_pdf import PdfPages
    measured_widths_mm = []
    annotation_heights_mm = []
    savefig = PdfPages.savefig
    export_plan = pdf_module._export_paginated_plan

    def inspect_annotations(doc, *args):
        annotation_heights_mm.extend(entity.dxf.height * 1000 / scale
            for entity in doc.modelspace().query('TEXT[layer=="S2B-MARKS"]'))
        annotation_heights_mm.extend(entity.dxf.char_height * 1000 / scale
            for dimension in doc.modelspace().query("DIMENSION")
            for entity in dimension.virtual_entities() if entity.dxftype() == "MTEXT")
        return export_plan(doc, *args)

    def inspect_scale(pdf, figure, *args, **kwargs):
        if any(text.get_text().startswith("Фрагмент") for text in figure.texts):
            figure.canvas.draw()
            transform = figure.axes[0].transData
            a, b = transform.transform((0, 0)), transform.transform((0.5, 0))
            measured_widths_mm.append((b[0] - a[0]) / figure.dpi * 25.4)
        return savefig(pdf, figure, *args, **kwargs)

    monkeypatch.setattr(PdfPages, "savefig", inspect_scale)
    monkeypatch.setattr(pdf_module, "_export_paginated_plan", inspect_annotations)
    element = {"id": "scale-column", "class_name": "column", "geometry": {
        "kind": "oriented_box", "center": [0, 0, 3], "rotation_z": 0,
        "sizes": {"length": 0.5, "thickness": 0.4, "height": 6}}}
    export_structural_plan_pdf([element], tmp_path / f"scale-{scale}.pdf", "columns", scale=scale)
    assert measured_widths_mm == pytest.approx([500 / scale], abs=0.001)
    assert annotation_heights_mm == pytest.approx([2.5, 2.5, 2.5], abs=0.001)


def test_large_pdf_paginates_schedule_without_losing_instance_rows(tmp_path):
    elements = [{"id": f"long-instance-{index:03d}", "class_name": "column", "review_status": "unreviewed",
        "geometry": {"kind": "oriented_box", "center": [index % 10 * 6, index // 10 * 12, 4],
            "rotation_z": 0, "sizes": {"length": 0.5, "thickness": 0.4, "height": 8}}}
        for index in range(36)]
    out = export_structural_plan_pdf(elements, tmp_path / "large.pdf", "columns")
    content = out.read_bytes()
    assert len(re.findall(rb"/Type /Page\b", content)) >= 3
    from scan2bim.cad.pdf import structural_schedule_from_dxf
    dxf = export_structural_plan_dxf(elements, tmp_path / "large.dxf", "columns")
    schedule = structural_schedule_from_dxf(ezdxf.readfile(dxf))
    assert [row[1] for row in schedule["rows"]] == [element["id"] for element in elements]
    assert "Сечение, мм" in schedule["headers"]
    assert len(schedule["widths"]) == len(schedule["headers"])


def test_column_plan_projects_footprints_and_marks_candidates(tmp_path: Path):
    out = export_structural_plan_dxf(
        [
            {
                "id": "column-17",
                "class_name": "column",
                "review_status": "unreviewed",
                "geometry": {
                    "kind": "oriented_box",
                    "center": [6.0, 2.0, 4.0],
                    "sizes": {"length": 0.5, "thickness": 0.4, "height": 8.0},
                    "rotation_z": 0.0,
                },
            },
            {
                "id": "beam-1",
                "class_name": "beam",
                "dimensions": {"role": "floor_beam"},
                "geometry": {"kind": "member", "p0": [0, 0, 0], "p1": [6, 0, 0]},
            },
        ],
        tmp_path / "columns.dxf",
        drawing_type="columns",
        project_name="Workshop",
    )

    doc = ezdxf.readfile(out)
    msp = doc.modelspace()
    footprints = list(msp.query('LWPOLYLINE[layer=="S2B-COLUMNS"]'))
    assert len(footprints) == 1
    points = list(footprints[0].get_points("xy"))
    assert min(x for x, _ in points) == 5.75
    assert max(x for x, _ in points) == 6.25
    texts = [entity.dxf.text for entity in msp.query("TEXT")]
    assert "C-column-17" in texts
    mark_text = next(entity for entity in msp.query("TEXT") if entity.dxf.text == "C-column-17")
    assert mark_text.dxf.insert.y > max(y for _, y in points)
    assert "column-17" in texts
    assert "КАНДИДАТ" in texts
    assert any("ПЛАН КОЛОНН" in text for text in texts)
    title = next(entity for entity in msp.query("TEXT") if "ПЛАН КОЛОНН" in entity.dxf.text)
    assert 5.0 <= title.dxf.insert.x <= 6.0
    assert 2.0 <= title.dxf.insert.y <= 3.0
    assert not any(entity.dxf.layer == "S2B-BEAMS" for entity in msp)
    dimensions = list(msp.query('DIMENSION[layer=="S2B-DIMS"]'))
    assert sorted(round(dimension.get_measurement(), 3) for dimension in dimensions) == [0.4, 0.5]
    frame = list(msp.query('LWPOLYLINE[layer=="S2B-FRAME"]'))[0]
    assert frame.closed
    frame_points = list(frame.get_points("xy"))
    assert min(x for x, _ in frame_points) < 5.75
    assert max(x for x, _ in frame_points) > 6.25


def test_column_plan_uses_short_marks_with_editable_schedule_cross_reference(tmp_path: Path):
    element_id = "0123456789abcdef0123456789abcdef"
    out = export_structural_plan_dxf(
        [{
            "id": element_id,
            "class_name": "column",
            "review_status": "unreviewed",
            "geometry": {
                "kind": "oriented_box",
                "center": [6.0, 2.0, 4.0],
                "sizes": {"length": 0.5, "thickness": 0.4, "height": 8.0},
                "rotation_z": 0.0,
            },
        }],
        tmp_path / "columns-schedule.dxf",
        drawing_type="columns",
    )

    doc = ezdxf.readfile(out)
    texts = [entity.dxf.text for entity in doc.modelspace().query("TEXT")]
    mark_text = next(entity for entity in doc.modelspace().query("TEXT") if entity.dxf.text == "C-01234567")
    assert mark_text.dxf.height >= 0.22
    schedule_title = next(entity for entity in doc.modelspace().query("TEXT") if "ВЕДОМОСТЬ КОЛОНН" in entity.dxf.text)
    assert schedule_title.dxf.height >= 0.28
    assert any(element_id in text for text in texts)
    assert "X, м" in texts
    assert "Y, м" in texts


def test_crane_girder_plan_keeps_only_girder_role_and_review_status(tmp_path: Path):
    out = export_structural_plan_dxf(
        [
            {
                "id": "girder-2",
                "class_name": "beam",
                "review_status": "confirmed",
                "dimensions": {"role": "crane_girder"},
                "geometry": {"kind": "member", "p0": [1, 2, 8], "p1": [7, 2, 8]},
            },
            {
                "id": "beam-3",
                "class_name": "beam",
                "review_status": "unreviewed",
                "dimensions": {"role": "floor_beam"},
                "geometry": {"kind": "member", "p0": [1, 3, 8], "p1": [7, 3, 8]},
            },
        ],
        tmp_path / "runway.dxf",
        drawing_type="crane_girders",
    )

    doc = ezdxf.readfile(out)
    lines = list(doc.modelspace().query('LINE[layer=="S2B-CRANE-GIRDERS"]'))
    assert len(lines) == 1
    assert tuple(lines[0].dxf.start) == (1.0, 2.0, 0.0)
    assert tuple(lines[0].dxf.end) == (7.0, 2.0, 0.0)
    texts = [entity.dxf.text for entity in doc.modelspace().query("TEXT")]
    assert "G-girder-2" in texts
    assert "girder-2" in texts
    assert "ПРОВЕРЕНО" in texts


def test_crane_girder_oriented_box_exports_its_measured_plan_axis(tmp_path: Path):
    out = export_structural_plan_dxf(
        [{
            "id": "girder-box",
            "class_name": "beam",
            "review_status": "unreviewed",
            "dimensions": {"role": "crane_girder"},
            "geometry": {
                "kind": "oriented_box",
                "center": [10.0, 20.0, 8.0],
                "sizes": {"length": 8.0, "thickness": 0.4, "height": 0.5},
                "rotation_z": 1.5707963267948966,
            },
        }],
        tmp_path / "runway-box.dxf",
        drawing_type="crane_girders",
    )

    doc = ezdxf.readfile(out)
    lines = list(doc.modelspace().query('LINE[layer=="S2B-CRANE-GIRDERS"]'))
    assert len(lines) == 1


def test_final_issue_contains_only_confirmed_or_corrected_elements_and_types():
    elements = [
        {"id": "confirmed-col", "class_name": "column", "review_status": "confirmed", "geometry": {
            "kind": "oriented_box", "center": [0, 0, 3], "sizes": {"length": .5, "thickness": .4, "height": 6}}},
        {"id": "corrected-col", "class_name": "column", "review_status": "corrected", "geometry": {
            "kind": "oriented_box", "center": [6, 0, 3], "sizes": {"length": .6, "thickness": .4, "height": 6}}},
        {"id": "pending-col", "class_name": "column", "review_status": "unreviewed", "geometry": {
            "kind": "oriented_box", "center": [12, 0, 3], "sizes": {"length": .5, "thickness": .4, "height": 6}}},
        {"id": "rejected-col", "class_name": "column", "review_status": "rejected", "geometry": {
            "kind": "oriented_box", "center": [18, 0, 3], "sizes": {"length": .5, "thickness": .4, "height": 6}}},
    ]
    types = [
        {"id": "confirmed-type", "mark": "К1", "status": "confirmed", "member_element_ids": ["confirmed-col"],
         "prototype": {"representative_sides_m": {"long": .5, "short": .4}}},
        {"id": "proposal-type", "mark": "ПР-2", "status": "proposed", "member_element_ids": ["corrected-col"],
         "prototype": {"representative_sides_m": {"long": .6, "short": .4}}},
    ]

    out = export_structural_plan_dxf(elements, _drawing_issue_output("final.dxf"), "columns", column_types=types, issue_mode="final")
    doc = ezdxf.readfile(out)
    msp = doc.modelspace()
    assert len(list(msp.query('LWPOLYLINE[layer=="S2B-COLUMNS"]'))) == 2
    texts = [entity.dxf.text for entity in msp.query("TEXT")]
    assert "confirmed-col" in texts and "corrected-col" in texts
    assert "pending-col" not in texts and "rejected-col" not in texts
    assert "К1" in texts and "ПР-2" not in texts
    assert any("ФИНАЛЬНЫЙ ВЫПУСК" in text for text in texts)


def test_draft_issue_carries_a_prominent_warning_and_candidate_rows():
    element = {"id": "pending-col", "class_name": "column", "review_status": "unreviewed", "geometry": {
        "kind": "oriented_box", "center": [0, 0, 3], "sizes": {"length": .5, "thickness": .4, "height": 6}}}

    out = export_structural_plan_dxf([element], _drawing_issue_output("draft.dxf"), "columns", issue_mode="draft")

    texts = [entity.dxf.text for entity in ezdxf.readfile(out).modelspace().query("TEXT")]
    assert "pending-col" in texts and "КАНДИДАТ" in texts
    assert any("ЧЕРНОВИК" in text for text in texts)


def test_final_pdf_keeps_release_stamp_on_the_printed_sheet():
    element = {"id": "checked-col", "class_name": "column", "review_status": "confirmed", "geometry": {
        "kind": "oriented_box", "center": [0, 0, 3], "sizes": {"length": .5, "thickness": .4, "height": 6}}}
    out = export_structural_plan_pdf([element], _drawing_issue_output("final.pdf"), "columns", issue_mode="final")
    assert out.read_bytes().startswith(b"%PDF")
    # The issue label is also present in the source DXF, which feeds the vector PDF renderer.
    dxf = _drawing_issue_output(".s2b_final_stamp_check.dxf")
    try:
        export_structural_plan_dxf([element], dxf, "columns", issue_mode="final")
        labels = [entity.dxf.text for entity in ezdxf.readfile(dxf).modelspace().query("TEXT")]
        assert any("ФИНАЛЬНЫЙ ВЫПУСК" in label for label in labels)
    finally:
        dxf.unlink(missing_ok=True)


def test_invalid_drawing_issue_mode_fails_instead_of_defaulting():
    with pytest.raises(ValueError, match="issue_mode"):
        export_structural_plan_dxf([], _drawing_issue_output("invalid.dxf"), "columns", issue_mode="release")


def test_explicit_drawing_mark_stays_short_while_schedule_keeps_full_id():
    from scan2bim.cad.pdf import structural_schedule_from_dxf

    element = {"id": "candidate-column-001", "drawing_mark": "C-01", "class_name": "column",
        "review_status": "unreviewed", "geometry": {"kind": "oriented_box", "center": [0, 0, 3],
        "sizes": {"length": .5, "thickness": .4, "height": 6}}}
    out = export_structural_plan_dxf([element], _drawing_issue_output("short-mark.dxf"), "columns")
    doc = ezdxf.readfile(out)
    texts = [entity.dxf.text for entity in doc.modelspace().query("TEXT")]
    rows = structural_schedule_from_dxf(doc)["rows"]
    assert "C-01" in texts
    assert "C-column-001" not in texts
    assert rows[0][0] == "C-01" and rows[0][1] == "candidate-column-001"


def test_structural_plan_pdf_is_vector_sheet_with_same_marks_and_schedule(tmp_path: Path):
    out = export_structural_plan_pdf(
        [{
            "id": "0123456789abcdef0123456789abcdef",
            "class_name": "column",
            "review_status": "confirmed",
            "geometry": {
                "kind": "oriented_box",
                "center": [6.0, 2.0, 4.0],
                "sizes": {"length": 0.5, "thickness": 0.4, "height": 8.0},
                "rotation_z": 0.0,
            },
        }],
        tmp_path / "columns.pdf",
        drawing_type="columns",
        project_name="Workshop",
    )

    content = out.read_bytes()
    assert content.startswith(b"%PDF")
    assert len(content) > 2_000
    media_box = re.search(rb"/MediaBox \[ 0 0 ([0-9.]+) ([0-9.]+) \]", content)
    assert media_box is not None
    width, height = (float(value) for value in media_box.groups())
    assert width == pytest.approx(16.54 * 72, abs=1)
    assert height == pytest.approx(11.69 * 72, abs=1)


def test_structural_plan_pdf_uses_short_temporary_dxf_path():
    # Keep the final PDF path below the Windows MAX_PATH boundary while the old
    # hidden UUID-based sibling DXF path would exceed it.
    target_length = 245
    name_length = target_length - len(str(Path.cwd())) - 1 - len(".pdf")
    if not 1 <= name_length <= 240:
        pytest.skip("workspace root cannot create a safe long-name path regression")
    out_path = Path.cwd() / ("p" * name_length + ".pdf")
    try:
        assert len(str(out_path)) < 260
        out = export_structural_plan_pdf(
            [{
                "id": "column-1",
                "class_name": "column",
                "geometry": {
                    "kind": "oriented_box",
                    "center": [0.0, 0.0, 0.0],
                    "sizes": {"length": 0.5, "thickness": 0.4, "height": 8.0},
                    "rotation_z": 0.0,
                },
            }],
            out_path,
            drawing_type="columns",
        )

        assert out == out_path
        assert out_path.read_bytes().startswith(b"%PDF")
    finally:
        out_path.unlink(missing_ok=True)

