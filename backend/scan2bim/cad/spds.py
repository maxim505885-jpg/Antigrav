"""SPDS drafting primitives for Russian Working Documentation (РД).

Conforms to:
- ГОСТ 21.101-2020 (СПДС. Основные требования к проектной и рабочей документации)
  Форма 3 - Основная надпись (185 x 55 мм)
- ГОСТ 21.501-2018 (СПДС. Правила выполнения рабочей документации архитектурных
  и конструктивных решений)
  Форма 1 - Ведомость элементов
- ГОСТ 2.307-2011 (Нанесение размеров)
"""
from __future__ import annotations

import math
from typing import Any
import ezdxf


# Standard sheet sizes in mm: (width, height)
SHEET_SIZES_MM: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "A0": (1189.0, 841.0),
}


def setup_spds_layers_and_styles(doc: ezdxf.document.Drawing) -> None:
    """Register standard SPDS layers with standard line weights and colors."""
    layers = {
        "SPDS-AXES": {"color": 1, "lineweight": 18, "linetype": "DASHDOT"},       # Осевые линии (красный тонкий)
        "SPDS-AXES-BUBBLES": {"color": 7, "lineweight": 35, "linetype": "Continuous"}, # Кружки осей
        "SPDS-DIMS": {"color": 3, "lineweight": 18, "linetype": "Continuous"},       # Размерные цепочки (зеленый тонкий)
        "SPDS-FRAME": {"color": 7, "lineweight": 70, "linetype": "Continuous"},      # Основная рамка листа (толстая 0.7 мм)
        "SPDS-FRAME-INNER": {"color": 7, "lineweight": 35, "linetype": "Continuous"}, # Внутренние линии рамки
        "SPDS-STAMP": {"color": 7, "lineweight": 70, "linetype": "Continuous"},      # Границы штампа 185x55
        "SPDS-STAMP-TEXT": {"color": 7, "lineweight": 25, "linetype": "Continuous"}, # Текст штампа
        "SPDS-COLUMNS": {"color": 4, "lineweight": 50, "linetype": "Continuous"},    # Несущие колонны (толстый контур)
        "SPDS-GIRDERS": {"color": 5, "lineweight": 50, "linetype": "Continuous"},    # Подкрановые балки
        "SPDS-BRACES": {"color": 6, "lineweight": 35, "linetype": "Continuous"},     # Связи и фермы
        "SPDS-TABLE": {"color": 7, "lineweight": 35, "linetype": "Continuous"},      # Таблицы ведомостей
    }
    for name, attrs in layers.items():
        if name not in doc.layers:
            doc.layers.add(name, color=attrs["color"], lineweight=attrs["lineweight"], linetype=attrs.get("linetype", "Continuous"))

    # Ensure font style uses clean sans-serif/ISOCPEUR
    standard_style = doc.styles.get("Standard")
    if standard_style:
        standard_style.dxf.font = "isocpeur.ttf"


def draw_spds_sheet_frame(
    msp: Any,
    origin_x: float,
    origin_y: float,
    format_name: str = "A3",
    scale_factor: float = 1.0,
) -> tuple[float, float, float, float]:
    """Draw sheet outer border and inner margin border (20mm left, 5mm other sides).

    Returns inner usable bounding box: (min_x, min_y, max_x, max_y) in drawing units.
    """
    w_mm, h_mm = SHEET_SIZES_MM.get(format_name.upper(), (420.0, 297.0))
    w = (w_mm / 1000.0) * scale_factor
    h = (h_mm / 1000.0) * scale_factor

    # Outer sheet cut line (тонкая)
    msp.add_lwpolyline(
        [(origin_x, origin_y), (origin_x + w, origin_y), (origin_x + w, origin_y + h), (origin_x, origin_y + h)],
        close=True,
        dxfattribs={"layer": "SPDS-FRAME-INNER"}
    )

    # Margins: Left = 20 mm, Right = 5 mm, Top = 5 mm, Bottom = 5 mm
    m_left = (0.020) * scale_factor
    m_right = (0.005) * scale_factor
    m_top = (0.005) * scale_factor
    m_bottom = (0.005) * scale_factor

    inner_x0 = origin_x + m_left
    inner_y0 = origin_y + m_bottom
    inner_x1 = origin_x + w - m_right
    inner_y1 = origin_y + h - m_top

    # Inner thick border (0.7 mm)
    msp.add_lwpolyline(
        [(inner_x0, inner_y0), (inner_x1, inner_y0), (inner_x1, inner_y1), (inner_x0, inner_y1)],
        close=True,
        dxfattribs={"layer": "SPDS-FRAME"}
    )
    return (inner_x0, inner_y0, inner_x1, inner_y1)


def draw_spds_title_block(
    msp: Any,
    bottom_right_x: float,
    bottom_right_y: float,
    project_title: str,
    sheet_title: str,
    scale_factor: float = 1.0,
    org_name: str = "Intelligent Scan-to-BIM",
    stage: str = "Р",
    sheet_num: int = 1,
    total_sheets: int = 1,
) -> None:
    """Draw standard ГОСТ 21.101-2020 Form 3 title block (185 x 55 mm)."""
    s = scale_factor
    stamp_w = 0.185 * s
    stamp_h = 0.055 * s

    x0 = bottom_right_x - stamp_w
    y0 = bottom_right_y
    x1 = bottom_right_x
    y1 = bottom_right_y + stamp_h

    # Outer border of stamp
    msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": "SPDS-STAMP"})

    # Key horizontal dividing lines
    line_y_15 = y0 + 0.015 * s
    line_y_20 = y0 + 0.020 * s
    line_y_35 = y0 + 0.035 * s
    msp.add_line((x0, line_y_15, 0.0), (x1, line_y_15, 0.0), dxfattribs={"layer": "SPDS-STAMP"})
    msp.add_line((x0 + 0.120 * s, line_y_20, 0.0), (x1, line_y_20, 0.0), dxfattribs={"layer": "SPDS-STAMP"})
    msp.add_line((x0 + 0.120 * s, line_y_35, 0.0), (x1, line_y_35, 0.0), dxfattribs={"layer": "SPDS-STAMP"})

    # Left signature columns (65 mm total: 7 + 10 + 23 + 15 + 10)
    col_x = x0 + 0.065 * s
    msp.add_line((col_x, y0, 0.0), (col_x, y1, 0.0), dxfattribs={"layer": "SPDS-STAMP"})

    # Column: Stage, Sheet, Sheets (15, 15, 15 mm)
    c_stage_x = x0 + 0.120 * s
    msp.add_line((c_stage_x, line_y_15, 0.0), (c_stage_x, line_y_35, 0.0), dxfattribs={"layer": "SPDS-STAMP"})
    c_sheet_x = c_stage_x + 0.015 * s
    msp.add_line((c_sheet_x, line_y_15, 0.0), (c_sheet_x, line_y_35, 0.0), dxfattribs={"layer": "SPDS-STAMP"})
    c_sheets_x = c_sheet_x + 0.015 * s
    msp.add_line((c_sheets_x, line_y_15, 0.0), (c_sheets_x, line_y_35, 0.0), dxfattribs={"layer": "SPDS-STAMP"})

    # Roles table text
    txt_h = 0.0022 * s
    msp.add_text("Разраб.", dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": txt_h}).set_placement((x0 + 0.002 * s, y0 + 0.030 * s))
    msp.add_text("Инженер", dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": txt_h}).set_placement((x0 + 0.020 * s, y0 + 0.030 * s))
    msp.add_text("Пров.", dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": txt_h}).set_placement((x0 + 0.002 * s, y0 + 0.022 * s))
    msp.add_text("Ведущий", dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": txt_h}).set_placement((x0 + 0.020 * s, y0 + 0.022 * s))
    msp.add_text("ГИП", dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": txt_h}).set_placement((x0 + 0.002 * s, y0 + 0.004 * s))
    msp.add_text("Главный", dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": txt_h}).set_placement((x0 + 0.020 * s, y0 + 0.004 * s))

    # Stage / Sheet / Sheets headers & values
    msp.add_text("Стадия", dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": txt_h}).set_placement((c_stage_x + 0.002 * s, line_y_35 - 0.004 * s))
    msp.add_text(stage, dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": txt_h * 1.5}).set_placement((c_stage_x + 0.004 * s, line_y_20 + 0.004 * s))

    msp.add_text("Лист", dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": txt_h}).set_placement((c_sheet_x + 0.002 * s, line_y_35 - 0.004 * s))
    msp.add_text(str(sheet_num), dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": txt_h * 1.5}).set_placement((c_sheet_x + 0.005 * s, line_y_20 + 0.004 * s))

    msp.add_text("Листов", dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": txt_h}).set_placement((c_sheets_x + 0.001 * s, line_y_35 - 0.004 * s))
    msp.add_text(str(total_sheets), dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": txt_h * 1.5}).set_placement((c_sheets_x + 0.004 * s, line_y_20 + 0.004 * s))

    # Project and Sheet titles
    proj_h = 0.0035 * s
    msp.add_text(project_title[:45], dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": proj_h}).set_placement((col_x + 0.003 * s, y0 + 0.045 * s))
    msp.add_text(sheet_title[:45], dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": proj_h * 1.1}).set_placement((col_x + 0.003 * s, y0 + 0.038 * s))

    # Organization block
    msp.add_text(org_name, dxfattribs={"layer": "SPDS-STAMP-TEXT", "height": proj_h}).set_placement((c_stage_x + 0.003 * s, y0 + 0.005 * s))


def draw_spds_axis_bubble(
    msp: Any,
    center_x: float,
    center_y: float,
    label: str,
    radius: float = 0.5,
) -> None:
    """Draw a circular SPDS axis bubble with centered label."""
    msp.add_circle((center_x, center_y, 0.0), radius=radius, dxfattribs={"layer": "SPDS-AXES-BUBBLES"})
    # Label height approximately 60-70% of diameter
    th = radius * 1.2
    t = msp.add_text(label, dxfattribs={"layer": "SPDS-AXES-BUBBLES", "height": th})
    # Center text placement
    t.dxf.halign = 1  # Center
    t.dxf.valign = 2  # Middle
    t.dxf.align_point = (center_x, center_y, 0.0)


def draw_spds_dimension_chain(
    msp: Any,
    points_along: list[float],
    fixed_coord: float,
    axis: str = "x",
    offset: float = 1.5,
    tick_size: float = 0.25,
) -> None:
    """Draw standard SPDS dimension chain with 45-degree ticks."""
    if len(points_along) < 2:
        return
    pts = sorted(set(points_along))

    # Baseline dimension line
    line_coord = fixed_coord + offset
    if axis == "x":
        p_start = (pts[0], line_coord, 0.0)
        p_end = (pts[-1], line_coord, 0.0)
    else:
        p_start = (line_coord, pts[0], 0.0)
        p_end = (line_coord, pts[-1], 0.0)

    msp.add_line(p_start, p_end, dxfattribs={"layer": "SPDS-DIMS"})

    # Ticks and values
    for i, val in enumerate(pts):
        if axis == "x":
            # Extension line from object to dimension line
            msp.add_line((val, fixed_coord, 0.0), (val, line_coord + tick_size * 0.8, 0.0), dxfattribs={"layer": "SPDS-DIMS"})
            # 45-deg tick
            msp.add_line(
                (val - tick_size * 0.707, line_coord - tick_size * 0.707, 0.0),
                (val + tick_size * 0.707, line_coord + tick_size * 0.707, 0.0),
                dxfattribs={"layer": "SPDS-DIMS"}
            )
        else:
            msp.add_line((fixed_coord, val, 0.0), (line_coord + tick_size * 0.8, val, 0.0), dxfattribs={"layer": "SPDS-DIMS"})
            msp.add_line(
                (line_coord - tick_size * 0.707, val - tick_size * 0.707, 0.0),
                (line_coord + tick_size * 0.707, val + tick_size * 0.707, 0.0),
                dxfattribs={"layer": "SPDS-DIMS"}
            )

        # Dimension text (length between consecutive points) in mm
        if i < len(pts) - 1:
            segment_len_mm = round(abs(pts[i+1] - val) * 1000.0)
            text_str = f"{segment_len_mm:.0f}"
            mid_val = (val + pts[i+1]) / 2.0
            th = tick_size * 0.9
            if axis == "x":
                t = msp.add_text(text_str, dxfattribs={"layer": "SPDS-DIMS", "height": th})
                t.dxf.halign = 1
                t.dxf.align_point = (mid_val, line_coord + th * 0.3, 0.0)
            else:
                t = msp.add_text(text_str, dxfattribs={"layer": "SPDS-DIMS", "height": th, "rotation": 90})
                t.dxf.halign = 1
                t.dxf.align_point = (line_coord + th * 0.3, mid_val, 0.0)
