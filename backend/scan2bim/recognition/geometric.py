"""Geometric recognition baseline with review-only structural candidates.

The baseline combines architectural geometry with steel-frame candidates.
Confidence values are heuristic scores in [0,1], not calibrated probabilities.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy import ndimage
from scipy.signal import find_peaks
from shapely.geometry import Polygon

from ..config import MAX_RASTER_CELLS
from ..geometry.section import CloudGeometry
from ..geometry.vectorize import vectorize_2d

CHUNK = 4_000_000
GRID_RES = 0.10
BAND_HEIGHT = 0.50

# Physical acceptance limits. They encode what an engineer would call a
# structural element, not just "a compact blob of points".
COLUMN_MIN_SIDE_M = 0.15
COLUMN_MIN_AREA_M2 = 0.05
COLUMN_MIN_HEIGHT_M = 1.50
WALL_MIN_LENGTH_M = 2.00
WALL_MAX_THICKNESS_M = 0.60
# Below this many points per 0.10 m occupancy cell, thin-element detection is
# not trustworthy and recognition must say so instead of guessing.


@dataclass
class DetectedElement:
    class_name: str
    geometry: dict[str, Any]
    bbox: dict[str, Any]
    confidence: float
    measured: bool = True
    inferred: bool = False
    source: str = "geometric"
    dimensions: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecognitionResult:
    elements: list[DetectedElement]
    levels: list[dict[str, Any]]
    warnings: list[str]
    stats: dict[str, Any]


def _iter_positions(path: Path):
    arr = np.load(path, mmap_mode="r")
    for start in range(0, arr.shape[0], CHUNK):
        yield np.asarray(arr[start : start + CHUNK])


def _detect_levels(geom: CloudGeometry, progress=None) -> tuple[list[dict[str, Any]], np.ndarray, np.ndarray]:
    local_min = geom.bbox_min - geom.origin
    local_max = geom.bbox_max - geom.origin
    height = float(local_max[2] - local_min[2])
    if height <= 0:
        return [], np.array([0]), np.array([0])
    bin_size = 0.05
    nbins = max(2, int(math.ceil(height / bin_size)))
    hist = np.zeros(nbins, dtype=np.int64)
    zmin, zmax = float(local_min[2]), float(local_max[2])
    total = 0
    for chunk in _iter_positions(geom.positions_path):
        z = chunk[:, 2]
        idx = np.floor((z - zmin) / bin_size).astype(np.int64)
        valid = (idx >= 0) & (idx < nbins)
        hist += np.bincount(idx[valid], minlength=nbins)
        total += len(z)
    if total == 0:
        return [], hist, np.array([0.0])
    smooth = ndimage.gaussian_filter1d(hist.astype(np.float32), sigma=2.0)
    if smooth.max() <= 0:
        return [], hist, np.array([0.0])
    distance = max(2, int(1.0 / bin_size))
    # Pad both ends so floor and roof peaks touching the cloud bounds are found.
    padded = np.concatenate([[0.0], smooth.astype(np.float64), [0.0]])
    raw_peaks, _ = find_peaks(
        padded,
        height=padded.max() * 0.12,
        prominence=padded.max() * 0.05,
        distance=distance,
    )
    peaks = [int(p) - 1 for p in raw_peaks if 0 <= int(p) - 1 < nbins]
    peaks = sorted(peaks, key=lambda i: smooth[i], reverse=True)[:8]
    levels: list[dict[str, Any]] = []
    for idx in peaks:
        z = zmin + (idx + 0.5) * bin_size
        # Count points in a thin band around the candidate level.
        band = np.abs(np.arange(nbins) - idx) <= 2
        band_count = int(hist[band].sum())
        if band_count < 50:
            continue
        levels.append(
            {
                "z": round(z + float(geom.origin[2]), 4),
                "z_local": round(float(z), 4),
                "point_count": band_count,
                "confidence": round(float(min(0.9, 0.35 + 0.55 * (smooth[idx] / smooth.max()))), 3),
                "method": "z-histogram peak (horizontal surface candidate)",
            }
        )
    levels.sort(key=lambda item: item["z"])
    return levels, hist, np.array([zmin])


def _occurrence_grid(geom: CloudGeometry, progress=None):
    local_min = geom.bbox_min - geom.origin
    local_max = geom.bbox_max - geom.origin
    res = GRID_RES
    width = float(local_max[0] - local_min[0])
    depth = float(local_max[1] - local_min[1])
    height = float(local_max[2] - local_min[2])
    cells = max(1, math.ceil(width / res) * math.ceil(depth / res))
    while cells > MAX_RASTER_CELLS / 4:
        res *= 1.25
        cells = max(1, math.ceil(width / res) * math.ceil(depth / res))
    nu = max(1, int(math.ceil(width / res)) + 1)
    nv = max(1, int(math.ceil(depth / res)) + 1)
    # +1 keeps the top boundary (z == max) inside a band; z extents are clipped.
    nbands = max(1, int(math.ceil(height / BAND_HEIGHT)) + 1)

    counts = np.zeros(nv * nu, dtype=np.int64)
    band_occ = np.zeros((nbands, nv * nu), dtype=bool)
    total = 0
    for chunk in _iter_positions(geom.positions_path):
        x = chunk[:, 0]
        y = chunk[:, 1]
        z = chunk[:, 2]
        ix = np.floor((x - local_min[0]) / res).astype(np.int64)
        iy = np.floor((y - local_min[1]) / res).astype(np.int64)
        ib = np.floor((z - local_min[2]) / BAND_HEIGHT).astype(np.int64)
        valid = (ix >= 0) & (ix < nu) & (iy >= 0) & (iy < nv) & (ib >= 0) & (ib < nbands)
        if not np.any(valid):
            continue
        flat = iy[valid] * nu + ix[valid]
        ib = ib[valid]
        counts += np.bincount(flat, minlength=nv * nu)
        for band in range(nbands):
            sel = ib == band
            if np.any(sel):
                band_occ[band] |= np.bincount(flat[sel], minlength=nv * nu).astype(bool)
        total += int(valid.sum())
    return {
        "res": res,
        "nu": nu,
        "nv": nv,
        "nbands": nbands,
        "counts": counts.reshape(nv, nu),
        "band_occ": band_occ.reshape(nbands, nv, nu),
        "min": local_min,
        "total": total,
        "assumed_band_height": BAND_HEIGHT,
    }


def density_scale(counts: np.ndarray) -> float:
    """How much to tighten physical thresholds on a sparse sample.

    On 0.10 m cells a sparse scan cannot resolve a 0.2 m column or a thin
    wall: the same blob of cells is either a construction or scan noise. The
    acceptance bar is therefore raised, never lowered, so dense clouds keep
    the calibrated limits and sparse clouds stop emitting noise-sized
    "columns". Values above 1.0 mean "thin elements are not trustworthy".
    """
    occupied = counts[counts > 0]
    if occupied.size == 0:
        return 1.6
    mean_points = float(occupied.mean())
    if mean_points < 1.0:
        return 1.6
    if mean_points < 2.0:
        return 1.3
    if mean_points < 4.0:
        return 1.15
    return 1.0


def density_grade(mean_points: float) -> str:
    if mean_points <= 0:
        return "нет данных"
    if mean_points < 1.0:
        return "низкая"
    if mean_points < 4.0:
        return "средняя"
    return "высокая"


def _vertical_elements(geom: CloudGeometry, grid: dict[str, Any]) -> list[DetectedElement]:
    counts = grid["counts"]
    band_occ = grid["band_occ"]
    res = grid["res"]
    minx, miny = float(grid["min"][0]), float(grid["min"][1])
    scale = density_scale(counts)
    min_side_threshold = COLUMN_MIN_SIDE_M * scale
    min_area_threshold = COLUMN_MIN_AREA_M2 * scale * scale
    min_height_threshold = COLUMN_MIN_HEIGHT_M * min(1.15, scale)
    resolution_limit = 2.0 * res
    occupied = band_occ.any(axis=0)
    band_count = band_occ.sum(axis=0)
    min_extent = 1.2 * min(1.15, scale)
    vertical = occupied & (band_count * BAND_HEIGHT >= min_extent) & (counts >= 5 * (1 if scale < 1.2 else 2))
    labelled, ncomp = ndimage.label(vertical, structure=np.ones((3, 3), dtype=bool))
    elements: list[DetectedElement] = []
    for comp in range(1, ncomp + 1):
        mask = labelled == comp
        iy, ix = np.nonzero(mask)
        if len(ix) < 3:
            continue
        # Long connected wall runs are decomposed into straight segments by
        # the Hough stage; only compact components are treated as columns here.
        comp_w = (int(ix.max()) - int(ix.min()) + 1) * res
        comp_h = (int(iy.max()) - int(iy.min()) + 1) * res
        if max(comp_w, comp_h) > 1.5:
            continue
        xs = minx + (ix + 0.5) * res
        ys = miny + (iy + 0.5) * res
        pts = np.column_stack([xs, ys])
        center = pts.mean(axis=0)
        centered = pts - center
        try:
            cov = np.cov(centered.T)
            eigvals, eigvecs = np.linalg.eigh(cov)
            major = eigvecs[:, int(np.argmax(eigvals))]
        except Exception:
            major = np.array([1.0, 0.0])
        angle = math.atan2(float(major[1]), float(major[0]))
        ca, sa = math.cos(angle), math.sin(angle)
        along = centered[:, 0] * ca + centered[:, 1] * sa
        across = -centered[:, 0] * sa + centered[:, 1] * ca
        length = float(along.max() - along.min()) + res
        thickness = float(across.max() - across.min()) + res
        along_mid = (along.max() + along.min()) / 2
        across_mid = (across.max() + across.min()) / 2
        cx = center[0] + along_mid * ca - across_mid * sa
        cy = center[1] + along_mid * sa + across_mid * ca

        # Occupied band range for the cells of this component.
        occupied_bands = np.nonzero(band_occ[:, mask].any(axis=1))[0]
        z_min = float(grid["min"][2])
        z_max = float(geom.bbox_max[2] - geom.origin[2])
        z0_local = z_min + float(occupied_bands.min()) * BAND_HEIGHT
        z1_local = min(z_min + float(occupied_bands.max() + 1) * BAND_HEIGHT, z_max)
        height = z1_local - z0_local
        cells = int(len(ix))
        comp_count = int(counts[mask].sum())
        fill = cells / max(1.0, (length / res) * (thickness / res))
        density = min(1.0, comp_count / max(1.0, cells * 6.0))
        height_factor = min(1.0, height / 3.0)

        min_side = min(length, thickness)
        area = length * thickness
        # Minimum physical size of a structural column. Without this every
        # scan-noise filament became a "column": on a real 145 x 86 m site the
        # first build produced 950 columns with a 0.03 m^2 median footprint,
        # which no engineer would accept.
        if length <= 1.0 and thickness <= 1.0:
            if min_side < min_side_threshold or area < min_area_threshold:
                continue
            if height < min_height_threshold or cells < 6:
                continue
            class_name = "column"
            confidence = 0.40 + 0.25 * density + 0.15 * height_factor + 0.1 * min(1.0, fill)
        elif length >= 1.2:
            if length < WALL_MIN_LENGTH_M or thickness > WALL_MAX_THICKNESS_M:
                continue
            class_name = "wall"
            confidence = 0.35 + 0.2 * density + 0.2 * height_factor + 0.15 * min(1.0, fill)
        else:
            if area < 0.12 or height < 1.5:
                continue
            class_name = "unknown"
            confidence = 0.25
        confidence = float(max(0.15, min(0.9, confidence)))
        z_center = (z0_local + z1_local) / 2
        world_center = [
            round(cx + float(geom.origin[0]), 4),
            round(cy + float(geom.origin[1]), 4),
            round(z_center + float(geom.origin[2]), 4),
        ]
        geometry = {
            "kind": "oriented_box",
            "center": world_center,
            "sizes": {
                "length": round(length, 3),
                "thickness": round(thickness, 3),
                "height": round(height, 3),
            },
            "rotation_z": round(angle, 5),
            "note": "measured footprint and height; box orientation from 2D PCA",
        }
        wx0 = min(xs) + float(geom.origin[0])
        wy0 = min(ys) + float(geom.origin[1])
        wx1 = max(xs) + float(geom.origin[0])
        wy1 = max(ys) + float(geom.origin[1])
        bbox = {
            "min": [round(wx0, 3), round(wy0, 3), round(z0_local + float(geom.origin[2]), 3)],
            "max": [round(wx1, 3), round(wy1, 3), round(z1_local + float(geom.origin[2]), 3)],
        }
        elements.append(
            DetectedElement(
                class_name=class_name,
                geometry=geometry,
                bbox=bbox,
                confidence=round(confidence, 3),
                measured=True,
                inferred=False,
                dimensions={
                    "length_m": round(length, 3),
                    "thickness_m": round(thickness, 3),
                    "height_m": round(height, 3),
                    "footprint_area_m2": round(length * thickness, 3),
                    "below_resolution": bool(min_side <= resolution_limit),
                    "density_scale": round(scale, 2),
                },
                metadata={
                    "method": "vertical occupancy grid + connected components + 2D PCA",
                    "point_count_in_cells": comp_count,
                    "grid_res_m": res,
                    "confidence_kind": "heuristic",
                    "material": None,
                    "load_bearing": None,
                    "notes": "class is a geometric hypothesis; verify in the editor",
                },
            )
        )
    return elements


def _slab_elements(
    geom: CloudGeometry,
    levels: list[dict[str, Any]],
    progress=None,
) -> list[DetectedElement]:
    if not levels:
        return []
    arr = np.load(geom.positions_path, mmap_mode="r")
    elements: list[DetectedElement] = []
    for level in levels:
        z_local = float(level["z_local"])
        half = 0.10
        u_parts: list[np.ndarray] = []
        v_parts: list[np.ndarray] = []
        for start in range(0, arr.shape[0], CHUNK):
            chunk = np.asarray(arr[start : start + CHUNK])
            mask = np.abs(chunk[:, 2] - z_local) <= half
            if np.any(mask):
                u_parts.append(chunk[mask, 0])
                v_parts.append(chunk[mask, 1])
        if not u_parts:
            continue
        u = np.concatenate(u_parts)
        v = np.concatenate(v_parts)
        if len(u) < 100:
            continue
        result = vectorize_2d(
            u,
            v,
            grid_res=0.05,
            close_radius_m=0.08,
            regularize=True,
            min_component_area=max(1.0, 0.02 * float(np.ptp(u)) * float(np.ptp(v))),
            max_preview_points=0,
        )
        for poly in result.get("polygons", []):
            if poly.get("is_hole") or poly["area"] < 1.0:
                continue
            world_points = [
                [round(x + float(geom.origin[0]), 4), round(y + float(geom.origin[1]), 4)]
                for x, y in poly["points"]
            ]
            elements.append(
                DetectedElement(
                    class_name="slab",
                    geometry={
                        "kind": "slab",
                        "polygon": world_points,
                        "z": round(float(level["z"]), 4),
                        "assumed_thickness": 0.20,
                        "note": "footprint measured; thickness assumed, not measured",
                    },
                    bbox={
                        "min": [
                            round(min(p[0] for p in world_points), 3),
                            round(min(p[1] for p in world_points), 3),
                            round(float(level["z"]) - 0.10, 3),
                        ],
                        "max": [
                            round(max(p[0] for p in world_points), 3),
                            round(max(p[1] for p in world_points), 3),
                            round(float(level["z"]) + 0.10, 3),
                        ],
                    },
                    confidence=round(float(min(0.75, 0.3 + level.get("confidence", 0.3) * 0.5)), 3),
                    measured=True,
                    inferred=True,
                    dimensions={
                        "area_m2": round(float(poly["area"]), 3),
                        "assumed_thickness_m": 0.20,
                    },
                    metadata={
                        "method": "level z-histogram peak + 2D footprint vectorisation",
                        "level_confidence": level.get("confidence"),
                        "thickness_source": "assumed_default",
                        "confidence_kind": "heuristic",
                        "material": None,
                        "load_bearing": None,
                    },
                )
            )
    return elements


def structural_only(elements: list[DetectedElement]) -> tuple[list[DetectedElement], int]:
    """Drop non-structural ``unknown`` fragments; return (kept, dropped_count).

    The request is a structural model only ("только конструктив, лишнего не
    надо"): walls, columns, slabs, beams, trusses and bracing. ``unknown``
    blobs carry no load-bearing meaning, so they are excluded from the output
    while their count is preserved for honest reporting.
    """
    kept = [e for e in elements if e.class_name != "unknown"]
    return kept, len(elements) - len(kept)


def format_recognition_summary(elements: list[DetectedElement]) -> str:
    """Report this run's actual classes without treating missing classes as absent."""
    labels = {
        "column": "колонны",
        "wall": "стены",
        "slab": "плиты",
        "beam": "балки",
        "truss": "фермы",
        "bracing": "связи",
        "brace": "связи",
        "stair": "лестницы",
        "opening": "проёмы",
    }
    counts: dict[str, int] = {}
    for element in elements:
        counts[element.class_name] = counts.get(element.class_name, 0) + 1
    detected = [f"{labels.get(name, name)} — {count}" for name, count in sorted(counts.items())]
    found_text = ", ".join(detected) if detected else "кандидаты не найдены"
    return (
        f"В этом запуске найдено: {found_text}. Это геометрические кандидаты; "
        "отсутствие класса в результате не доказывает его отсутствия в облаке. "
        "Покрытие и исходные точки проверьте вручную; тип, сечение, опоры и соединения не подтверждены."
    )


def detect_structures(geom: CloudGeometry, progress=None) -> RecognitionResult:
    warnings: list[str] = []
    levels, zhist, _ = _detect_levels(geom, progress)
    if progress:
        progress(0.2, "поиск вертикальных конструкций")
    grid = _occurrence_grid(geom, progress)
    if progress:
        progress(0.45, "классификация колонн")
    column_elements = _vertical_elements(geom, grid)
    if progress:
        progress(0.6, "выделение прямолинейных участков стен")
    from .walls import detect_walls  # local import avoids a cycle

    wall_elements = detect_walls(geom, grid)
    if progress:
        progress(0.75, "выделение контуров плит")
    slab_elements = _slab_elements(geom, levels, progress)
    elements = column_elements + wall_elements + slab_elements

    # Consolidation stage: bind elements to levels, merge collinear wall
    # fragments and overlapping column shafts, demote single-storey "columns"
    # in multi-storey buildings. See recognition/consolidate.py.
    from .consolidate import consolidate  # local import avoids a cycle

    if progress:
        progress(0.85, "консолидация фрагментов в конструкции")
    elements, consolidation = consolidate(elements, levels)
    warnings.extend(consolidation.warnings)

    # Structural steel frame stage: crane runways, purlins, floor beams,
    # trusses, vertical/horizontal bracing, column section typing.
    # See recognition/steel.py.
    from .steel import detect_structural_frame

    if progress:
        progress(0.86, "распознавание металлического каркаса (балки, фермы, связи)")
    column_elements = [e for e in elements if e.class_name == "column"]
    steel_elements, steel_stats, steel_warnings = detect_structural_frame(
        geom, levels, grid, column_elements, progress
    )
    elements = elements + steel_elements
    warnings.extend(steel_warnings)

    # Openings and stairs: both are review hypotheses, not measured products.
    # Openings are gaps in the consolidated wall faces; stairs are inclined
    # planar flights between adjacent levels. See recognition/openings.py and
    # recognition/stairs.py.
    from .openings import detect_openings
    from .stairs import detect_stairs

    if progress:
        progress(0.90, "поиск проёмов в стенах")
    wall_elements = [e for e in elements if e.class_name == "wall"]
    opening_elements = detect_openings(geom, wall_elements, levels)
    if progress:
        progress(0.94, "поиск лестничных маршей")
    stair_elements = detect_stairs(geom, levels)
    elements = elements + opening_elements + stair_elements
    if opening_elements:
        warnings.append(
            f"Проёмы (двери/окна): {len(opening_elements)} гипотез по разрывам в "
            "просканированных стенах. Отверстия в скане неотличимы от проёма — проверьте ширину, "
            "отметку подоконника и тип вручную."
        )
    if stair_elements:
        warnings.append(
            f"Лестницы: {len(stair_elements)} наклонных марша между соседними уровнями. "
            "Пандус или наклонный участок кровли выглядит так же; ступени и ограждения не "
            "распознаны."
        )

    # Review-only workshop layout hypothesis:
    # The nominal grid is not surveyed control, so it must never reject detections,
    # assign engineering marks/sections, or promote a candidate to confirmed.
    cols = [e for e in elements if e.class_name == "column"]
    if len(cols) >= 15:
        from ..structure.workshop_topology import StructuralTopologyValidator
        val = StructuralTopologyValidator()
        for el in cols:
            center = el.geometry.get("center") if el.geometry else None
            sizes = el.geometry.get("sizes") if el.geometry else None
            if center and sizes:
                lens = (float(sizes.get("length", 0.6)), float(sizes.get("thickness", 0.5)), float(sizes.get("height", 3.0)))
                res = val.classify_element_role("column", (center[0], center[1], center[2]), lens)
                el.dimensions["nominal_grid_hypothesis"] = res

    # "Только конструктив, лишнего не надо": the baseline also emits
    # non-structural fragments as ``unknown`` (blobs too long to be a column
    # and too short to be a wall, plus single-storey shafts demoted by the
    # consolidation stage). They are equipment/stands/scan noise, not
    # load-bearing, so they are dropped from the model the engineer sees.
    # The count stays in stats so nothing disappears silently.
    elements, dropped_unknown = structural_only(elements)
    if dropped_unknown:
        warnings.append(
            f"Исключено {dropped_unknown} неструктурных фрагментов (класс «не опознано»): "
            "оборудование, стойки, шум скана. В модель не входят — только конструктив."
        )

    warnings.append(format_recognition_summary(elements))
    if not levels:
        warnings.append("Горизонтальные уровни не найдены; обнаружение плит и покрытий недоступно.")
    if len(elements) == 0:
        warnings.append(
            "Ни один элемент не прошёл геометрические пороги; проверьте плотность, единицы и ориентацию."
        )

    # Honest density report: recognition at 0.10 m resolution cannot resolve
    # thin elements on a sparse sample, and the engineer must be told.
    occupied = grid["counts"] > 0
    occupied_cells = int(occupied.sum())
    mean_pts_cell = (
        float(grid["counts"][occupied].mean()) if occupied_cells else 0.0
    )
    plan_area = float(
        (geom.bbox_max[0] - geom.bbox_min[0]) * (geom.bbox_max[1] - geom.bbox_min[1])
    )
    rejection = grid.get("wall_rejections", {})
    grade = density_grade(mean_pts_cell)
    scale = density_scale(grid["counts"])
    if mean_pts_cell and mean_pts_cell < 3.0:
        warnings.append(
            f"Плотность выборки всего {mean_pts_cell:.1f} точки на ячейку {grid['res']:.2f} м. "
            "При такой плотности гипотезы о стенах и колоннах ненадёжны и требуют проверки "
            "в редакторе; для полноразрешённого распознавания увеличьте S2B_MAX_INGEST_POINTS."
        )
    if scale > 1.0:
        warnings.append(
            "Пороги распознавания ужесточены под низкую плотность ("
            f"×{scale:.2f}): элементы тоньше {0.15 * scale:.2f} м (колонны) в такой "
            "выборке не различаются и в модель не попадают. Это пропуск, а не отсутствие "
            "конструкции."
        )
    stats = {
        "method": "geometric-baseline-v1",
        "grid_res_m": round(grid["res"], 3),
        "bands": grid["nbands"],
        "band_height_m": BAND_HEIGHT,
        "points_processed": grid["total"],
        "occupied_cells": occupied_cells,
        "mean_points_per_cell": round(mean_pts_cell, 3),
        "density_grade": grade,
        "density_scale": round(scale, 2),
        "plan_area_m2": round(plan_area, 1),
        "points_per_m2_plan": round(grid["total"] / plan_area, 2) if plan_area > 0 else None,
        "wall_rejections": rejection,
        "consolidation": consolidation.as_stats(),
        "steel": steel_stats,
        "level_candidates": len(levels),
        "wall_count": sum(1 for e in elements if e.class_name == "wall"),
        "column_count": sum(1 for e in elements if e.class_name == "column"),
        "slab_count": sum(1 for e in elements if e.class_name == "slab"),
        "beam_count": sum(1 for e in elements if e.class_name == "beam"),
        "truss_count": sum(1 for e in elements if e.class_name == "truss"),
        "brace_count": sum(1 for e in elements if e.class_name == "brace"),
        "stair_count": sum(1 for e in elements if e.class_name == "stair"),
        "opening_count": sum(1 for e in elements if e.class_name == "opening"),
        "non_structural_excluded": dropped_unknown,
        "unimplemented_classes": [
            "girder",
            "pipe",
            "duct",
            "equipment",
        ],
        "confidence_kind": "heuristic (not calibrated probabilities)",
    }
    return RecognitionResult(elements=elements, levels=levels, warnings=warnings, stats=stats)
