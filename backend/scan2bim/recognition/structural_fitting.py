"""Fitted structural frame extractor: extracts actual crane beam axes and roof truss positions
directly from cloud points, complementing column recognition.
"""
from __future__ import annotations

import math
from typing import Any
import numpy as np


def extract_actual_workshop_structural_members(
    positions: np.ndarray,
    rotation_deg: float = -10.23,
) -> dict[str, Any]:
    """Analyze cloud points in workshop coordinate system and return fitted axes of:
    - Crane beams / rail tracks (at Z ~ +3.8..+4.3 m)
    - Roof truss planes (at Z ~ +6.2..+7.2 m, stepped along X at ~6 m bays)
    """
    theta = math.radians(rotation_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    R = np.array([[cos_t, -sin_t], [sin_t, cos_t]], dtype=np.float64)

    # 1. Подкрановые балки: Z [3.7 .. 4.5]
    mask_crane = (positions[:, 2] >= 3.7) & (positions[:, 2] <= 4.5)
    crane_pts = positions[mask_crane]
    crane_xy_rot = crane_pts[:, :2] @ R.T

    # Кластеризация направляющих вдоль оси Y (пролеты цеха)
    # Ожидаемые линии пролетов в локальной СК цеха: Y ~ -4.5, +6.0 и т.д.
    crane_rails = []
    for y_center in [-3.5, 6.0]:
        near = np.abs(crane_xy_rot[:, 1] - y_center) < 1.2
        if np.sum(near) > 10000:
            actual_y = float(np.median(crane_xy_rot[near, 1]))
            x_min = float(np.percentile(crane_xy_rot[near, 0], 1))
            x_max = float(np.percentile(crane_xy_rot[near, 0], 99))
            crane_rails.append({
                "type": "crane_rail",
                "y_local_m": round(actual_y, 3),
                "z_local_m": round(float(np.median(crane_pts[near, 2])), 3),
                "span_x_start_m": round(x_min, 2),
                "span_x_end_m": round(x_max, 2),
                "length_m": round(x_max - x_min, 2),
                "point_count": int(np.sum(near)),
            })

    # 2. Стропильные фермы кровли: Z [6.2 .. 7.5]
    mask_roof = (positions[:, 2] >= 6.2) & (positions[:, 2] <= 7.5)
    roof_pts = positions[mask_roof]
    roof_xy_rot = roof_pts[:, :2] @ R.T

    # Поиск шагов ферм по оси X (шаг ~6.0 м)
    # Порог адаптивный: либо 50000, либо 10% от максимума гистограммы при достаточной плотности
    hist_x, edges_x = np.histogram(roof_xy_rot[:, 0], bins=140)
    bin_centers = (edges_x[:-1] + edges_x[1:]) / 2.0
    thresh = min(50000, max(500, int(hist_x.max() * 0.25)))

    detected_trusses = []
    for i in range(len(hist_x)):
        if hist_x[i] >= thresh:
            x_c = float(bin_centers[i])
            # Проверим, нет ли уже рядом фермы (минимальное расстояние 4 м)
            if not any(abs(t["x_local_m"] - x_c) < 4.0 for t in detected_trusses):
                near_t = np.abs(roof_xy_rot[:, 0] - x_c) < 0.6
                y_min = float(np.percentile(roof_xy_rot[near_t, 1], 2))
                y_max = float(np.percentile(roof_xy_rot[near_t, 1], 98))
                detected_trusses.append({
                    "type": "roof_truss",
                    "x_local_m": round(x_c, 3),
                    "z_bottom_m": round(float(np.percentile(roof_pts[near_t, 2], 5)), 3),
                    "z_top_m": round(float(np.percentile(roof_pts[near_t, 2], 95)), 3),
                    "span_y_start_m": round(y_min, 2),
                    "span_y_end_m": round(y_max, 2),
                    "span_length_m": round(y_max - y_min, 2),
                    "point_count": int(np.sum(near_t)),
                })

    return {
        "rotation_deg": rotation_deg,
        "crane_rails": crane_rails,
        "trusses": detected_trusses,
        "crane_points_total": int(len(crane_pts)),
        "roof_points_total": int(len(roof_pts)),
    }
