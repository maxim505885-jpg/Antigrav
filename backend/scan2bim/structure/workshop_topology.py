"""Industrial Workshop Structural Topology & Domain Knowledge Engine.

This module encodes the fundamental structural engineering principles of
single-storey industrial buildings with overhead bridge cranes (промышленные цеха
с мостовыми опорными кранами) in accordance with:
- СП 16.13330.2017 "Стальные конструкции" (СНиП II-23-81*)
- СП 20.13330.2016 "Нагрузки и воздействия"
- СП 56.13330.2021 "Производственные здания"
- ГОСТ 23838-89 "Здания предприятий. Модульные координаты и параметры"
- Серия 1.424.1-5 / 1.423.1-3 "Колонны железобетонные и стальные ступенчатые"
- Серия 1.426.2-7 "Балки подкрановые стальные путей мостовых кранов"
- Серия 1.460.2-10 / 1.460.3 "Стальные стропильные фермы покрытий"
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkshopGridTopology:
    """Provisional workshop layout values used only to produce review hypotheses."""
    
    # 1. Coordinate frame alignment
    orientation_angle_deg: float = 10.260  # Provisional; replace with surveyed frame.
    
    # 2. Longitudinal Bay Parameters (Продольный шаг рам каркаса)
    bay_step_m: float = 6.000          # User-provided nominal step, not a measured tolerance.
    u_origin_m: float = 0.140          # Provisional origin; requires project control.
    total_transverse_axes: int = 24    # Оси 1 .. 24 (k = -16 .. +7)
    hall_length_m: float = 138.000     # Длина цеха: 23 шага по 6.0м = 138м
    grid_search_window_m: float = 1.200  # Heuristic search window, not an acceptance tolerance.
    
    # 3. Transverse Spans & Rows (Поперечный профиль: 3 пролета, 4 ряда колонн)
    # V coordinates in the aligned building frame:
    # Row A: Outer facade wall (крайний ряд А)
    # Row B: Middle crane row between Span 1 and Span 2 (средний ряд Б)
    # Row C: Middle crane row between Span 2 and Span 3 (средний ряд В)
    # Row D: Outer facade wall (крайний ряд Г)
    v_row_a_m: float = -29.800
    v_row_b_m: float = -16.550
    v_row_c_m: float = -4.850
    v_row_d_m: float = 8.400
    
    # Unverified transverse span hypotheses; do not use as design or acceptance values.
    # Span 1 (A - B): 13.25 m
    # Span 2 (B - C): 11.70 m
    # Span 3 (C - D): 13.25 m
    # Total width: 38.20 m
    spans: tuple[tuple[str, str, str, float], ...] = (
        ("Пролет 1", "А", "Б", 13.250),
        ("Пролет 2", "Б", "В", 11.700),
        ("Пролет 3", "В", "Г", 13.250),
    )
    
    # 4. Vertical Elevations (Высотные отметки по ГОСТ 21.101-2020)
    # Floor level / Column base (Уровень чистого пола): отм. 0.000 (Z_scan = -11.55 m)
    z_floor_scan_m: float = -11.550
    
    # Crane bracket step / Rail level (Отметка верха подкранового рельса):
    # отм. +6.800 (Z_scan = -4.75 m)
    z_crane_bracket_scan_m: float = -4.750
    
    # Column head / Truss bottom chord (Оголовок колонны / низ стропильных ферм):
    # отм. +9.600 (Z_scan = -1.95 m)
    z_column_head_scan_m: float = -1.950
    
    # Roof ridge / Truss top chord (Конек кровли / верх стропильных ферм):
    # отм. +12.500 (Z_scan = +0.95 m)
    z_roof_ridge_scan_m: float = +0.950

    @property
    def rad(self) -> float:
        return math.radians(self.orientation_angle_deg)

    @property
    def cos(self) -> float:
        return math.cos(self.rad)

    @property
    def sin(self) -> float:
        return math.sin(self.rad)

    @property
    def row_v_coords(self) -> dict[str, float]:
        return {
            "А": self.v_row_a_m,
            "Б": self.v_row_b_m,
            "В": self.v_row_c_m,
            "Г": self.v_row_d_m,
        }

    @property
    def transverse_u_coords(self) -> list[float]:
        # k from -16 to +7 -> 24 axes
        return [round(self.u_origin_m + k * self.bay_step_m, 3) for k in range(-16, 8)]

    def to_world(self, u: float, v: float, z: float) -> tuple[float, float, float]:
        """Convert aligned (U, V, Z) coordinates to point cloud world frame (X, Y, Z)."""
        x = u * self.cos - v * self.sin
        y = u * self.sin + v * self.cos
        return round(x, 4), round(y, 4), round(z, 4)

    def to_aligned(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        """Convert point cloud world frame (X, Y, Z) to aligned building frame (U, V, Z)."""
        u = x * self.cos + y * self.sin
        v = -x * self.sin + y * self.cos
        return round(u, 4), round(v, 4), round(z, 4)


class StructuralTopologyValidator:
    """Compare detections with an unverified nominal layout hypothesis.

    This class must not confirm structural roles, dimensions, engineering marks,
    tolerance compliance, or reject candidates. Default coordinates are provisional
    and are not a surveyed control grid.
    """

    def __init__(self, topology: WorkshopGridTopology | None = None):
        self.topo = topology or WorkshopGridTopology()

    def classify_element_role(
        self,
        class_name: str,
        center_world: tuple[float, float, float],
        sizes: tuple[float, float, float],
    ) -> dict[str, Any]:
        """Return a review-only hypothesis without changing measured geometry."""
        u, v, _z = self.topo.to_aligned(*center_world)
        _ = sizes  # Measured dimensions are evidence and are never rewritten here.
        result: dict[str, Any] = {
            "candidate_role": class_name,
            "review_state": "unreviewed",
            "hypothesis_basis": "geometric_class_and_unverified_nominal_layout",
        }

        if class_name == "column":
            row_letter, row_v = min(
                self.topo.row_v_coords.items(), key=lambda item: abs(v - item[1])
            )
            axis_index, axis_u = min(
                enumerate(self.topo.transverse_u_coords, start=1),
                key=lambda item: abs(u - item[1]),
            )
            delta_u_mm = int(round((u - axis_u) * 1000))
            delta_v_mm = int(round((v - row_v) * 1000))
            search_window_mm = self.topo.grid_search_window_m * 1000
            within_search_window = (
                abs(delta_u_mm) <= search_window_mm
                and abs(delta_v_mm) <= search_window_mm
            )
            result["grid_hypothesis"] = {
                "row": row_letter,
                "axis": axis_index,
                "delta_u_mm": delta_u_mm,
                "delta_v_mm": delta_v_mm,
                "status": (
                    "unverified_candidate"
                    if within_search_window
                    else "outside_nominal_grid_search_window"
                ),
                "nominal_step_m": self.topo.bay_step_m,
                "review_state": "unreviewed",
            }
        return result

    def regularize_elements(
        self, elements: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Attach review-only hypotheses and preserve all source candidates."""
        regularized: list[dict[str, Any]] = []
        counts: dict[str, int] = {}

        for element in elements:
            element_out = dict(element)
            dimensions = dict(element_out.get("dimensions") or {})
            geometry = element_out.get("geometry") or {}
            center = geometry.get("center")
            if not center and element_out.get("bbox"):
                bounds = element_out["bbox"]
                center = [
                    (bounds["min"][index] + bounds["max"][index]) / 2.0
                    for index in range(3)
                ]

            class_name = str(element_out.get("class_name", "unknown"))
            counts[class_name] = counts.get(class_name, 0) + 1
            if center and len(center) == 3:
                hypothesis = self.classify_element_role(
                    class_name, tuple(center), (0.0, 0.0, 0.0)
                )
            else:
                hypothesis = {
                    "candidate_role": class_name,
                    "review_state": "unreviewed",
                    "hypothesis_basis": "geometry_unavailable",
                }
            dimensions["nominal_grid_hypothesis"] = hypothesis
            element_out["dimensions"] = dimensions
            regularized.append(element_out)

        column_count = counts.get("column", 0)
        summary = {
            "status": "review_required",
            "total_candidates": len(regularized),
            "preserved_candidates": len(regularized),
            "columns": {"total": column_count, "unassessed": column_count},
            "candidate_counts_by_source_class": counts,
            "engineering_tolerances": "not_assessed",
            "required_evidence": [
                "project grid control",
                "physical element labels",
                "approved project tolerance",
            ],
        }
        return regularized, summary


def regularize_workshop_model(
    elements: list[dict[str, Any]],
    topology: WorkshopGridTopology | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Helper entry point to regularize workshop elements."""
    validator = StructuralTopologyValidator(topology=topology)
    return validator.regularize_elements(elements)

