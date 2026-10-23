"""SP 70.13330 (Bearing and enclosing structures) compliance and deformation analysis.

Computes column verticality tilt (крен колонны), horizontal deflection (стрела прогиба),
and surface deviation heatmaps (тепловые карты отклонений от проекта) with
pass/fail limits defined by Russian construction standard СП 70.13330.2012.
"""
from __future__ import annotations

import math
from typing import Any
import numpy as np


def compute_column_verticality_inspection(
    column_id: str,
    points: np.ndarray,
    column_height_m: float,
    material_type: str = "steel",  # "steel" or "reinforced_concrete"
    storey_count: int = 1,
) -> dict[str, Any]:
    """Compute verticality tolerance according to СП 70.13330.2012 Table 4.9 / Table 5.12.

    Parameters:
    - column_id: Identifier of the structural element.
    - points: Nx3 array of point cloud positions associated with this column.
    - column_height_m: Total column height H in meters.
    - material_type: 'steel' (СП 70.13330 Таблица 4.9) or 'reinforced_concrete' (Таблица 5.12).
    - storey_count: Number of storeys (for multi-storey buildings).

    Returns:
    - Dict with top_deviation_mm, tilt_angle_arcmin, limit_deviation_mm, status ('compliant'/'exceeded'),
      and elevation-binned horizontal deflections.
    """
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 20:
        raise ValueError(f"Not enough points ({len(pts)}) to inspect column {column_id}")
    if column_height_m <= 0 or not math.isfinite(column_height_m):
        raise ValueError("column_height_m must be a positive finite number")

    # Sort points along Z axis
    z_min = float(np.min(pts[:, 2]))
    z_max = float(np.max(pts[:, 2]))
    actual_span_z = z_max - z_min

    # Fit linear centerline along Z
    poly_x = np.polyfit(pts[:, 2], pts[:, 0], 1)
    poly_y = np.polyfit(pts[:, 2], pts[:, 1], 1)

    dx_span = float(np.polyval(poly_x, z_max) - np.polyval(poly_x, z_min))
    dy_span = float(np.polyval(poly_y, z_max) - np.polyval(poly_y, z_min))

    # Extrapolate/scale tilt across nominal column height
    scale = (column_height_m / actual_span_z) if actual_span_z > 0 else 1.0
    dx = dx_span * scale
    dy = dy_span * scale

    horizontal_offset_m = math.hypot(dx, dy)
    horizontal_offset_mm = horizontal_offset_m * 1000.0

    tilt_angle_rad = math.atan2(math.hypot(dx_span, dy_span), max(0.01, actual_span_z))
    tilt_angle_arcmin = float(math.degrees(tilt_angle_rad) * 60.0)

    base_center = np.array([float(np.polyval(poly_x, z_min)), float(np.polyval(poly_y, z_min)), z_min])

    # СП 70.13330.2012 limit computation:
    # Steel columns (Таблица 4.9 п. 2):
    # Отклонение от вертикали верха колонны:
    # при длине до 15 м: H / 1000, но не более 15 мм
    # при длине свыше 15 м: 15 мм + 0.5 * (H - 15) в мм
    h_m = column_height_m
    if material_type == "steel":
        if h_m <= 15.0:
            limit_mm = min(15.0, (h_m * 1000.0) / 1000.0)
            limit_mm = max(5.0, limit_mm)  # minimum standard tolerance
        else:
            limit_mm = 15.0 + 0.5 * (h_m - 15.0)
        sp_clause = "СП 70.13330.2012 Таблица 4.9 п.2"
    else:
        # Reinforced concrete (Таблица 5.12):
        # Отклонение линий плоскостей пересечений от вертикали или проектного наклона на один этаж:
        # 15 мм для колонн
        limit_mm = 15.0
        sp_clause = "СП 70.13330.2012 Таблица 5.12 п.1"

    is_compliant = horizontal_offset_mm <= limit_mm

    # Elevation deflection profile (slices every 1 meter)
    elevation_slices = []
    num_slices = max(3, int(actual_span_z / 1.0))
    for s_i in range(num_slices):
        z_curr = z_min + (s_i + 0.5) * (actual_span_z / num_slices)
        mask = np.abs(pts[:, 2] - z_curr) <= (actual_span_z / (2 * num_slices))
        if np.sum(mask) >= 3:
            sl_pts = pts[mask]
            center_curr = np.mean(sl_pts, axis=0)
            # Theoretical plumb line from base_center
            ideal_x = base_center[0]
            ideal_y = base_center[1]
            dev_mm = math.hypot(center_curr[0] - ideal_x, center_curr[1] - ideal_y) * 1000.0
            elevation_slices.append({
                "elevation_z_m": float(z_curr),
                "center_x_m": float(center_curr[0]),
                "center_y_m": float(center_curr[1]),
                "deviation_mm": float(round(dev_mm, 2)),
            })

    return {
        "column_id": column_id,
        "material_type": material_type,
        "standard_clause": sp_clause,
        "measured_height_m": float(round(actual_span_z, 3)),
        "nominal_height_m": float(round(column_height_m, 3)),
        "top_deviation_dx_mm": float(round(dx * 1000.0, 2)),
        "top_deviation_dy_mm": float(round(dy * 1000.0, 2)),
        "top_deviation_total_mm": float(round(horizontal_offset_mm, 2)),
        "limit_deviation_mm": float(round(limit_mm, 2)),
        "tilt_angle_arcmin": float(round(tilt_angle_arcmin, 2)),
        "status": "compliant" if is_compliant else "exceeded",
        "margin_mm": float(round(limit_mm - horizontal_offset_mm, 2)),
        "elevation_slices": elevation_slices,
    }
