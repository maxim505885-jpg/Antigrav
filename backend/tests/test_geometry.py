"""Measured geometry must match the known synthetic room within tolerance."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from scan2bim.bim import export_ifc
from scan2bim.cad import export_section_dxf, export_section_pdf
from scan2bim.demo import generate_room_points
from scan2bim.geometry.section import CloudGeometry, extract_section
from scan2bim.recognition import detect_structures


def _geometry(tmp_path: Path, spacing: float = 0.06) -> tuple[CloudGeometry, dict]:
    xyz, _, truth = generate_room_points(spacing=spacing)
    origin = (xyz.min(axis=0) + xyz.max(axis=0)) / 2
    local = (xyz - origin).astype(np.float32)
    path = tmp_path / "positions.npy"
    np.save(path, local)
    return (
        CloudGeometry(
            positions_path=path,
            origin=origin,
            bbox_min=xyz.min(axis=0),
            bbox_max=xyz.max(axis=0),
            count=len(xyz),
        ),
        truth,
    )


def _overall_bbox(section: dict) -> tuple[float, float, float, float]:
    offset = section["frame"]["world_offset"]
    xs: list[float] = []
    ys: list[float] = []
    for poly in section["polygons"]:
        if poly["is_hole"]:
            continue
        for x, y in poly["points"]:
            xs.append(x + offset[0])
            ys.append(y + offset[1])
    return min(xs), min(ys), max(xs), max(ys)


def test_horizontal_section_matches_room(tmp_path: Path):
    geom, truth = _geometry(tmp_path)
    section = extract_section(
        geom,
        kind="horizontal",
        position=1.5,
        thickness=0.2,
        grid_res=0.02,
    )
    assert section["polygons"], section["warnings"]
    minx, miny, maxx, maxy = _overall_bbox(section)
    assert abs((maxx - minx) - truth["width_x"]) < 0.15
    assert abs((maxy - miny) - truth["depth_y"]) < 0.15
    assert section["slab_point_count"] > 1000
    assert any(poly["is_hole"] and poly["area"] > 15 for poly in section["polygons"])
    assert section["measured"] is True


def test_vertical_section_height(tmp_path: Path):
    geom, truth = _geometry(tmp_path)
    section = extract_section(
        geom,
        kind="vertical",
        axis="x",
        position=3.0,
        thickness=0.2,
        grid_res=0.02,
    )
    assert section["polygons"], section["warnings"]
    minx, miny, maxx, maxy = _overall_bbox(section)
    assert abs((maxy - miny) - truth["height_z"]) < 0.15
    assert section["frame"]["u_label"] == "Y"
    assert section["frame"]["v_label"] == "Z"


def test_dxf_is_editable_and_has_dimensions(tmp_path: Path):
    import ezdxf

    geom, _ = _geometry(tmp_path)
    section = extract_section(geom, kind="horizontal", position=1.5, thickness=0.2)
    out = export_section_dxf(section, tmp_path / "plan.dxf", project_name="Test", scale=50)
    assert out.exists() and out.stat().st_size > 2000
    doc = ezdxf.readfile(out)
    msp = doc.modelspace()
    polylines = list(msp.query("LWPOLYLINE"))
    assert len(polylines) >= 2
    assert all(poly.closed for poly in polylines)
    assert len(list(msp.query("DIMENSION"))) >= 2
    assert len(list(msp.query("LINE"))) >= 4
    layers = {layer.dxf.name for layer in doc.layers}
    assert {"S2B-CONTOURS", "S2B-HOLES", "S2B-AXES", "S2B-DIMS"} <= layers
    # Extents of measured polylines must match the room, not an image canvas.
    xs = [p[0] for poly in polylines for p in poly.get_points("xy")]
    ys = [p[1] for poly in polylines for p in poly.get_points("xy")]
    assert abs((max(xs) - min(xs)) - 6.0) < 0.2
    assert abs((max(ys) - min(ys)) - 4.0) < 0.2
    assert "S2B-50" in doc.layouts.names()


def test_pdf_export(tmp_path: Path):
    geom, _ = _geometry(tmp_path)
    section = extract_section(geom, kind="horizontal", position=1.5, thickness=0.2)
    out = export_section_pdf(section, tmp_path / "plan.pdf", project_name="Test")
    assert out.read_bytes()[:4] == b"%PDF"


def test_recognition_classes_and_ifc(tmp_path: Path):
    geom, truth = _geometry(tmp_path, spacing=0.08)
    result = detect_structures(geom)
    assert not any("Ошибка трассировки MEP" in warning for warning in result.warnings)
    walls = [e for e in result.elements if e.class_name == "wall"]
    columns = [e for e in result.elements if e.class_name == "column"]
    slabs = [e for e in result.elements if e.class_name == "slab"]
    assert len(walls) >= 4, [(e.class_name, e.dimensions) for e in result.elements]
    assert len(columns) >= 1
    assert len(slabs) >= 2
    positions = np.load(geom.positions_path)
    for column in columns:
        metadata = column.metadata
        row_ids = metadata.get("source_point_ids")
        assert row_ids, "recognized columns must retain source row IDs"
        assert len(row_ids) <= 512
        assert metadata["source_point_support_count"] >= len(row_ids)
        assert metadata.get("source_point_id_space") == "positions.npy row index"
        rows = positions[np.asarray(row_ids, dtype=np.int64)] + geom.origin
        bbox_min = np.asarray(column.bbox["min"], dtype=np.float64) - 0.05
        bbox_max = np.asarray(column.bbox["max"], dtype=np.float64) + 0.05
        assert np.all((rows >= bbox_min) & (rows <= bbox_max))
    from shapely import contains_xy
    from shapely.geometry import Polygon

    for slab in slabs:
        row_ids = slab.metadata.get("source_point_ids")
        assert row_ids, "recognized slabs must retain source row IDs"
        assert len(row_ids) <= 512
        assert slab.metadata["source_point_support_count"] >= len(row_ids)
        assert slab.metadata.get("source_point_id_space") == "positions.npy row index"
        rows = positions[np.asarray(row_ids, dtype=np.int64)] + geom.origin
        bbox_min = np.asarray(slab.bbox["min"], dtype=np.float64) - 0.05
        bbox_max = np.asarray(slab.bbox["max"], dtype=np.float64) + 0.05
        assert np.all((rows >= bbox_min) & (rows <= bbox_max))
        polygon = Polygon(np.asarray(slab.geometry["polygon"]) - geom.origin[:2])
        assert np.all(contains_xy(polygon, rows[:, 0] - geom.origin[0], rows[:, 1] - geom.origin[1]))
    for wall in walls:
        row_ids = wall.metadata.get("source_point_ids")
        assert row_ids, "recognized walls must retain source row IDs"
        assert len(row_ids) <= 512
        assert wall.metadata["source_point_support_count"] >= len(row_ids)
        rows = positions[np.asarray(row_ids, dtype=np.int64)] + geom.origin
        bbox_min = np.asarray(wall.bbox["min"], dtype=np.float64) - 0.05
        bbox_max = np.asarray(wall.bbox["max"], dtype=np.float64) + 0.05
        assert np.all((rows >= bbox_min) & (rows <= bbox_max))
        center = np.asarray(wall.geometry["center"], dtype=np.float64)
        angle = float(wall.geometry["rotation_z"])
        direction = np.array([np.cos(angle), np.sin(angle)])
        normal = np.array([-direction[1], direction[0]])
        relative = rows[:, :2] - center[:2]
        assert np.all(np.abs(relative @ direction) <= wall.dimensions["length_m"] / 2 + 0.05)
        assert np.all(np.abs(relative @ normal) <= wall.dimensions["thickness_m"] / 2 + 0.05)
    assert len(result.levels) >= 2
    assert abs(result.levels[0]["z"] - 0.0) < 0.1
    assert abs(result.levels[-1]["z"] - truth["height_z"]) < 0.1
    # Longest wall should approximate the 6 m facade.
    longest = max(walls, key=lambda e: e.dimensions["length_m"])
    assert abs(longest.dimensions["length_m"] - 6.0) < 0.35
    assert all(e.metadata["material"] is None for e in result.elements)

    elements = []
    for i, detected in enumerate(result.elements):
        elements.append(
            {
                "id": f"el{i:04d}",
                "class_name": detected.class_name,
                "geometry": detected.geometry,
                "bbox": detected.bbox,
                "confidence": detected.confidence,
                "confidence_kind": "heuristic",
                "measured": detected.measured,
                "inferred": detected.inferred,
                "source": detected.source,
                "review_status": "unreviewed",
                "dimensions": detected.dimensions,
            }
        )
    model = {
        "project": {"id": "p1", "name": "Test"},
        "levels": result.levels,
        "elements": elements,
    }
    ifc_path = export_ifc(model, tmp_path / "model.ifc", project_name="Test")
    import ifcopenshell

    ifc = ifcopenshell.open(ifc_path)
    assert len(ifc.by_type("IfcWall")) == len(walls)
    assert len(ifc.by_type("IfcColumn")) == len(columns)
    assert len(ifc.by_type("IfcSlab")) == len(slabs)
    assert len(ifc.by_type("IfcPropertySet")) == len(elements)
    pset = ifc.by_type("IfcPropertySet")[0]
    names = {prop.Name for prop in pset.HasProperties}
    assert {"Confidence", "Measured", "Inferred", "ReviewStatus"} <= names


def test_column_source_rows_fall_back_to_bbox_when_grid_has_no_component(tmp_path: Path):
    from scan2bim.recognition.geometric import DetectedElement, _attach_architectural_source_rows

    local_points = np.array([
        [1.02, 2.02, 3.5],
        [1.05, 2.03, 4.0],
        [1.08, 2.04, 4.5],
    ], dtype=np.float32)
    path = tmp_path / "positions.npy"
    np.save(path, local_points)
    geom = CloudGeometry(
        positions_path=path,
        origin=np.zeros(3),
        bbox_min=local_points.min(axis=0),
        bbox_max=local_points.max(axis=0),
        count=len(local_points),
    )
    column = DetectedElement(
        class_name="column",
        geometry={"kind": "oriented_box", "center": [1.05, 2.03, 4.0], "rotation_z": 0.0},
        bbox={"min": [1.04, 2.02, 3.0], "max": [1.06, 2.04, 5.0]},
        confidence=0.25,
    )
    grid = {"res": 0.1, "min": [0.0, 0.0, 0.0], "nu": 50, "nv": 50}
    labels = np.zeros((50, 50), dtype=np.int32)

    _attach_architectural_source_rows(geom, grid, labels, [column])

    assert column.metadata["source_point_ids"] == [0, 1, 2]
    assert column.metadata["source_point_support_count"] == 3


def test_size_floor_rejects_scan_filaments(tmp_path: Path):
    """A real site produced 950 'columns' with a 0.03 m^2 median footprint.

    Those were scan-noise filaments, not structures. The size floor must keep a
    0.5 m post and reject a 0.1 m filament, using an occupancy grid built by
    hand so the test states exactly what is being asserted.
    """
    from scan2bim.recognition.geometric import _vertical_elements

    res, nu, nv, nbands = 0.1, 60, 60, 12
    counts = np.zeros((nv, nu), dtype=np.int64)
    band_occ = np.zeros((nbands, nv, nu), dtype=bool)

    def add_block(iy0, iy1, ix0, ix1, nbands_used):
        counts[iy0:iy1, ix0:ix1] += 40
        band_occ[:nbands_used, iy0:iy1, ix0:ix1] = True

    add_block(10, 11, 10, 11, 12)      # 0.1 x 0.1 m filament: noise
    add_block(30, 35, 30, 35, 12)      # 0.5 x 0.5 m post: a real column

    grid = {
        "res": res,
        "nu": nu,
        "nv": nv,
        "nbands": nbands,
        "counts": counts,
        "band_occ": band_occ,
        "min": np.array([0.0, 0.0, 0.0]),
        "total": int(counts.sum()),
        "assumed_band_height": 0.5,
    }
    geom = CloudGeometry(
        positions_path=tmp_path / "unused.npy",
        origin=np.zeros(3),
        bbox_min=np.zeros(3),
        bbox_max=np.array([6.0, 6.0, 6.0]),
        count=int(counts.sum()),
    )
    elements = _vertical_elements(geom, grid)
    columns = [e for e in elements if e.class_name == "column"]
    assert len(columns) == 1, [(e.class_name, e.dimensions) for e in elements]
    kept = columns[0].dimensions
    assert kept["length_m"] >= 0.45 and kept["thickness_m"] >= 0.45
    assert kept["footprint_area_m2"] >= 0.05
