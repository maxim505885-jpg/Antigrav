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
from shapely import contains_xy
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
    grid["vertical_component_labels"] = labelled
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


def _attach_architectural_source_rows(
    geom: CloudGeometry,
    grid: dict[str, Any],
    component_labels: np.ndarray,
    elements: list[DetectedElement],
    *,
    max_ids: int = 512,
    bbox_margin_m: float = 0.05,
) -> None:
    """Attach bounded source-row evidence to columns and detected walls.

    The occupancy grid locates candidate footprints but does not retain which
    input rows contributed to them. Revisit the stored array once, assigning
    rows through their connected-component cell and keeping a deterministic
    bounded sample inside each candidate bbox.
    """
    path = Path(geom.positions_path)
    if not path.is_file() or max_ids <= 0:
        for element in elements:
            element.metadata.pop("_occupancy_component_id", None)
        return

    res = float(grid["res"])
    minx, miny = float(grid["min"][0]), float(grid["min"][1])
    nu, nv = int(grid["nu"]), int(grid["nv"])
    columns = [element for element in elements if element.class_name == "column"]
    walls = [element for element in elements if element.class_name == "wall"]

    bounds: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    by_component: dict[int, list[DetectedElement]] = {}
    for element in columns:
        lower = np.asarray(element.bbox["min"], dtype=np.float64) - geom.origin
        upper = np.asarray(element.bbox["max"], dtype=np.float64) - geom.origin
        lower -= bbox_margin_m
        upper += bbox_margin_m
        bounds[id(element)] = (lower, upper)
        ix0 = max(0, int(math.floor((lower[0] - minx) / res)))
        iy0 = max(0, int(math.floor((lower[1] - miny) / res)))
        ix1 = min(nu, int(math.floor((upper[0] - minx) / res)) + 1)
        iy1 = min(nv, int(math.floor((upper[1] - miny) / res)) + 1)
        if ix0 >= ix1 or iy0 >= iy1:
            continue
        component_ids = np.unique(component_labels[iy0:iy1, ix0:ix1])
        for component in component_ids[component_ids > 0]:
            by_component.setdefault(int(component), []).append(element)
    component_bound_columns = {
        id(element)
        for component_elements in by_component.values()
        for element in component_elements
    }
    # Consolidation can retain small one-storey occupancy candidates whose
    # footprint overlaps no labelled vertical component. Their points still
    # need provenance: use the same bounded bbox corridor as the audit below.
    fallback_columns = [
        element for element in columns if id(element) not in component_bound_columns
    ]
    if not by_component and not walls and not fallback_columns:
        return

    sampled: dict[int, list[int]] = {id(element): [] for element in columns + walls}
    support: dict[int, int] = {id(element): 0 for element in columns + walls}
    wall_geometry: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray, float, float, np.ndarray, np.ndarray]] = {}
    for element in walls:
        lower = np.asarray(element.bbox["min"], dtype=np.float64) - geom.origin - bbox_margin_m
        upper = np.asarray(element.bbox["max"], dtype=np.float64) - geom.origin + bbox_margin_m
        center = np.asarray(element.geometry["center"], dtype=np.float64)[:2] - geom.origin[:2]
        angle = float(element.geometry.get("rotation_z") or 0.0)
        direction = np.array([math.cos(angle), math.sin(angle)])
        normal = np.array([-direction[1], direction[0]])
        half_length = float(element.dimensions["length_m"]) / 2.0 + bbox_margin_m
        half_thickness = float(element.dimensions["thickness_m"]) / 2.0 + bbox_margin_m
        wall_geometry[id(element)] = (lower, upper, center, half_length, half_thickness, direction, normal)

    positions = np.load(path, mmap_mode="r")
    chunk_size = CHUNK
    for start in range(0, len(positions), chunk_size):
        chunk = np.asarray(positions[start : start + chunk_size])
        ix = np.floor((chunk[:, 0] - minx) / res).astype(np.int64)
        iy = np.floor((chunk[:, 1] - miny) / res).astype(np.int64)
        valid = (
            np.isfinite(chunk).all(axis=1)
            & (ix >= 0) & (ix < nu)
            & (iy >= 0) & (iy < nv)
        )
        if not valid.any():
            continue
        labels = np.zeros(len(chunk), dtype=np.int32)
        labels[valid] = component_labels[iy[valid], ix[valid]]
        if by_component:
            for component in np.intersect1d(np.unique(labels), list(by_component), assume_unique=False):
                point_indices = np.flatnonzero(labels == component)
                if not len(point_indices):
                    continue
                points = chunk[point_indices]
                for element in by_component[int(component)]:
                    lower, upper = bounds[id(element)]
                    inside = np.all((points >= lower) & (points <= upper), axis=1)
                    if not inside.any():
                        continue
                    key = id(element)
                    row_ids = (start + point_indices[inside]).tolist()
                    support[key] += len(row_ids)
                    combined = sampled[key] + row_ids
                    if len(combined) > max_ids:
                        selection = np.linspace(0, len(combined) - 1, max_ids, dtype=np.int64)
                        combined = [combined[int(index)] for index in selection]
                    sampled[key] = combined

        for element in fallback_columns:
            key = id(element)
            lower, upper = bounds[key]
            inside = np.all((chunk >= lower) & (chunk <= upper), axis=1)
            point_indices = np.flatnonzero(inside)
            if not len(point_indices):
                continue
            row_ids = (start + point_indices).tolist()
            support[key] += len(row_ids)
            combined = sampled[key] + row_ids
            if len(combined) > max_ids:
                selection = np.linspace(0, len(combined) - 1, max_ids, dtype=np.int64)
                combined = [combined[int(index)] for index in selection]
            sampled[key] = combined

        for element in walls:
            key = id(element)
            lower, upper, center, half_length, half_thickness, direction, normal = wall_geometry[key]
            in_bbox = np.all((chunk >= lower) & (chunk <= upper), axis=1)
            point_indices = np.flatnonzero(in_bbox)
            if not len(point_indices):
                continue
            points = chunk[point_indices]
            relative = points[:, :2] - center
            inside = (
                (np.abs(relative @ direction) <= half_length)
                & (np.abs(relative @ normal) <= half_thickness)
            )
            if not inside.any():
                continue
            row_ids = (start + point_indices[inside]).tolist()
            support[key] += len(row_ids)
            combined = sampled[key] + row_ids
            if len(combined) > max_ids:
                selection = np.linspace(0, len(combined) - 1, max_ids, dtype=np.int64)
                combined = [combined[int(index)] for index in selection]
            sampled[key] = combined

    for element in columns + walls:
        key = id(element)
        element.metadata.update({
                "source_point_ids": sampled[key],
                "source_point_id_space": "positions.npy row index",
                "source_point_ids_sampled": support[key] > max_ids,
                "source_point_support_count": support[key],
        })


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
        row_parts: list[np.ndarray] = []
        for start in range(0, arr.shape[0], CHUNK):
            chunk = np.asarray(arr[start : start + CHUNK])
            mask = np.abs(chunk[:, 2] - z_local) <= half
            if np.any(mask):
                u_parts.append(chunk[mask, 0])
                v_parts.append(chunk[mask, 1])
                row_parts.append(start + np.flatnonzero(mask))
        if not u_parts:
            continue
        u = np.concatenate(u_parts)
        v = np.concatenate(v_parts)
        source_rows = np.concatenate(row_parts)
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
            local_polygon = Polygon(poly["points"])
            polygon_x = np.asarray(poly["points"], dtype=np.float64)[:, 0]
            polygon_y = np.asarray(poly["points"], dtype=np.float64)[:, 1]
            polygon_min = np.array([polygon_x.min(), polygon_y.min()])
            polygon_max = np.array([polygon_x.max(), polygon_y.max()])
            sampled_rows: list[int] = []
            support_count = 0
            for point_start in range(0, len(u), 250_000):
                point_stop = min(len(u), point_start + 250_000)
                xs = u[point_start:point_stop]
                ys = v[point_start:point_stop]
                in_polygon_bounds = (
                    (xs >= polygon_min[0]) & (xs <= polygon_max[0])
                    & (ys >= polygon_min[1]) & (ys <= polygon_max[1])
                )
                if not in_polygon_bounds.any():
                    continue
                offsets = np.flatnonzero(in_polygon_bounds)
                inside = contains_xy(local_polygon, xs[offsets], ys[offsets])
                matched = source_rows[point_start + offsets[inside]]
                if not len(matched):
                    continue
                support_count += len(matched)
                merged_rows = sampled_rows + matched.tolist()
                if len(merged_rows) > 512:
                    selection = np.linspace(0, len(merged_rows) - 1, 512, dtype=np.int64)
                    merged_rows = [merged_rows[int(index)] for index in selection]
                sampled_rows = merged_rows
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
                        "source_point_ids": sampled_rows,
                        "source_point_id_space": "positions.npy row index",
                        "source_point_ids_sampled": support_count > 512,
                        "source_point_support_count": support_count,
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
    _attach_architectural_source_rows(
        geom, grid, grid["vertical_component_labels"], elements,
    )

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

    # MEP pipelines and linear equipment recognition
    from .mep import detect_pipe_network
    if progress:
        progress(0.96, "поиск трасс трубопроводов и сетей (MEP)")
    try:
        stored_positions = np.load(geom.positions_path, mmap_mode="r")
        # CloudGeometry intentionally stores a path rather than a resident
        # point array. Give the experimental MEP recognizer a bounded,
        # deterministic sample without materializing a large FARO cloud.
        # The current MEP detector uses a CPU RANSAC loop. Cap its input and
        # iteration count so an experimental subsystem cannot dominate a
        # large structural recognition run.
        sample_size = min(len(stored_positions), 10000)
        if sample_size == len(stored_positions):
            sample_pts = np.array(stored_positions, copy=True)
        elif sample_size:
            sample_rows = np.linspace(
                0, len(stored_positions) - 1, sample_size, dtype=np.int64
            )
            sample_pts = np.asarray(stored_positions[sample_rows])
        else:
            sample_pts = np.empty((0, 3), dtype=np.float32)
        mapping = getattr(stored_positions, "_mmap", None)
        if mapping is not None:
            mapping.close()
        del stored_positions

        def mep_checkpoint() -> None:
            if progress is not None:
                progress(0.96, "проверка MEP гипотез")

        detected_pipes = detect_pipe_network(
            sample_pts,
            min_segment_points=25,
            max_segments=3,
            max_iterations=30,
            checkpoint=mep_checkpoint if progress is not None else None,
        )
        mep_elements = []
        for p in detected_pipes:
            sp = p.start_point
            ep = p.end_point
            center = [(sp[0] + ep[0]) / 2.0, (sp[1] + ep[1]) / 2.0, (sp[2] + ep[2]) / 2.0]
            bbox = [
                min(sp[0], ep[0]) - p.radius_m, min(sp[1], ep[1]) - p.radius_m, min(sp[2], ep[2]) - p.radius_m,
                max(sp[0], ep[0]) + p.radius_m, max(sp[1], ep[1]) + p.radius_m, max(sp[2], ep[2]) + p.radius_m,
            ]
            mep_el = DetectedElement(
                class_name="pipe",
                geometry={
                    "start_point": sp,
                    "end_point": ep,
                    "axis_direction": p.axis_direction,
                    "center": center,
                    "radius_m": p.radius_m,
                    "diameter_mm": p.diameter_mm,
                    "length_m": p.length_m,
                    "slope_percent": p.slope_percent,
                },
                bbox=bbox,
                confidence=p.confidence,
                measured=True,
                inferred=False,
                source="geometric",
                dimensions={
                    "diameter_mm": p.diameter_mm,
                    "length_m": p.length_m,
                    "slope_percent": p.slope_percent,
                    "system_type": p.system_type,
                },
                metadata={
                    "shape": "cylinder",
                    "inliers": p.inlier_count,
                    "review_required": True,
                },
            )
            mep_elements.append(mep_el)
        elements = elements + mep_elements
        if mep_elements:
            warnings.append(
                f"Инженерные сети (MEP): обнаружено {len(mep_elements)} участков трубопроводов "
                "методом цилиндрического RANSAC. Требуется верификация диаметра и уклонов."
            )
    except Exception as exc:
        warnings.append(f"Ошибка трассировки MEP сетей: {exc}")

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
