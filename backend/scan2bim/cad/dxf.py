"""Editable DXF export for a measured section.

Output is real CAD geometry (LWPOLYLINE / LINE / TEXT / DIMENSION) on named
layers, not a raster image of the point cloud. Coordinates are written in world
coordinates using the section frame offset.
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf.enums import TextEntityAlignment

LAYERS = {
    "S2B-CONTOURS": (7, 35),
    "S2B-HOLES": (8, 18),
    "S2B-AXES": (1, 13),
    "S2B-DIMS": (3, 13),
    "S2B-TEXT": (7, 18),
    "S2B-LEVELS": (4, 13),
    "S2B-FRAME": (8, 9),
    "S2B-MARKS": (7, 18),
    "S2B-SCHEDULE": (7, 9),
}


def _setup_document() -> ezdxf.document.Drawing:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 6  # metres
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LUNITS"] = 2
    doc.header["$LUPREC"] = 3
    for name, (color, lineweight) in LAYERS.items():
        if name not in doc.layers:
            doc.layers.add(name, color=color, lineweight=lineweight)
    if "S2B-HOLES" in doc.layers:
        doc.layers.get("S2B-HOLES").dxf.linetype = "DASHED"
    dimstyle = doc.dimstyles.get("EZDXF")
    if dimstyle is not None:
        dimstyle.dxf.dimtxt = 0.30
        dimstyle.dxf.dimasz = 0.15
        dimstyle.dxf.dimexe = 0.10
        dimstyle.dxf.dimexo = 0.08
        dimstyle.dxf.dimgap = 0.06
        dimstyle.dxf.dimdec = 3
        dimstyle.dxf.dimlunit = 2
        dimstyle.dxf.dimscale = 1.0
        dimstyle.dxf.dimlfac = 1.0  # model coordinates and displayed dimensions are metres
        dimstyle.dxf.dimtad = 1
        dimstyle.dxf.dimtih = 0
        dimstyle.dxf.dimtoh = 0
    return doc


def _set_element_provenance(entity: Any, element: dict[str, Any]) -> None:
    """Keep exchange identity and review evidence beside editable DXF geometry."""
    payload = {
        "schema": "scan2bim.dxf-provenance/1",
        "id": str(element.get("id", "")),
        "class_name": str(element.get("class_name", "other")),
        "role": (element.get("dimensions") or {}).get("role", ""),
        "units": "m",
        "coordinate_frame": "source_cloud_world",
        "geometry": element.get("geometry") or {},
        "confidence": element.get("confidence"),
        "measured": element.get("measured"),
        "inferred": element.get("inferred"),
        "source": element.get("source", "geometric"),
        "review_status": element.get("review_status", "unreviewed"),
        "dimensions": element.get("dimensions") or {},
        "metadata": element.get("metadata") or {},
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    record = entity.new_extension_dict().add_xrecord("SCAN_PROVENANCE_V1")
    record.extend([(1, "scan2bim.dxf-provenance/1")])
    record.extend((1, serialized[index:index + 240]) for index in range(0, len(serialized), 240))


def _bounds(polygons: list[dict[str, Any]], offset: tuple[float, float]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for poly in polygons:
        if poly.get("is_hole"):
            continue
        for x, y in poly.get("points", []):
            xs.append(x + offset[0])
            ys.append(y + offset[1])
    if not xs:
        return 0.0, 0.0, 1.0, 1.0
    return min(xs), min(ys), max(xs), max(ys)


def _elevation_label(value: float) -> str:
    if abs(value) < 0.0005:
        return "±0.000"
    return f"{value:+.3f}"


def export_section_dxf(
    section: dict[str, Any],
    out_path: str | Path,
    cloud_name: str = "",
    project_name: str = "",
    scale: int = 50,
    draw_scan_points: bool = False,
    max_scan_points: int = 20000,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = _setup_document()
    msp = doc.modelspace()
    frame = section["frame"]
    offset = tuple(frame["world_offset"])
    polygons = section.get("polygons", [])
    minx, miny, maxx, maxy = _bounds(polygons, offset)
    width = max(1e-6, maxx - minx)
    height = max(1e-6, maxy - miny)

    doc.header["$PROJECTNAME"] = project_name or "Intelligent Scan-to-BIM"
    doc.header["$USERI1"] = int(scale)

    # Measured contours.
    for poly in polygons:
        layer = "S2B-HOLES" if poly.get("is_hole") else "S2B-CONTOURS"
        points = [(x + offset[0], y + offset[1]) for x, y in poly.get("points", [])]
        if len(points) < 3:
            continue
        msp.add_lwpolyline(
            points,
            close=True,
            dxfattribs={"layer": layer},
        )

    if draw_scan_points:
        preview = section.get("preview_points", [])[:max_scan_points]
        if preview:
            msp.add_point(
                [(x + offset[0], y + offset[1], 0.0) for x, y in preview],
                dxfattribs={"layer": "S2B-FRAME"},
            )

    # Axes: two horizontal and two vertical construction lines outside the model.
    ext = max(width, height) * 0.08 + 0.5
    if frame["kind"] == "horizontal":
        for x in (minx, maxx):
            msp.add_line(
                (x, miny - ext, 0),
                (x, maxy + ext, 0),
                dxfattribs={"layer": "S2B-AXES", "linetype": "CENTER"},
            )
        for y in (miny, maxy):
            msp.add_line(
                (minx - ext, y, 0),
                (maxx + ext, y, 0),
                dxfattribs={"layer": "S2B-AXES", "linetype": "CENTER"},
            )
        msp.add_circle(
            (minx - ext * 0.8, maxy + ext * 0.8),
            radius=max(0.15, ext * 0.08),
            dxfattribs={"layer": "S2B-AXES"},
        )
        msp.add_text(
            "1",
            height=0.25,
            dxfattribs={"layer": "S2B-TEXT"},
        ).set_placement((minx, miny - ext * 1.4), align=TextEntityAlignment.CENTER)
    else:
        for v in (miny, maxy):
            msp.add_line(
                (minx - ext, v, 0),
                (maxx + ext, v, 0),
                dxfattribs={"layer": "S2B-AXES", "linetype": "CENTER"},
            )
        msp.add_text(
            _elevation_label(frame["position_world"]),
            height=0.25,
            dxfattribs={"layer": "S2B-LEVELS"},
        ).set_placement((minx - ext * 1.6, maxy), align=TextEntityAlignment.MIDDLE_RIGHT)
        msp.add_line(
            (minx - ext * 1.2, miny, 0),
            (minx - ext * 1.2, maxy, 0),
            dxfattribs={"layer": "S2B-LEVELS"},
        )

    # Overall dimensions (editable DIMENSION entities).
    dim_offset = max(0.5, ext)
    try:
        msp.add_linear_dim(
            base=(minx, miny - dim_offset, 0),
            p1=(minx, miny, 0),
            p2=(maxx, miny, 0),
            angle=0,
            dimstyle="EZDXF",
            dxfattribs={"layer": "S2B-DIMS"},
        ).render()
        msp.add_linear_dim(
            base=(maxx + dim_offset, miny, 0),
            p1=(maxx, miny, 0),
            p2=(maxx, maxy, 0),
            angle=90,
            dimstyle="EZDXF",
            dxfattribs={"layer": "S2B-DIMS"},
        ).render()
    except Exception:
        # Dimension rendering must never break a drawing export.
        pass

    # Labels.
    msp.add_text(
        f"{'PLAN' if frame['kind'] == 'horizontal' else 'SECTION'} {frame['position_world']:.3f} m",
        height=0.35,
        dxfattribs={"layer": "S2B-TEXT"},
    ).set_placement((minx, maxy + ext * 0.5), align=TextEntityAlignment.LEFT)
    msp.add_text(
        f"Measured point-cloud section | thickness {frame['thickness']:.3f} m | scale 1:{scale}",
        height=0.18,
        dxfattribs={"layer": "S2B-TEXT"},
    ).set_placement((minx, miny - ext * 2.1), align=TextEntityAlignment.LEFT)

    # A3 sheet with a viewport; the model space stays fully editable.
    layout_name = f"S2B-{scale}"
    try:
        layout = doc.layouts.get(layout_name)
    except KeyError:
        layout = doc.layouts.new(layout_name)
    try:
        layout.page_setup(size=(420, 297), margins=(10, 10, 10, 10), units="mm")
    except Exception:
        layout.dxf.paper_width = 420
        layout.dxf.paper_height = 297
    try:
        layout.add_viewport(
            center=(210, 148),
            size=(380, 240),
            view_center_point=((minx + maxx) / 2, (miny + maxy) / 2),
            view_height=280 / scale,
        )
    except Exception:
        pass
    layout.add_text(
        f"{project_name or 'Intelligent Scan-to-BIM'} — {cloud_name or 'cloud'}",
        dxfattribs={"height": 5, "layer": "S2B-TEXT"},
    ).set_placement((20, 280))
    layout.add_text(
        f"Section at {frame['position_world']:.3f} m   scale 1:{scale}   {date.today().isoformat()}",
        dxfattribs={"height": 3, "layer": "S2B-TEXT"},
    ).set_placement((20, 270))
    layout.add_text(
        "Measured geometry. Orthogonal regularisation applied where reported. "
        "No material or structural function is inferred.",
        dxfattribs={"height": 2.2, "layer": "S2B-TEXT"},
    ).set_placement((20, 18))

    doc.saveas(out_path)
    return out_path


def export_elements_dxf(elements: list[dict[str, Any]], out_path: str | Path, project_name: str = "") -> Path:
    """Export recognised construction elements as editable 3D/2D CAD outlines."""
    out_path = Path(out_path)
    doc = _setup_document()
    msp = doc.modelspace()
    layer_map = {
        "wall": "S2B-WALLS",
        "column": "S2B-COLUMNS",
        "beam": "S2B-BEAMS",
        "slab": "S2B-SLABS",
        "brace": "S2B-BRACES",
        "truss": "S2B-TRUSSES",
    }
    for name, color in (
        ("S2B-WALLS", 7),
        ("S2B-COLUMNS", 2),
        ("S2B-BEAMS", 5),
        ("S2B-SLABS", 4),
        ("S2B-BRACES", 6),
        ("S2B-TRUSSES", 3),
    ):
        if name not in doc.layers:
            doc.layers.add(name, color=color)
    for el in elements:
        layer = layer_map.get(el.get("class_name", ""), "S2B-CONTOURS")
        geom = el.get("geometry", {})
        exported_entities = []
        if geom.get("kind") == "slab" and geom.get("polygon"):
            exported_entities.append(msp.add_lwpolyline(
                [(float(x), float(y)) for x, y in geom["polygon"]],
                close=True,
                dxfattribs={"layer": layer, "elevation": float(geom.get("z", 0.0))},
            ))
        elif geom.get("kind") == "oriented_box":
            cx, cy, cz = geom["center"]
            length = float(geom["sizes"]["length"])
            thickness = float(geom["sizes"]["thickness"])
            height = float(geom["sizes"]["height"])
            z_bottom = float(cz) - height / 2.0
            z_top = float(cz) + height / 2.0
            angle = float(geom.get("rotation_z", 0.0))
            ca, sa = math.cos(angle), math.sin(angle)
            pts = []
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                lx, ly = sx * length / 2, sy * thickness / 2
                pts.append((cx + lx * ca - ly * sa, cy + lx * sa + ly * ca, z_bottom))
            exported_entities.append(msp.add_polyline3d(pts + [pts[0]], dxfattribs={"layer": layer}))
            exported_entities.append(msp.add_polyline3d(
                [(x, y, z_top) for x, y, _ in pts] + [(pts[0][0], pts[0][1], z_top)],
                dxfattribs={"layer": layer},
            ))
            for p in pts:
                exported_entities.append(msp.add_line(p, (p[0], p[1], z_top), dxfattribs={"layer": layer}))
        elif geom.get("kind") == "member":
            p0 = geom.get("p0")
            p1 = geom.get("p1")
            if not p0 or not p1 or len(p0) != 3 or len(p1) != 3:
                continue
            start = tuple(float(value) for value in p0)
            end = tuple(float(value) for value in p1)
            if not all(math.isfinite(value) for value in (*start, *end)):
                continue
            if math.dist(start, end) <= 1e-9:
                continue
            exported_entities.append(msp.add_line(start, end, dxfattribs={"layer": layer}))
        for entity in exported_entities:
            _set_element_provenance(entity, el)
    msp.add_text(project_name or "Intelligent Scan-to-BIM elements", height=0.4).set_placement((0, 0))
    doc.saveas(out_path)
    return out_path


def _column_type_members(column_types: list[dict[str, Any]]) -> dict[str, tuple[str, str, float, float]]:
    members: dict[str, tuple[str, str, float, float]] = {}
    ordered = sorted(column_types, key=lambda item: (
        item.get("status") == "confirmed", str(item.get("mark", "")), str(item.get("proposal_key", "")),
    ))
    for index, column_type in enumerate(ordered):
        status = column_type.get("status")
        if status not in {"confirmed", "proposed"}:
            continue
        mark = str(column_type.get("mark") or (f"ПР-{index + 1}" if status == "proposed" else "")).strip()
        if not mark:
            raise ValueError("confirmed column type requires a mark")
        prototype = column_type.get("prototype") or column_type
        sides = prototype.get("representative_sides_m") or {}
        try:
            long, short = float(sides["long"]), float(sides["short"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("column type requires measured prototype sides") from exc
        if not all(math.isfinite(value) and value > 0 for value in (long, short)) or short > long:
            raise ValueError("column type prototype sides are invalid")
        for element_id in column_type.get("member_element_ids", []):
            previous = members.get(element_id)
            if previous and previous[1] == "confirmed" and status == "confirmed":
                raise ValueError("column has conflicting confirmed type assignments")
            members[element_id] = (mark, status, long, short)
    return members


def export_structural_plan_dxf(
    elements: list[dict[str, Any]],
    out_path: str | Path,
    drawing_type: str,
    project_name: str = "",
    *,
    column_types: list[dict[str, Any]] | None = None,
    annotation_scale: int = 100,
    issue_mode: str = "draft",
) -> Path:
    """Export an editable XY plan for column footprints or crane-girder axes."""
    if drawing_type not in {"columns", "crane_girders"}:
        raise ValueError("drawing_type must be 'columns' or 'crane_girders'")
    if issue_mode not in {"draft", "final"}:
        raise ValueError("issue_mode must be 'draft' or 'final'")
    if not math.isfinite(annotation_scale) or not 10 <= annotation_scale <= 1000:
        raise ValueError("annotation scale must be between 10 and 1000")
    annotation_factor = annotation_scale / 100

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = _setup_document()
    msp = doc.modelspace()
    layer = "S2B-COLUMNS" if drawing_type == "columns" else "S2B-CRANE-GIRDERS"
    doc.styles.get("Standard").dxf.font = "arial.ttf"
    if "S2B-SCHEDULE" not in doc.appids:
        doc.appids.add("S2B-SCHEDULE")
    color = 2 if drawing_type == "columns" else 5
    if layer not in doc.layers:
        doc.layers.add(layer, color=color, lineweight=35)
    title = "ПЛАН КОЛОНН" if drawing_type == "columns" else "ПЛАН ПОДКРАНОВЫХ БАЛОК"
    schedule_title = "ВЕДОМОСТЬ КОЛОНН" if drawing_type == "columns" else "ВЕДОМОСТЬ ПОДКРАНОВЫХ БАЛОК"
    mark_prefix = "C" if drawing_type == "columns" else "G"
    doc.header["$PROJECTNAME"] = project_name or "Intelligent Scan-to-BIM"
    drawing_points: list[tuple[float, float]] = []
    schedule_rows: list[tuple[str, ...]] = []
    used_marks: set[str] = set()
    if issue_mode == "final":
        elements = [element for element in elements if element.get("review_status") in {"confirmed", "corrected"}]
        column_types = [column_type for column_type in (column_types or []) if column_type.get("status") == "confirmed"]
    type_members = _column_type_members(column_types or []) if drawing_type == "columns" else {}
    type_counts: dict[tuple[str, str, float, float], int] = {}

    for element in elements:
        if element.get("review_status") == "rejected":
            continue
        geometry = element.get("geometry") or {}
        dimensions = element.get("dimensions") or {}
        if drawing_type == "columns":
            if element.get("class_name") != "column" or geometry.get("kind") != "oriented_box":
                continue
            try:
                cx, cy = (float(value) for value in geometry["center"][:2])
                length = float(geometry["sizes"]["length"])
                thickness = float(geometry["sizes"]["thickness"])
                angle = float(geometry.get("rotation_z", 0.0))
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            if not all(math.isfinite(value) for value in (cx, cy, length, thickness, angle)) or length <= 0 or thickness <= 0:
                continue
            ca, sa = math.cos(angle), math.sin(angle)
            corners = []
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                lx, ly = sx * length / 2.0, sy * thickness / 2.0
                corners.append((cx + lx * ca - ly * sa, cy + lx * sa + ly * ca))
            msp.add_lwpolyline(corners, close=True, dxfattribs={"layer": layer})
            drawing_points.extend(corners)
            label_point = (cx, cy)
        else:
            if element.get("class_name") != "beam" or dimensions.get("role") != "crane_girder":
                continue
            if geometry.get("kind") == "member":
                p0, p1 = geometry.get("p0"), geometry.get("p1")
                if not p0 or not p1 or len(p0) != 3 or len(p1) != 3:
                    continue
                start = (float(p0[0]), float(p0[1]), 0.0)
                end = (float(p1[0]), float(p1[1]), 0.0)
                if not all(math.isfinite(value) for value in (*start, *end)) or math.dist(start[:2], end[:2]) <= 1e-9:
                    continue
            elif geometry.get("kind") == "oriented_box":
                try:
                    cx, cy = (float(value) for value in geometry["center"][:2])
                    length = float(geometry["sizes"]["length"])
                    angle = float(geometry.get("rotation_z", 0.0))
                except (KeyError, TypeError, ValueError, IndexError):
                    continue
                if not all(math.isfinite(value) for value in (cx, cy, length, angle)) or length <= 0:
                    continue
                dx, dy = math.cos(angle) * length / 2.0, math.sin(angle) * length / 2.0
                start, end = (cx - dx, cy - dy, 0.0), (cx + dx, cy + dy, 0.0)
            else:
                continue
            msp.add_line(start, end, dxfattribs={"layer": layer})
            drawing_points.extend((start[:2], end[:2]))
            label_point = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)

        status = element.get("review_status", "unreviewed")
        status_label = "ПРОВЕРЕНО" if status in {"confirmed", "corrected"} else "КАНДИДАТ"
        element_id = str(element.get("id", "без-ID"))
        if element_id.startswith("candidate-"):
            mark_suffix = element_id.removeprefix("candidate-")
        else:
            mark_suffix = element_id if len(element_id) <= 12 else element_id[:8]
        default_mark = f"{mark_prefix}-{mark_suffix}"
        type_member = type_members.get(element_id)
        drawing_mark = str(element.get("drawing_mark") or "").strip()
        mark = type_member[0] if type_member else (drawing_mark or default_mark)
        if mark in used_marks:
            suffix = 2
            while f"{mark}-{suffix}" in used_marks:
                suffix += 1
            mark = f"{mark}-{suffix}"
        used_marks.add(mark)
        msp.add_text(
            mark,
            height=0.25 * annotation_factor,
            dxfattribs={"layer": "S2B-MARKS"},
        ).set_placement((label_point[0] + 0.15 * annotation_factor,
            (max(point[1] for point in corners) if drawing_type == "columns" else label_point[1]) + 0.15 * annotation_factor))
        row = (mark, element_id, f"{label_point[0]:.3f}", f"{label_point[1]:.3f}", status_label)
        if drawing_type == "columns":
            long, short = max(length, thickness), min(length, thickness)
            delta = "-"
            type_status = "БЕЗ ТИПА"
            if type_member:
                _, type_state, prototype_long, prototype_short = type_member
                delta = f"{(long - prototype_long) * 1000:+.1f} / {(short - prototype_short) * 1000:+.1f}"
                type_status = "ТИП ПОДТВ." if type_state == "confirmed" else "ПРЕДЛОЖЕНИЕ"
                type_counts[type_member] = type_counts.get(type_member, 0) + 1
            row += (f"{long * 1000:.1f} × {short * 1000:.1f}", delta, type_status)
        schedule_rows.append(row)

    if drawing_points:
        min_x = min(point[0] for point in drawing_points)
        min_y = min(point[1] for point in drawing_points)
        max_x = max(point[0] for point in drawing_points)
        max_y = max(point[1] for point in drawing_points)
        padding = max(max_x - min_x, max_y - min_y, 0.5) * 0.08 + 0.5
    else:
        min_x = min_y = max_x = max_y = 0.0
        padding = 0.5

    span_x = max_x - min_x
    span_y = max_y - min_y
    dim_override = {"dimtxt": 0.25, "dimasz": 0.14, "dimexe": 0.10, "dimexo": 0.06, "dimgap": 0.05, "dimdec": 3}
    dim_override = {key: value if key == "dimdec" else value * annotation_factor
        for key, value in dim_override.items()}
    if span_x > 0.001:
        msp.add_linear_dim(
            base=(min_x, min_y - padding * 0.32),
            p1=(min_x, min_y),
            p2=(max_x, min_y),
            dimstyle="EZDXF",
            override=dim_override,
            dxfattribs={"layer": "S2B-DIMS"},
        ).render()
    if span_y > 0.001:
        msp.add_linear_dim(
            base=(max_x + padding * 0.32, min_y),
            p1=(max_x, min_y),
            p2=(max_x, max_y),
            angle=90,
            dimstyle="EZDXF",
            override=dim_override,
            dxfattribs={"layer": "S2B-DIMS"},
        ).render()

    table_x = max_x + padding * 0.8
    row_height = 0.42
    table_top = max_y
    column_widths = (1.5, 4.7, 1.6, 1.6, 2.1)
    column_titles = ("Марка", "ID элемента", "X, м", "Y, м", "Статус")
    if drawing_type == "columns":
        column_widths += (2.5, 2.5, 2.5)
        column_titles += ("Сечение, мм", "Откл. к типу, мм", "Статус типа")
    table_right = table_x + sum(column_widths)
    table_bottom = table_top - row_height * (len(schedule_rows) + 1)
    if schedule_rows:
        msp.add_text(schedule_title, height=0.30, dxfattribs={"layer": "S2B-SCHEDULE"}).set_placement(
            (table_x, table_top + 0.18)
        )
        for row_index in range(len(schedule_rows) + 2):
            y = table_top - row_index * row_height
            msp.add_line((table_x, y, 0.0), (table_right, y, 0.0), dxfattribs={"layer": "S2B-SCHEDULE"})
        x = table_x
        msp.add_line((x, table_top, 0.0), (x, table_bottom, 0.0), dxfattribs={"layer": "S2B-SCHEDULE"})
        for width in column_widths:
            x += width
            msp.add_line((x, table_top, 0.0), (x, table_bottom, 0.0), dxfattribs={"layer": "S2B-SCHEDULE"})
        for row_index, row in enumerate([column_titles, *schedule_rows]):
            text_y = table_top - (row_index + 0.78) * row_height
            text_x = table_x
            for column_index, (value, width) in enumerate(zip(row, column_widths)):
                cell = msp.add_text(str(value), height=0.20, dxfattribs={"layer": "S2B-SCHEDULE"}).set_placement(
                    (text_x + 0.06, text_y)
                )
                cell.set_xdata("S2B-SCHEDULE", [(1070, row_index), (1070, column_index), (1040, width)])
                text_x += width
        if type_counts:
            table_bottom -= row_height * 1.5
            msp.add_text("ТИПЫ КОЛОНН - количество на этом листе", height=0.24,
                dxfattribs={"layer": "S2B-SCHEDULE"}).set_placement((table_x, table_bottom))
            for (mark, state, long, short), count in sorted(type_counts.items()):
                table_bottom -= row_height
                label = "тип подтверждён" if state == "confirmed" else "предложение"
                summary = msp.add_text(f"{mark}: {count} шт.; прототип {long * 1000:.1f} × {short * 1000:.1f} мм; {label}",
                    height=0.20, dxfattribs={"layer": "S2B-SCHEDULE"}).set_placement((table_x, table_bottom))
                summary.set_xdata("S2B-SCHEDULE", [(1000, "summary")])

    frame_min_y = min_y - padding * 1.35
    frame_max_x = max_x + padding
    if schedule_rows:
        frame_min_y = min(frame_min_y, table_bottom - 0.3)
        frame_max_x = max(frame_max_x, table_right + padding * 0.25)
    frame_min = (min_x - padding, frame_min_y)
    frame_max = (frame_max_x, max_y + padding * 1.35)
    msp.add_lwpolyline(
        [frame_min, (frame_max[0], frame_min[1]), frame_max, (frame_min[0], frame_max[1])],
        close=True,
        dxfattribs={"layer": "S2B-FRAME"},
    )
    msp.add_text(title, height=0.45, dxfattribs={"layer": "S2B-TEXT"}).set_placement((min_x, max_y + padding))
    issue_stamp = "ЧЕРНОВИК · НЕ ДЛЯ РАБОТЫ" if issue_mode == "draft" else "ФИНАЛЬНЫЙ ВЫПУСК · ТОЛЬКО ПРОВЕРЕННЫЕ ОБЪЕКТЫ"
    msp.add_text(issue_stamp, height=0.28, dxfattribs={"layer": "S2B-TEXT"}).set_placement(
        (min_x, max_y + padding * 0.55)
    )
    msp.add_text(
        "Координаты и размеры - м; сечения и отклонения - мм. Сетка 6000 мм не применялась. Непроверенные элементы - кандидаты.",
        height=0.18,
        dxfattribs={"layer": "S2B-TEXT"},
    ).set_placement((min_x, min_y - padding))
    doc.saveas(out_path)
    return out_path
