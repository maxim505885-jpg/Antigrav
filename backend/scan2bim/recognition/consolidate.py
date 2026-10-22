"""Consolidate raw detections into engineering constructions.

The recognition baseline emits every compact blob it can defend geometrically.
On a real 145 x 86 m industrial site that produced 318 "columns" and 43 "walls"
for 12 500 m^2 — mostly honest fragments, but fragments: wall runs broken at
doorways, columns seen on one storey only, no binding to building levels.

This stage performs four consolidations, each one a defensible engineering
statement rather than a cosmetic count reduction:

1. Level binding — every element records which storeys it occupies
   (``storey_count``, ``level_base_z``, ``level_top_z``), so the model can be
   read per floor.
2. Collinear wall merge — wall fragments on one line with a gap up to
   1.2 m (doorways, occlusions) become one wall. The gap is recorded.
3. Column shaft merge — column fragments whose plan footprints overlap and
   whose height ranges touch (gap <= 0.6 m) become one shaft.
4. Multi-storey support filter — in a building with >= 2 inter-level zones, a
   "column" seen on only one zone is not a structural column (roof clutter,
   equipment legs, scan noise). It is DOWNGRADED to ``unknown``, never deleted:
   the points are real, the classification was not.

Confidences stay heuristic. Nothing here invents geometry that was not measured.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from shapely.geometry import Polygon

from .geometric import DetectedElement
from .column_validator import WorkshopColumnValidator

# Merge tolerances (metres / radians).
WALL_MERGE_ANGLE_DEG = 10.0
WALL_MERGE_OFFSET_M = 0.35
WALL_MERGE_GAP_M = 1.2
COLUMN_MERGE_INFLATE_M = 0.12
COLUMN_MERGE_Z_GAP_M = 0.6
# A zone counts as occupied when the element covers > 35 % of its height.
ZONE_COVERAGE = 0.35


@dataclass
class ConsolidationReport:
    walls_merged_into: int = 0          # fragments consumed by wall merging
    walls_produced: int = 0             # continuous walls produced
    columns_merged_into: int = 0        # fragments consumed by shaft merging
    columns_produced: int = 0
    columns_demoted: int = 0            # single-storey columns -> unknown
    unknowns_demoted: int = 0           # single-storey unknowns kept as unknown
    columns_embedded_in_walls: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_stats(self) -> dict[str, Any]:
        return {
            "method": (
                "level binding + collinear wall merge + column shaft merge "
                "+ multi-storey support filter"
            ),
            "wall_fragments_merged": self.walls_merged_into,
            "continuous_walls_produced": self.walls_produced,
            "column_fragments_merged": self.columns_merged_into,
            "column_shafts_produced": self.columns_produced,
            "single_storey_columns_demoted_to_unknown": self.columns_demoted,
            "columns_embedded_in_walls": self.columns_embedded_in_walls,
        }


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, a: int) -> int:
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _angle_diff(a: float, b: float) -> float:
    d = abs(a - b) % math.pi
    return min(d, math.pi - d)


def _zones(levels: list[dict[str, Any]]) -> list[tuple[float, float]]:
    return [
        (float(lo["z"]), float(hi["z"]))
        for lo, hi in zip(levels[:-1], levels[1:])
    ]


def _storeys_of(z0: float, z1: float, zones: list[tuple[float, float]]) -> list[int]:
    occupied = []
    for index, (a, b) in enumerate(zones):
        overlap = min(z1, b) - max(z0, a)
        if overlap > ZONE_COVERAGE * (b - a):
            occupied.append(index)
    return occupied


def _plan_polygon(element: DetectedElement) -> Polygon:
    center = np.array(element.geometry["center"][:2], dtype=float)
    angle = float(element.geometry.get("rotation_z") or 0.0)
    length = float(element.dimensions.get("length_m") or 0.1)
    thickness = float(element.dimensions.get("thickness_m") or 0.1)
    ca, sa = math.cos(angle), math.sin(angle)
    corners = []
    for lx, ly in (
        (-length / 2, -thickness / 2),
        (length / 2, -thickness / 2),
        (length / 2, thickness / 2),
        (-length / 2, thickness / 2),
    ):
        corners.append((center[0] + lx * ca - ly * sa, center[1] + lx * sa + ly * ca))
    return Polygon(corners)


def _z_range(element: DetectedElement) -> tuple[float, float]:
    return float(element.bbox["min"][2]), float(element.bbox["max"][2])


# ---------------------------------------------------------------------- walls
def _wall_endpoints(element: DetectedElement) -> tuple[np.ndarray, np.ndarray]:
    center = np.array(element.geometry["center"], dtype=float)
    angle = float(element.geometry["rotation_z"])
    half = float(element.dimensions["length_m"]) / 2.0
    direction = np.array([math.cos(angle), math.sin(angle), 0.0])
    return center - direction * half, center + direction * half


def _merge_wall_group(group: list[DetectedElement]) -> DetectedElement:
    # Length-weighted mean direction (doubled angle keeps the line undirected).
    weight = sum(float(e.dimensions["length_m"]) for e in group)
    c_sum = sum(
        math.cos(2 * float(e.geometry["rotation_z"])) * float(e.dimensions["length_m"])
        for e in group
    )
    s_sum = sum(
        math.sin(2 * float(e.geometry["rotation_z"])) * float(e.dimensions["length_m"])
        for e in group
    )
    angle = 0.5 * math.atan2(s_sum, c_sum)
    direction = np.array([math.cos(angle), math.sin(angle), 0.0])

    endpoints = [p for e in group for p in _wall_endpoints(e)]
    reference = endpoints[0]
    projections = [float(np.dot(p - reference, direction)) for p in endpoints]
    t_min, t_max = min(projections), max(projections)
    center = reference + direction * ((t_min + t_max) / 2.0)

    length = float(t_max - t_min)
    thickness = float(
        sum(float(e.dimensions["thickness_m"]) * float(e.dimensions["length_m"]) for e in group)
        / max(weight, 1e-9)
    )
    z0 = min(_z_range(e)[0] for e in group)
    z1 = max(_z_range(e)[1] for e in group)
    height = max(0.05, z1 - z0)
    confidence = min(0.9, max(float(e.confidence) for e in group) + 0.05)

    ca, sa = math.cos(angle), math.sin(angle)
    corners = []
    for lx, ly in (
        (-length / 2, -thickness / 2),
        (length / 2, -thickness / 2),
        (length / 2, thickness / 2),
        (-length / 2, thickness / 2),
    ):
        corners.append((center[0] + lx * ca - ly * sa, center[1] + lx * sa + ly * ca))
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    thickness_source = next(
        (
            e.dimensions.get("thickness_source")
            for e in sorted(group, key=lambda e: -float(e.dimensions["length_m"]))
            if e.dimensions.get("thickness_source")
        ),
        None,
    )
    intervals = []
    for element in group:
        p0, p1 = _wall_endpoints(element)
        t0 = float(np.dot(p0 - center, direction))
        t1 = float(np.dot(p1 - center, direction))
        intervals.append((min(t0, t1), max(t0, t1)))
    intervals.sort()
    gaps = [
        max(0.0, intervals[i + 1][0] - intervals[i][1])
        for i in range(len(intervals) - 1)
    ]
    return DetectedElement(
        class_name="wall",
        geometry={
            "kind": "oriented_box",
            "center": [round(float(center[0]), 4), round(float(center[1]), 4), round((z0 + z1) / 2.0, 4)],
            "sizes": {
                "length": round(length, 3),
                "thickness": round(thickness, 3),
                "height": round(height, 3),
            },
            "rotation_z": round(float(angle), 5),
            "note": "continuous wall merged from collinear scan fragments; centreline measured",
        },
        bbox={
            "min": [round(min(xs), 3), round(min(ys), 3), round(z0, 3)],
            "max": [round(max(xs), 3), round(max(ys), 3), round(z1, 3)],
        },
        confidence=round(confidence, 3),
        measured=True,
        inferred=False,
        dimensions={
            "length_m": round(length, 3),
            "thickness_m": round(thickness, 3),
            "height_m": round(height, 3),
            "footprint_area_m2": round(length * thickness, 3),
            "thickness_source": thickness_source,
            "merged_from": len(group),
            "merged_gap_m": round(max(gaps) if gaps else 0.0, 3),
        },
        metadata={
            "method": "consolidation: collinear wall merge (gap <= 1.2 m incl. doorways)",
            "confidence_kind": "heuristic",
            "material": None,
            "load_bearing": None,
            "notes": (
                "fragments joined on one line; openings inside the merged run are "
                "NOT detected in this build — verify doorways in the editor"
            ),
        },
    )


def _merge_walls(
    walls: list[DetectedElement], report: ConsolidationReport
) -> list[DetectedElement]:
    if len(walls) < 2:
        return list(walls)
    uf = _UnionFind(len(walls))
    for i in range(len(walls)):
        for j in range(i + 1, len(walls)):
            a, b = walls[i], walls[j]
            angle_a = float(a.geometry["rotation_z"])
            if _angle_diff(angle_a, float(b.geometry["rotation_z"])) > math.radians(
                WALL_MERGE_ANGLE_DEG
            ):
                continue
            center_a = np.array(a.geometry["center"], dtype=float)
            center_b = np.array(b.geometry["center"], dtype=float)
            direction = np.array([math.cos(angle_a), math.sin(angle_a), 0.0])
            normal = np.array([-direction[1], direction[0], 0.0])
            offset = abs(float(np.dot(center_b - center_a, normal)))
            face_gap = (
                float(a.dimensions["thickness_m"]) + float(b.dimensions["thickness_m"])
            ) / 2.0
            if offset > max(WALL_MERGE_OFFSET_M, face_gap + 0.15):
                continue
            along = abs(float(np.dot(center_b - center_a, direction)))
            gap = along - float(a.dimensions["length_m"]) / 2.0 - float(b.dimensions["length_m"]) / 2.0
            if gap > WALL_MERGE_GAP_M:
                continue
            uf.union(i, j)
    groups: dict[int, list[DetectedElement]] = {}
    for index, wall in enumerate(walls):
        groups.setdefault(uf.find(index), []).append(wall)
    merged: list[DetectedElement] = []
    for group in groups.values():
        if len(group) == 1:
            merged.append(group[0])
            continue
        report.walls_merged_into += len(group)
        report.walls_produced += 1
        merged.append(_merge_wall_group(group))
    return merged


# -------------------------------------------------------------------- columns
def _merge_column_group(group: list[DetectedElement]) -> DetectedElement:
    polygons = [_plan_polygon(e) for e in group]
    xs = [x for poly in polygons for x, _ in poly.exterior.coords]
    ys = [y for poly in polygons for _, y in poly.exterior.coords]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    dx, dy = max_x - min_x, max_y - min_y
    length, thickness = max(dx, dy), min(dx, dy)
    envelope_angle = 0.0 if dx >= dy else math.pi / 2
    z0 = min(_z_range(e)[0] for e in group)
    z1 = max(_z_range(e)[1] for e in group)
    height = max(0.05, z1 - z0)
    center_x, center_y = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0
    confidence = min(0.9, max(float(e.confidence) for e in group))
    return DetectedElement(
        class_name="column",
        geometry={
            "kind": "oriented_box",
            "center": [round(center_x, 4), round(center_y, 4), round((z0 + z1) / 2.0, 4)],
            "sizes": {
                "length": round(length, 3),
                "thickness": round(thickness, 3),
                "height": round(height, 3),
            },
            "rotation_z": envelope_angle,
            "note": "shaft merged from overlapping per-storey fragments; plan extent measured",
        },
        bbox={
            "min": [round(min_x, 3), round(min_y, 3), round(z0, 3)],
            "max": [round(max_x, 3), round(max_y, 3), round(z1, 3)],
        },
        confidence=round(confidence, 3),
        measured=True,
        inferred=False,
        dimensions={
            "length_m": round(length, 3),
            "thickness_m": round(thickness, 3),
            "height_m": round(height, 3),
            "footprint_area_m2": round(dx * dy, 3),
            "merged_from": len(group),
        },
        metadata={
            "method": "consolidation: column shaft merge (plan overlap + z continuity)",
            "confidence_kind": "heuristic",
            "material": None,
            "load_bearing": None,
            "notes": "class is a geometric hypothesis; verify in the editor",
        },
    )


def _merge_columns(
    columns: list[DetectedElement], report: ConsolidationReport
) -> list[DetectedElement]:
    if len(columns) < 2:
        return list(columns)
    polygons = [_plan_polygon(e) for e in columns]
    inflated = [poly.buffer(COLUMN_MERGE_INFLATE_M) for poly in polygons]
    ranges = [_z_range(e) for e in columns]
    uf = _UnionFind(len(columns))
    for i in range(len(columns)):
        for j in range(i + 1, len(columns)):
            if not inflated[i].intersects(inflated[j]):
                continue
            z0a, z1a = ranges[i]
            z0b, z1b = ranges[j]
            gap = max(z0a - z1b, z0b - z1a, 0.0)
            if gap > COLUMN_MERGE_Z_GAP_M:
                continue
            uf.union(i, j)
    groups: dict[int, list[DetectedElement]] = {}
    for index, column in enumerate(columns):
        groups.setdefault(uf.find(index), []).append(column)
    merged: list[DetectedElement] = []
    for group in groups.values():
        if len(group) == 1:
            merged.append(group[0])
            continue
        report.columns_merged_into += len(group)
        report.columns_produced += 1
        merged.append(_merge_column_group(group))
    return merged


# ------------------------------------------------------------- main entry
def consolidate(
    elements: list[DetectedElement],
    levels: list[dict[str, Any]],
) -> tuple[list[DetectedElement], ConsolidationReport]:
    report = ConsolidationReport()
    walls = [e for e in elements if e.class_name == "wall"]
    columns = [e for e in elements if e.class_name == "column"]
    slabs = [e for e in elements if e.class_name == "slab"]
    others = [
        e for e in elements if e.class_name not in {"wall", "column", "slab"}
    ]

    walls = _merge_walls(walls, report)
    columns = _merge_columns(columns, report)

    zones = _zones(levels)

    # Multi-storey & Structural Workshop Validator filter:
    # 1. First run the WorkshopColumnValidator to reject pipes, HVAC ducts, thin posts and suspended elements.
    validator = WorkshopColumnValidator()
    kept_columns: list[DetectedElement] = []
    for column in columns:
        col_dict = {
            "class_name": column.class_name,
            "geometry": column.geometry,
            "bbox": column.bbox,
            "dimensions": column.dimensions,
        }
        is_true, reason = validator.is_true_column(col_dict)
        if not is_true:
            column.class_name = "unknown"
            column.dimensions["demoted_from"] = "column"
            column.dimensions["rejection_reason"] = reason
            column.dimensions["structural_status"] = "rejected_non_structural"
            column.metadata["method"] = "workshop structural validator"
            column.metadata["notes"] = reason
            column.confidence = round(min(column.confidence, 0.25), 3)
            report.columns_demoted += 1
            others.append(column)
        else:
            column.dimensions["structural_status"] = "verified_structural_column"
            kept_columns.append(column)
    columns = kept_columns

    # 2. Multi-storey support filter (if building has multi levels)
    if len(zones) >= 2:
        kept_columns = []
        for column in columns:
            z0, z1 = _z_range(column)
            storeys = _storeys_of(z0, z1, zones)
            if len(storeys) < 2:
                column.class_name = "unknown"
                column.dimensions["demoted_from"] = "column"
                column.dimensions["storey_count"] = len(storeys)
                column.metadata["method"] = (
                    "consolidation: demoted column (single-storey support in a "
                    "multi-storey building)"
                )
                column.metadata["notes"] = (
                    "measured vertical object seen on one storey only; not a "
                    "structural column — verify in the editor"
                )
                column.confidence = round(min(column.confidence, 0.3), 3)
                report.columns_demoted += 1
                others.append(column)
            else:
                kept_columns.append(column)
        columns = kept_columns

    # Columns whose footprint lies inside a wall line are double-counted scan
    # returns (wall corners, pilasters). Flag them; do not delete: a real column
    # embedded in a wall is a legitimate design too.
    embedded = 0
    wall_polygons = [_plan_polygon(w) for w in walls]
    for column in columns:
        poly = _plan_polygon(column)
        area = max(poly.area, 1e-9)
        for wall_poly in wall_polygons:
            if not wall_poly.intersects(poly):
                continue
            if wall_poly.intersection(poly).area / area > 0.6:
                column.dimensions["embedded_in_wall"] = True
                embedded += 1
                break
    report.columns_embedded_in_walls = embedded

    # Level binding for every surviving element.
    for element in walls + columns + others:
        if element.class_name == "slab":
            continue
        z0, z1 = _z_range(element)
        storeys = _storeys_of(z0, z1, zones)
        element.dimensions["storey_count"] = len(storeys)
        if storeys:
            element.dimensions["level_base_z"] = zones[storeys[0]][0]
            element.dimensions["level_top_z"] = zones[storeys[-1]][1]
    for slab in slabs:
        z = float(slab.geometry.get("z") or 0.0)
        if levels:
            slab.dimensions["level_index"] = min(
                range(len(levels)),
                key=lambda i: abs(float(levels[i]["z"]) - z),
            )
        slab.dimensions["storey_count"] = 1

    if report.walls_merged_into:
        report.warnings.append(
            f"Консолидация стен: {report.walls_merged_into} фрагментов объединены в "
            f"{report.walls_produced} сплошных стен по одной линии (разрыв до 1.2 м — "
            "проёмы внутри объединённого участка НЕ распознаются и требуют проверки)."
        )
    if report.columns_merged_into:
        report.warnings.append(
            f"Консолидация колонн: {report.columns_merged_into} фрагментов объединены в "
            f"{report.columns_produced} стояков по совпадению следа и высоты."
        )
    if report.columns_demoted:
        report.warnings.append(
            f"{report.columns_demoted} «колонн» видны ТОЛЬКО на одном этаже из "
            f"{len(zones) + 1} — это оборудование, стойки или шум скана, а не несущие "
            "колонны; в конструктивную модель они не включаются."
        )
    if embedded:
        report.warnings.append(
            f"{embedded} колонн имеют след внутри стен (углы, пилоны или колонны в "
            "плоскости стены) — отмечены флагом embedded_in_wall, требуют проверки."
        )

    consolidated = walls + columns + slabs + others
    return consolidated, report
