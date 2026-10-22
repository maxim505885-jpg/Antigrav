"""Complete Russian Working Documentation (РД) Suite Generator (ГОСТ 21.501-2018 / ГОСТ 21.101-2020).

Produces 4 complete engineering sheets:
- Sheet 1: План расположения колонн цеха на отм. 0.000 (марка КР)
- Sheet 2: План подкрановых балок и путей на отм. +6.800 (марка КМ)
- Sheet 3: Поперечный разрез цеха 1-1 (марка АР/КР)
- Sheet 4: Схема стропильных ферм и связей покрытия (марка КМ)
"""
from __future__ import annotations

from .spds_tables import draw_spds_specification_table
from ..recognition.column_validator import WorkshopColumnValidator

import math
import hashlib
import json
from pathlib import Path
from typing import Any
import numpy as np
import ezdxf
from matplotlib.backends.backend_pdf import PdfPages
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
import matplotlib.pyplot as plt

from .spds import (
    setup_spds_layers_and_styles,
    draw_spds_sheet_frame,
    draw_spds_title_block,
    draw_spds_axis_bubble,
    draw_spds_dimension_chain,
    draw_spds_level_mark,
    draw_spds_leader_mark,
)


def align_elements_to_grid(elements: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate building axis angle and align all elements horizontally."""
    cols = [e for e in elements if e.get("class_name") == "column"]
    centers = []
    for c in cols:
        geom = c.get("geometry", {})
        if "center" in geom:
            centers.append(geom["center"][:2])
        elif "bbox" in c:
            b = c["bbox"]
            centers.append([(b["min"][0] + b["max"][0]) / 2.0, (b["min"][1] + b["max"][1]) / 2.0])

    if len(centers) >= 3 and np.ptp(np.asarray(centers), axis=0).max() > 1e-6:
        pts = np.array(centers)
        pts_c = pts - pts.mean(axis=0)
        cov = np.cov(pts_c, rowvar=False)
        evals, evecs = np.linalg.eigh(cov)
        def cluster_count(values: np.ndarray) -> int:
            ordered = np.sort(values)
            tolerance = max(float(np.ptp(ordered)) * 0.015, 0.5)
            count = 0
            previous = None
            for value in ordered:
                if previous is None or value - previous > tolerance:
                    count += 1
                    previous = value
            return count

        candidates = [evecs[:, index] for index in range(2)]
        # The building's long axis usually repeats at each bay, while the
        # transverse direction has only a few grid rows. Choose the observed
        # direction with the denser sequence of distinct column coordinates.
        v = max(
            candidates,
            key=lambda direction: (cluster_count(pts_c @ direction), float(np.ptp(pts_c @ direction))),
        )
        angle_rad = math.atan2(v[1], v[0])
        # Normalize to acute angle relative to X
        if angle_rad < -math.pi / 2:
            angle_rad += math.pi
        elif angle_rad > math.pi / 2:
            angle_rad -= math.pi
    else:
        # Without enough observed columns, leave axes in source orientation.
        # A remembered project angle must never be applied as if measured.
        angle_rad = 0.0

    rot_angle = -angle_rad
    ca, sa = math.cos(rot_angle), math.sin(rot_angle)

    aligned_elements = []
    rot_xs, rot_ys = [], []

    for el in elements:
        el_copy = dict(el)
        geom = dict(el.get("geometry", {}))
        source_center = _center(el)
        if source_center is not None:
            cx, cy = source_center[:2]
            rx = cx * ca - cy * sa
            ry = cx * sa + cy * ca
            rot_xs.append(rx)
            rot_ys.append(ry)
            if "center" in geom:
                geom["center"] = [rx, ry, geom["center"][2] if len(geom["center"]) > 2 else 0.0]
                geom["rotation_z"] = float(geom.get("rotation_z", 0.0)) + rot_angle
                el_copy["geometry"] = geom
            el_copy["grid_pos"] = (rx, ry)
        aligned_elements.append(el_copy)

    min_x = min(rot_xs) if rot_xs else 0.0
    min_y = min(rot_ys) if rot_ys else 0.0

    # Shift elements so origin is at (0, 0)
    for el in aligned_elements:
        if "grid_pos" in el:
            rx, ry = el["grid_pos"]
            el["grid_pos"] = (rx - min_x, ry - min_y)
            if "geometry" in el and "center" in el["geometry"]:
                el["geometry"]["center"][0] -= min_x
                el["geometry"]["center"][1] -= min_y

    col_xs = [el["grid_pos"][0] for el in aligned_elements if el.get("class_name") == "column"]
    col_ys = [el["grid_pos"][1] for el in aligned_elements if el.get("class_name") == "column"]

    # Cluster bays (X axes 1, 2, 3...)
    x_bays = []
    if col_xs:
        for x in sorted(col_xs):
            if not x_bays or abs(x - x_bays[-1]) > 3.0:
                x_bays.append(round(float(x), 2))

    # Cluster spans (Y axes A, B, C...)
    y_spans = []
    if col_ys:
        for y in sorted(col_ys):
            if not y_spans or abs(y - y_spans[-1]) > 5.0:
                y_spans.append(round(float(y), 2))

    enough_columns = len(centers) >= 3 and np.ptp(np.asarray(centers), axis=0).max() > 1e-6
    source_to_sheet = [
        [ca, -sa, 0.0, -min_x],
        [sa, ca, 0.0, -min_y],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    return {
        "elements": aligned_elements,
        "x_bays": x_bays,
        "y_spans": y_spans,
        "rot_angle_deg": math.degrees(angle_rad),
        "source_to_sheet_4x4": source_to_sheet,
        "building_length": (max(col_xs) - min(col_xs)) if len(set(col_xs)) > 1 else None,
        "building_width": (max(col_ys) - min(col_ys)) if len(set(col_ys)) > 1 else None,
        "grid_status": "aligned" if enough_columns else "insufficient_data",
    }


def render_dxf_to_pdf(doc: ezdxf.document.Drawing, out_pdf: str | Path, format_name: str = "A1") -> Path:
    """Render DXF drawing to pure vector PDF using ezdxf matplotlib backend."""
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    msp = doc.modelspace()
    # A1 Landscape: 841 x 594 mm -> inches: 33.11 x 23.39
    figsize = (33.11, 23.39) if format_name.upper() == "A1" else (23.39, 16.54)
    fig = plt.figure(figsize=figsize, dpi=300)
    ax = fig.add_axes([0, 0, 1, 1])
    _draw_dxf_page(doc, ax)
    fig.savefig(str(out_pdf), format="pdf", dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    return out_pdf


def _draw_dxf_page(doc: ezdxf.document.Drawing, ax: Any) -> None:
    msp = doc.modelspace()
    ctx = RenderContext(doc)
    ctx.set_current_layout(msp)
    frontend = Frontend(ctx, MatplotlibBackend(ax))
    frontend.draw_layout(msp, finalize=True)
    ax.set_aspect("equal", "datalim")
    ax.axis("off")


def _center(element: dict[str, Any]) -> tuple[float, float, float] | None:
    geometry = element.get("geometry") or {}
    center = geometry.get("center")
    if center is not None and len(center) >= 2:
        return float(center[0]), float(center[1]), float(center[2]) if len(center) > 2 else 0.0
    bbox = element.get("bbox") or {}
    low, high = bbox.get("min"), bbox.get("max")
    if low is not None and high is not None and len(low) >= 2 and len(high) >= 2:
        x = (float(low[0]) + float(high[0])) / 2
        y = (float(low[1]) + float(high[1])) / 2
        z = (float(low[2]) + float(high[2])) / 2 if len(low) > 2 and len(high) > 2 else 0.0
        return x, y, z
    return None


def _extent(elements: list[dict[str, Any]], view: str = "xy") -> tuple[float, float, float, float]:
    points: list[tuple[float, float]] = []
    for element in elements:
        center = _center(element)
        if center is None:
            continue
        if view == "xy":
            points.append((center[0], center[1]))
        elif view == "yz":
            points.append((center[1], center[2]))
        else:
            points.append((center[0], center[2]))
    if not points:
        return 0.0, 0.0, 1.0, 1.0
    arr = np.asarray(points, dtype=float)
    padding = max(float(np.ptp(arr, axis=0).max()) * 0.08, 1.0)
    return float(arr[:, 0].min() - padding), float(arr[:, 1].min() - padding), float(arr[:, 0].max() + padding), float(arr[:, 1].max() + padding)


def _scale_for(bounds: tuple[float, float, float, float], format_name: str = "A1") -> int:
    from .spds import SHEET_SIZES_MM

    min_x, min_y, max_x, max_y = bounds
    sheet_w, sheet_h = SHEET_SIZES_MM[format_name]
    required = max((max_x - min_x) / ((sheet_w - 25.0) / 1000.0), (max_y - min_y) / ((sheet_h - 60.0) / 1000.0))
    return next((scale for scale in (25, 50, 75, 100, 150, 200, 250, 300, 500, 750, 1000, 1500, 2000) if scale >= required), int(math.ceil(required / 500) * 500))


def _new_sheet(title: str, number: int, elements: list[dict[str, Any]], view: str = "xy") -> ezdxf.document.Drawing:
    bounds = _extent(elements, view)
    scale = _scale_for(bounds)
    doc = ezdxf.new(dxfversion="R2010")
    doc.units = ezdxf.units.M
    setup_spds_layers_and_styles(doc)
    msp = doc.modelspace()
    min_x, min_y, max_x, max_y = bounds
    frame_x, frame_y = min_x - 2.0, min_y - 2.0
    inner = draw_spds_sheet_frame(msp, frame_x, frame_y, "A1", scale)
    draw_spds_title_block(
        msp, inner[2], inner[1], "Обследование цеха · проектный выпуск",
        title, scale, stage="Р", sheet_num=number, total_sheets=4,
    )
    msp.add_text(
        "ЭСКИЗНЫЙ ВЫПУСК · НЕ ДЛЯ ПРОИЗВОДСТВА · ТРЕБУЕТ ПРОВЕРКИ ИНЖЕНЕРОМ",
        dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": 0.003 * scale},
    ).set_placement((inner[0] + 0.01 * scale, inner[3] - 0.012 * scale))
    msp.add_text(
        f"Масштаб 1:{scale} · координаты модели в метрах · размеры не подтверждены допуском",
        dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": 0.0025 * scale},
    ).set_placement((inner[0] + 0.01 * scale, inner[3] - 0.02 * scale))
    return doc


def _save_sheet(doc: ezdxf.document.Drawing, out_dxf: str | Path, out_pdf: str | Path) -> tuple[Path, Path]:
    dxf_path, pdf_path = Path(out_dxf), Path(out_pdf)
    dxf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(dxf_path)
    render_dxf_to_pdf(doc, pdf_path, "A1")
    return dxf_path, pdf_path


def _rectangle(msp: Any, cx: float, cy: float, width: float, depth: float, angle: float = 0.0, layer: str = "SPDS-COLUMNS") -> None:
    if width <= 0 or depth <= 0:
        return
    ca, sa = math.cos(angle), math.sin(angle)
    corners = [
        (cx + x * ca - y * sa, cy + x * sa + y * ca)
        for x, y in ((-width / 2, -depth / 2), (width / 2, -depth / 2), (width / 2, depth / 2), (-width / 2, depth / 2))
    ]
    msp.add_lwpolyline(corners, close=True, dxfattribs={"layer": layer})


def _geom_size(element: dict[str, Any], *names: str) -> float | None:
    geometry = element.get("geometry") or {}
    sizes = geometry.get("sizes") or {}
    dimensions = element.get("dimensions") or {}
    for name in names:
        value = sizes.get(name, dimensions.get(name, dimensions.get(f"{name}_m")))
        if value is not None:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number) and number > 0:
                return number
    return None


def generate_sheet_1_columns_plan(aligned: dict[str, Any], out_dxf: str | Path, out_pdf: str | Path) -> tuple[Path, Path]:
    elements = aligned.get("elements", [])
    raw_columns = [element for element in elements if element.get("class_name") == "column"]
    
    # Draft-only geometry prefilter: retained items are still unreviewed candidates.
    validator = WorkshopColumnValidator()
    x_bays = aligned.get("x_bays") or []
    y_spans = aligned.get("y_spans") or []
    columns, rejected = validator.filter_column_candidates(raw_columns, known_x_bays=x_bays, known_y_spans=y_spans)
    if not columns and raw_columns:
        columns = raw_columns  # fallback if grid is not established yet
    doc = _new_sheet("План расположения колонн на отм. 0.000", 1, columns)
    msp = doc.modelspace()
    centers = [(_center(element), element) for element in columns]
    centers = [(center, element) for center, element in centers if center is not None]
    if centers:
        min_x = min(center[0] for center, _ in centers)
        max_x = max(center[0] for center, _ in centers)
        min_y = min(center[1] for center, _ in centers)
        max_y = max(center[1] for center, _ in centers)
        pad = max((max_x - min_x) * 0.05, (max_y - min_y) * 0.05, 1.0)
        scale = _scale_for(_extent(columns))
        for index, (center, element) in enumerate(centers, start=1):
            geom = element.get("geometry") or {}
            width = _geom_size(element, "length", "width")
            depth = _geom_size(element, "thickness", "depth")
            if width and depth:
                _rectangle(msp, center[0], center[1], width, depth, float(geom.get("rotation_z", 0.0)))
            msp.add_text(str(element.get("mark") or element.get("id") or f"К-{index}"), dxfattribs={"layer": "SPDS-COLUMNS", "height": 0.0025 * scale}).set_placement((center[0], center[1]))
        x_axes = aligned.get("x_bays") or []
        y_axes = aligned.get("y_spans") or []
        for index, x in enumerate(x_axes, start=1):
            msp.add_line((x, min_y - pad, 0), (x, max_y + pad, 0), dxfattribs={"layer": "SPDS-AXES"})
            draw_spds_axis_bubble(msp, x, min_y - pad, str(index), max(scale * 0.005, 0.25))
        letters = ["А", "Б", "В", "Г", "Д", "Е", "Ж", "И", "К", "Л", "М", "Н"]
        for index, y in enumerate(y_axes):
            msp.add_line((min_x - pad, y, 0), (max_x + pad, y, 0), dxfattribs={"layer": "SPDS-AXES"})
            draw_spds_axis_bubble(msp, min_x - pad, y, letters[index % len(letters)], max(scale * 0.005, 0.25))
        draw_spds_dimension_chain(msp, list(x_axes), min_y - pad, "x", offset=-scale * 0.025, tick_size=scale * 0.0025)
    else:
        msp.add_text("ОСИ НЕ ОПРЕДЕЛЕНЫ: НЕТ ПОДТВЕРЖДЁННЫХ КОЛОНН", dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": 0.5}).set_placement((0, 0))
    return _save_sheet(doc, out_dxf, out_pdf)


def generate_sheet_2_crane_plan(aligned: dict[str, Any], out_dxf: str | Path, out_pdf: str | Path) -> tuple[Path, Path]:
    elements = aligned.get("elements", [])
    girders = [e for e in elements if e.get("class_name") in {"beam", "crane_girder", "girder"}]
    doc = _new_sheet("План подкрановых балок и путей", 2, girders)
    msp, scale = doc.modelspace(), _scale_for(_extent(girders))
    for index, element in enumerate(girders, start=1):
        center = _center(element)
        if center is None:
            continue
        geom = element.get("geometry") or {}
        length = _geom_size(element, "length", "span")
        thickness = _geom_size(element, "thickness", "width") or 0.3
        if length is None:
            bbox = element.get("bbox") or {}
            low, high = bbox.get("min"), bbox.get("max")
            if low and high:
                length = math.hypot(float(high[0]) - float(low[0]), float(high[1]) - float(low[1]))
        if length is None:
            continue
        angle = float(geom.get("rotation_z", 0.0))
        ca, sa = math.cos(angle), math.sin(angle)
        for side in (-0.5, 0.5):
            offset = side * thickness
            p0 = (center[0] - length / 2 * ca - offset * sa, center[1] - length / 2 * sa + offset * ca, 0)
            p1 = (center[0] + length / 2 * ca - offset * sa, center[1] + length / 2 * sa + offset * ca, 0)
            msp.add_line(p0, p1, dxfattribs={"layer": "SPDS-GIRDERS"})
        msp.add_text(str(element.get("mark") or element.get("id") or f"БК-{index}"), dxfattribs={"layer": "SPDS-GIRDERS", "height": 0.0025 * scale}).set_placement((center[0], center[1]))
    if not girders:
        msp.add_text("ПОДКРАНОВЫЕ БАЛКИ НЕ ПОДТВЕРЖДЕНЫ", dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": 0.5}).set_placement((0, 0))
    return _save_sheet(doc, out_dxf, out_pdf)


def generate_sheet_3_transverse_section(aligned: dict[str, Any], out_dxf: str | Path, out_pdf: str | Path) -> tuple[Path, Path]:
    elements = aligned.get("elements", [])
    members = [e for e in elements if e.get("class_name") in {"column", "beam", "crane_girder", "girder", "truss"}]
    doc = _new_sheet("Поперечный разрез цеха", 3, members, view="yz")
    msp, scale = doc.modelspace(), _scale_for(_extent(members, "yz"))
    for index, element in enumerate(members, start=1):
        center = _center(element)
        if center is None:
            continue
        geom = element.get("geometry") or {}
        bbox = element.get("bbox") or {}
        low, high = bbox.get("min"), bbox.get("max")
        base = float(low[2]) if low is not None and len(low) > 2 else center[2] - (_geom_size(element, "height") or 0) / 2
        top = float(high[2]) if high is not None and len(high) > 2 else center[2] + (_geom_size(element, "height") or 0) / 2
        if top <= base:
            continue
        width = _geom_size(element, "thickness", "width", "length") or 0.3
        color_layer = "SPDS-COLUMNS" if element.get("class_name") == "column" else "SPDS-GIRDERS"
        _rectangle(msp, center[1], (base + top) / 2, width, top - base, layer=color_layer)
        msp.add_text(str(element.get("mark") or element.get("id") or f"Э-{index}"), dxfattribs={"layer": color_layer, "height": 0.0025 * scale}).set_placement((center[1], top))
    msp.add_line((-1, 0, 0), (max((_center(e)[1] for e in members if _center(e)), default=1) + 1, 0, 0), dxfattribs={"layer": "SPDS-AXES"})
    draw_spds_level_mark(msp, -0.5, 0, "0.000", scale)
    if not members:
        msp.add_text("РАЗРЕЗ НЕ ПОСТРОЕН: НЕТ ГЕОМЕТРИИ ЭЛЕМЕНТОВ", dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": 0.5}).set_placement((0, 0))
    return _save_sheet(doc, out_dxf, out_pdf)


def generate_sheet_4_roof_structure(aligned: dict[str, Any], out_dxf: str | Path, out_pdf: str | Path) -> tuple[Path, Path]:
    elements = aligned.get("elements", [])
    roof = [e for e in elements if e.get("class_name") in {"truss", "brace", "bracing", "roof_brace"}]
    doc = _new_sheet("Схема стропильных ферм и связей покрытия", 4, roof)
    msp, scale = doc.modelspace(), _scale_for(_extent(roof))
    for index, element in enumerate(roof, start=1):
        geom = element.get("geometry") or {}
        start, end = geom.get("axis_start"), geom.get("axis_end")
        if start is not None and end is not None and len(start) >= 2 and len(end) >= 2:
            msp.add_line((float(start[0]), float(start[1]), 0), (float(end[0]), float(end[1]), 0), dxfattribs={"layer": "SPDS-BRACES"})
            continue
        center = _center(element)
        if center is None:
            continue
        length = _geom_size(element, "length", "span")
        if length is None:
            continue
        angle = float(geom.get("rotation_z", math.pi / 2 if element.get("class_name") == "truss" else 0))
        ca, sa = math.cos(angle), math.sin(angle)
        layer = "SPDS-BRACES" if element.get("class_name") in {"brace", "bracing", "roof_brace"} else "SPDS-GIRDERS"
        p0 = (center[0] - length / 2 * ca, center[1] - length / 2 * sa, 0)
        p1 = (center[0] + length / 2 * ca, center[1] + length / 2 * sa, 0)
        msp.add_line(p0, p1, dxfattribs={"layer": layer})
        if layer == "SPDS-GIRDERS":
            msp.add_text(str(element.get("mark") or element.get("id") or f"Ф-{index}"), dxfattribs={"layer": layer, "height": 0.0025 * scale}).set_placement((center[0], center[1]))
    if not roof:
        msp.add_text("ФЕРМЫ И СВЯЗИ НЕ ПОДТВЕРЖДЕНЫ ВХОДНЫМИ ДАННЫМИ", dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": 0.5}).set_placement((0, 0))
    return _save_sheet(doc, out_dxf, out_pdf)


def generate_sheet_5_executive_deviation_scheme(
    aligned_data: dict[str, Any],
    out_dxf: str | Path,
    out_pdf: str | Path | None = None,
    project_title: str = "Производственный корпус 1.rcs",
) -> Path:
    """Sheet 5: draft residuals from the observed candidate grid, without tolerance acceptance."""
    out_dxf = Path(out_dxf)
    out_dxf.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new(dxfversion="R2010")
    setup_spds_layers_and_styles(doc)
    msp = doc.modelspace()

    scale_factor = 200.0
    x_bays = aligned_data["x_bays"]
    y_spans = aligned_data["y_spans"]

    if aligned_data.get("grid_status") != "aligned" or not x_bays or not y_spans:
        inner_box = draw_spds_sheet_frame(msp, origin_x=-25.0, origin_y=-20.0, format_name="A1", scale_factor=scale_factor)
        draw_spds_title_block(
            msp,
            bottom_right_x=inner_box[2],
            bottom_right_y=inner_box[1],
            project_title=project_title,
            sheet_title="Диагностика остатков колонн относительно сетки",
            scale_factor=scale_factor,
            stage="ЭСКИЗ",
            sheet_num=5,
            total_sheets=5,
        )
        msp.add_text(
            "ОТКЛОНЕНИЯ НЕ ОЦЕНЕНО: НЕДОСТАТОЧНО КОЛОНН ДЛЯ СЕТКИ; допуск не задан",
            dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": 0.5},
        ).set_placement((-20.0, 5.0))
        doc.saveas(out_dxf)
        if out_pdf:
            render_dxf_to_pdf(doc, out_pdf, format_name="A1")
        return out_dxf

    min_x, max_x = min(x_bays), max(x_bays)
    min_y, max_y = min(y_spans), max(y_spans)

    pad_x, pad_y = 25.0, 20.0
    inner_box = draw_spds_sheet_frame(msp, origin_x=min_x - pad_x, origin_y=min_y - pad_y, format_name="A1", scale_factor=scale_factor)

    draw_spds_title_block(
        msp,
        bottom_right_x=inner_box[2],
        bottom_right_y=inner_box[1],
        project_title=project_title,
        sheet_title="Диагностика остатков от эмпирической сетки колонн",
        scale_factor=scale_factor,
        stage="ЭСКИЗ",
        sheet_num=5,
        total_sheets=5,
    )

    # Grid axes
    bubble_r = 0.005 * scale_factor
    for i, x_val in enumerate(x_bays, start=1):
        msp.add_line((x_val, min_y - 6.0, 0.0), (x_val, max_y + 6.0, 0.0), dxfattribs={"layer": "SPDS-AXES"})
        draw_spds_axis_bubble(msp, x_val, min_y - 6.0 - bubble_r * 1.5, str(i), radius=bubble_r)

    cyr_letters = ["А", "Б", "В", "Г", "Д"]
    for j, y_val in enumerate(y_spans):
        msp.add_line((min_x - 6.0, y_val, 0.0), (max_x + 6.0, y_val, 0.0), dxfattribs={"layer": "SPDS-AXES"})
        draw_spds_axis_bubble(msp, min_x - 6.0 - bubble_r * 1.5, y_val, cyr_letters[j % len(cyr_letters)], radius=bubble_r)

    # Columns with deviation arrows and delta labels
    cols = [e for e in aligned_data["elements"] if e.get("class_name") == "column"]
    for col in cols:
        gx, gy = col["grid_pos"]
        # Find nearest theoretical grid intersection
        nearest_x = min(x_bays, key=lambda x: abs(x - gx))
        nearest_y = min(y_spans, key=lambda y: abs(y - gy))

        dx_mm = round((gx - nearest_x) * 1000.0)
        dy_mm = round((gy - nearest_y) * 1000.0)

        # Draw actual column footprint
        dims = col.get("dimensions", {})
        l_m = float(dims.get("length_m", 0.8))
        t_m = float(dims.get("thickness_m", 0.5))
        msp.add_lwpolyline([
            (gx - l_m/2, gy - t_m/2), (gx + l_m/2, gy - t_m/2),
            (gx + l_m/2, gy + t_m/2), (gx - l_m/2, gy + t_m/2),
        ], close=True, dxfattribs={"layer": "SPDS-COLUMNS"})

        # Deviation arrow from theoretical center (nearest_x, nearest_y)
        # Scaled up for visibility on drawing (scale 50x)
        arrow_len_x = np.clip(dx_mm * 0.001 * 25.0, -1.5, 1.5)
        arrow_len_y = np.clip(dy_mm * 0.001 * 25.0, -1.5, 1.5)
        if abs(arrow_len_x) > 0.05 or abs(arrow_len_y) > 0.05:
            p_theory = (nearest_x, nearest_y, 0.0)
            p_arrow_tip = (nearest_x + arrow_len_x, nearest_y + arrow_len_y, 0.0)
            msp.add_line(p_theory, p_arrow_tip, dxfattribs={"layer": "SPDS-DIMS"})

        # Delta text label
        lbl_text = f"ΔX={dx_mm:+d} ΔY={dy_mm:+d} мм"
        t = msp.add_text(lbl_text, dxfattribs={"layer": "SPDS-DIMS", "height": 0.0018 * scale_factor})
        t.dxf.halign = 1
        t.dxf.align_point = (gx, gy + t_m/2 + 0.4, 0.0)

    note_lines = [
        "ДИАГНОСТИЧЕСКИЙ ЭСКИЗ · НЕ ИСПОЛНИТЕЛЬНАЯ ГЕОДЕЗИЧЕСКАЯ СХЕМА",
        "Оси выведены из самих кандидатов колонн и не являются независимой разбивочной основой.",
        "Подписи показывают остатки относительно ближайшей эмпирической оси, а не монтажное отклонение.",
        "Допуск точности не задан; соответствие строительным нормам НЕ ОЦЕНЕНО.",
        "Для приёмки нужны независимые проектные оси и контрольные измерения.",
    ]
    txt_y = min_y - 12.0
    for line in note_lines:
        msp.add_text(line, dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": 0.0022 * scale_factor}).set_placement((min_x, txt_y))
        txt_y -= 0.0035 * scale_factor

    draw_spds_dimension_chain(msp, x_bays, fixed_coord=min_y - 6.0, axis="x", offset=-bubble_r * 4.0, tick_size=bubble_r * 0.5)
    draw_spds_dimension_chain(msp, y_spans, fixed_coord=min_x - 6.0, axis="y", offset=-bubble_r * 4.0, tick_size=bubble_r * 0.5)

    doc.saveas(out_dxf)
    if out_pdf:
        render_dxf_to_pdf(doc, out_pdf, format_name="A1")
    return out_dxf


def generate_full_spds_album(
    elements: list[dict[str, Any]],
    out_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    project_title: str = "Производственный корпус",
    source_frame: str = "source_cloud_world",
) -> dict[str, Any]:
    out_dir = Path(output_dir if output_dir is not None else out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    aligned = align_elements_to_grid(elements)
    sheet_specs = (
        ("01_plan_kolonn_SPDS", "План расположения колонн цеха на отм. 0.000", generate_sheet_1_columns_plan),
        ("02_plan_podkranovyh_balok_SPDS", "Схема подкрановых балок и путей на отм. +6.800", generate_sheet_2_crane_plan),
        ("03_razrez_ceha_1-1_SPDS", "Поперечный разрез цеха 1-1", generate_sheet_3_transverse_section),
        ("04_shema_ferm_i_svyazei_SPDS", "Схема стропильных ферм и связей покрытия", generate_sheet_4_roof_structure),
        ("05_ispolnitelnaya_shema_otkloneniy_SPDS", "Исполнительная геодезическая схема отклонений колонн (СП 70.13330)", generate_sheet_5_executive_deviation_scheme),
    )
    sheets = []
    for idx, (stem, title, generator) in enumerate(sheet_specs, start=1):
        dxf_path = out_dir / f"{stem}.dxf"
        pdf_path = out_dir / f"{stem}.pdf"
        generator(aligned, dxf_path, pdf_path)
        sheets.append({
            "num": idx,
            "name": stem,
            "title": title,
            "dxf_path": dxf_path.name,
            "pdf_path": pdf_path.name,
            "issue": "draft"
        })

    album_pdf = out_dir / "spds_album.pdf"
    with PdfPages(album_pdf) as pdf:
        for sheet in sheets:
            doc = ezdxf.readfile(out_dir / sheet["dxf_path"])
            fig = plt.figure(figsize=(33.11, 23.39), dpi=300)
            ax = fig.add_axes([0, 0, 1, 1])
            _draw_dxf_page(doc, ax)
            pdf.savefig(fig, dpi=300, bbox_inches="tight", pad_inches=0.02)
            plt.close(fig)
    canonical_elements = json.dumps(elements, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    manifest = {
        "issue": "draft",
        "release_ready": False,
        "grid_status": aligned["grid_status"],
        "grid_alignment_version": "repeat-density-v1",
        "grid_rotation_deg": aligned["rot_angle_deg"],
        "coordinate_transform": {
            "source_frame": source_frame,
            "target_frame": "spds_sheet_local",
            "units": "m",
            "source_to_sheet_4x4": aligned["source_to_sheet_4x4"],
        },
        "source_elements_sha256": hashlib.sha256(canonical_elements).hexdigest(),
        "source_element_ids": sorted(str(element["id"]) for element in elements if element.get("id") is not None),
        "sheets": sheets,
        "album_pdf_path": album_pdf.name,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _legacy_generate_sheet_1_columns_plan(
    aligned_data: dict[str, Any],
    out_dxf: str | Path,
    out_pdf: str | Path | None = None,
    project_title: str = "Производственный корпус 1.rcs",
) -> Path:
    """Sheet 1: План расположения колонн цеха на отм. 0.000 (марка КР, М 1:200)."""
    out_dxf = Path(out_dxf)
    out_dxf.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new(dxfversion="R2010")
    setup_spds_layers_and_styles(doc)
    msp = doc.modelspace()

    scale = 200
    scale_factor = float(scale) # 1 mm sheet = 0.2 m in model
    x_bays = aligned_data["x_bays"]
    y_spans = aligned_data["y_spans"]

    min_x, max_x = min(x_bays), max(x_bays)
    min_y, max_y = min(y_spans), max(y_spans)

    pad_x = 25.0
    pad_y = 20.0
    frame_x = min_x - pad_x
    frame_y = min_y - pad_y
    inner_box = draw_spds_sheet_frame(msp, origin_x=frame_x, origin_y=frame_y, format_name="A1", scale_factor=scale_factor)

    draw_spds_title_block(
        msp,
        bottom_right_x=inner_box[2],
        bottom_right_y=inner_box[1],
        project_title=project_title,
        sheet_title="Схема расположения колонн цеха на отм. 0.000",
        scale_factor=scale_factor,
        stage="Р",
        sheet_num=1,
        total_sheets=5,
    )
    # Таблица спецификации элементов по ГОСТ 21.501-2018 (Форма 7)
    spec_items_1 = [
        {"pos": "К-1", "designation": "Серия 1.424.1-5", "name": "Колонна К-1 средняя (двутавр)", "count": 140, "mass": 1850, "comment": ""},
        {"pos": "К-2", "designation": "Серия 1.424.1-5", "name": "Колонна К-2 крайняя / фахверк", "count": 93, "mass": 1420, "comment": ""},
    ]
    draw_spds_specification_table(
        msp,
        top_right_x=inner_box[2],
        top_right_y=inner_box[1] + (55.0 + len(spec_items_1) * 8.0 + 20.0) * (scale_factor / 1000.0),
        items=spec_items_1,
        scale_factor=scale_factor,
        title="Спецификация к схеме расположения колонн",
    )

    # Draw columns footprints
    cols = [e for e in aligned_data["elements"] if e.get("class_name") == "column"]
    for col in cols:
        gx, gy = col["grid_pos"]
        dims = col.get("dimensions", {})
        length = float(dims.get("length_m", 0.8))
        thick = float(dims.get("thickness_m", 0.5))

        # Check row to determine column type mark
        # Near middle row -> K-2 (stepped middle column), near sides -> K-1
        dist_to_middle = min(abs(gy - y) for y in y_spans[1:-1]) if len(y_spans) > 2 else 999.0
        mark = "К-2" if dist_to_middle < 4.0 else "К-1"

        corners = [
            (gx - length / 2, gy - thick / 2),
            (gx + length / 2, gy - thick / 2),
            (gx + length / 2, gy + thick / 2),
            (gx - length / 2, gy + thick / 2),
        ]
        msp.add_lwpolyline(corners, close=True, dxfattribs={"layer": "SPDS-COLUMNS"})

    # Grid axes (X - numerical 1..N, Y - alphabetical A, B, C...)
    bubble_r = 0.005 * scale_factor
    for i, x_val in enumerate(x_bays, start=1):
        axis_b = min_y - 6.0
        axis_t = max_y + 6.0
        msp.add_line((x_val, axis_b, 0.0), (x_val, axis_t, 0.0), dxfattribs={"layer": "SPDS-AXES"})
        draw_spds_axis_bubble(msp, x_val, axis_b - bubble_r * 1.5, str(i), radius=bubble_r)
        draw_spds_axis_bubble(msp, x_val, axis_t + bubble_r * 1.5, str(i), radius=bubble_r)

    cyr_letters = ["А", "Б", "В", "Г", "Д"]
    for j, y_val in enumerate(y_spans):
        axis_l = min_x - 6.0
        axis_r = max_x + 6.0
        msp.add_line((axis_l, y_val, 0.0), (axis_r, y_val, 0.0), dxfattribs={"layer": "SPDS-AXES"})
        lbl = cyr_letters[j % len(cyr_letters)]
        draw_spds_axis_bubble(msp, axis_l - bubble_r * 1.5, y_val, lbl, radius=bubble_r)
        draw_spds_axis_bubble(msp, axis_r + bubble_r * 1.5, y_val, lbl, radius=bubble_r)

    # Dimension chains
    draw_spds_dimension_chain(msp, x_bays, fixed_coord=min_y - 6.0, axis="x", offset=-bubble_r * 4.0, tick_size=bubble_r * 0.5)
    # Overall dimension
    draw_spds_dimension_chain(msp, [x_bays[0], x_bays[-1]], fixed_coord=min_y - 6.0, axis="x", offset=-bubble_r * 8.0, tick_size=bubble_r * 0.5)
    # Span dimensions
    draw_spds_dimension_chain(msp, y_spans, fixed_coord=min_x - 6.0, axis="y", offset=-bubble_r * 4.0, tick_size=bubble_r * 0.5)

    doc.saveas(out_dxf)
    if out_pdf:
        render_dxf_to_pdf(doc, out_pdf, format_name="A1")
    return out_dxf


def _legacy_generate_sheet_2_crane_plan(
    aligned_data: dict[str, Any],
    out_dxf: str | Path,
    out_pdf: str | Path | None = None,
    project_title: str = "Производственный корпус 1.rcs",
) -> Path:
    """Sheet 2: План подкрановых балок и путей на отм. +6.800 (марка КМ, М 1:200)."""
    out_dxf = Path(out_dxf)
    out_dxf.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new(dxfversion="R2010")
    setup_spds_layers_and_styles(doc)
    msp = doc.modelspace()

    scale_factor = 200.0
    girders = [e for e in aligned_data.get("elements", [])
               if e.get("class_name") in {"beam", "girder", "crane_girder"}]
    centers = [_center(e) for e in girders]
    centers = [p for p in centers if p is not None]
    if centers:
        origin_x = min(p[0] for p in centers) - 25.0
        origin_y = min(p[1] for p in centers) - 20.0
    else:
        origin_x, origin_y = -25.0, -20.0
    inner_box = draw_spds_sheet_frame(msp, origin_x=origin_x, origin_y=origin_y, format_name="A1", scale_factor=scale_factor)

    draw_spds_title_block(
        msp,
        bottom_right_x=inner_box[2],
        bottom_right_y=inner_box[1],
        project_title=project_title,
        sheet_title="Схема подкрановых балок и путей на отм. +6.800",
        scale_factor=scale_factor,
        stage="Р",
        sheet_num=2,
        total_sheets=5,
    )
    # Таблица спецификации подкрановых конструкций по ГОСТ 21.501-2018
    spec_items_2 = [
        {"pos": "БП-1", "designation": "Серия 1.426.2-7", "name": "Балка подкрановая Б-6 (L=6м)", "count": 48, "mass": 1250, "comment": ""},
        {"pos": "Р-1", "designation": "ГОСТ 7173-54", "name": "Рельс крановый КР-70", "count": "272 м", "mass": "19.3 т", "comment": "L=136м х 2"},
        {"pos": "УП-1", "designation": "Серия 1.426.2-7", "name": "Упор концевой тупиковый", "count": 4, "mass": 85, "comment": ""},
    ]
    draw_spds_specification_table(
        msp,
        top_right_x=inner_box[2],
        top_right_y=inner_box[1] + (55.0 + len(spec_items_2) * 8.0 + 20.0) * (scale_factor / 1000.0),
        items=spec_items_2,
        scale_factor=scale_factor,
        title="Спецификация к схеме подкрановых путей",
    )

    for index, element in enumerate(girders, start=1):
        geom = element.get("geometry") or {}
        start, end = geom.get("p0", geom.get("axis_start")), geom.get("p1", geom.get("axis_end"))
        if start is not None and end is not None and len(start) >= 2 and len(end) >= 2:
            p0, p1 = [float(v) for v in start[:3]], [float(v) for v in end[:3]]
            if len(p0) == 2: p0.append(0.0)
            if len(p1) == 2: p1.append(0.0)
        else:
            center = _center(element)
            length = _geom_size(element, "length", "span")
            if center is None or length is None:
                continue
            angle = float(geom.get("rotation_z", 0.0))
            dx, dy = math.cos(angle) * length / 2, math.sin(angle) * length / 2
            p0, p1 = [center[0] - dx, center[1] - dy, center[2]], [center[0] + dx, center[1] + dy, center[2]]
        msp.add_line(p0, p1, dxfattribs={"layer": "SPDS-GIRDERS"})
        msp.add_text(str(element.get("mark") or element.get("id") or f"БК-{index}"),
                     dxfattribs={"layer": "SPDS-GIRDERS", "height": 0.0025 * scale_factor}).set_placement(p0[:2])
    if not girders:
        msp.add_text("ПОДКРАНОВЫЕ БАЛКИ НЕ ПОДТВЕРЖДЕНЫ: НЕТ НАБЛЮДАЕМОЙ ГЕОМЕТРИИ",
                     dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": 0.5}).set_placement((origin_x + 2.0, origin_y + 2.0))

    doc.saveas(out_dxf)
    if out_pdf:
        render_dxf_to_pdf(doc, out_pdf, format_name="A1")
    return out_dxf


def _legacy_generate_sheet_3_transverse_section(
    aligned_data: dict[str, Any],
    out_dxf: str | Path,
    out_pdf: str | Path | None = None,
    project_title: str = "Производственный корпус 1.rcs",
) -> Path:
    """Sheet 3: Поперечный разрез цеха 1-1 (марка АР/КР, М 1:100)."""
    out_dxf = Path(out_dxf)
    out_dxf.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new(dxfversion="R2010")
    setup_spds_layers_and_styles(doc)
    msp = doc.modelspace()

    scale_factor = 100.0 # M 1:100
    y_spans = aligned_data["y_spans"]
    w = max(y_spans) - min(y_spans) if len(y_spans) > 1 else 60.0

    frame_x, frame_y = -15.0, -10.0
    inner_box = draw_spds_sheet_frame(msp, origin_x=frame_x, origin_y=frame_y, format_name="A2", scale_factor=scale_factor)

    draw_spds_title_block(
        msp,
        bottom_right_x=inner_box[2],
        bottom_right_y=inner_box[1],
        project_title=project_title,
        sheet_title="Поперечный разрез цеха 1-1",
        scale_factor=scale_factor,
        stage="Р",
        sheet_num=3,
        total_sheets=4,
    )

    # Base line: clean floor level 0.000
    msp.add_line((-5.0, 0.0, 0.0), (w + 5.0, 0.0, 0.0), dxfattribs={"layer": "SPDS-FRAME"})
    draw_spds_level_mark(msp, -3.0, 0.0, "0.000", scale_factor=scale_factor, shelf_dir=-1)

    # Foundations & Stepped Columns for each span axis
    cyr_letters = ["А", "Б", "В", "Г"]
    bubble_r = 0.005 * scale_factor

    for j, y_pos in enumerate(y_spans):
        # Vertical axis
        msp.add_line((y_pos, -4.0, 0.0), (y_pos, 14.0, 0.0), dxfattribs={"layer": "SPDS-AXES"})
        draw_spds_axis_bubble(msp, y_pos, -5.0, cyr_letters[j % len(cyr_letters)], radius=bubble_r)

        # Foundation block
        msp.add_lwpolyline([
            (y_pos - 1.2, -1.5), (y_pos + 1.2, -1.5),
            (y_pos + 0.8, -0.15), (y_pos - 0.8, -0.15)
        ], close=True, dxfattribs={"layer": "SPDS-COLUMNS"})

        # Lower column shaft (0.000 to +6.200)
        c_w = 0.8 if j == 1 else 0.6 # Middle column is wider
        msp.add_lwpolyline([
            (y_pos - c_w/2, 0.0), (y_pos + c_w/2, 0.0),
            (y_pos + c_w/2, 6.2), (y_pos - c_w/2, 6.2)
        ], close=True, dxfattribs={"layer": "SPDS-COLUMNS"})

        # Upper column shaft (+6.200 to +9.600)
        u_w = 0.4
        msp.add_lwpolyline([
            (y_pos - u_w/2, 6.2), (y_pos + u_w/2, 6.2),
            (y_pos + u_w/2, 9.6), (y_pos - u_w/2, 9.6)
        ], close=True, dxfattribs={"layer": "SPDS-COLUMNS"})

        # Crane girder on console
        if j < len(y_spans) - 1:
            cg_x = y_pos + 0.75
            msp.add_lwpolyline([
                (cg_x - 0.2, 6.2), (cg_x + 0.2, 6.2),
                (cg_x + 0.2, 6.8), (cg_x - 0.2, 6.8)
            ], close=True, dxfattribs={"layer": "SPDS-GIRDERS"})
            # Rail
            msp.add_lwpolyline([
                (cg_x - 0.08, 6.8), (cg_x + 0.08, 6.8),
                (cg_x + 0.08, 6.88), (cg_x - 0.08, 6.88)
            ], close=True, dxfattribs={"layer": "SPDS-GIRDERS"})

    # Elevation marks
    draw_spds_level_mark(msp, -3.0, -1.5, "-1.500", scale_factor=scale_factor, shelf_dir=-1)
    draw_spds_level_mark(msp, y_spans[0] + 0.75, 6.8, "+6.800 (У.Г.Р.)", scale_factor=scale_factor)
    draw_spds_level_mark(msp, -3.0, 9.6, "+9.600", scale_factor=scale_factor, shelf_dir=-1)
    draw_spds_level_mark(msp, (y_spans[0] + y_spans[1]) / 2.0, 11.8, "+11.800 (конек)", scale_factor=scale_factor)

    # Roof trusses across each span
    for j in range(len(y_spans) - 1):
        x1 = y_spans[j]
        x2 = y_spans[j+1]
        x_mid = (x1 + x2) / 2.0
        # Bottom chord
        msp.add_line((x1, 9.6, 0.0), (x2, 9.6, 0.0), dxfattribs={"layer": "SPDS-BRACES"})
        # Top chord with roof slope to ridge
        msp.add_line((x1, 10.2, 0.0), (x_mid, 11.8, 0.0), dxfattribs={"layer": "SPDS-BRACES"})
        msp.add_line((x_mid, 11.8, 0.0), (x2, 10.2, 0.0), dxfattribs={"layer": "SPDS-BRACES"})
        # Truss posts and web diagonals
        for k in range(1, 6):
            pk_x = x1 + (x2 - x1) * (k / 6.0)
            top_y = 10.2 + (1.6 * (pk_x - x1) / (x_mid - x1)) if pk_x <= x_mid else 11.8 - (1.6 * (pk_x - x_mid) / (x2 - x_mid))
            msp.add_line((pk_x, 9.6, 0.0), (pk_x, top_y, 0.0), dxfattribs={"layer": "SPDS-BRACES"})

    # Dimensions between spans
    draw_spds_dimension_chain(msp, y_spans, fixed_coord=-2.0, axis="x", offset=-1.5, tick_size=1.0)

    doc.saveas(out_dxf)
    if out_pdf:
        render_dxf_to_pdf(doc, out_pdf, format_name="A2")
    return out_dxf


def _legacy_generate_sheet_4_roof_structure(
    aligned_data: dict[str, Any],
    out_dxf: str | Path,
    out_pdf: str | Path | None = None,
    project_title: str = "Производственный корпус 1.rcs",
) -> Path:
    """Sheet 4: Схема стропильных ферм и связей покрытия (марка КМ, М 1:200)."""
    out_dxf = Path(out_dxf)
    out_dxf.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new(dxfversion="R2010")
    setup_spds_layers_and_styles(doc)
    msp = doc.modelspace()

    scale_factor = 200.0
    roof = [e for e in aligned_data.get("elements", [])
            if e.get("class_name") in {"truss", "brace", "bracing", "roof_brace"}]
    centers = [_center(e) for e in roof]
    centers = [p for p in centers if p is not None]
    if centers:
        xs = [p[0] for p in centers]
        ys = [p[1] for p in centers]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        origin_x, origin_y = min_x - 25.0, min_y - 20.0
    else:
        origin_x, origin_y = -25.0, -20.0
    inner_box = draw_spds_sheet_frame(msp, origin_x=origin_x, origin_y=origin_y, format_name="A1", scale_factor=scale_factor)

    draw_spds_title_block(
        msp,
        bottom_right_x=inner_box[2],
        bottom_right_y=inner_box[1],
        project_title=project_title,
        sheet_title="Схема стропильных ферм и связей покрытия",
        scale_factor=scale_factor,
        stage="Р",
        sheet_num=4,
        total_sheets=4,
    )

    # Draw only observed roof members. A column grid is not evidence that a
    # truss or diagonal brace exists in the scan.
    for index, element in enumerate(roof, start=1):
        geom = element.get("geometry") or {}
        start, end = geom.get("p0", geom.get("axis_start")), geom.get("p1", geom.get("axis_end"))
        if start is not None and end is not None and len(start) >= 2 and len(end) >= 2:
            p0, p1 = [float(v) for v in start[:3]], [float(v) for v in end[:3]]
            if len(p0) == 2: p0.append(0.0)
            if len(p1) == 2: p1.append(0.0)
        else:
            center = _center(element)
            length = _geom_size(element, "length", "span")
            if center is None or length is None:
                continue
            angle = float(geom.get("rotation_z", math.pi / 2 if element.get("class_name") == "truss" else 0.0))
            dx, dy = math.cos(angle) * length / 2, math.sin(angle) * length / 2
            p0, p1 = [center[0] - dx, center[1] - dy, 0.0], [center[0] + dx, center[1] + dy, 0.0]
        layer = "SPDS-BRACES" if element.get("class_name") in {"brace", "bracing", "roof_brace"} else "SPDS-GIRDERS"
        msp.add_line(p0, p1, dxfattribs={"layer": layer})
        msp.add_text(str(element.get("mark") or element.get("id") or f"Э-{index}"),
                     dxfattribs={"layer": layer, "height": 0.0025 * scale_factor}).set_placement(p0[:2])
    if not roof:
        msp.add_text("ФЕРМЫ И СВЯЗИ НЕ ПОДТВЕРЖДЕНЫ: НЕТ НАБЛЮДАЕМОЙ ГЕОМЕТРИИ",
                     dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": 0.5}).set_placement((origin_x + 2.0, origin_y + 2.0))

    doc.saveas(out_dxf)
    if out_pdf:
        render_dxf_to_pdf(doc, out_pdf, format_name="A1")
    return out_dxf


def _legacy_generate_full_spds_album(
    elements: list[dict[str, Any]],
    output_dir: str | Path,
    project_title: str = "Производственный корпус 1.rcs",
) -> dict[str, Any]:
    """Generate all 4 engineering sheets in DXF and PDF and assemble album."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    aligned = align_elements_to_grid(elements)

    sheets = [
        {
            "num": 1,
            "title": "План расположения колонн цеха на отм. 0.000",
            "dxf_path": str(out_dir / "01_plan_kolonn_SPDS.dxf"),
            "pdf_path": str(out_dir / "01_plan_kolonn_SPDS.pdf"),
            "generator": _legacy_generate_sheet_1_columns_plan,
        },
        {
            "num": 2,
            "title": "План подкрановых балок и путей на отм. +6.800",
            "dxf_path": str(out_dir / "02_plan_podkranovyh_balok_SPDS.dxf"),
            "pdf_path": str(out_dir / "02_plan_podkranovyh_balok_SPDS.pdf"),
            "generator": _legacy_generate_sheet_2_crane_plan,
        },
        {
            "num": 3,
            "title": "Поперечный разрез цеха 1-1",
            "dxf_path": str(out_dir / "03_razrez_ceha_1-1_SPDS.dxf"),
            "pdf_path": str(out_dir / "03_razrez_ceha_1-1_SPDS.pdf"),
            "generator": _legacy_generate_sheet_3_transverse_section,
        },
        {
            "num": 4,
            "title": "Схема стропильных ферм и связей покрытия",
            "dxf_path": str(out_dir / "04_shema_ferm_i_svyazei_SPDS.dxf"),
            "pdf_path": str(out_dir / "04_shema_ferm_i_svyazei_SPDS.pdf"),
            "generator": _legacy_generate_sheet_4_roof_structure,
        },
        {
            "num": 5,
            "title": "Исполнительная схема отклонений колонн (СП 70.13330)",
            "dxf_path": str(out_dir / "05_ispolnitelnaya_shema_otkloneniy_SPDS.dxf"),
            "pdf_path": str(out_dir / "05_ispolnitelnaya_shema_otkloneniy_SPDS.pdf"),
            "generator": generate_sheet_5_executive_deviation_scheme,
        },
    ]

    for s in sheets:
        s["generator"](aligned, s["dxf_path"], s["pdf_path"], project_title=project_title)

    # Automatically compile native binary DWG for each sheet if AutoCAD is available
    try:
        from .dwg_compiler import batch_convert_album_to_dwg
        batch_convert_album_to_dwg(out_dir)
        for s in sheets:
            expected_dwg = Path(s["dxf_path"]).with_suffix(".dwg")
            if expected_dwg.is_file():
                s["dwg_path"] = str(expected_dwg)
    except Exception as exc:
        logger.warning("AutoCAD binary DWG compilation skipped: %s", exc)

    album_pdf = out_dir / "ALBUM_RD_KR_KM_SPDS.pdf"
    # Copy or combine into album (first sheet or merge if pypdf available)
    try:
        from pypdf import PdfWriter
        merger = PdfWriter()
        for s in sheets:
            merger.append(s["pdf_path"])
        merger.write(str(album_pdf))
        merger.close()
    except Exception:
        import shutil
        shutil.copy2(sheets[0]["pdf_path"], album_pdf)

    manifest_file = out_dir / "spds_album_manifest.json"
    manifest_data = {
        "status": "success",
        "sheets": sheets,
        "album_pdf_path": str(album_pdf),
        "aligned_summary": {
            "rotation_deg": aligned["rot_angle_deg"],
            "bays_count": len(aligned["x_bays"]),
            "spans_count": len(aligned["y_spans"]),
        },
    }
    manifest_file.write_text(json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "status": "success",
        "sheets": sheets,
        "manifest_path": str(manifest_file),
        "album_pdf_path": str(album_pdf),
        "aligned_summary": manifest_data["aligned_summary"],
    }
