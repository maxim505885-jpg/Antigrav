"""Full SPDS Working Documentation (РД) Plan generator for steel columns and axes.

Conforms to:
- ГОСТ 21.501-2018 (Правила выполнения архитектурно-строительных рабочих чертежей)
- ГОСТ 21.101-2020 (Основные требования к проектной и рабочей документации)
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any
import numpy as np
import ezdxf

from .spds import (
    setup_spds_layers_and_styles,
    draw_spds_sheet_frame,
    draw_spds_title_block,
    draw_spds_axis_bubble,
    draw_spds_dimension_chain,
)


def export_spds_structural_plan_dxf(
    elements: list[dict[str, Any]],
    out_path: str | Path,
    project_title: str = "Производственный цех 1.rcs",
    sheet_title: str = "Схема расположения колонн и осей",
    sheet_format: str = "A3",
    scale: int = 100,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = ezdxf.new(dxfversion="R2010")
    setup_spds_layers_and_styles(doc)
    msp = doc.modelspace()

    # Filter columns with valid oriented_box geometry
    columns = [
        el for el in elements
        if el.get("class_name") == "column" and (el.get("geometry") or {}).get("kind") == "oriented_box"
    ]

    centers = []
    for c in columns:
        centers.append(c["geometry"]["center"][:2])
    centers = np.array(centers) if centers else np.zeros((0, 2))

    # Calculate bounding box
    if len(centers) > 0:
        min_x, min_y = float(centers[:, 0].min()), float(centers[:, 1].min())
        max_x, max_y = float(centers[:, 0].max()), float(centers[:, 1].max())
    else:
        min_x, min_y, max_x, max_y = 0.0, 0.0, 100.0, 50.0

    pad = 5.0
    model_w = (max_x - min_x) + pad * 2
    model_h = (max_y - min_y) + pad * 2

    # Scale factor for sheet border in model units (for scale 1:100, 1 mm sheet = 0.1 m model space)
    scale_factor = float(scale)

    # Place sheet frame
    frame_x = min_x - pad - 10.0
    frame_y = min_y - pad - 10.0
    inner_box = draw_spds_sheet_frame(msp, origin_x=frame_x, origin_y=frame_y, format_name=sheet_format, scale_factor=scale_factor)

    # Draw Title Block (185 x 55 mm)
    draw_spds_title_block(
        msp,
        bottom_right_x=inner_box[2],
        bottom_right_y=inner_box[1],
        project_title=project_title,
        sheet_title=sheet_title,
        scale_factor=scale_factor,
        stage="Р",
        sheet_num=1,
        total_sheets=1,
    )

    # Draw columns footprints
    for col in columns:
        geom = col["geometry"]
        cx, cy = float(geom["center"][0]), float(geom["center"][1])
        length = float(geom["sizes"]["length"])
        thick = float(geom["sizes"]["thickness"])
        angle = float(geom.get("rotation_z", 0.0))

        ca, sa = math.cos(angle), math.sin(angle)
        corners = [
            (cx + lx * ca - ly * sa, cy + lx * sa + ly * ca)
            for lx, ly in (
                (-length / 2, -thick / 2),
                (length / 2, -thick / 2),
                (length / 2, thick / 2),
                (-length / 2, thick / 2),
            )
        ]
        msp.add_lwpolyline(corners, close=True, dxfattribs={"layer": "SPDS-COLUMNS"})

    # Grid axes clustering along X and Y
    if len(centers) > 0:
        # X-axes (numerical: 1, 2, 3...)
        sorted_x = np.sort(centers[:, 0])
        x_clusters: list[float] = []
        for x_val in sorted_x:
            if not x_clusters or abs(x_val - x_clusters[-1]) > 3.0:
                x_clusters.append(float(x_val))

        # Y-axes (alphabetical: А, Б, В, Г...)
        sorted_y = np.sort(centers[:, 1])
        y_clusters: list[float] = []
        for y_val in sorted_y:
            if not y_clusters or abs(y_val - y_clusters[-1]) > 3.0:
                y_clusters.append(float(y_val))

        # Draw X-axes lines and bubbles
        bubble_r = 0.005 * scale_factor  # 5 mm on sheet
        for i, x_val in enumerate(x_clusters[:25], start=1):
            axis_bottom = min_y - pad * 0.5
            axis_top = max_y + pad * 0.5
            msp.add_line((x_val, axis_bottom, 0.0), (x_val, axis_top, 0.0), dxfattribs={"layer": "SPDS-AXES"})
            draw_spds_axis_bubble(msp, x_val, axis_bottom - bubble_r * 1.5, str(i), radius=bubble_r)
            draw_spds_axis_bubble(msp, x_val, axis_top + bubble_r * 1.5, str(i), radius=bubble_r)

        # Draw Y-axes lines and bubbles
        cyr_letters = ["А", "Б", "В", "Г", "Д", "Е", "Ж", "И", "К", "Л"]
        for j, y_val in enumerate(y_clusters[:10]):
            axis_left = min_x - pad * 0.5
            axis_right = max_x + pad * 0.5
            msp.add_line((axis_left, y_val, 0.0), (axis_right, y_val, 0.0), dxfattribs={"layer": "SPDS-AXES"})
            lbl = cyr_letters[j % len(cyr_letters)]
            draw_spds_axis_bubble(msp, axis_left - bubble_r * 1.5, y_val, lbl, radius=bubble_r)
            draw_spds_axis_bubble(msp, axis_right + bubble_r * 1.5, y_val, lbl, radius=bubble_r)

        # Dimension chains
        if len(x_clusters) >= 2:
            draw_spds_dimension_chain(
                msp,
                x_clusters[:15],
                fixed_coord=min_y - pad * 0.5,
                axis="x",
                offset=-bubble_r * 4.0,
                tick_size=bubble_r * 0.5
            )

    doc.saveas(out_path)
    return out_path
