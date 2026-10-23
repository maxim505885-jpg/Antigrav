"""Horizontal and vertical section extraction from a stored cloud."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from ..config import (
    DEFAULT_GRID_RES,
    DEFAULT_SECTION_THICKNESS,
    MAX_SECTION_PREVIEW_POINTS,
    MAX_SECTION_RASTER_CELLS,
)
from .vectorize import vectorize_2d

CHUNK = 4_000_000


@dataclass
class CloudGeometry:
    positions_path: Path
    origin: np.ndarray
    bbox_min: np.ndarray
    bbox_max: np.ndarray
    count: int
    spatial_index_path: Path | None = None


@dataclass
class SectionFrame:
    """Maps (u, v) drawing coordinates to world coordinates."""

    kind: str
    axis: str | None
    plane: str
    u_axis: str
    v_axis: str
    w_axis: str
    position_world: float
    position_local: float
    thickness: float
    world_offset: tuple[float, float]
    u_label: str
    v_label: str

    def to_world(self, u: float, v: float) -> tuple[float, float, float]:
        cu = u + self.world_offset[0]
        cv = v + self.world_offset[1]
        if self.kind == "horizontal":
            return cu, cv, self.position_world
        if self.axis == "x":
            return self.position_world, cu, cv
        return cu, self.position_world, cv

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "axis": self.axis,
            "plane": self.plane,
            "u_axis": self.u_axis,
            "v_axis": self.v_axis,
            "w_axis": self.w_axis,
            "position_world": round(self.position_world, 4),
            "thickness": self.thickness,
            "world_offset": [round(self.world_offset[0], 4), round(self.world_offset[1], 4)],
            "u_label": self.u_label,
            "v_label": self.v_label,
        }


def build_frame(geom: CloudGeometry, kind: str, axis: str | None, position: float | None, thickness: float) -> SectionFrame:
    bmin = geom.bbox_min
    bmax = geom.bbox_max
    if kind == "horizontal":
        if position is None:
            position = float((bmin[2] + bmax[2]) / 2.0)
        return SectionFrame(
            kind="horizontal",
            axis=None,
            plane="xy",
            u_axis="x",
            v_axis="y",
            w_axis="z",
            position_world=float(position),
            position_local=float(position - geom.origin[2]),
            thickness=thickness,
            world_offset=(float(geom.origin[0]), float(geom.origin[1])),
            u_label="X",
            v_label="Y",
        )
    if axis not in {"x", "y"}:
        raise ValueError("vertical sections require axis 'x' or 'y'")
    widx = 0 if axis == "x" else 1
    if position is None:
        position = float((bmin[widx] + bmax[widx]) / 2.0)
    if axis == "x":
        return SectionFrame(
            kind="vertical",
            axis="x",
            plane="yz",
            u_axis="y",
            v_axis="z",
            w_axis="x",
            position_world=float(position),
            position_local=float(position - geom.origin[0]),
            thickness=thickness,
            world_offset=(float(geom.origin[1]), float(geom.origin[2])),
            u_label="Y",
            v_label="Z",
        )
    return SectionFrame(
        kind="vertical",
        axis="y",
        plane="xz",
        u_axis="x",
        v_axis="z",
        w_axis="y",
        position_world=float(position),
        position_local=float(position - geom.origin[1]),
        thickness=thickness,
        world_offset=(float(geom.origin[0]), float(geom.origin[2])),
        u_label="X",
        v_label="Z",
    )


def _iter_positions(path: Path) -> Iterator[np.ndarray]:
    arr = np.load(path, mmap_mode="r")
    if arr.ndim != 2 or arr.shape[1] != 3:
        raise ValueError(f"invalid positions array {arr.shape}")
    for start in range(0, arr.shape[0], CHUNK):
        yield np.asarray(arr[start : start + CHUNK])


def _iter_slice_positions(geom: CloudGeometry, frame: SectionFrame) -> Iterator[np.ndarray]:
    if geom.spatial_index_path is None:
        yield from _iter_positions(geom.positions_path)
        return
    from ..pointdata import NpyPointProvider, PointQuery
    from ..pointdata.index import IndexedPointProvider

    colors = geom.positions_path.with_name("colors.npy")
    source = NpyPointProvider(geom.positions_path, origin=geom.origin,
                              colors_path=colors if colors.exists() else None)
    indexed = IndexedPointProvider(source, geom.spatial_index_path)
    w_index = {"x": 0, "y": 1, "z": 2}[frame.w_axis]
    # Use the index's conservative data bounds so indexed and linear scans
    # include the same rows even if the cloud metadata bbox is slightly stale.
    lower, upper = (bound.copy() for bound in indexed.grid_bounds_world)
    # Broad phase must cover float32 slab arithmetic in the legacy exact filter.
    extent = max(1., float(np.max(np.abs(lower-geom.origin))),
                 float(np.max(np.abs(upper-geom.origin))), abs(frame.position_local))
    pad = float(np.finfo(np.float32).eps) * extent * 4
    lower -= pad
    upper += pad
    lower[w_index] = frame.position_world-frame.thickness/2-pad
    upper[w_index] = frame.position_world+frame.thickness/2+pad
    query = PointQuery(tuple(lower)+tuple(upper))
    if not indexed.should_use_index(query):
        yield from _iter_positions(geom.positions_path)
        return
    positions = np.load(geom.positions_path, mmap_mode="r", allow_pickle=False)
    try:
        for batch in indexed.iter_points(query):
            # Keep the original local float32 values, not a world-space roundtrip.
            yield np.asarray(positions[batch.source_indices])
    finally:
        del positions


def collect_slice(
    geom: CloudGeometry,
    frame: SectionFrame,
    region: tuple[float, float, float, float] | None = None,
    max_points: int | None = None,
    progress=None,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Return (u, v, slab_point_count) for points inside the slicing slab."""
    w_index = {"x": 0, "y": 1, "z": 2}[frame.w_axis]
    u_index = {"x": 0, "y": 1, "z": 2}[frame.u_axis]
    v_index = {"x": 0, "y": 1, "z": 2}[frame.v_axis]
    half = frame.thickness / 2.0
    total = 0
    u_parts: list[np.ndarray] = []
    v_parts: list[np.ndarray] = []
    for chunk in _iter_slice_positions(geom, frame):
        w = chunk[:, w_index]
        mask = np.abs(w - frame.position_local) <= half
        selected = int(mask.sum())
        if selected == 0:
            continue
        total += selected
        uv = chunk[mask][:, [u_index, v_index]].astype(np.float64, copy=False)
        if region is not None:
            min_u, max_u, min_v, max_v = region
            keep = (
                (uv[:, 0] >= min_u)
                & (uv[:, 0] <= max_u)
                & (uv[:, 1] >= min_v)
                & (uv[:, 1] <= max_v)
            )
            uv = uv[keep]
        u_parts.append(uv[:, 0])
        v_parts.append(uv[:, 1])
        if progress:
            progress(min(0.8, 0.1 + 0.1 * len(u_parts)), "сбор точек в слое сечения")
    if not u_parts:
        return np.empty(0), np.empty(0), 0
    u = np.concatenate(u_parts)
    v = np.concatenate(v_parts)
    if max_points and len(u) > max_points:
        idx = np.random.default_rng(11).choice(len(u), size=max_points, replace=False)
        u, v = u[idx], v[idx]
    return u, v, total


def extract_section(
    geom: CloudGeometry,
    kind: str = "horizontal",
    axis: str | None = None,
    position: float | None = None,
    thickness: float = DEFAULT_SECTION_THICKNESS,
    grid_res: float = DEFAULT_GRID_RES,
    region: tuple[float, float, float, float] | None = None,
    regularize: bool = True,
    min_component_area: float = 0.03,
    close_radius_m: float = 0.06,
    max_preview_points: int = MAX_SECTION_PREVIEW_POINTS,
    progress=None,
) -> dict[str, Any]:
    frame = build_frame(geom, kind, axis, position, thickness)
    if region is not None:
        # API regions are given in world section coordinates (what the user sees).
        region = (
            region[0] - frame.world_offset[0],
            region[1] - frame.world_offset[0],
            region[2] - frame.world_offset[1],
            region[3] - frame.world_offset[1],
        )
    u, v, slab_total = collect_slice(geom, frame, region=region, progress=progress)
    warnings: list[str] = []
    if len(u) == 0:
        return {
            "frame": frame.as_dict(),
            "polygons": [],
            "point_count": 0,
            "slab_point_count": 0,
            "warnings": [
                "no points inside the slicing slab; adjust position/thickness or region"
            ],
            "grid_res": grid_res,
            "total_area_m2": 0.0,
            "preview_points": [],
        }
    if len(u) < 20:
        warnings.append("в слое слишком мало точек; геометрия ненадёжна")
    if progress:
        progress(0.6, "векторизация сечения")
    result = vectorize_2d(
        u,
        v,
        grid_res=grid_res,
        region=None,
        close_radius_m=close_radius_m,
        regularize=regularize,
        min_component_area=min_component_area,
        max_preview_points=max_preview_points,
        # Interactive budget: coarsen (with a warning) instead of spending
        # minutes on a site-wide plan at 2 cm.
        max_cells=MAX_SECTION_RASTER_CELLS,
    )
    warnings.extend(result.get("warnings", []))
    total_area = result.get("total_area_m2", 0.0)
    density = float(slab_total) / total_area if total_area else 0.0
    result.update(
        {
            "frame": frame.as_dict(),
            "slab_point_count": int(slab_total),
            "point_count": int(len(u)),
            "density_pts_per_m2": round(density, 1),
            "warnings": warnings,
            "measured": True,
            "note": (
                "Контуры измерены по точкам внутри слоя; ортогональная регуляризация и "
                "упрощение линий применены и отражены в предупреждениях."
            ),
        }
    )
    return result
