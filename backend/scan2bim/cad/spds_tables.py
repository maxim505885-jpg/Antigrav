"""SPDS Table generators according to GOST 21.501-2018:
- Спецификация элементов к схеме расположения (Форма 7 по ГОСТ 21.501-2018)
- Ведомость расхода стали (ВРС по ГОСТ 21.501-2018)
"""
from __future__ import annotations

from typing import Any
import ezdxf


def draw_spds_specification_table(
    msp: Any,
    top_right_x: float,
    top_right_y: float,
    items: list[dict[str, Any]],
    scale_factor: float = 200.0,
    title: str = "Спецификация к схеме расположения элементов",
) -> float:
    """Draw standard GOST 21.501-2018 Form 7 Specification Table.
    
    Columns (standard width in mm):
    - Поз. (15 мм)
    - Обозначение (60 мм)
    - Наименование (65 мм)
    - Кол. (10 мм)
    - Масса ед. кг (15 мм)
    - Примечание (20 мм)
    Total width = 185 мм (matches title block 185 mm!).
    Header height = 15 мм, row height = 8 мм.
    """
    s = scale_factor / 1000.0  # mm to model meters

    col_widths_mm = [15.0, 60.0, 65.0, 10.0, 15.0, 20.0]
    total_w_mm = sum(col_widths_mm)  # 185 mm
    col_widths = [w * s for w in col_widths_mm]
    total_w = total_w_mm * s

    x0 = top_right_x - total_w
    y0 = top_right_y

    header_h = 14.0 * s
    row_h = 8.0 * s
    total_h = header_h + len(items) * row_h

    # Table Title
    msp.add_text(
        title,
        dxfattribs={
            "layer": "SPDS-TEXT",
            "style": "SPDS_TITLE",
            "height": 3.5 * s,
            "color": 7,
        },
    ).set_placement((x0, y0 + 3.0 * s))

    # Outer border
    pts = [
        (x0, y0),
        (x0 + total_w, y0),
        (x0 + total_w, y0 - total_h),
        (x0, y0 - total_h),
    ]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "SPDS-TITLE", "color": 7})

    # Header horizontal line
    msp.add_line((x0, y0 - header_h), (x0 + total_w, y0 - header_h), dxfattribs={"layer": "SPDS-TITLE", "color": 7})

    # Column vertical separators
    curr_x = x0
    for w in col_widths[:-1]:
        curr_x += w
        msp.add_line((curr_x, y0), (curr_x, y0 - total_h), dxfattribs={"layer": "SPDS-TITLE", "color": 7})

    # Column header titles
    headers = ["Поз.", "Обозначение", "Наименование", "Кол.", "Масса\nед. кг", "Прим."]
    curr_x = x0
    for w, h_text in zip(col_widths, headers):
        text_lines = h_text.split("\n")
        line_offset = 0
        for line in text_lines:
            msp.add_text(
                line,
                dxfattribs={
                    "layer": "SPDS-TEXT",
                    "style": "SPDS_TEXT",
                    "height": 2.5 * s,
                    "color": 7,
                },
            ).set_placement((curr_x + w * 0.1, y0 - 6.0 * s - line_offset))
            line_offset += 3.5 * s
        curr_x += w

    # Rows
    curr_y = y0 - header_h
    for item in items:
        # row bottom line
        msp.add_line((x0, curr_y - row_h), (x0 + total_w, curr_y - row_h), dxfattribs={"layer": "SPDS-TITLE", "color": 7})
        
        row_vals = [
            str(item.get("pos", "")),
            str(item.get("designation", "")),
            str(item.get("name", "")),
            str(item.get("count", "")),
            str(item.get("mass", "")),
            str(item.get("comment", "")),
        ]
        curr_x = x0
        for w, val in zip(col_widths, row_vals):
            msp.add_text(
                val,
                dxfattribs={
                    "layer": "SPDS-TEXT",
                    "style": "SPDS_TEXT",
                    "height": 2.5 * s,
                    "color": 7,
                },
            ).set_placement((curr_x + 1.5 * s, curr_y - 5.5 * s))
            curr_x += w
        curr_y -= row_h

    return y0 - total_h


def draw_spds_tolerance_schedule_table(
    msp: Any,
    top_right_x: float,
    top_right_y: float,
    rows: list[dict[str, Any]],
    scale_factor: float = 200.0,
    title: str = "Ведомость отклонений колонн от разбивочных осей (СП 70.13330)",
) -> float:
    """Draw Executive Tolerance Schedule table according to SP 70.13330.2012 / GOST R 51872-2019.

    Columns:
    - Поз. (15 мм)
    - Ряд/Ось (30 мм)
    - ΔU, мм (20 мм)
    - ΔV, мм (20 мм)
    - ΔR, мм (20 мм)
    - Допуск СП 70 (35 мм)
    - Оценка (45 мм)
    Total width = 185 мм.
    """
    s = scale_factor / 1000.0

    col_widths_mm = [15.0, 30.0, 20.0, 20.0, 20.0, 35.0, 45.0]
    total_w_mm = sum(col_widths_mm)  # 185.0 mm
    col_widths = [w * s for w in col_widths_mm]
    total_w = total_w_mm * s

    x0 = top_right_x - total_w
    y0 = top_right_y

    header_h = 14.0 * s
    row_h = 7.0 * s
    total_h = header_h + len(rows) * row_h

    msp.add_text(
        title,
        dxfattribs={
            "layer": "SPDS-TEXT",
            "style": "SPDS_TITLE",
            "height": 3.2 * s,
            "color": 7,
        },
    ).set_placement((x0, y0 + 3.0 * s))

    # Outer border
    pts = [
        (x0, y0),
        (x0 + total_w, y0),
        (x0 + total_w, y0 - total_h),
        (x0, y0 - total_h),
    ]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "SPDS-TITLE", "color": 7})
    msp.add_line((x0, y0 - header_h), (x0 + total_w, y0 - header_h), dxfattribs={"layer": "SPDS-TITLE", "color": 7})

    # Vertical separators
    curr_x = x0
    for w in col_widths[:-1]:
        curr_x += w
        msp.add_line((curr_x, y0), (curr_x, y0 - total_h), dxfattribs={"layer": "SPDS-TITLE", "color": 7})

    headers = [
        "Поз.",
        "Ряд / Ось",
        "ΔU, мм",
        "ΔV, мм",
        "ΔR, мм",
        "Допуск СП 70",
        "Заключение",
    ]
    curr_x = x0
    for w, h_text in zip(col_widths, headers):
        msp.add_text(
            h_text,
            dxfattribs={
                "layer": "SPDS-TEXT",
                "style": "SPDS_TEXT",
                "height": 2.3 * s,
                "color": 7,
            },
        ).set_placement((curr_x + 1.5 * s, y0 - 8.0 * s))
        curr_x += w

    curr_y = y0 - header_h
    for item in rows:
        msp.add_line((x0, curr_y - row_h), (x0 + total_w, curr_y - row_h), dxfattribs={"layer": "SPDS-TITLE", "color": 7})
        row_vals = [
            str(item.get("pos", "")),
            str(item.get("grid", "")),
            str(item.get("delta_u", "")),
            str(item.get("delta_v", "")),
            str(item.get("delta_r", "")),
            str(item.get("tolerance", "±15 мм")),
            str(item.get("status", "")),
        ]
        curr_x = x0
        for w, val in zip(col_widths, row_vals):
            msp.add_text(
                val,
                dxfattribs={
                    "layer": "SPDS-TEXT",
                    "style": "SPDS_TEXT",
                    "height": 2.2 * s,
                    "color": 7,
                },
            ).set_placement((curr_x + 1.2 * s, curr_y - 5.0 * s))
            curr_x += w
        curr_y -= row_h

    return y0 - total_h

