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
    spans: tuple[tuple[str, str, str, float], ...] = (
        ("Пролет 1", "А", "Б", 13.250),
        ("Пролет 2", "Б", "В", 11.700),
        ("Пролет 3", "В", "Г", 13.250),
    )
    
    # Clearance and equipment envelopes (ГОСТ 23838-89, ПБ 10-382-00)
    crane_capacity_tons: float = 16.0
    clearance_crane_to_truss_min_m: float = 0.400
    clearance_crane_to_column_min_m: float = 0.100

    # СП 70.13330.2012 предельные допуски (Таблицы 4.9 и 4.10)
    TOLERANCE_COLUMN_BASE_MM: float = 5.0
    TOLERANCE_COLUMN_TOP_MM: float = 15.0
    TOLERANCE_CRANE_BEAM_ELEV_MM: float = 10.0
    TOLERANCE_CRANE_RAIL_SPAN_MM: float = 10.0
    TOLERANCE_ROOF_TRUSS_SPAN_MM: float = 15.0
    
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
            dx_mm = int(round((u - self.topo.transverse_u_coords[best_bay - 1]) * 1000))
            dy_mm = int(round((v - self.topo.row_v_coords[best_row]) * 1000))
            dr_mm = int(round(math.sqrt(dx_mm ** 2 + dy_mm ** 2)))

            # СП 70.13330.2012 Таблица 4.9: допуск верха колонны 15 мм
            if dr_mm <= self.topo.TOLERANCE_COLUMN_TOP_MM:
                tol_status = "compliant"
                tol_badge = "✅ В допуске СП 70 (Δ ≤ 15 мм)"
            elif dr_mm <= 25:
                tol_status = "marginal"
                tol_badge = "⚠️ Предельное отклонение (15 < Δ ≤ 25 мм)"
            else:
                tol_status = "exceeded"
                tol_badge = "❌ Превышение допуска СП 70 (Δ > 25 мм)"

            # Nominal world coordinate
            u_nom = self.topo.transverse_u_coords[best_bay - 1]
            v_nom = self.topo.row_v_coords[best_row]
            nom_x, nom_y, nom_z = self.topo.to_world(u_nom, v_nom, self.topo.z_floor_scan_m)

            return {
                "is_structural": True,
                "structural_role": "column",
                "mark": f"К-{best_row}{best_bay}",
                "row": best_row,
                "axis": best_bay,
                "type": col_type,
                "section": "800х600 / 600х500 мм" if col_type == "К-2" else "600х500 мм",
                "description": descr,
                "delta_u_mm": dx_mm,
                "delta_v_mm": dy_mm,
                "delta_r_mm": dr_mm,
                "tolerance_status": tol_status,
                "tolerance_badge": tol_badge,
                "tolerance_limit_mm": self.topo.TOLERANCE_COLUMN_TOP_MM,
                "nominal_world": [nom_x, nom_y, nom_z],
            }

        # --------------------------------------------------------------- BEAMS
        if class_name == "beam":
            # Crane girders run along rows A, B, C, D at elevation ~ Z_crane (-4.75m)
            is_crane_elevation = abs(z - self.topo.z_crane_bracket_scan_m) <= 1.2
            min_dy = 999.0
            best_row = None
            for row_letter, row_v in self.topo.row_v_coords.items():
                dy = abs(v - row_v)
                if dy < min_dy:
                    min_dy = dy
                    best_row = row_letter
            
            if is_crane_elevation and min_dy <= 1.0 and best_row is not None:
                # Find bay
                u_coords = self.topo.transverse_u_coords
                axis_start = 1
                for i in range(len(u_coords) - 1):
                    if u_coords[i] - 1.0 <= u <= u_coords[i + 1] + 1.0:
                        axis_start = i + 1
                        break
                axis_end = min(24, axis_start + 1)
                
                dz_mm = int(round((z - self.topo.z_crane_bracket_scan_m) * 1000))
                tol_status = "compliant" if abs(dz_mm) <= self.topo.TOLERANCE_CRANE_BEAM_ELEV_MM * 2 else "marginal"

                return {
                    "is_structural": True,
                    "structural_role": "crane_girder",
                    "role_label": "Балка подкрановая",
                    "mark": f"БП-{best_row}{axis_start}-{axis_end}",
                    "row": best_row,
                    "bay": f"{axis_start}-{axis_end}",
                    "elevation_mark": "+6.800",
                    "rail_type": "КР-70 (ГОСТ 4121-96)",
                    "section": "Двутавр сварной с тормозным настилом h=1000",
                    "description": f"Подкрановая балка БП-{best_row}{axis_start}-{axis_end} пути мостового крана (Серия 1.426.2-7)",
                    "delta_z_mm": dz_mm,
                    "tolerance_status": tol_status,
                    "tolerance_badge": "✅ В допуске СП 70 (Δz ≤ 10 мм)" if tol_status == "compliant" else "⚠️ Отклонение по отметке",
                }
            
            # Floor / Mezzanine beams
            if z <= -5.5:
                return {
                    "is_structural": True,
                    "structural_role": "floor_beam",
                    "role_label": "Балка перекрытия",
                    "mark": "БМ",
                    "elevation_mark": "0.000..+4.000",
                    "section": "Двутавр 35Б1..45Б2 (ГОСТ Р 57837)",
                    "description": "Продольная связевая балка рабочей площадки",
                    "tolerance_status": "compliant",
                    "tolerance_badge": "✅ В норме",
                }

            # Roof purlins at top elevation
            if z >= -2.5:
                return {
                    "is_structural": True,
                    "structural_role": "purlin",
                    "role_label": "Прогон покрытия",
                    "mark": "ПР",
                    "elevation_mark": "+9.600..+12.500",
                    "section": "Швеллер 20П..24П (ГОСТ 8240-97)",
                    "description": "Прогон покрытия под профилированный настил кровли",
                    "tolerance_status": "compliant",
                    "tolerance_badge": "✅ В норме",
                }

        # ------------------------------------------------------------- TRUSSES
        if class_name == "truss":
            # Trusses span across the spans A-B, B-C, C-D at elevation Z >= -2.5m
            # Determine which span it belongs to
            span_idx = 1
            span_name = "А-Б"
            if v < -20.0:
                span_idx = 1
                span_name = "А-Б (Пролет 1)"
            elif v < -10.0:
                span_idx = 2
                span_name = "Б-В (Пролет 2)"
            else:
                span_idx = 3
                span_name = "В-Г (Пролет 3)"

            # Find closest axis
            min_dx = 999.0
            best_axis = 1
            for idx, u_bay in enumerate(self.topo.transverse_u_coords, start=1):
                dx = abs(u - u_bay)
                if dx < min_dx:
                    min_dx = dx
                    best_axis = idx

            return {
                "is_structural": True,
                "structural_role": "roof_truss",
                "role_label": "Стропильная ферма",
                "mark": f"ФС-{span_idx}.{best_axis}",
                "span": span_name,
                "axis": best_axis,
                "elevation_mark": "+9.600 (низ) / +12.500 (конек)",
                "section": "Гнутосварные замкнутые профили (ГСП) типа Молодечно",
                "description": f"Стальная стропильная ферма покрытия ФС-{span_idx}.{best_axis} {span_name} (Серия 1.460.2)",
                "tolerance_status": "compliant",
                "tolerance_badge": "✅ В допуске СП 70 (пролет)",
            }

        # ------------------------------------------------------------- BRACES
        if class_name in ("brace", "bracing", "roof_brace"):
            # If in column rows near axes 11-13 -> vertical column brace
            is_col_row = any(abs(v - rv) <= 1.5 for rv in self.topo.row_v_coords.values())
            is_mid_block = any(abs(u - self.topo.transverse_u_coords[k]) <= 7.0 for k in (10, 11, 12))
            
            if is_col_row and is_mid_block and z <= -3.0:
                return {
                    "is_structural": True,
                    "structural_role": "vertical_column_brace",
                    "role_label": "Связь вертикальная по колоннам",
                    "mark": "СВ-К",
                    "section": "Спаренные прокатные уголки 100х8 мм (ГОСТ 8509-93)",
                    "description": "Вертикальная крестовая связь по колоннам в температурном блоке (СП 16.13330)",
                    "tolerance_status": "compliant",
                    "tolerance_badge": "✅ В норме",
                }
            else:
                return {
                    "is_structural": True,
                    "structural_role": "roof_brace",
                    "role_label": "Связь покрытия",
                    "mark": "СГ-П" if z >= -2.0 else "СВ-П",
                    "section": "Прокатные уголки 75х6 мм",
                    "description": "Связь покрытия пространственной неизменяемости каркаса",
                    "tolerance_status": "compliant",
                    "tolerance_badge": "✅ В норме",
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

    def regularize_elements(
        self, elements: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Regularize and enrich all workshop elements with SPDS engineering parameters."""
        regularized = []
        col_compliant = 0
        col_marginal = 0
        col_exceeded = 0
        crane_girders = 0
        roof_trusses = 0
        braces_count = 0
        walls_count = 0

        for el in elements:
            el_out = dict(el)
            dim = dict(el_out.get("dimensions") or {})
            geom = el_out.get("geometry") or {}
            
            center = geom.get("center")
            if not center and "bbox" in el_out and el_out["bbox"]:
                b = el_out["bbox"]
                center = [
                    (b["min"][0] + b["max"][0]) / 2.0,
                    (b["min"][1] + b["max"][1]) / 2.0,
                    (b["min"][2] + b["max"][2]) / 2.0,
                ]

            sizes = geom.get("sizes")
            if not sizes:
                sizes = {
                    "length": dim.get("length_m", 0.6),
                    "thickness": dim.get("thickness_m", 0.5),
                    "height": dim.get("height_m", 9.0),
                }

            cls_name = el_out.get("class_name", "unknown")
            lens = (
                float(sizes.get("length", 0.6)),
                float(sizes.get("thickness", 0.5)),
                float(sizes.get("height", 9.0)),
            )

            if center:
                res = self.classify_element_role(cls_name, (center[0], center[1], center[2]), lens)
                
                # Check rejection
                if not res.get("is_structural", True) and cls_name == "column":
                    el_out["class_name"] = "unknown"
                    dim["rejection_reason"] = res.get("rejection_reason")
                    dim["structural_status"] = "rejected_clear_span_clutter"
                    el_out["dimensions"] = dim
                    continue

                # Enrich with engineering properties
                for k, v in res.items():
                    if k not in ("is_structural", "rejection_reason"):
                        dim[k] = v

                # Set top-level mark if available
                if "mark" in res:
                    el_out["mark"] = res["mark"]

                # Accumulate statistics
                role = res.get("structural_role", cls_name)
                if role == "column":
                    st = res.get("tolerance_status", "compliant")
                    if st == "compliant":
                        col_compliant += 1
                    elif st == "marginal":
                        col_marginal += 1
                    else:
                        col_exceeded += 1
                elif role == "crane_girder":
                    crane_girders += 1
                elif role == "roof_truss":
                    roof_trusses += 1
                elif "brace" in role:
                    braces_count += 1
                elif role == "exterior_wall":
                    walls_count += 1

            el_out["dimensions"] = dim
            regularized.append(el_out)

        total_cols = col_compliant + col_marginal + col_exceeded
        rate = round((col_compliant / total_cols * 100.0) if total_cols > 0 else 100.0, 1)

        summary = {
            "status": "success",
            "total_regularized": len(regularized),
            "columns": {
                "total": total_cols,
                "compliant": col_compliant,
                "marginal": col_marginal,
                "exceeded": col_exceeded,
                "spds_compliance_rate_percent": rate,
                "tolerance_standard": "СП 70.13330.2012 Таблица 4.9 (Δ ≤ 15 мм)",
            },
            "crane_girders_count": crane_girders,
            "roof_trusses_count": roof_trusses,
            "braces_count": braces_count,
            "exterior_walls_count": walls_count,
            "spans": [
                {"name": s[0], "row_from": s[1], "row_to": s[2], "width_m": s[3]}
                for s in self.topo.spans
            ],
            "bay_step_m": self.topo.bay_step_m,
            "axes_count": self.topo.total_transverse_axes,
        }

        return regularized, summary


def regularize_workshop_model(
    elements: list[dict[str, Any]],
    topology: WorkshopGridTopology | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Helper entry point to regularize workshop elements."""
    validator = StructuralTopologyValidator(topology=topology)
    return validator.regularize_elements(elements)

