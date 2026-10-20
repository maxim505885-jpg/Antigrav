"""Wall extraction from the vertical occupancy grid.

Long connected runs (rooms, facades) are skeletonised and decomposed into
straight segments with a probabilistic Hough transform. Parallel segments that
are closer than 0.45 m are merged, which turns the two scanned faces of a wall
into one centreline with a measured thickness.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import ndimage
from skimage.morphology import skeletonize
from skimage.transform import probabilistic_hough_line

from ..geometry.section import CloudGeometry
from .geometric import (
    BAND_HEIGHT,
    WALL_MAX_THICKNESS_M,
    WALL_MIN_LENGTH_M,
    DetectedElement,
)

Segment = dict[str, Any]


def _vertical_mask(grid: dict[str, Any], min_extent: float = 1.2) -> np.ndarray:
    band_occ = grid["band_occ"]
    counts = grid["counts"]
    occupied = band_occ.any(axis=0)
    band_count = band_occ.sum(axis=0)
    return occupied & (band_count * BAND_HEIGHT >= min_extent) & (counts >= 5)


def _angle_diff(a: float, b: float) -> float:
    d = abs(a - b) % math.pi
    return min(d, math.pi - d)


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


def _hough_segments(mask: np.ndarray, res: float, minx: float, miny: float) -> list[Segment]:
    if mask.sum() < 10:
        return []
    skeleton = skeletonize(mask)
    lines = probabilistic_hough_line(
        skeleton,
        threshold=8,
        line_length=max(6, int(1.2 / res)),
        line_gap=max(2, int(0.45 / res)),
    )
    segments: list[Segment] = []
    for (x0, y0), (x1, y1) in lines:
        p0 = np.array([minx + (x0 + 0.5) * res, miny + (y0 + 0.5) * res])
        p1 = np.array([minx + (x1 + 0.5) * res, miny + (y1 + 0.5) * res])
        delta = p1 - p0
        length = float(np.linalg.norm(delta))
        if length < 0.8:
            continue
        angle = math.atan2(float(delta[1]), float(delta[0])) % math.pi
        direction = np.array([math.cos(angle), math.sin(angle)])
        segments.append(
            {
                "p0": p0,
                "p1": p1,
                "mid": (p0 + p1) / 2,
                "dir": direction,
                "angle": angle,
                "length": length,
            }
        )
    return segments


def _group_segments(segments: list[Segment]) -> list[list[Segment]]:
    if not segments:
        return []
    uf = _UnionFind(len(segments))
    for i in range(len(segments)):
        si = segments[i]
        for j in range(i + 1, len(segments)):
            sj = segments[j]
            if _angle_diff(si["angle"], sj["angle"]) > math.radians(12):
                continue
            normal = np.array([-si["dir"][1], si["dir"][0]])
            if abs(float(np.dot(sj["mid"] - si["mid"], normal))) > 0.45:
                continue
            projections = [
                float(np.dot(sj["p0"] - si["mid"], si["dir"])),
                float(np.dot(sj["p1"] - si["mid"], si["dir"])),
            ]
            overlap = min(max(projections), si["length"] / 2) - max(
                min(projections), -si["length"] / 2
            )
            if overlap > -0.5:
                uf.union(i, j)
    groups: dict[int, list[Segment]] = {}
    for i, segment in enumerate(segments):
        groups.setdefault(uf.find(i), []).append(segment)
    return list(groups.values())


def _group_line(group: list[Segment]) -> tuple[np.ndarray, np.ndarray, float]:
    weight = sum(s["length"] for s in group)
    c = sum(math.cos(2 * s["angle"]) * s["length"] for s in group) / weight
    s_ = sum(math.sin(2 * s["angle"]) * s["length"] for s in group) / weight
    angle = 0.5 * math.atan2(s_, c)
    direction = np.array([math.cos(angle), math.sin(angle)])
    endpoints = np.array([p for seg in group for p in (seg["p0"], seg["p1"])])
    center = endpoints.mean(axis=0)
    projections = (endpoints - center) @ direction
    center = center + direction * ((projections.min() + projections.max()) / 2)
    length = float(projections.max() - projections.min())
    return center, direction, length


def _thickness_source(thickness: float, res: float) -> str:
    """Say honestly whether the wall thickness was observed or is a floor.

    A single scanned face rasterised on a 0.10 m grid already spreads over
    ~2-3 cells, so anything at that scale is not evidence of two faces.
    """
    if thickness <= 2.5 * res + res:
        return "single face (thickness at grid resolution, not observed)"
    return "face spacing"


def _box_element(
    geom: CloudGeometry,
    grid: dict[str, Any],
    center: np.ndarray,
    direction: np.ndarray,
    length: float,
    thickness: float,
    z0: float,
    z1: float,
    confidence: float,
    point_count: int,
    method: str,
) -> DetectedElement:
    angle = math.atan2(float(direction[1]), float(direction[0]))
    height = max(0.05, z1 - z0)
    z_center = (z0 + z1) / 2
    world_center = [
        round(float(center[0]) + float(geom.origin[0]), 4),
        round(float(center[1]) + float(geom.origin[1]), 4),
        round(float(z_center) + float(geom.origin[2]), 4),
    ]
    ca, sa = math.cos(angle), math.sin(angle)
    corners = []
    for lx, ly in (
        (-length / 2, -thickness / 2),
        (length / 2, -thickness / 2),
        (length / 2, thickness / 2),
        (-length / 2, thickness / 2),
    ):
        corners.append((center[0] + lx * ca - ly * sa, center[1] + lx * sa + ly * ca))
    xs = [c[0] + float(geom.origin[0]) for c in corners]
    ys = [c[1] + float(geom.origin[1]) for c in corners]
    return DetectedElement(
        class_name="wall",
        geometry={
            "kind": "oriented_box",
            "center": world_center,
            "sizes": {
                "length": round(float(length), 3),
                "thickness": round(float(thickness), 3),
                "height": round(float(height), 3),
            },
            "rotation_z": round(float(angle), 5),
            "note": "measured wall segment; centreline from Hough, thickness from face spacing",
        },
        bbox={
            "min": [
                round(min(xs), 3),
                round(min(ys), 3),
                round(z0 + float(geom.origin[2]), 3),
            ],
            "max": [
                round(max(xs), 3),
                round(max(ys), 3),
                round(z1 + float(geom.origin[2]), 3),
            ],
        },
        confidence=round(float(max(0.2, min(0.9, confidence))), 3),
        measured=True,
        inferred=False,
        dimensions={
            "length_m": round(float(length), 3),
            "thickness_m": round(float(thickness), 3),
            "height_m": round(float(height), 3),
            "footprint_area_m2": round(float(length * thickness), 3),
            "thickness_source": _thickness_source(thickness, float(grid["res"])),
        },
        metadata={
            "method": method,
            "point_count_in_cells": int(point_count),
            "grid_res_m": float(grid["res"]),
            "confidence_kind": "heuristic",
            "material": None,
            "load_bearing": None,
            "notes": "class is a geometric hypothesis; verify in the editor",
        },
    )


def detect_walls(geom: CloudGeometry, grid: dict[str, Any]) -> list[DetectedElement]:
    mask = _vertical_mask(grid)
    if mask.sum() < 20:
        return []
    res = float(grid["res"])
    minx, miny = float(grid["min"][0]), float(grid["min"][1])
    minz = float(grid["min"][2])
    z_max = minz + grid["band_occ"].shape[0] * BAND_HEIGHT

    segments = _hough_segments(mask, res, minx, miny)
    groups = _group_segments(segments)
    iy_all, ix_all = np.nonzero(mask)
    if len(ix_all) == 0:
        return []
    points = np.column_stack(
        [minx + (ix_all + 0.5) * res, miny + (iy_all + 0.5) * res]
    )
    counts = grid["counts"]
    band_occ = grid["band_occ"]
    elements: list[DetectedElement] = []
    rejected = {"too_thick": 0, "thin_support": 0, "short": 0}

    for group in groups:
        center, direction, provisional_length = _group_line(group)
        if provisional_length < 1.0:
            rejected["short"] += 1
            continue
        normal = np.array([-direction[1], direction[0]])
        for _ in range(2):
            rel = points - center
            along = rel @ direction
            perp = rel @ normal
            keep = (
                (np.abs(perp) <= 0.50)
                & (along >= -provisional_length / 2 - 0.25)
                & (along <= provisional_length / 2 + 0.25)
            )
            if keep.sum() < 5:
                break
            center = points[keep].mean(axis=0)
            provisional_length = min(
                provisional_length + 0.5,
                float(np.ptp(along[keep])) + res,
            )
        selected = (
            (np.abs((points - center) @ normal) <= 0.50)
            & ((points - center) @ direction >= -provisional_length / 2 - 0.25)
            & ((points - center) @ direction <= provisional_length / 2 + 0.25)
        )
        idx = np.nonzero(selected)[0]
        if len(idx) < 5:
            continue
        rel = points[idx] - center
        along = rel @ direction
        perp = rel @ normal
        length = float(np.ptp(along)) + res
        if length < WALL_MIN_LENGTH_M:
            continue
        # Recentre on the scanned faces and measure their spacing.
        center = center + direction * ((along.min() + along.max()) / 2)
        rel_after = points[idx] - center
        along_after = rel_after @ direction
        perp_after = rel_after @ normal
        # Robust spread ACROSS the wall. The old 2 * p95(|perp|) doubled the
        # one-sided tail (corner points inside the selection strip), so real
        # single-face walls measured ~0.8 m "thick". A percentile span is
        # symmetric and equals the face spacing when both faces are scanned.
        # Only the central part of the run is used: near a corner the strip
        # collects the perpendicular branch, which is not wall thickness.
        central = np.abs(along_after) <= 0.35 * max(length, 0.5)
        across = perp_after[central] if central.sum() >= 5 else perp_after
        thickness_raw = float(np.percentile(across, 97) - np.percentile(across, 2)) + res
        # A "thickness" wider than any real wall means the group collected a
        # corridor of clutter (rack rows, pipes) rather than two wall faces.
        # Such hypotheses are dropped instead of being emitted as 0.9 m walls.
        if thickness_raw > WALL_MAX_THICKNESS_M:
            rejected["too_thick"] += 1
            continue
        thickness = float(max(res, thickness_raw))
        center = center + normal * float(np.median(perp_after))
        selected_iy = iy_all[idx]
        selected_ix = ix_all[idx]
        bands = band_occ[:, selected_iy, selected_ix].any(axis=1)
        occupied = np.nonzero(bands)[0]
        if len(occupied) == 0:
            continue
        z0 = minz + float(occupied.min()) * BAND_HEIGHT
        z1 = min(z_max, minz + float(occupied.max() + 1) * BAND_HEIGHT)
        cell_count = int(counts[selected_iy, selected_ix].sum())
        # Support test: a wall must be backed by points along its whole length,
        # not by a handful of speckle cells.
        if cell_count < 10 * max(1.0, length):
            rejected["thin_support"] += 1
            continue
        density = float(min(1.0, cell_count / max(1.0, len(idx) * 6.0)))
        height = z1 - z0
        height_factor = float(min(1.0, height / 3.0))
        coverage = float(min(1.0, length / max(1.0, provisional_length + 0.5)))
        confidence = 0.38 + 0.22 * density + 0.18 * height_factor + 0.14 * coverage
        elements.append(
            _box_element(
                geom,
                grid,
                center,
                direction,
                length,
                thickness,
                z0,
                z1,
                confidence,
                cell_count,
                "vertical occupancy + skeleton + probabilistic Hough + face merge",
            )
        )

    # Remove near-duplicate centreline hypotheses.
    unique: list[DetectedElement] = []
    for element in sorted(elements, key=lambda e: -e.dimensions["length_m"]):
        duplicate = False
        for other in unique:
            c1 = np.array(element.geometry["center"][:2])
            c2 = np.array(other.geometry["center"][:2])
            if np.linalg.norm(c1 - c2) < 0.25:
                a1 = element.geometry["rotation_z"]
                a2 = other.geometry["rotation_z"]
                if _angle_diff(a1, a2) < math.radians(10):
                    duplicate = True
                    break
        if not duplicate:
            unique.append(element)
    grid["wall_rejections"] = dict(rejected)
    return unique
