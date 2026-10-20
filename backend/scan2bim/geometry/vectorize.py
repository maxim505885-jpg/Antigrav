"""Turn a 2D point slice into editable polylines.

Pipeline: occupancy raster -> morphological closing -> connected components ->
contour tracing -> simplification -> dominant-direction regularisation.

Everything produced here is *measured* geometry: it is derived from the points
inside the slicing slab. Nothing is inferred beyond the line simplification and
orthogonal regularisation, which are reported in the result metadata.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import ndimage
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union
from skimage.measure import find_contours

from ..config import MAX_RASTER_CELLS, MIN_COMPONENT_AREA


def _estimate_dominant_angle(mask: np.ndarray) -> tuple[float, float]:
    """Return (angle_rad, concentration) of dominant linear structure.

    Angles are folded modulo 90 degrees because a wall is undirected.
    Concentration in [0,1]; low values mean the regularisation is unreliable.
    """
    if mask.size == 0 or not mask.any():
        return 0.0, 0.0
    smooth = ndimage.gaussian_filter(mask.astype(np.float32), 1.0)
    gy, gx = np.gradient(smooth)
    mag = np.hypot(gx, gy)
    strong = mag > (mag.max() * 0.05 if mag.max() > 0 else 0)
    if not np.any(strong):
        return 0.0, 0.0
    # Gradient points across the wall, so wall direction is gradient + 90 deg.
    angles = np.arctan2(gy[strong], gx[strong]) + math.pi / 2.0
    weights = mag[strong].astype(np.float64)
    folded = np.mod(angles, math.pi / 2.0)
    c = float(np.sum(weights * np.cos(4.0 * folded)))
    s = float(np.sum(weights * np.sin(4.0 * folded)))
    theta = math.atan2(s, c) / 4.0
    concentration = math.hypot(c, s) / max(1e-9, float(np.sum(weights)))
    return float(theta), float(concentration)


def _rotate(u: np.ndarray, v: np.ndarray, angle: float) -> tuple[np.ndarray, np.ndarray]:
    """Rotate by +angle (counter-clockwise)."""
    ca, sa = math.cos(angle), math.sin(angle)
    return u * ca - v * sa, u * sa + v * ca


def _rasterize(
    u: np.ndarray,
    v: np.ndarray,
    res: float,
    region: tuple[float, float, float, float] | None,
    pad_cells: int = 2,
    max_cells: int = MAX_RASTER_CELLS,
) -> tuple[np.ndarray, float, float, float, float, bool]:
    if len(u) == 0:
        raise ValueError("cannot rasterise an empty slice")
    if region is not None:
        min_u, max_u, min_v, max_v = region
        keep = (u >= min_u) & (u <= max_u) & (v >= min_v) & (v <= max_v)
        u, v = u[keep], v[keep]
        if len(u) == 0:
            raise ValueError("no points fall inside the requested region")
    min_u = float(np.min(u))
    max_u = float(np.max(u))
    min_v = float(np.min(v))
    max_v = float(np.max(v))
    if max_u - min_u < res:
        max_u = min_u + res
    if max_v - min_v < res:
        max_v = min_v + res

    nu = int(math.ceil((max_u - min_u) / res)) + 1 + 2 * pad_cells
    nv = int(math.ceil((max_v - min_v) / res)) + 1 + 2 * pad_cells
    resized = False
    if nu * nv > max_cells:
        factor = math.sqrt((nu * nv) / max_cells)
        res = res * factor
        nu = int(math.ceil((max_u - min_u) / res)) + 1 + 2 * pad_cells
        nv = int(math.ceil((max_v - min_v) / res)) + 1 + 2 * pad_cells
        resized = True

    origin_u = min_u - pad_cells * res
    origin_v = min_v - pad_cells * res
    iu = np.floor((u - origin_u) / res).astype(np.int32)
    iv = np.floor((v - origin_v) / res).astype(np.int32)
    valid = (iu >= 0) & (iu < nu) & (iv >= 0) & (iv < nv)
    mask = np.zeros((nv, nu), dtype=bool)
    mask[iv[valid], iu[valid]] = True
    return mask, origin_u, origin_v, res, nu, nv, resized


def _polygons_from_mask(
    mask: np.ndarray,
    origin_u: float,
    origin_v: float,
    res: float,
    theta: float,
    min_area: float,
    simplify_tol: float,
) -> list[dict[str, Any]]:
    """Trace contours; theta is the angle used to rotate the slice, so undo it here."""
    labelled, count = ndimage.label(mask, structure=np.ones((3, 3), dtype=bool))
    polys: list[dict[str, Any]] = []
    for comp in range(1, count + 1):
        comp_mask = labelled == comp
        padded = np.pad(comp_mask, 1, mode="constant", constant_values=False)
        contours = find_contours(padded.astype(np.float32), 0.5)
        for contour in contours:
            if len(contour) < 4:
                continue
            rows = contour[:, 0] - 1.0
            cols = contour[:, 1] - 1.0
            cu = origin_u + cols * res
            cv = origin_v + rows * res
            if theta:
                # The slice was rotated by -theta for rasterisation; undo that
                # rotation so the output uses measured coordinates.
                cu, cv = _rotate(cu, cv, theta)
            try:
                poly = Polygon(np.column_stack([cu, cv]))
                if not poly.is_valid:
                    poly = poly.buffer(0)
            except Exception:
                continue
            if poly.is_empty:
                continue
            if isinstance(poly, MultiPolygon):
                candidates = list(poly.geoms)
            else:
                candidates = [poly]
            for part in candidates:
                if part.area < min_area or len(part.exterior.coords) < 4:
                    continue
                simplified = part.simplify(max(simplify_tol, res * 0.5), preserve_topology=True)
                if simplified.is_empty or simplified.area < min_area:
                    simplified = part
                pts = [(round(float(x), 4), round(float(y), 4)) for x, y in simplified.exterior.coords]
                if len(pts) > 1 and pts[0] == pts[-1]:
                    pts = pts[:-1]
                if len(pts) < 3:
                    continue
                minx, miny, maxx, maxy = simplified.bounds
                polys.append(
                    {
                        "points": pts,
                        "area": round(float(simplified.area), 4),
                        "perimeter": round(float(simplified.length), 4),
                        "bbox": [round(minx, 4), round(miny, 4), round(maxx, 4), round(maxy, 4)],
                        "component": int(comp),
                        "closed": True,
                        "is_hole": False,
                    }
                )
    # Containment parity: a polygon inside an odd number of larger polygons is a hole.
    shapely_polys = []
    for item in polys:
        try:
            shapely_polys.append(Polygon(item["points"]))
        except Exception:
            shapely_polys.append(None)
    for i, item in enumerate(polys):
        pi = shapely_polys[i]
        if pi is None or pi.is_empty:
            continue
        depth = 0
        probe = pi.representative_point()
        for j, item2 in enumerate(polys):
            if i == j:
                continue
            pj = shapely_polys[j]
            if pj is None or pj.area <= pi.area * 1.0001:
                continue
            try:
                if pj.contains(probe):
                    depth += 1
            except Exception:
                pass
        item["is_hole"] = bool(depth % 2 == 1)
    return polys


def vectorize_2d(
    u: np.ndarray,
    v: np.ndarray,
    grid_res: float = 0.02,
    region: tuple[float, float, float, float] | None = None,
    close_radius_m: float = 0.06,
    regularize: bool = True,
    min_component_area: float = MIN_COMPONENT_AREA,
    min_points: int = 20,
    max_preview_points: int = 80000,
    max_cells: int = MAX_RASTER_CELLS,
    fill_holes_narrower_than_m: float = 0.40,
    fill_holes_smaller_than_m2: float = 0.15,
    rng_seed: int = 7,
) -> dict[str, Any]:
    """Vectorise 2D points into measured polylines.

    Returns a JSON-friendly dictionary with polygons, statistics and warnings.
    """
    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    warnings: list[str] = []
    if len(u) < min_points:
        return {
            "polygons": [],
            "point_count": int(len(u)),
            "warnings": ["too few points in the section slab to build geometry"],
            "regularization": None,
            "grid_res": grid_res,
        }

    # Remove exact duplicates cheaply at raster resolution; they bias nothing but
    # this also gives a stable point count independent of scanner overlap.
    mask, origin_u, origin_v, used_res, nu, nv, resized = _rasterize(
        u, v, grid_res, region, max_cells=max_cells
    )
    if resized:
        warnings.append(
            f"grid resolution increased to {used_res:.3f} m to respect the raster cell limit"
        )
    if not mask.any():
        return {
            "polygons": [],
            "point_count": int(len(u)),
            "warnings": warnings + ["empty raster"],
            "regularization": None,
            "grid_res": used_res,
        }

    theta, concentration = _estimate_dominant_angle(mask)
    if not regularize or concentration < 0.15:
        theta = 0.0
        if regularize and concentration < 0.15:
            warnings.append(
                "dominant direction is weak; orthogonal regularisation was skipped"
            )
    if theta:
        u_rot, v_rot = _rotate(u, v, -theta)
        # The region filter is expressed in original coordinates and has already
        # been applied by the first rasterisation.
        mask, origin_u, origin_v, used_res, nu, nv, resized = _rasterize(
            u_rot, v_rot, used_res, None
        )
        if resized:
            warnings.append("grid resolution increased after rotation")

    radius = max(1, int(round(close_radius_m / used_res / 2.0))) if close_radius_m > 0 else 0
    if radius > 0:
        footprint = np.zeros((2 * radius + 1, 2 * radius + 1), dtype=bool)
        yy, xx = np.mgrid[-radius : radius + 1, -radius : radius + 1]
        footprint[yy * yy + xx * xx <= radius * radius + 1] = True
        # Scanner returns sparse hits on a surface. A brush dilation bridges
        # those gaps without eroding the measured surface away again.
        mask = ndimage.binary_dilation(mask, structure=footprint)
        mask = ndimage.binary_closing(mask, structure=footprint)
        warnings.append(
            "surface bands are drawn with a {:.0f} mm brush; measured positions remain "
            "the scan points (contour is offset by up to one brush radius)".format(
                radius * used_res * 1000
            )
        )

    polys = _polygons_from_mask(
        mask,
        origin_u,
        origin_v,
        used_res,
        theta,
        min_component_area,
        simplify_tol=max(0.01, used_res * 0.9),
    )

    # Narrow cavities between the two measured faces of a wall (and the hollow
    # between the four faces of a column) are not useful drawing holes. Rooms
    # are wide and remain. The simplification is explicit in the result.
    filled_holes = 0
    kept: list[dict[str, Any]] = []
    for poly in polys:
        if poly["is_hole"]:
            width = poly["bbox"][2] - poly["bbox"][0]
            height = poly["bbox"][3] - poly["bbox"][1]
            if (
                min(width, height) < fill_holes_narrower_than_m
                or poly["area"] < fill_holes_smaller_than_m2
            ):
                filled_holes += 1
                continue
        kept.append(poly)
    polys = [p for p in kept if p["area"] >= min_component_area]
    outer_area = sum(p["area"] for p in polys if not p["is_hole"])
    hole_area = sum(p["area"] for p in polys if p["is_hole"])
    total_area = max(0.0, outer_area - hole_area)
    covered_cells = int(mask.sum())
    preview: list[list[float]] = []
    if max_preview_points and max_preview_points > 0:
        sampled = min(len(u), max_preview_points)
        if sampled < len(u):
            idx = np.random.default_rng(rng_seed).choice(len(u), size=sampled, replace=False)
            pu, pv = u[idx], v[idx]
        else:
            pu, pv = u, v
        step = max(1, len(pu) // max_preview_points)
        preview = [
            [round(float(a), 3), round(float(b), 3)]
            for a, b in zip(pu[::step], pv[::step])
        ]

    return {
        "polygons": polys,
        "point_count": int(len(u)),
        "covered_cells": covered_cells,
        "grid_res": used_res,
        "raster_size": [int(nu), int(nv)],
        "regularization": {
            "enabled": bool(regularize and theta != 0.0),
            "angle_deg": round(math.degrees(theta), 3),
            "concentration": round(concentration, 3),
            "close_radius_m": close_radius_m,
        },
        "total_area_m2": round(float(total_area), 4),
        "outer_area_m2": round(float(outer_area), 4),
        "open_hole_area_m2": round(float(hole_area), 4),
        "filled_small_holes": filled_holes,
        "warnings": warnings,
        "preview_points": preview,
    }
