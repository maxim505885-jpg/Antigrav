"""Geometric prefilter for review-only column candidates.

The checks below only compare supplied geometry with broad heuristics. Passing
them cannot establish a physical ID, structural role, measured section, or
construction acceptance; failing them cannot prove an object is non-structural.
"""
from __future__ import annotations

import math
from typing import Any
import numpy as np


class WorkshopColumnValidator:
    """Keep the legacy class name; results are heuristic candidate decisions."""

    def __init__(
        self,
        min_structural_height_m: float = 2.5,
        min_section_dim_m: float = 0.25,
        max_section_dim_m: float = 1.60,
        grid_tolerance_m: float = 1.50,
    ):
        self.min_height = min_structural_height_m
        self.min_dim = min_section_dim_m
        self.max_dim = max_section_dim_m
        self.grid_tolerance = grid_tolerance_m

    def is_true_column(
        self,
        element: dict[str, Any],
        known_x_bays: list[float] | None = None,
        known_y_spans: list[float] | None = None,
    ) -> tuple[bool, str]:
        """Compatibility wrapper for :meth:`is_column_candidate`."""
        return self.is_column_candidate(element, known_x_bays, known_y_spans)

    def is_column_candidate(
        self,
        element: dict[str, Any],
        known_x_bays: list[float] | None = None,
        known_y_spans: list[float] | None = None,
    ) -> tuple[bool, str]:
        """Return whether broad geometry filters retain this review candidate."""
        geom = element.get("geometry") or {}
        center = geom.get("center")
        sizes = geom.get("sizes") or {}

        # 1. Проверка габаритов сечения
        width = float(sizes.get("width") or sizes.get("length") or 0.0)
        depth = float(sizes.get("depth") or sizes.get("thickness") or 0.0)
        dim = max(width, depth)
        min_d = min(width, depth)

        if dim < self.min_dim:
            return False, f"Эвристика сечения не пройдена ({dim:.2f} м): кандидат слишком тонкий; проверьте вручную"
        
        if dim > self.max_dim:
            return False, f"Эвристика сечения не пройдена ({dim:.2f} м): ширина вне текущего диапазона кандидатов"

        # 2. Проверка непрерывной высоты
        height = float(sizes.get("height") or 0.0)
        if height < self.min_height:
            return False, f"Эвристика высоты не пройдена ({height:.2f} м); конструктивная роль неизвестна"

        # 3. Проверка отметки низа (опирание на фундамент/пол)
        if center is not None and len(center) >= 3:
            z_bottom = center[2] - height / 2.0
            if z_bottom > 1.8:
                return False, f"Эвристика отметки низа не пройдена (Z_низ={z_bottom:.2f} м); причина неизвестна"

        # 4. Проверка координационной привязки к сетке осей (если сетка известна)
        if center is not None and known_x_bays and known_y_spans:
            cx, cy = center[0], center[1]
            dist_x = min(abs(cx - bx) for bx in known_x_bays)
            dist_y = min(abs(cy - sy) for sy in known_y_spans)

            if dist_x > self.grid_tolerance or dist_y > self.grid_tolerance:
                return False, f"Кандидат далеко от переданной сетки (X={dist_x:.2f} м, Y={dist_y:.2f} м); сетка и роль требуют проверки"

        return True, "Кандидат прошёл геометрический фильтр; конструктивная роль не подтверждена"

    def filter_column_candidates(
        self,
        elements: list[dict[str, Any]],
        known_x_bays: list[float] | None = None,
        known_y_spans: list[float] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split retained and filtered candidates without physical classification."""
        retained_candidates = []
        filtered_candidates = []

        for el in elements:
            if el.get("class_name") != "column":
                continue
            is_candidate, reason = self.is_column_candidate(el, known_x_bays, known_y_spans)
            if is_candidate:
                retained_candidates.append(el)
            else:
                filtered_candidates.append({
                    "id": el.get("id"),
                    "geometry": el.get("geometry"),
                    "reason": reason
                })

        return retained_candidates, filtered_candidates
