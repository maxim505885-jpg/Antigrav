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
from dataclasses import dataclass, field
from typing import Any
import numpy as np


@dataclass(frozen=True)
class WorkshopGridTopology:
    """Rigorous parametric definition of the 3-span industrial workshop frame."""
    
    # 1. Coordinate frame alignment
    orientation_angle_deg: float = 10.260
    
    # 2. Longitudinal Bay Parameters (Продольный шаг рам каркаса)
    bay_step_m: float = 6.000          # Строго унифицированный шаг 6000 мм по ГОСТ 23838
    u_origin_m: float = 0.140          # Привязка оси 17 (k=0)
    total_transverse_axes: int = 24    # Оси 1 .. 24 (k = -16 .. +7)
    hall_length_m: float = 138.000     # Длина цеха: 23 шага по 6.0м = 138м
    
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
    
    # Spans (Расчетные пролёты цеха):
    # Span 1 (A - B): 13.25 m
    # Span 2 (B - C): 11.70 m
    # Span 3 (C - D): 13.25 m
    # Total width: 38.20 m
    
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
    """Enforces industrial workshop design rules on candidate detections.
    
    Rules:
    1. Columns can ONLY exist on grid intersections (U_k, V_r).
    2. Crane girders run ONLY along rows V_r between columns (step 6000 mm) at Z_crane.
    3. Roof trusses run ONLY across spans between rows (A-B, B-C, C-D) at Z_head.
    4. Exterior walls exist ONLY along the outer boundary (Row A, Row Г, Axis 1, Axis 24).
    5. Inner hall clearances (inside Spans 1, 2, 3) MUST BE FREE of columns and walls.
    """

    def __init__(self, topology: WorkshopGridTopology | None = None):
        self.topo = topology or WorkshopGridTopology()

    def classify_element_role(
        self,
        class_name: str,
        center_world: tuple[float, float, float],
        sizes: tuple[float, float, float],
    ) -> dict[str, Any]:
        """Verify whether an element satisfies the structural topology of the workshop."""
        u, v, z = self.topo.to_aligned(*center_world)
        length, thickness, height = sizes

        # ------------------------------------------------------------- COLUMNS
        if class_name == "column":
            # Check proximity to 4 rows
            min_dy = 999.0
            best_row = None
            for row_letter, row_v in self.topo.row_v_coords.items():
                dy = abs(v - row_v)
                if dy < min_dy:
                    min_dy = dy
                    best_row = row_letter

            # Check proximity to 24 transverse axes
            min_dx = 999.0
            best_bay = None
            for idx, u_bay in enumerate(self.topo.transverse_u_coords, start=1):
                dx = abs(u - u_bay)
                if dx < min_dx:
                    min_dx = dx
                    best_bay = idx

            # Tolerance: column center must be within 1.2m of true grid node
            if min_dy > 1.2 or min_dx > 1.2:
                return {
                    "is_structural": False,
                    "rejection_reason": f"Объект находится внутри свободного габарита пролета (ΔV={min_dy:.2f}м, ΔU={min_dx:.2f}м). Внутри пролета цеха колонн быть не может.",
                    "structural_role": "equipment_or_clutter",
                }

            col_type = "К-2" if best_row in ("Б", "В") else "К-1"
            descr = (
                f"Колонна {col_type} среднего ряда ступенчатая подкрановая (800х600 мм)"
                if col_type == "К-2"
                else f"Колонна {col_type} крайнего ряда фахверково-несущая (600х500 мм)"
            )
            return {
                "is_structural": True,
                "structural_role": "column",
                "mark": f"К-{best_row}{best_bay}",
                "row": best_row,
                "axis": best_bay,
                "type": col_type,
                "description": descr,
                "delta_u_mm": int(round((u - self.topo.transverse_u_coords[best_bay - 1]) * 1000)),
                "delta_v_mm": int(round((v - self.topo.row_v_coords[best_row]) * 1000)),
            }

        # --------------------------------------------------------------- BEAMS
        if class_name == "beam":
            # Crane girders run along rows A, B, C, D at elevation ~ Z_crane (-4.75m)
            is_crane_elevation = abs(z - self.topo.z_crane_bracket_scan_m) <= 1.2
            min_dy = min(abs(v - rv) for rv in self.topo.row_v_coords.values())
            
            if is_crane_elevation and min_dy <= 1.0:
                return {
                    "is_structural": True,
                    "structural_role": "crane_girder",
                    "role_label": "Балка подкрановая",
                    "elevation_mark": "+6.800",
                    "description": "Подкрановая балка путей мостового крана (Серия 1.426.2-7)",
                }
            
            # Floor / Mezzanine beams
            if z <= -5.5:
                return {
                    "is_structural": True,
                    "structural_role": "floor_beam",
                    "role_label": "Балка перекрытия",
                    "elevation_mark": "0.000..+4.000",
                    "description": "Продольная связевая балка рабочей площадки",
                }

            # Roof purlins at top elevation
            if z >= -2.5:
                return {
                    "is_structural": True,
                    "structural_role": "purlin",
                    "role_label": "Прогон покрытия",
                    "elevation_mark": "+9.600..+12.500",
                    "description": "Прогон покрытия под профилированный настил кровли",
                }

        # ------------------------------------------------------------- TRUSSES
        if class_name == "truss":
            # Trusses span across the spans A-B, B-C, C-D at elevation Z >= -2.5m
            return {
                "is_structural": True,
                "structural_role": "roof_truss",
                "role_label": "Стропильная ферма",
                "elevation_mark": "+9.600",
                "description": "Стальная стропильная ферма покрытия пролета цеха (Серия 1.460.2)",
            }

        # --------------------------------------------------------------- WALLS
        if class_name == "wall":
            # Exterior facade walls are only along Row A (v ~ -29.8) and Row D (v ~ +8.4)
            is_outer_a = abs(v - self.topo.v_row_a_m) <= 1.5
            is_outer_d = abs(v - self.topo.v_row_d_m) <= 1.5
            is_gable_1 = abs(u - self.topo.transverse_u_coords[0]) <= 2.0
            is_gable_24 = abs(u - self.topo.transverse_u_coords[-1]) <= 2.0

            if is_outer_a or is_outer_d or is_gable_1 or is_gable_24:
                wall_type = "Наружная продольная стена" if (is_outer_a or is_outer_d) else "Торцевая стена цеха"
                return {
                    "is_structural": True,
                    "structural_role": "exterior_wall",
                    "role_label": wall_type,
                    "description": f"{wall_type} из сэндвич-панелей / кирпича",
                }
            else:
                return {
                    "is_structural": False,
                    "structural_role": "partition_or_enclosure",
                    "role_label": "Внутренняя технологическая перегородка",
                    "description": "Выгородка бытовых помещений / венткамеры внутри цеха",
                }

        return {"is_structural": True, "structural_role": class_name}
