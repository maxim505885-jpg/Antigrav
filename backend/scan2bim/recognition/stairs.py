"""Stair detection: inclined flights between adjacent storey levels.

A stair flight is an inclined planar surface that rises from one level towards
another. Between every adjacent pair of detected levels the points are
rastered in plan at 0.10 m; connected components of occupied cells are then
fitted with a line of mean-z along their principal axis. A component is a
stair flight when the fit is strongly linear, the incline is a walkable
angle (14-60 degrees), the strip is elongated and its rise is a plausible
fraction of the storey height.

Everything here is a geometric hypothesis: a loading ramp or a sloped roof
segment inside the band looks the same as a stair, so elements carry
``inferred=True`` and low-to-moderate confidence for engineer review.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import ndimage

from ..geometry.section import CloudGeometry
from .geometric import CHUNK, DetectedElement

STAIR_RES = 0.10              # plan raster resolution, m
STAIR_BAND_MARGIN_M = 0.25    # distance kept from the level planes, m
STAIR_MIN_POINTS_CELL = 3
STAIR_MIN_CELLS = 40          # >= 0.40 m^2 plan area
STAIR_MIN_RUN_M = 1.20
STAIR_MAX_RUN_M = 12.0
STAIR_MIN_WIDTH_M = 0.60
STAIR_MAX_WIDTH_M = 3.20
STAIR_MIN_RISE_M = 0.80
STAIR_MAX_RISE_M = 4.80
STAIR_MIN_ANGLE_DEG = 14.0
STAIR_MAX_ANGLE_DEG = 60.0
STAIR_MIN_R2 = 0.55
STAIR_LEVEL_GAP_MIN_M = 0.80
STAIR_LEVEL_GAP_MAX_M = 5.20
STAIR_TREAD_M = 0.175         # assumed riser height for the step estimate


def _iter_positions(path):
    arr = np.load(path, mmap_mode="r")
    for start in range(0, arr.shape[0], CHUNK):
        yield np.asarray(arr[start : start + CHUNK])


def _level_pairs(levels: list[dict[str, Any]]) -> list[tuple[float, float]]:
    zs = sorted(float(level["z_local"]) for level in levels if level.get("z_local") is not None)
    pairs = []
    for low, high in zip(zs, zs[1:]):
        gap = high - low
        if STAIR_LEVEL_GAP_MIN_M <= gap <= STAIR_LEVEL_GAP_MAX_M:
            pairs.append((low, high))
    return pairs


def detect_stairs(geom: CloudGeometry, levels: list[dict[str, Any]]) -> list[DetectedElement]:
    """Find stair flights as inclined planar strips between adjacent levels."""
    pairs = _level_pairs(levels)
    if not pairs:
        return []
    local_min = geom.bbox_min - geom.origin
    res = STAIR_RES
    nu = max(1, int(math.ceil((float(geom.bbox_max[0] - local_min[0])) / res)) + 1)
    nv = max(1, int(math.ceil((float(geom.bbox_max[1] - local_min[1])) / res)) + 1)
    ncells = nv * nu

    counts_all = [np.zeros(ncells, dtype=np.int32) for _ in pairs]
    zsum_all = [np.zeros(ncells, dtype=np.float64) for _ in pairs]
    zmin_all = [np.full(ncells, np.inf, dtype=np.float32) for _ in pairs]
    zmax_all = [np.full(ncells, -np.inf, dtype=np.float32) for _ in pairs]

    for chunk in _iter_positions(geom.positions_path):
        x = chunk[:, 0]
        y = chunk[:, 1]
        z = chunk[:, 2]
        ix = np.floor((x - local_min[0]) / res).astype(np.int64)
        iy = np.floor((y - local_min[1]) / res).astype(np.int64)
        valid = (ix >= 0) & (ix < nu) & (iy >= 0) & (iy < nv)
        if not valid.any():
            continue
        ix = ix[valid]
        iy = iy[valid]
        zv = z[valid]
        flat = iy * nu + ix
        for index, (low, high) in enumerate(pairs):
            sel = (zv > low + STAIR_BAND_MARGIN_M) & (zv < high - STAIR_BAND_MARGIN_M)
            if not sel.any():
                continue
            zf = zv[sel]
            ff = flat[sel]
            counts_all[index] += np.bincount(ff, minlength=ncells).astype(np.int32)
            zsum_all[index] += np.bincount(ff, weights=zf, minlength=ncells)
            np.minimum.at(zmin_all[index], ff, zf)
            np.maximum.at(zmax_all[index], ff, zf)

    elements: list[DetectedElement] = []
    minx = float(local_min[0])
    miny = float(local_min[1])
    origin = geom.origin
    for index, (low, high) in enumerate(pairs):
        counts = counts_all[index].reshape(nv, nu)
        zsum = zsum_all[index].reshape(nv, nu)
        zmin = zmin_all[index].reshape(nv, nu)
        zmax = zmax_all[index].reshape(nv, nu)
        mask = counts >= STAIR_MIN_POINTS_CELL
        if not mask.any():
            continue
        labelled, ncomp = ndimage.label(mask, structure=np.ones((3, 3), dtype=bool))
        for comp in range(1, ncomp + 1):
            comp_mask = labelled == comp
            cells = int(comp_mask.sum())
            if cells < STAIR_MIN_CELLS:
                continue
            iy, ix = np.nonzero(comp_mask)
            weights = counts[comp_mask].astype(np.float64)
            cx_cells = minx + (ix + 0.5) * res
            cy_cells = miny + (iy + 0.5) * res
            wsum = float(weights.sum())
            mx = float((cx_cells * weights).sum() / wsum)
            my = float((cy_cells * weights).sum() / wsum)
            dx = cx_cells - mx
            dy = cy_cells - my
            cov_xx = float((weights * dx * dx).sum() / wsum)
            cov_yy = float((weights * dy * dy).sum() / wsum)
            cov_xy = float((weights * dx * dy).sum() / wsum)
            trace = cov_xx + cov_yy
            det = cov_xx * cov_yy - cov_xy * cov_xy
            disc = max(0.0, trace * trace / 4.0 - det)
            root = math.sqrt(disc)
            lam1 = trace / 2.0 + root
            if lam1 <= 1e-9:
                continue
            if abs(cov_xy) > 1e-12:
                axis = np.array([lam1 - cov_yy, cov_xy])
            else:
                axis = np.array([1.0, 0.0]) if cov_xx >= cov_yy else np.array([0.0, 1.0])
            norm = float(np.linalg.norm(axis))
            if norm <= 1e-12:
                continue
            axis = axis / norm
            t = dx * axis[0] + dy * axis[1]
            perp = np.array([-axis[1], axis[0]])
            s = dx * perp[0] + dy * perp[1]
            # Robust plan width: a percentile span of the perpendicular
            # offsets. 2*sqrt(lambda2) only gives the uniform-strip standard
            # deviation and understated a 1.2 m flight as 0.7 m.
            width_est = float(np.percentile(s, 97) - np.percentile(s, 2)) + res
            length = float(t.max() - t.min()) + res
            if not (STAIR_MIN_RUN_M <= length <= STAIR_MAX_RUN_M):
                continue
            if not (STAIR_MIN_WIDTH_M <= max(width_est, res) <= STAIR_MAX_WIDTH_M):
                continue
            # Mean z per cell and a linear fit along the principal axis.
            cell_z = np.divide(zsum[comp_mask], counts[comp_mask])
            order = np.argsort(t)
            t_sorted = t[order]
            z_sorted = cell_z[order]
            t_mean = float(t_sorted.mean())
            z_mean = float(z_sorted.mean())
            var_t = float(((t_sorted - t_mean) ** 2).sum())
            if var_t <= 1e-9:
                continue
            slope = float(((t_sorted - t_mean) * (z_sorted - z_mean)).sum() / var_t)
            intercept = z_mean - slope * t_mean
            resid = z_sorted - (slope * t_sorted + intercept)
            ss_res = float((resid**2).sum())
            ss_tot = float(((z_sorted - z_mean) ** 2).sum())
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-9 else 0.0
            if r2 < STAIR_MIN_R2:
                continue
            angle_deg = math.degrees(math.atan(abs(slope)))
            if not (STAIR_MIN_ANGLE_DEG <= angle_deg <= STAIR_MAX_ANGLE_DEG):
                continue
            rise = abs(slope) * length
            if not (STAIR_MIN_RISE_M <= rise <= STAIR_MAX_RISE_M):
                continue
            # The flight must stay inside its storey band, not span levels.
            z_low_end = slope * float(t.min()) + intercept
            z_high_end = slope * float(t.max()) + intercept
            if min(z_low_end, z_high_end) < low + 0.1 or max(z_low_end, z_high_end) > high - 0.1:
                continue

            lower_first = slope >= 0
            t_lo = float(t.min()) if lower_first else float(t.max())
            t_hi = float(t.max()) if lower_first else float(t.min())
            p0 = [
                round(mx + t_lo * axis[0] + float(origin[0]), 4),
                round(my + t_lo * axis[1] + float(origin[1]), 4),
                round(slope * t_lo + intercept + float(origin[2]), 4),
            ]
            p1 = [
                round(mx + t_hi * axis[0] + float(origin[0]), 4),
                round(my + t_hi * axis[1] + float(origin[1]), 4),
                round(slope * t_hi + intercept + float(origin[2]), 4),
            ]
            bbox_min = [
                round(min(p0[0], p1[0]) - width_est / 2.0, 3),
                round(min(p0[1], p1[1]) - width_est / 2.0, 3),
                round(min(p0[2], p1[2]), 3),
            ]
            bbox_max = [
                round(max(p0[0], p1[0]) + width_est / 2.0, 3),
                round(max(p0[1], p1[1]) + width_est / 2.0, 3),
                round(max(p0[2], p1[2]), 3),
            ]
            confidence = min(0.75, 0.35 + 0.30 * r2 + 0.10 * min(1.0, cells / 120.0))
            elements.append(
                DetectedElement(
                    class_name="stair",
                    geometry={
                        "kind": "member",
                        "p0": p0,
                        "p1": p1,
                        "section_m": round(max(width_est, res), 3),
                        "note": "inclined planar flight between two level candidates",
                    },
                    bbox={"min": bbox_min, "max": bbox_max},
                    confidence=round(float(confidence), 3),
                    measured=True,
                    inferred=True,
                    dimensions={
                        "run_m": round(length * math.cos(math.radians(angle_deg)), 3),
                        "rise_m": round(rise, 3),
                        "width_m": round(max(width_est, res), 3),
                        "slope_deg": round(angle_deg, 1),
                        "steps_est": max(2, int(round(rise / STAIR_TREAD_M))),
                        "length_m": round(length, 3),
                    },
                    metadata={
                        "method": "inclined-plane-fit-v1",
                        "level_low_z": round(low + float(origin[2]), 3),
                        "level_high_z": round(high + float(origin[2]), 3),
                        "plan_cells": cells,
                        "fit_r2": round(r2, 3),
                        "confidence_kind": "heuristic",
                        "notes": "geometric hypothesis; a ramp or slope looks the same - verify",
                    },
                )
            )
    return elements
