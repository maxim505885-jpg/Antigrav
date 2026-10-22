"""Propose grid correspondences for tall point-derived column candidates.

Grid proximity can suggest an axis label, but cannot verify a physical column,
its section type, support, or dimensions. Every result remains review-only.
"""
from __future__ import annotations

import math
from typing import Any


class StructuralWorkshopClassifier:
    """Консервативные предложения соответствия кандидатов заданной сетке."""

    def __init__(
        self,
        bay_step_m: float = 6.0,
        grid_tolerance_m: float = 0.90,
        min_column_height_m: float = 4.5,
    ):
        self.bay_step = bay_step_m
        self.grid_tolerance = grid_tolerance_m
        self.min_height = min_column_height_m

    def classify_and_regularize(
        self,
        raw_candidates: list[dict[str, Any]],
        known_x_bays: list[float],
        known_y_rows: dict[str, float],
    ) -> list[dict[str, Any]]:
        """Return unreviewed grid-match proposals without assigning a column type."""
        proposals = []

        for candidate in raw_candidates:
            center = candidate.get("geometry", {}).get("center")
            if not center:
                continue

            cx, cy, cz = float(center[0]), float(center[1]), float(center[2])
            sizes = candidate.get("geometry", {}).get("sizes", {})
            height = float(sizes.get("height", 0.0))

            # 1. Проверка высоты (отсекаем станки и низкие короба)
            if height < self.min_height:
                continue

            # 2. Поиск ближайшей оси пролета (буквенной оси)
            best_row = None
            min_dy = 999.0
            for row_letter, row_y in known_y_rows.items():
                dy = abs(cy - row_y)
                if dy < min_dy and dy <= self.grid_tolerance:
                    min_dy = dy
                    best_row = (row_letter, row_y)

            if not best_row:
                # Объект находится в проходе цеха, а не в створах рядов -> оборудование/мусор
                continue

            row_letter, row_y = best_row

            # 3. Поиск ближайшей поперечной оси (цифровой оси 1..N)
            best_bay = None
            min_dx = 999.0
            for bay_idx, bay_x in enumerate(known_x_bays, start=1):
                dx = abs(cx - bay_x)
                if dx < min_dx and dx <= self.grid_tolerance:
                    min_dx = dx
                    best_bay = (bay_idx, bay_x)

            if not best_bay:
                continue

            bay_idx, bay_x = best_bay
            raw_confidence = candidate.get("confidence")
            confidence = None
            if (not isinstance(raw_confidence, bool)
                    and isinstance(raw_confidence, (int, float))
                    and math.isfinite(float(raw_confidence))):
                confidence = float(raw_confidence)

            proposals.append({
                "id": candidate.get("id"),
                "class_name": "column_candidate",
                "review_state": "proposed",
                "status": "unreviewed",
                "grid_match": {
                    "row_axis": row_letter,
                    "bay_axis": str(bay_idx),
                    "mark_candidate": f"К-{row_letter}{bay_idx}",
                    "status": "proposed",
                    "grid_center_m": [bay_x, row_y, cz],
                    "observed_center_m": [cx, cy, cz],
                    "residual_dx_mm": int(round((cx - bay_x) * 1000)),
                    "residual_dy_mm": int(round((cy - row_y) * 1000)),
                    "tolerance_m": self.grid_tolerance,
                },
                "measured_height_m": height,
                "section_type": {"value": "unknown", "status": "unknown"},
                "section_dimensions_m": {"width": None, "depth": None},
                "source_geometry": candidate.get("geometry", {}),
                "confidence": confidence,
                "confidence_kind": candidate.get("confidence_kind", "not_calibrated"),
                "unresolved_fields": [
                    "physical_column_identity", "section_type", "section_dimensions",
                    "supports", "grid_axis_confirmation",
                ],
            })

        return proposals
