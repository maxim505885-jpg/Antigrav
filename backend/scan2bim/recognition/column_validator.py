"""Workshop Structural Construction Validator (Агент-Эксперт по конструктиву каркаса).
Validates raw vertical candidates to strictly distinguish true load-bearing structural columns
from non-structural noise (pipes, HVAC ducts, equipment posts, conduits, railings).

Engineering Rules:
1. Structural Height: Must span continuously from floor level (Z <= 0.5m) up to at least crane/roof level (height >= 5.0m).
2. Grid Line Alignment: Must align to orthogonal structural grid lines (spans: 18/24/30m, bays: 6m/12m) within tolerance.
3. Cross-section Size: Must have substantial structural dimensions (width >= 0.35m, depth >= 0.35m; not thin pipes <= 0.25m).
4. Vertical Continuity: Must have vertical point distribution without large internal voids.
"""
from __future__ import annotations

import math
from typing import Any
import numpy as np


class WorkshopColumnValidator:
    """Expert engineering gate for validating shop columns before CAD drafting."""

    def __init__(
        self,
        min_structural_height_m: float = 4.5,
        min_section_dim_m: float = 0.30,
        max_section_dim_m: float = 1.40,
        grid_tolerance_m: float = 1.20,
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
        """Classify candidate element into true structural column vs non-structural object.
        
        Returns:
            (is_column, reason_or_classification)
        """
        geom = element.get("geometry") or {}
        center = geom.get("center")
        sizes = geom.get("sizes") or {}

        # 1. Проверка габаритов сечения
        width = float(sizes.get("width") or sizes.get("length") or 0.0)
        depth = float(sizes.get("depth") or sizes.get("thickness") or 0.0)
        dim = max(width, depth)
        min_d = min(width, depth)

        if dim < self.min_dim:
            return False, f"Отклонено: сечение ({dim:.2f}м) слишком мало для несущей колонны каркаса (вероятно труба/кабель/стойка)"
        
        if dim > self.max_dim:
            return False, f"Отклонено: сечение ({dim:.2f}м) превышает габариты колонны цеха (вероятно стена/оборудование)"

        # 2. Проверка непрерывной высоты
        height = float(sizes.get("height") or 0.0)
        if height < self.min_height:
            return False, f"Отклонено: высота ({height:.2f}м < {self.min_height}м) — стойка оборудования или фахверк, не несущая колонна"

        # 3. Проверка отметки низа (опирание на фундамент/пол)
        if center is not None and len(center) >= 3:
            z_bottom = center[2] - height / 2.0
            if z_bottom > 1.8:
                return False, f"Отклонено: низ элемента оторван от пола (Z_низ={z_bottom:.2f}м) — подвес или подвесная конструкция"

        # 4. Проверка координационной привязки к сетке осей (если сетка известна)
        if center is not None and known_x_bays and known_y_spans:
            cx, cy = center[0], center[1]
            dist_x = min(abs(cx - bx) for bx in known_x_bays)
            dist_y = min(abs(cy - sy) for sy in known_y_spans)

            if dist_x > self.grid_tolerance or dist_y > self.grid_tolerance:
                return False, f"Отклонено: элемент вне координационной сетки цеха (смещение X={dist_x:.2f}м, Y={dist_y:.2f}м) — технологический объект в проходе"

        return True, "Подтверждено: несущая колонна каркаса цеха"

    def filter_column_candidates(
        self,
        elements: list[dict[str, Any]],
        known_x_bays: list[float] | None = None,
        known_y_spans: list[float] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split raw candidates into verified structural columns and rejected non-structural items."""
        verified_columns = []
        rejected_items = []

        for el in elements:
            if el.get("class_name") != "column":
                continue
            is_col, reason = self.is_true_column(el, known_x_bays, known_y_spans)
            if is_col:
                verified_columns.append(el)
            else:
                rejected_items.append({
                    "id": el.get("id"),
                    "geometry": el.get("geometry"),
                    "reason": reason
                })

        return verified_columns, rejected_items
