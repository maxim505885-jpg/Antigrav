"""Structural frame recognition for industrial halls (geometric, no ML).

Detects the steel/concrete load-bearing frame that the baseline stage cannot
see, because these members are thin and horizontal:

* horizontal members in thin bands around every level:
  - crane runways (``crane_girder``) — long axis-aligned beams between the
    mezzanine and the low roof; a 120 m line at 5.2 m in a 145 x 86 m hall is
    a crane runway, not a wall;
  - purlins (``purlin``) — thin axis-aligned beams at the upper roof band;
  - floor beams (``floor_beam``) — mezzanine-level members;
  - horizontal bracing (``brace``, orientation horizontal) — plan diagonals
    25..65 deg from the hall axis in the crane/roof bands;
* roof trusses: planes perpendicular to the hall axis in the zone between the
  low roof and the upper roof. A plane qualifies as a truss only when it has
  measured top and bottom chords, >= 2 vertical posts, and a *sparse* (v, z)
  section — a wall-like filled plane is rejected, not relabelled;
* vertical bracing planes: inter-truss planes with diagonals but no chords;
* column section typing: from the 3D occupancy grid each column gets a
  measured area-vs-height profile -> ``stepped`` (crane column with a corbel
  step), ``built_up`` (I/lattice section, bimodal flange signature),
  ``rectangular_solid``.

Every emitted element records how it was measured. Confidences are heuristic
scores, not calibrated probabilities. Non-structural clutter (pipes, ducts,
equipment) is NOT detected here on purpose — it is reported as
unimplemented.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import numpy as np
from scipy import ndimage
from skimage.morphology import skeletonize
from skimage.transform import probabilistic_hough_line

from ..geometry.bounds import derive_bbox
from ..geometry.section import CloudGeometry
from ..structure.proposals import build_assembly_proposal, build_member_proposal
from .geometric import CHUNK, DetectedElement, _iter_positions


def _source_row_evidence_for_bbox(
    points: np.ndarray,
    source_rows: np.ndarray,
    *,
    origin: np.ndarray,
    bbox_min: np.ndarray,
    bbox_max: np.ndarray,
    max_ids: int = 512,
) -> dict[str, Any]:
    """Return bounded, deterministic row evidence for points inside a world bbox."""
    local = np.asarray(points)
    rows = np.asarray(source_rows)
    if local.ndim != 2 or local.shape[1] != 3:
        raise ValueError("source evidence points must have shape (n, 3)")
    if rows.ndim != 1 or len(rows) != len(local) or not np.issubdtype(rows.dtype, np.integer):
        raise ValueError("source evidence rows must be a matching integer vector")
    if max_ids <= 0:
        raise ValueError("max_ids must be positive")
    world = local + np.asarray(origin, dtype=np.float64)
    lower = np.asarray(bbox_min, dtype=np.float64)
    upper = np.asarray(bbox_max, dtype=np.float64)
    inside = np.isfinite(world).all(axis=1) & np.all((world >= lower) & (world <= upper), axis=1)
    matched = rows[inside]
    support_count = int(len(matched))
    if support_count > max_ids:
        matched = matched[np.linspace(0, support_count - 1, max_ids, dtype=np.int64)]
    return {
        "source_point_ids": matched.astype(np.int64, copy=False).tolist(),
        "source_point_id_space": "positions.npy row index",
        "source_point_ids_sampled": support_count > len(matched),
        "source_point_support_count": support_count,
    }

# Physical thresholds. They encode what a structural engineer recognises as a
# frame member, not merely "a line of points".
BEAM_MIN_LENGTH_M = 2.5
# Hough fragments are merged only when they overlap by more than one 10 cm
# plan-raster cell. A touch or gap at a possible support is ambiguous joint
# evidence and stays as separate review candidates instead of assumed continuity.
SEGMENT_MERGE_MIN_OVERLAP_M = 0.10
# Nearby parallel axes may belong to separate runway members. Keep the merge
# tolerance near the 10 cm plan-raster resolution instead of joining members
# separated by a substantial fraction of a metre.
SEGMENT_MERGE_MAX_LATERAL_M = 0.20
# A beam is at most 0.70 m wide in plan; anything thicker is a wall, a walkway
# bundle or merged clutter, not a member an engineer would call a beam.
BEAM_MAX_THICKNESS_M = 0.70
# Individual span members must be eligible, not only continuous multi-span runs.
# This is a detection floor, NOT the project's nominal column pitch.
CRANE_MIN_LENGTH_M = BEAM_MIN_LENGTH_M
FLOOR_BEAM_MIN_LENGTH_M = 4.0
PURLIN_MAX_THICKNESS_M = 0.40
BRACE_MIN_LENGTH_M = 3.0
# A brace is accepted by POINT CONCENTRATION, not by raw strip width: on this
# roof the strip width saturates at 1.3..1.55 m for every diagonal, while real
# members keep >= 55 % of their points inside a +-0.15 m core. Uniform clutter
# would put only core/window = 0.25 of its points there.
BRACE_MIN_CONCENTRATION = 0.55
BRACE_CORE_M = 0.15
# Horizontal bracing is a thin plan member. A whole 1 m level band mixes in the
# roof-deck plane, whose filled raster hides the member from Hough AND dilutes
# its concentration, so diagonal candidates are ALSO sought in thin
# overlapping plan slices and then deduplicated against the full-band ones.
BRACE_SLICE_THICK_M = 0.40
BRACE_SLICE_STEP_M = 0.10
BRACE_SLICE_MIN_POINTS = 300
BRACE_DEDUP_POS_M = 1.2
BRACE_DEDUP_ANGLE_DEG = 12.0
DIAGONAL_MIN_DEG = 25.0
DIAGONAL_MAX_DEG = 65.0
ALIGNED_TOL_DEG = 20.0

TRUSS_MIN_SPAN_M = 6.0
TRUSS_MIN_POSTS = 3
TRUSS_MIN_CHORD_M = 4.0
BRACE_MIN_DIAGONAL_M = 1.5
# A roof-truss role is only proposed when its source points remain concentrated
# in the detected section plane. This is a conservative recognition heuristic,
# not an engineering tolerance.
TRUSS_MAX_MEMBER_PLANE_SUPPORT_P95_M = 0.20
# A (v, z) section of a truss is mostly empty space; a wall-like plane fills
# more than this share of its raster and is rejected as a truss.
TRUSS_MAX_SECTION_FILL = 0.35

BAND_CAP_POINTS = 3_000_000
TRUSS_ZONE_CAP_POINTS = 6_000_000
HOUGH_SEED = 20261020

# Column section completion and typification. A scan measures each column with
# noise and occlusion, while a yard fabricates a handful of standard sizes.
# Two visible sides (adjacent or opposite) fully determine a rectangular
# section; one visible side determines only one axis.
# Sections are measured from the POINTS on a local 2 cm raster: the 0.10 m
# occupancy grid that finds the columns cannot size them (one-cell steps make
# a hall of identical columns read as 0.4..0.9 m) and its PCA puts the
# orientation 10 deg off.
COLUMN_MEASURE_RES = 0.02
COLUMN_MEASURE_CELL_MIN = 2
COLUMN_MEASURE_MIN_POINTS = 60
COLUMN_SIDE_BAND_CELLS = 1.5
COLUMN_SIDE_MIN_COVERAGE = 0.50
# The coarse footprint that crops the measurement window is quantized to its
# 0.10 m grid, so a section can never be resolved finer than that; grouping at
# 50 mm split one physical size into 0.41 / 0.51 / 0.61 "types".
COLUMN_SECTION_TOLERANCE_M = 0.10
COLUMN_SECTION_MAX_RESIDUAL_M = 0.12
COLUMN_NOMINAL_ROUND_M = 0.005
COLUMN_SECTION_MAX_FILL = 0.92

# Column typing.
COLUMN_TYPE_SOLID = "rectangular_solid"
COLUMN_TYPE_BUILT_UP = "built_up"
COLUMN_TYPE_STEPPED = "stepped"
COLUMN_TYPE_OTHER = "other_section"
STEPPED_AREA_RATIO = 0.70        # top area < 70 % of base area => stepped
BIMODAL_VALLEY_RATIO = 0.45      # projection valley < 45 % of peak => two flanges
BIMODAL_SEPARATION_M = 0.15


def _angle_diff(a: float, b: float) -> float:
    d = abs(a - b) % math.pi
    return min(d, math.pi - d)


def _bands_points_with_source_ids(
    geom: CloudGeometry, bands: list[tuple[float, float]],
) -> list[tuple[np.ndarray, np.ndarray, int]]:
    """Return band points and their original row indices in one cloud pass."""
    point_collectors: list[list[np.ndarray]] = [[] for _ in bands]
    row_collectors: list[list[np.ndarray]] = [[] for _ in bands]
    source_offset = 0
    for chunk in _iter_positions(geom.positions_path):
        z = chunk[:, 2]
        row_ids = np.arange(source_offset, source_offset + len(chunk), dtype=np.int64)
        for index, (z0, z1) in enumerate(bands):
            mask = (z >= z0) & (z < z1)
            if mask.any():
                point_collectors[index].append(chunk[mask])
                row_collectors[index].append(row_ids[mask])
        source_offset += len(chunk)
    out: list[tuple[np.ndarray, np.ndarray, int]] = []
    for point_parts, row_parts in zip(point_collectors, row_collectors):
        if not point_parts:
            out.append((np.zeros((0, 3), dtype=np.float32), np.zeros(0, dtype=np.int64), 0))
            continue
        points = np.concatenate(point_parts)
        source_rows = np.concatenate(row_parts)
        full_band_count = len(points)
        if len(points) > BAND_CAP_POINTS:
            stride = int(math.ceil(len(points) / BAND_CAP_POINTS))
            points = points[::stride]
            source_rows = source_rows[::stride]
        out.append((points, source_rows, full_band_count))
    return out


def _bands_points(geom: CloudGeometry, bands: list[tuple[float, float]]) -> list[np.ndarray]:
    """Points of the cloud inside several local z bands in ONE pass."""
    return [points for points, _source_rows, _total in _bands_points_with_source_ids(geom, bands)]


def _band_points(geom: CloudGeometry, z0: float, z1: float) -> np.ndarray:
    """Points of the cloud inside the local z band, capped for cost."""
    return _bands_points(geom, [(z0, z1)])[0]


def _plan_segments(
    xy: np.ndarray,
    res: float,
    min_length_m: float,
    line_gap_m: float = 0.5,
) -> list[dict[str, Any]]:
    """Skeleton + probabilistic Hough on a plan raster of the band points."""
    if len(xy) < 50:
        return []
    lo = xy.min(axis=0) - 0.5
    hi = xy.max(axis=0) + 0.5
    nu = max(1, int(math.ceil((hi[0] - lo[0]) / res)) + 1)
    nv = max(1, int(math.ceil((hi[1] - lo[1]) / res)) + 1)
    mask = np.zeros((nv, nu), dtype=bool)
    ix = np.clip(((xy[:, 0] - lo[0]) / res).astype(np.int64), 0, nu - 1)
    iy = np.clip(((xy[:, 1] - lo[1]) / res).astype(np.int64), 0, nv - 1)
    mask[iy, ix] = True
    if mask.sum() < 30:
        return []
    skeleton = skeletonize(mask)
    lines = probabilistic_hough_line(
        skeleton,
        threshold=6,
        line_length=max(5, int(min_length_m / res)),
        line_gap=max(2, int(line_gap_m / res)),
        rng=HOUGH_SEED,
    )
    segments: list[dict[str, Any]] = []
    for (x0, y0), (x1, y1) in lines:
        p0 = np.array([lo[0] + (x0 + 0.5) * res, lo[1] + (y0 + 0.5) * res])
        p1 = np.array([lo[0] + (x1 + 0.5) * res, lo[1] + (y1 + 0.5) * res])
        delta = p1 - p0
        length = float(np.linalg.norm(delta))
        if length < min_length_m:
            continue
        angle = math.atan2(float(delta[1]), float(delta[0])) % math.pi
        segments.append(
            {
                "p0": p0,
                "p1": p1,
                "mid": (p0 + p1) / 2,
                "dir": np.array([math.cos(angle), math.sin(angle)]),
                "angle": angle,
                "length": length,
            }
        )
    return segments


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


def _group_segments(segments: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
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
            if abs(float(np.dot(sj["mid"] - si["mid"], normal))) > SEGMENT_MERGE_MAX_LATERAL_M:
                continue
            projections = [
                float(np.dot(sj["p0"] - si["mid"], si["dir"])),
                float(np.dot(sj["p1"] - si["mid"], si["dir"])),
            ]
            overlap = min(max(projections), si["length"] / 2) - max(
                min(projections), -si["length"] / 2
            )
            if overlap > SEGMENT_MERGE_MIN_OVERLAP_M:
                uf.union(i, j)
    groups: dict[int, list[dict[str, Any]]] = {}
    for i, segment in enumerate(segments):
        groups.setdefault(uf.find(i), []).append(segment)
    return list(groups.values())


def _group_line(group: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, float]:
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


def _measure_strip(
    points_xy: np.ndarray,
    points_z: np.ndarray,
    center: np.ndarray,
    direction: np.ndarray,
    length: float,
    *,
    return_indices: bool = False,
) -> tuple[float, float, float, int] | tuple[float, float, float, int, np.ndarray]:
    """Thickness across the line, z extent, and point support along it."""
    normal = np.array([-direction[1], direction[0]])
    rel = points_xy - center
    along = rel @ direction
    across = rel @ normal
    # Central slice must be limited BOTH along and across the line, otherwise
    # points of nearby walls hundreds of metres away leak into the thickness.
    central = (np.abs(along) <= 0.35 * max(length, 0.5)) & (np.abs(across) <= 0.8)
    selected = (np.abs(across) <= 0.6) & (np.abs(along) <= length / 2 + 0.25)
    if central.sum() >= 5:
        across_c = across[central]
        quantiles = (2, 97)
        # Sparse neighbouring objects used to inflate a clear thin ridge to
        # 1.5 m. Narrow the measurement window only when MOST central evidence
        # hugs the line; a broad wall/surface must retain its measured width.
        concentration = float((np.abs(across_c) <= BRACE_CORE_M).mean())
        if concentration >= 0.60:
            core = across_c[np.abs(across_c) <= BEAM_MAX_THICKNESS_M / 2]
            if len(core) >= 5:
                across_c = core
                # The restricted window can still contain sparse outliers.
                # Trim both tails; this envelope is not a fitted steel profile.
                quantiles = (5, 95)
                selected &= np.abs(across) <= BEAM_MAX_THICKNESS_M / 2
        thickness = float(np.percentile(across_c, quantiles[1]) - np.percentile(across_c, quantiles[0]))
    else:
        thickness = 0.0
    if selected.sum() >= 3:
        zs = points_z[selected]
        z0 = float(np.percentile(zs, 2))
        z1 = float(np.percentile(zs, 98))
    else:
        z0 = z1 = 0.0
    result = (thickness, z0, z1, int(selected.sum()))
    if return_indices:
        return (*result, np.flatnonzero(selected))
    return result


def _vertical_layer_evidence(points_z: np.ndarray) -> dict[str, Any] | None:
    """Flag clearly separated height modes without assigning member identities.

    A rail and girder can occupy the same plan line.  This small diagnostic
    detects distinct Z bands in the line support, but a multi-level profile can
    also be a single built-up section, so it must never split or reclassify a
    member on its own.
    """
    z = np.asarray(points_z, dtype=float)
    z = z[np.isfinite(z)]
    if len(z) < 60 or float(np.ptp(z)) < 0.12:
        return None
    bin_width = 0.02
    edges = np.arange(float(z.min()) - bin_width, float(z.max()) + 2 * bin_width, bin_width)
    counts, edges = np.histogram(z, bins=edges)
    profile = ndimage.gaussian_filter1d(counts.astype(float), sigma=1.0)
    from scipy.signal import find_peaks

    min_distance = max(1, int(math.ceil(0.12 / bin_width)))
    peaks, _ = find_peaks(
        profile, distance=min_distance,
        prominence=max(2.0, float(profile.max()) * 0.12),
    )
    if len(peaks) < 2:
        return None
    candidates = sorted(peaks.tolist(), key=lambda peak: profile[peak], reverse=True)
    min_support = max(30, int(math.ceil(0.10 * len(z))))
    qualifying: list[int] = []
    for peak in candidates:
        if not qualifying:
            qualifying.append(peak)
            continue
        if all(abs(peak - prior) * bin_width >= 0.12 for prior in qualifying):
            qualifying.append(peak)
    qualifying.sort()
    if len(qualifying) < 2:
        return None

    centers: list[float] = []
    supports: list[int] = []
    for index, peak in enumerate(qualifying):
        left = float(z.min()) if index == 0 else (
            edges[(qualifying[index - 1] + peak) // 2 + 1]
        )
        right = float(z.max()) if index == len(qualifying) - 1 else (
            edges[(peak + qualifying[index + 1]) // 2 + 1]
        )
        cluster = z[(z >= left) & (z <= right)]
        if len(cluster) < min_support:
            continue
        centers.append(float(np.median(cluster)))
        supports.append(int(len(cluster)))
    if len(centers) < 2:
        return None
    separations = np.diff(centers)
    if not np.any(separations >= 0.12):
        return None
    return {
        "interpretation": "ambiguous_vertical_profile",
        "layer_centers_m": [round(value, 4) for value in centers],
        "layer_support_counts": supports,
        "layer_separation_m": round(float(max(separations)), 4),
        "role_assignment": "unresolved",
    }


def _beam_terminal_evidence(
    points_xy: np.ndarray,
    center: np.ndarray,
    direction: np.ndarray,
    length: float,
) -> dict[str, Any] | None:
    """Flag a cross-strip concentrated at a candidate beam end.

    This is evidence of an end detail (plate, connection, or nearby clutter),
    not evidence that the beam is supported or that its physical span ends
    there. The candidate's measured Hough axis remains unchanged.
    """
    points = np.asarray(points_xy, dtype=float)
    center = np.asarray(center, dtype=float)
    direction = np.asarray(direction, dtype=float)
    if (points.ndim != 2 or points.shape[1] != 2 or center.shape != (2,)
            or direction.shape != (2,) or not np.isfinite(points).all()
            or not np.isfinite(center).all() or not np.isfinite(direction).all()
            or not math.isfinite(length) or length <= 0):
        raise ValueError("beam terminal evidence needs finite plan points and a valid axis")
    norm = float(np.linalg.norm(direction))
    if norm <= 1e-12:
        raise ValueError("beam terminal evidence axis must be non-zero")
    direction = direction / norm
    normal = np.array([-direction[1], direction[0]])
    rel = points - center
    along = rel @ direction
    across = rel @ normal
    ambiguous: list[str] = []
    evidence: dict[str, dict[str, float | int]] = {}
    for name, endpoint in (("start", -length / 2), ("end", length / 2)):
        endpoint_mask = (np.abs(along - endpoint) <= 0.08) & (np.abs(across) <= 0.60)
        interior_mask = (
            (np.abs(along - endpoint) >= 0.30)
            & (np.abs(along - endpoint) <= 0.80)
            & (np.abs(across) <= 0.60)
        )
        if int(endpoint_mask.sum()) < 15 or int(interior_mask.sum()) < 30:
            continue
        endpoint_span = float(np.percentile(across[endpoint_mask], 90)
                              - np.percentile(across[endpoint_mask], 10))
        interior_span = float(np.percentile(across[interior_mask], 90)
                              - np.percentile(across[interior_mask], 10))
        if endpoint_span >= max(0.25, interior_span * 2.5):
            ambiguous.append(name)
            evidence[name] = {
                "terminal_support_count": int(endpoint_mask.sum()),
                "interior_support_count": int(interior_mask.sum()),
                "terminal_cross_span_m": round(endpoint_span, 4),
                "interior_cross_span_m": round(interior_span, 4),
            }
    if not ambiguous:
        return None
    return {
        "interpretation": "possible_end_plate_or_connection_detail",
        "ambiguous_end_regions": ambiguous,
        "end_region_evidence": evidence,
        "physical_support": "unknown",
        "axis_changed": False,
    }


def _beam_internal_gap_evidence(
    points_xy: np.ndarray,
    source_rows: np.ndarray,
    center: np.ndarray,
    direction: np.ndarray,
    length: float,
) -> list[dict[str, Any]]:
    """Propose internal no-return intervals without assigning a physical cause.

    Positions are measured from the candidate axis start. A gap may be caused
    by scan occlusion, a physical joint, or missing source coverage; it never
    changes the candidate axis or splits one candidate into multiple members.
    """
    points = np.asarray(points_xy, dtype=float)
    rows = np.asarray(source_rows)
    center = np.asarray(center, dtype=float)
    direction = np.asarray(direction, dtype=float)
    if (points.ndim != 2 or points.shape[1] != 2 or rows.ndim != 1
            or len(points) != len(rows) or not np.issubdtype(rows.dtype, np.integer)
            or np.any(rows < 0) or center.shape != (2,) or direction.shape != (2,)
            or not np.isfinite(points).all() or not np.isfinite(center).all()
            or not np.isfinite(direction).all() or not math.isfinite(length) or length <= 0):
        raise ValueError("beam gap evidence needs aligned finite points, source rows, and a valid axis")
    norm = float(np.linalg.norm(direction))
    if norm <= 1e-12:
        raise ValueError("beam gap evidence axis must be non-zero")
    direction = direction / norm
    normal = np.array([-direction[1], direction[0]])
    rel = points - center
    along = rel @ direction + length / 2
    across = rel @ normal
    core = (np.abs(across) <= 0.15) & (along >= 0) & (along <= length)
    if int(core.sum()) < 12:
        return []

    bin_width = 0.10
    bin_count = max(1, int(math.ceil(length / bin_width)))
    indices = np.clip((along[core] / bin_width).astype(np.int64), 0, bin_count - 1)
    occupied = np.bincount(indices, minlength=bin_count) > 0
    empty = ~occupied
    candidates: list[dict[str, Any]] = []
    index = 0
    while index < bin_count:
        if not empty[index]:
            index += 1
            continue
        stop = index + 1
        while stop < bin_count and empty[stop]:
            stop += 1
        gap_start = index * bin_width
        gap_end = min(length, stop * bin_width)
        gap_width = gap_end - gap_start
        position = (gap_start + gap_end) / 2
        if gap_width >= 0.25 and position >= 0.30 and length - position >= 0.30:
            flank_window = 0.25
            left = core & (along >= gap_start - flank_window) & (along < gap_start)
            right = core & (along > gap_end) & (along <= gap_end + flank_window)
            if int(left.sum()) >= 3 and int(right.sum()) >= 3:
                left_indices = np.flatnonzero(left)
                right_indices = np.flatnonzero(right)
                left_indices = left_indices[np.argsort(-along[left_indices], kind="stable")[:4]]
                right_indices = right_indices[np.argsort(along[right_indices], kind="stable")[:4]]
                linked_rows = np.unique(np.concatenate((rows[left_indices], rows[right_indices])).astype(np.int64))
                candidates.append({
                    "kind": "gap",
                    "position_m": round(float(min(length, max(0.0, position))), 4),
                    "reason": (
                        "No sampled points were observed in the member-axis core; this may be "
                        "scan occlusion, a physical joint, or missing/decimated coverage and "
                        "is not confirmed."
                    ),
                    "source_point_ids": linked_rows.tolist(),
                })
        index = stop
    return candidates[:16]


def _line_concentration(
    points_xy: np.ndarray,
    center: np.ndarray,
    direction: np.ndarray,
    length: float,
    core_m: float = 0.15,
    window_m: float = 0.60,
) -> float:
    """Share of nearby points that hug the line itself.

    ``_measure_strip`` width saturates on a busy roof: a thin diagonal brace
    flanked by purlins reads 1.3..1.55 m wide because the +-0.6 m window fills
    with the neighbours. A real linear member is different in that its points
    concentrate in a narrow core along the centreline even when the window is
    crowded, so the fraction inside ``core_m`` separates brace from clutter.
    Near 1.0 = a clean thin ridge; near ``core_m / window_m`` = evenly spread
    clutter with no member on the line.
    """
    if len(points_xy) == 0:
        return 0.0
    normal = np.array([-direction[1], direction[0]])
    rel = points_xy - center
    along = rel @ direction
    across = rel @ normal
    window = (np.abs(across) <= window_m) & (np.abs(along) <= length / 2 + 0.25)
    total = int(window.sum())
    if total < 20:
        return 0.0
    core = int((np.abs(across[window]) <= core_m).sum())
    return core / total


def _wall_continued(
    grid: dict[str, Any],
    points_xy: np.ndarray,
    center: np.ndarray,
    direction: np.ndarray,
    length: float,
    z0_local: float,
) -> bool:
    """True when the candidate line continues downward to the floor.

    A beam floats in space; a wall (or a column row) occupies the same plan
    cells in most bands from the floor up to the candidate level. The check
    samples plan cells along the line in the 3D occupancy grid.
    """
    band_occ = grid["band_occ"]
    res = float(grid["res"])
    minx = float(grid["min"][0])
    miny = float(grid["min"][1])
    level_band = int((z0_local - float(grid["min"][2])) / grid_band_height())
    if level_band < 2:
        return False
    normal = np.array([-direction[1], direction[0]])
    occupied_fractions: list[float] = []
    step = max(1.0, length / 40.0)
    t = -length / 2
    while t <= length / 2:
        p = center + direction * t
        ix = int((p[0] - minx) / res)
        iy = int((p[1] - miny) / res)
        if 0 <= ix < band_occ.shape[2] and 0 <= iy < band_occ.shape[1]:
            below = band_occ[:level_band, iy, ix]
            if below.size:
                occupied_fractions.append(float(below.mean()))
        t += step
    del normal, points_xy
    if len(occupied_fractions) < 5:
        return False
    return float(np.median(occupied_fractions)) >= 0.70


def _axis_angle(band_xy: list[np.ndarray]) -> float | None:
    """Hall axis from the PCA of all horizontal-band points.

    Slab-like bands dominate the covariance with the rectangle axes, and the
    long hall side wins the major eigenvector; beams reinforce it.
    """
    usable = [xy for xy in band_xy if len(xy) >= 2000]
    if not usable:
        return None
    sample = np.concatenate(
        [xy[:: max(1, len(xy) // 500_000)] for xy in usable]
    )
    if len(sample) < 100:
        return None
    centered = sample - sample.mean(axis=0)
    cov = np.cov(centered.T)
    _, vecs = np.linalg.eigh(cov)
    major = vecs[:, int(np.argmax(np.linalg.eigvalsh(cov)))]
    return math.atan2(float(major[1]), float(major[0])) % math.pi


def _axis_from_segments(segments: list[dict[str, Any]], reference: float | None) -> float | None:
    """Orthogonal frame consensus, with PCA only choosing longitudinal vs cross.

    Crop shape can bias PCA. Actual measured line directions establish the
    frame, modulo 90 degrees. No line or column is snapped to the returned axis.
    """
    usable = [s for s in segments if math.isfinite(s["angle"]) and s["length"] > 0]
    if not usable:
        return reference
    angles = np.array([s["angle"] for s in usable])
    weights = np.array([min(s["length"], 20.0) for s in usable])
    period = math.pi / 2
    bins = np.arange(90) * math.pi / 180
    distances = np.abs((angles[:, None]-bins[None, :]+period/2) % period-period/2)
    votes = (distances <= math.radians(6)).T @ weights
    best = bins[int(np.argmax(votes))]
    keep = np.abs((angles-best+period/2) % period-period/2) <= math.radians(6)
    vector = np.sum(weights[keep] * np.exp(4j * angles[keep]))
    if abs(vector) < 1e-9:
        return reference
    angle = float(np.angle(vector) / 4) % period
    choices = (angle, angle+period)
    return min(choices, key=lambda a: _angle_diff(a, reference)) if reference is not None else angle


def _beam_bbox(
    geom: CloudGeometry, center: np.ndarray, direction: np.ndarray,
    length: float, thickness: float, z0_local: float, z1_local: float,
) -> dict[str, list[float]]:
    """AABB emitted for one measured oriented beam candidate."""
    angle = math.atan2(float(direction[1]), float(direction[0]))
    ca, sa = math.cos(angle), math.sin(angle)
    corners = [
        (center[0] + lx * ca - ly * sa, center[1] + lx * sa + ly * ca)
        for lx, ly in (
            (-length / 2, -thickness / 2), (length / 2, -thickness / 2),
            (length / 2, thickness / 2), (-length / 2, thickness / 2),
        )
    ]
    return {
        "min": [
            round(min(x for x, _ in corners) + float(geom.origin[0]), 3),
            round(min(y for _, y in corners) + float(geom.origin[1]), 3),
            round(float(z0_local + geom.origin[2]), 3),
        ],
        "max": [
            round(max(x for x, _ in corners) + float(geom.origin[0]), 3),
            round(max(y for _, y in corners) + float(geom.origin[1]), 3),
            round(float(z1_local + geom.origin[2]), 3),
        ],
    }


def _beam_element(
    geom: CloudGeometry,
    center: np.ndarray,
    direction: np.ndarray,
    length: float,
    thickness: float,
    z0_local: float,
    z1_local: float,
    role: str,
    role_note: str,
    confidence: float,
    band_label: str,
    support: int,
    source_point_ids: np.ndarray | None = None,
    source_band_point_count: int | None = None,
    source_band_points_used: int | None = None,
    vertical_profile_evidence: dict[str, Any] | None = None,
    terminal_evidence: dict[str, Any] | None = None,
    joint_gap_evidence: list[dict[str, Any]] | None = None,
) -> DetectedElement:
    angle = math.atan2(float(direction[1]), float(direction[0]))
    height = max(0.05, z1_local - z0_local)
    z_center = (z0_local + z1_local) / 2
    world_center = [
        round(float(center[0]) + float(geom.origin[0]), 4),
        round(float(center[1]) + float(geom.origin[1]), 4),
        round(z_center + float(geom.origin[2]), 4),
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
    bbox = _beam_bbox(geom, center, direction, length, thickness, z0_local, z1_local)
    label = {
        "crane_girder": "подкрановая балка",
        "purlin": "прогон",
        "floor_beam": "балка перекрытия",
    }.get(role, role)
    metadata = {
        "method": "thin-band plan raster + skeleton + probabilistic Hough + collinear merge",
        "band_label": band_label,
        "support_points": support,
        "confidence_kind": "heuristic",
        "notes": role_note,
    }
    if source_point_ids is not None:
        source_rows = np.asarray(source_point_ids)
        if source_rows.ndim != 1 or not np.issubdtype(source_rows.dtype, np.integer):
            raise ValueError("beam source_point_ids must be a one-dimensional integer array")
        source_rows = np.unique(source_rows.astype(np.int64, copy=False))
        sampled_for_size = len(source_rows) > 512
        gap_evidence = joint_gap_evidence or []
        pinned_rows = np.unique(np.asarray(
            [row for gap in gap_evidence for row in gap["source_point_ids"]], dtype=np.int64,
        )) if gap_evidence else np.zeros(0, dtype=np.int64)
        if not set(pinned_rows.tolist()).issubset(set(source_rows.tolist())):
            raise ValueError("beam gap source rows must belong to the measured member rows")
        band_was_downsampled = (
            source_band_point_count is not None
            and source_band_points_used is not None
            and source_band_point_count > source_band_points_used
        )
        if sampled_for_size:
            available_rows = source_rows[~np.isin(source_rows, pinned_rows)]
            budget = max(0, 512 - len(pinned_rows))
            if len(available_rows) > budget:
                sample_indices = np.linspace(0, len(available_rows) - 1, budget, dtype=np.int64)
                available_rows = available_rows[sample_indices]
            source_rows = np.unique(np.concatenate((pinned_rows, available_rows)))
        metadata.update({
            "source_point_ids": source_rows.tolist(),
            "support_count_in_processing_sample": int(support),
            "source_point_ids_sampled": bool(sampled_for_size or band_was_downsampled),
            "source_point_id_space": "positions.npy row index",
        })
        if source_band_point_count is not None and source_band_points_used is not None:
            metadata["source_band_point_count"] = int(source_band_point_count)
            metadata["source_band_points_used"] = int(source_band_points_used)
            metadata["source_band_downsampled_for_recognition"] = bool(band_was_downsampled)
        axis_start = [
            float(center[0] - direction[0] * length / 2 + geom.origin[0]),
            float(center[1] - direction[1] * length / 2 + geom.origin[1]),
            float(z_center + geom.origin[2]),
        ]
        axis_end = [
            float(center[0] + direction[0] * length / 2 + geom.origin[0]),
            float(center[1] + direction[1] * length / 2 + geom.origin[1]),
            float(z_center + geom.origin[2]),
        ]
        proposal = build_member_proposal(
            role=role,
            axis_start_m=axis_start,
            axis_end_m=axis_end,
            source_point_ids=source_rows.tolist(),
            source_point_ids_sampled=bool(sampled_for_size or band_was_downsampled),
            support_count_in_processing_sample=int(support),
            joint_gaps=gap_evidence,
        )
        metadata["member_proposal_id"] = proposal["id"]
        metadata["member_proposal"] = proposal
    if vertical_profile_evidence is not None:
        metadata["vertical_profile_evidence"] = vertical_profile_evidence
        metadata["notes"] += (
            " Точки образуют несколько высотных слоёв; рельс, пояс и другие части "
            "сечения автоматически не разделены и требуют проверки."
        )
    if terminal_evidence is not None:
        metadata["terminal_evidence"] = terminal_evidence
        metadata["notes"] += (
            " У конца оси есть поперечно расширенная группа точек; это может быть "
            "торцевая пластина, соединительная деталь или помеха, опора не подтверждена."
        )
    return DetectedElement(
        class_name="beam",
        geometry={
            "kind": "oriented_box",
            "center": world_center,
            "sizes": {
                "length": round(length, 3),
                "thickness": round(thickness, 3),
                "height": round(height, 3),
            },
            "rotation_z": round(angle, 5),
            "note": f"horizontal member measured in thin band around level ({band_label})",
        },
        bbox=bbox,
        confidence=round(float(max(0.2, min(0.9, confidence))), 3),
        measured=True,
        inferred=False,
        dimensions={
            "length_m": round(length, 3),
            "thickness_m": round(thickness, 3),
            "height_m": round(height, 3),
            "role": role,
            "role_label": label,
            "role_status": "proposed",
            "profile_status": "not_fitted",
            "height_source": "percentiles within sampled level band, not full profile height",
            "thickness_source": "supported strip envelope, not a catalogue profile",
        },
        metadata=metadata,
    )


def _member_element(
    geom: CloudGeometry,
    p0_world: np.ndarray,
    p1_world: np.ndarray,
    section_m: float | None,
    role: str,
    orientation: str,
    confidence: float,
    method: str,
    source_point_ids: np.ndarray | None = None,
    source_point_ids_sampled: bool = False,
    class_name: str = "brace",
    role_evidence: dict[str, Any] | None = None,
) -> DetectedElement:
    length = float(np.linalg.norm(p1_world - p0_world))
    mid = (p0_world + p1_world) / 2
    label = {
        "brace": "связь",
        "truss_top_chord": "верхний пояс фермы",
        "truss_bottom_chord": "нижний пояс фермы",
        "truss_post": "стойка фермы",
        "truss_web": "раскос фермы",
        "unknown": "роль не определена",
    }.get(role, role)
    section_note = (
        "" if section_m is not None
        else "; поперечное сечение не определено, показана только измеренная ось"
    )
    metadata: dict[str, Any] = {
        "method": method,
        "confidence_kind": "heuristic",
        "notes": "стержень конструкции; роль, сечение и узлы остаются предложениями для проверки" + section_note,
    }
    if source_point_ids is not None:
        source_rows = np.asarray(source_point_ids)
        if source_rows.ndim != 1 or not np.issubdtype(source_rows.dtype, np.integer):
            raise ValueError("member source_point_ids must be a one-dimensional integer array")
        source_rows = np.unique(source_rows.astype(np.int64, copy=False))
        if len(source_rows):
            sampled = bool(source_point_ids_sampled or len(source_rows) > 512)
            if len(source_rows) > 512:
                source_rows = source_rows[np.linspace(0, len(source_rows) - 1, 512, dtype=np.int64)]
            metadata.update({
                "source_point_ids": source_rows.tolist(),
                "source_point_id_space": "positions.npy row index",
                "source_point_ids_sampled": sampled,
                "support_count_in_processing_sample": int(len(np.asarray(source_point_ids))),
            })
            proposal = build_member_proposal(
                role=role,
                axis_start_m=p0_world.tolist(),
                axis_end_m=p1_world.tolist(),
                source_point_ids=source_rows.tolist(),
                source_point_ids_sampled=sampled,
                support_count_in_processing_sample=max(
                    int(len(np.asarray(source_point_ids))), len(source_rows),
                ),
            )
            metadata["member_proposal_id"] = proposal["id"]
            metadata["member_proposal"] = proposal
        else:
            metadata["source_evidence_status"] = "insufficient"
    if role_evidence is not None:
        metadata["role_evidence"] = role_evidence
    geometry: dict[str, Any] = {
        "kind": "member",
        "p0": [round(float(v), 4) for v in p0_world],
        "p1": [round(float(v), 4) for v in p1_world],
        "note": f"diagonal member measured between two points ({orientation} bracing)",
    }
    if section_m is not None:
        if not math.isfinite(section_m) or section_m <= 0:
            raise ValueError("member section_m must be finite and positive when provided")
        geometry["section_m"] = round(section_m, 3)
    return DetectedElement(
        class_name=class_name,
        geometry=geometry,
        bbox=derive_bbox(geometry),
        confidence=round(float(max(0.2, min(0.9, confidence))), 3),
        measured=True,
        inferred=False,
        dimensions={
            "length_m": round(length, 3),
            "role": role,
            "role_label": label,
            "role_status": "proposed" if role != "unknown" else "unknown",
            "orientation": orientation,
        },
        metadata=metadata,
    )


def _distance_point_to_segment_2d(
    point: np.ndarray, segment: tuple[np.ndarray, np.ndarray, float],
) -> float:
    center, direction, length = segment
    start = center - direction * (length / 2.0)
    end = center + direction * (length / 2.0)
    vector = end - start
    denominator = float(vector @ vector)
    if denominator <= 1e-12:
        return float(np.linalg.norm(point - start))
    fraction = float(np.clip(((point - start) @ vector) / denominator, 0.0, 1.0))
    return float(np.linalg.norm(point - (start + fraction * vector)))


def _classify_truss_internal_member_role(
    line: tuple[np.ndarray, np.ndarray, float],
    top_chords: list[tuple[np.ndarray, np.ndarray, float]],
    bottom_chords: list[tuple[np.ndarray, np.ndarray, float]],
    *,
    endpoint_tolerance_m: float = 0.25,
    plane_support_p95_m: float = 0.0,
    max_plane_support_p95_m: float = TRUSS_MAX_MEMBER_PLANE_SUPPORT_P95_M,
) -> tuple[str, dict[str, Any]]:
    """Propose a post/web role only when both endpoints meet measured chords.

    This is a topology hypothesis in local (v, z) section coordinates. It does
    not establish that the members are physically connected or structurally
    serve those roles.
    """
    if (not math.isfinite(endpoint_tolerance_m) or endpoint_tolerance_m <= 0
            or not math.isfinite(plane_support_p95_m) or plane_support_p95_m < 0
            or not math.isfinite(max_plane_support_p95_m) or max_plane_support_p95_m <= 0
            or not math.isfinite(float(line[2])) or float(line[2]) <= 0
            or not top_chords or not bottom_chords):
        return "unknown", {
            "status": "unknown",
            "reason": "measured_top_and_bottom_chords_required",
            "supported_chords": [],
        }
    center = np.asarray(line[0], dtype=np.float64)
    direction = np.asarray(line[1], dtype=np.float64)
    norm = float(np.linalg.norm(direction))
    if center.shape != (2,) or direction.shape != (2,) or not np.isfinite(center).all() or not np.isfinite(direction).all() or norm <= 1e-12:
        return "unknown", {
            "status": "unknown",
            "reason": "invalid_member_axis",
            "supported_chords": [],
        }
    direction = direction / norm
    endpoints = (
        center - direction * (float(line[2]) / 2.0),
        center + direction * (float(line[2]) / 2.0),
    )
    distances = {
        "top": [min(_distance_point_to_segment_2d(point, chord) for chord in top_chords)
                for point in endpoints],
        "bottom": [min(_distance_point_to_segment_2d(point, chord) for chord in bottom_chords)
                   for point in endpoints],
    }
    assignments = []
    for top_index, bottom_index in ((0, 1), (1, 0)):
        if (distances["top"][top_index] <= endpoint_tolerance_m
                and distances["bottom"][bottom_index] <= endpoint_tolerance_m):
            assignments.append({"top": top_index, "bottom": bottom_index})
    if len(assignments) != 1:
        supported_chords = sorted({
            name for name, values in distances.items()
            if min(values) <= endpoint_tolerance_m
        })
        return "unknown", {
            "status": "unknown",
            "reason": (
                "ambiguous_endpoint_to_chord_assignment" if len(assignments) > 1
                else "member_axis_does_not_reach_both_measured_chords"
            ),
            "endpoint_distances_m": {
                name: [round(value, 4) for value in values]
                for name, values in distances.items()
            },
            "endpoint_tolerance_m": endpoint_tolerance_m,
            "supported_chords": supported_chords,
        }
    assignment = assignments[0]
    supported_chords = ["bottom", "top"]
    if plane_support_p95_m > max_plane_support_p95_m:
        return "unknown", {
            "status": "unknown",
            "reason": "member_point_support_is_non_planar",
            "endpoint_distances_m": {
                name: [round(value, 4) for value in values]
                for name, values in distances.items()
            },
            "endpoint_tolerance_m": endpoint_tolerance_m,
            "supported_chords": supported_chords,
            "endpoint_chord_assignment": assignment,
            "plane_support_p95_m": round(plane_support_p95_m, 4),
            "max_plane_support_p95_m": max_plane_support_p95_m,
        }
    role = "truss_post" if abs(float(direction[0])) < 0.25 else "truss_web"
    return role, {
        "status": "proposed",
        "reason": "both_member_endpoints_reach_measured_top_and_bottom_chords",
        "endpoint_distances_m": {
            name: [round(value, 4) for value in values]
            for name, values in distances.items()
        },
        "endpoint_tolerance_m": endpoint_tolerance_m,
        "supported_chords": supported_chords,
        "endpoint_chord_assignment": assignment,
        "plane_support_p95_m": round(plane_support_p95_m, 4),
        "max_plane_support_p95_m": max_plane_support_p95_m,
        "orientation_basis": "vertical_in_section" if role == "truss_post" else "diagonal_in_section",
    }


def _section_member_source_rows(
    points_vz: np.ndarray,
    source_rows: np.ndarray,
    center_vz: np.ndarray,
    direction_vz: np.ndarray,
    length: float,
    *,
    max_line_offset_m: float = 0.20,
    endpoint_buffer_m: float = 0.30,
) -> np.ndarray:
    """Return source rows near one measured line in a vertical section."""
    points = np.asarray(points_vz, dtype=float)
    rows = np.asarray(source_rows)
    center = np.asarray(center_vz, dtype=float)
    direction = np.asarray(direction_vz, dtype=float)
    if (points.ndim != 2 or points.shape[1] != 2 or rows.ndim != 1
            or len(points) != len(rows) or not np.issubdtype(rows.dtype, np.integer)
            or np.any(rows < 0)):
        raise ValueError("section points and source rows must be aligned N x 2 arrays")
    if (center.shape != (2,) or direction.shape != (2,) or not np.isfinite(points).all()
            or not np.isfinite(center).all() or not np.isfinite(direction).all()
            or not math.isfinite(length) or length <= 0):
        raise ValueError("section member line must contain finite 2D coordinates")
    direction_norm = float(np.linalg.norm(direction))
    if direction_norm <= 1e-12:
        raise ValueError("section member direction must be non-zero")
    direction = direction / direction_norm
    normal = np.array([-direction[1], direction[0]])
    offset = points - center
    along = offset @ direction
    across = offset @ normal
    selected = (
        (np.abs(along) <= length / 2 + endpoint_buffer_m)
        & (np.abs(across) <= max_line_offset_m)
    )
    return np.unique(rows[selected].astype(np.int64, copy=False))


def _section_node_evidence(
    members: list[tuple[tuple[np.ndarray, np.ndarray, float], str]],
    points_vz: np.ndarray,
    source_rows: np.ndarray,
    *,
    node_support_radius_m: float = 0.20,
    node_line_half_width_m: float = 0.08,
    min_member_axis_points: int = 3,
    min_member_axis_span_m: float = 0.04,
    plane_coordinates: np.ndarray | None = None,
    node_plane_tolerance_m: float = 0.15,
    node_merge_distance_m: float = 0.10,
) -> list[dict[str, Any]]:
    """Propose point-supported intersections without claiming a joint."""
    points = np.asarray(points_vz, dtype=float)
    rows = np.asarray(source_rows)
    plane = (
        np.zeros(len(points), dtype=float)
        if plane_coordinates is None else np.asarray(plane_coordinates, dtype=float)
    )
    if (points.ndim != 2 or points.shape[1] != 2 or rows.ndim != 1
            or len(points) != len(rows) or not np.issubdtype(rows.dtype, np.integer)
            or plane.shape != (len(points),) or not np.isfinite(plane).all()
            or not math.isfinite(node_plane_tolerance_m) or node_plane_tolerance_m <= 0):
        raise ValueError("section node points and source rows must be aligned")
    proposals: list[dict[str, Any]] = []
    for i, (line_a, member_a) in enumerate(members):
        center_a, direction_a, length_a = line_a
        start_a = center_a - direction_a * length_a / 2
        for line_b, member_b in members[i + 1:]:
            if member_a == member_b:
                continue
            center_b, direction_b, length_b = line_b
            start_b = center_b - direction_b * length_b / 2
            matrix = np.column_stack((direction_a, -direction_b))
            if abs(float(np.linalg.det(matrix))) <= 1e-6:
                continue
            distance_a, distance_b = np.linalg.solve(matrix, start_b - start_a)
            if (not (-0.03 <= distance_a <= length_a + 0.03)
                    or not (-0.03 <= distance_b <= length_b + 0.03)):
                continue
            point_vz = start_a + distance_a * direction_a
            offset = points - point_vz
            local_support: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
            for direction in (direction_a, direction_b):
                unit_direction = direction / np.linalg.norm(direction)
                normal = np.array([-unit_direction[1], unit_direction[0]])
                along = offset @ unit_direction
                across = offset @ normal
                supported = (
                    (np.abs(along) <= node_support_radius_m)
                    & (np.abs(across) <= node_line_half_width_m)
                )
                local_support.append((
                    np.unique(rows[supported].astype(np.int64, copy=False)),
                    along[supported],
                    plane[supported],
                ))
            if any(len(axis_rows) < min_member_axis_points
                   or float(np.ptp(axis_along)) < min_member_axis_span_m
                   for axis_rows, axis_along, _axis_plane in local_support):
                continue
            plane_centers = [float(np.median(axis_plane)) for _, _, axis_plane in local_support]
            plane_delta = abs(plane_centers[0] - plane_centers[1])
            if plane_delta > node_plane_tolerance_m:
                continue
            node_rows = np.unique(np.concatenate([axis_rows for axis_rows, _, _ in local_support]))
            if len(node_rows) < 5:
                continue
            existing = next((node for node in proposals
                             if np.linalg.norm(node["point_vz"] - point_vz) <= node_merge_distance_m), None)
            if existing is None:
                proposals.append({
                    "point_vz": point_vz,
                    "candidate_member_proposal_ids": {member_a, member_b},
                    "source_point_ids": set(node_rows.tolist()),
                    "plane_support_delta_m": plane_delta,
                })
            else:
                existing["candidate_member_proposal_ids"].update((member_a, member_b))
                existing["source_point_ids"].update(node_rows.tolist())
                existing["plane_support_delta_m"] = max(
                    existing["plane_support_delta_m"], plane_delta,
                )
    return proposals


def _diagonals_in_slices(
    points: np.ndarray,
    axis: float,
) -> list[tuple[np.ndarray, np.ndarray, float, float, float, float, float, int]]:
    """Diagonal plan candidates from thin z-slices of one level band.

    Horizontal bracing is a thin plan member. Measured over a whole 1 m band it
    is diluted by the roof-deck plane, which also fills the raster so the Hough
    stage cannot separate the member, and its concentration drops below the
    acceptance threshold. Each thin slice re-runs the plan Hough in isolation,
    where the deck plane no longer dominates the raster. Overlapping slices
    find different fragments of the same member, so the caller deduplicates.
    """
    z = points[:, 2]
    z0, z1 = float(z.min()), float(z.max())
    out: list[tuple[np.ndarray, np.ndarray, float, float, float, float, float, int]] = []
    start = z0
    while start + BRACE_SLICE_THICK_M <= z1 + 1e-9:
        stop = start + BRACE_SLICE_THICK_M
        mask = (z >= start) & (z < stop)
        start += BRACE_SLICE_STEP_M
        sub = points[mask]
        if len(sub) < BRACE_SLICE_MIN_POINTS:
            continue
        segments = _plan_segments(
            sub[:, :2], res=0.10, min_length_m=BRACE_MIN_LENGTH_M
        )
        for group in _group_segments(segments):
            center, direction, length = _group_line(group)
            if length < BRACE_MIN_LENGTH_M:
                continue
            angle = math.atan2(float(direction[1]), float(direction[0])) % math.pi
            rel_deg = math.degrees(_angle_diff(angle, axis))
            if not (DIAGONAL_MIN_DEG <= rel_deg <= DIAGONAL_MAX_DEG):
                continue
            conc = _line_concentration(
                sub[:, :2], center, direction, length, core_m=BRACE_CORE_M
            )
            if conc < BRACE_MIN_CONCENTRATION:
                continue
            thickness, bz0, bz1, support = _measure_strip(
                sub[:, :2], sub[:, 2], center, direction, length
            )
            if support < 5:
                continue
            out.append((center, direction, length, conc, thickness, bz0, bz1, support))
    return out


def _dedup_brace_candidates(
    candidates: list[tuple[np.ndarray, np.ndarray, float, float, float, float, float, int]],
) -> list[tuple[np.ndarray, np.ndarray, float, float, float, float, float, int]]:
    """Merge the same member found in overlapping slices and in the full band.

    Two candidates are the same member when their lines are nearly parallel,
    laterally within ``BRACE_DEDUP_POS_M`` and at the same height. The better
    supported one survives: higher concentration, then the longer fragment
    (a thin slice may clip the member's ends).
    """
    keep: list[tuple[np.ndarray, np.ndarray, float, float, float, float, float, int]] = []
    max_angle = math.radians(BRACE_DEDUP_ANGLE_DEG)
    for cand in candidates:
        center, direction = cand[0], cand[1]
        angle = math.atan2(float(direction[1]), float(direction[0])) % math.pi
        mid_z = (cand[5] + cand[6]) / 2
        is_duplicate = False
        for index, known in enumerate(keep):
            known_angle = math.atan2(float(known[1][1]), float(known[1][0])) % math.pi
            if _angle_diff(angle, known_angle) > max_angle:
                continue
            normal = np.array([-direction[1], direction[0]])
            if abs(float(np.dot(center - known[0], normal))) > BRACE_DEDUP_POS_M:
                continue
            if abs(mid_z - (known[5] + known[6]) / 2) > 0.6:
                continue
            if cand[3] - known[3] > 0.03 or (
                abs(cand[3] - known[3]) <= 0.03 and cand[2] > known[2]
            ):
                keep[index] = cand
            is_duplicate = True
            break
        if not is_duplicate:
            keep.append(cand)
    return keep


def _emit_horizontal_braces(
    geom: CloudGeometry,
    candidates: list[tuple[np.ndarray, np.ndarray, float, float, float, float, float, int]],
    *,
    source_points: np.ndarray | None = None,
    source_rows: np.ndarray | None = None,
    source_points_sampled: bool = False,
) -> list[DetectedElement]:
    """One brace element per deduplicated horizontal bracing member."""
    if (source_points is None) != (source_rows is None):
        raise ValueError("horizontal brace source points and rows must be provided together")
    if source_points is not None:
        source_points = np.asarray(source_points)
        source_rows = np.asarray(source_rows)
        if (source_points.ndim != 2 or source_points.shape[1] != 3
                or source_rows.ndim != 1 or len(source_points) != len(source_rows)
                or not np.issubdtype(source_rows.dtype, np.integer)):
            raise ValueError("horizontal brace source points and rows must be aligned")
    out: list[DetectedElement] = []
    for center, direction, length, conc, thickness, bz0, bz1, _support in candidates:
        center_z = (bz0 + bz1) / 2
        p0 = np.array(
            [
                center[0] - direction[0] * length / 2,
                center[1] - direction[1] * length / 2,
                center_z,
            ]
        ) + geom.origin
        p1 = np.array(
            [
                center[0] + direction[0] * length / 2,
                center[1] + direction[1] * length / 2,
                center_z,
            ]
        ) + geom.origin
        member_source_rows = None
        if source_points is not None and source_rows is not None:
            normal = np.array([-direction[1], direction[0]])
            rel_xy = source_points[:, :2] - center
            member_mask = (
                (np.abs(rel_xy @ direction) <= length / 2 + 0.30)
                & (np.abs(rel_xy @ normal) <= max(0.20, min(thickness, 0.35)))
                & (source_points[:, 2] >= bz0 - 0.15)
                & (source_points[:, 2] <= bz1 + 0.15)
            )
            member_source_rows = source_rows[member_mask]
        out.append(
            _member_element(
                geom,
                p0,
                p1,
                section_m=None,
                role="brace",
                orientation="horizontal",
                confidence=0.35
                + 0.1 * min(1.0, length / 10.0)
                + 0.15 * min(1.0, (conc - BRACE_MIN_CONCENTRATION) / 0.25),
                method=(
                    "plan Hough on thin z-slices and on the full level band, merged "
                    "by dedup; diagonal 25..65 deg from hall axis; accepted by "
                    f"line concentration >= {BRACE_MIN_CONCENTRATION:.2f}"
                ),
                source_point_ids=member_source_rows,
                source_point_ids_sampled=source_points_sampled,
            )
        )
    return out


# ------------------------------------------------------------- horizontal stage
def _runway_column_context(
    center, direction, length, z_local, origin, columns, member_thickness_m=0.4,
):
    """Geometric context only: nearby columns cannot prove a crane runway.

    Search margins are proposal heuristics, not engineering tolerances.
    Coordinates of columns are world coordinates; band geometry is local.
    """
    world_center = np.asarray(center) + np.asarray(origin)[:2]
    direction = np.asarray(direction, dtype=float)
    direction = direction / np.linalg.norm(direction)
    normal = np.array([-direction[1], direction[0]])
    z = float(z_local + origin[2])
    supports = []
    endpoint_search_margin_m = 0.6
    for index, column in enumerate(columns):
        if column.class_name != "column":
            continue
        lo = np.asarray(column.bbox.get("min", []), dtype=float)
        hi = np.asarray(column.bbox.get("max", []), dtype=float)
        if lo.shape != (3,) or hi.shape != (3,) or not np.isfinite([lo, hi]).all():
            continue
        if np.any(hi <= lo) or hi[2] - lo[2] < 1.5:
            continue
        if not lo[2] <= z <= hi[2] + 0.3:
            continue
        delta = (lo[:2] + hi[:2]) / 2 - world_center
        along, across = float(delta @ direction), abs(float(delta @ normal))
        half_width = float(np.abs(normal) @ (hi[:2] - lo[:2])) / 2
        # A column supports this candidate only when its footprint reaches the
        # beam strip (allowing 20 cm for coarse detection and scan occlusion).
        # The previous fixed 0.8 m offset linked beams to a separate parallel
        # column row, which made the runway context misleading.
        lateral_gap = max(0.15, float(member_thickness_m) / 2 + 0.20)
        if abs(along) <= length / 2 + endpoint_search_margin_m and across <= half_width + lateral_gap:
            half_extent_along = float(np.abs(direction) @ (hi[:2] - lo[:2])) / 2
            start_gap = max(0.0, abs(along + length / 2) - half_extent_along)
            end_gap = max(0.0, abs(along - length / 2) - half_extent_along)
            supports.append({"column_index": index, "along_m": round(along, 4),
                             "axis_offset_m": round(across, 4),
                             "axis_offset_limit_m": round(half_width + lateral_gap, 4),
                             "start_endpoint_gap_m": round(start_gap, 4),
                             "end_endpoint_gap_m": round(end_gap, 4)})
    spacing = max((s["along_m"] for s in supports), default=0) - min(
        (s["along_m"] for s in supports), default=0)
    start_choices = [
        item for item in supports
        if item["start_endpoint_gap_m"] <= endpoint_search_margin_m
    ]
    end_choices = [
        item for item in supports
        if item["end_endpoint_gap_m"] <= endpoint_search_margin_m
    ]
    endpoint_pairs = [
        (start, end)
        for start in start_choices
        for end in end_choices
        if start["column_index"] != end["column_index"]
    ]
    best_pair = min(
        endpoint_pairs,
        key=lambda pair: (
            pair[0]["start_endpoint_gap_m"] + pair[1]["end_endpoint_gap_m"],
            pair[0]["column_index"],
            pair[1]["column_index"],
        ),
        default=None,
    )
    end_supports = {
        "start": ({"column_index": best_pair[0]["column_index"],
                   "gap_m": best_pair[0]["start_endpoint_gap_m"]} if best_pair else None),
        "end": ({"column_index": best_pair[1]["column_index"],
                 "gap_m": best_pair[1]["end_endpoint_gap_m"]} if best_pair else None),
    }
    if best_pair is None:
        best_start = min(
            start_choices,
            key=lambda item: (item["start_endpoint_gap_m"], item["column_index"]),
            default=None,
        )
        best_end = min(
            end_choices,
            key=lambda item: (item["end_endpoint_gap_m"], item["column_index"]),
            default=None,
        )
        end_supports = {
            "start": ({"column_index": best_start["column_index"],
                       "gap_m": best_start["start_endpoint_gap_m"]} if best_start else None),
            "end": ({"column_index": best_end["column_index"],
                     "gap_m": best_end["end_endpoint_gap_m"]} if best_end else None),
        }
    supported = spacing >= 2.0 and best_pair is not None
    return {"status": "supported_hypothesis" if supported else "insufficient_context",
            "supports": supports, "support_spacing_m": round(spacing, 4),
            "support_count": len(supports),
            "end_supports": end_supports,
            "endpoint_search_margin_m": endpoint_search_margin_m,
            "requires_review": True,
            "basis": "column height, beam-strip overlap, and distinct footprint proximity to both beam endpoints; rail/corbel not verified"}


def _horizontal_members(
    geom: CloudGeometry,
    levels: list[dict[str, Any]],
    grid: dict[str, Any],
    progress=None,
    columns=None,
) -> tuple[list[DetectedElement], float | None, list[np.ndarray], list[str]]:
    warnings: list[str] = []
    band_xy: list[np.ndarray] = []
    band_data: list[tuple[float, float, str, str]] = []  # z0l, z1l, label, kind
    crane_index = max(1, len(levels) - 3) if len(levels) >= 4 else None
    for index, level in enumerate(levels):
        zl = float(level["z_local"])
        kind = "mid"
        if index == 0:
            kind = "floor"
        elif index >= len(levels) - 2:
            kind = "roof"
        elif crane_index is not None and index == crane_index:
            kind = "crane"
        band_data.append((zl - 0.50, zl + 0.50, f"{float(level['z']):.2f} м", kind))
    indexed_band_points = _bands_points_with_source_ids(
        geom, [(z0, z1) for z0, z1, *_ in band_data]
    )
    band_points = [points for points, _source_rows, _total in indexed_band_points]
    segments_by_band = [
        _plan_segments(points[:, :2], res=0.10, min_length_m=BEAM_MIN_LENGTH_M)
        if len(points) >= 500 else [] for points in band_points
    ]
    axis = _axis_from_segments(
        [segment for segments in segments_by_band for segment in segments],
        _axis_angle([points[:, :2] for points in band_points]),
    )
    if axis is None:
        warnings.append("Не удалось определить ось зала для распознавания горизонтальных связей и балок.")
    elements: list[DetectedElement] = []
    role_counts: dict[str, int] = {}
    for (z0, z1, label, kind), (points, source_rows, source_band_count), segments in zip(
        band_data, indexed_band_points, segments_by_band
    ):
        if progress:
            progress(0.88, f"горизонтальные члены в полосе {label}")
        band_xy.append(points[:, :2])
        if len(points) < 500:
            continue
        groups = _group_segments(segments)
        diag_candidates: list[
            tuple[np.ndarray, np.ndarray, float, float, float, float, float, int]
        ] = []
        for group in groups:
            center, direction, length = _group_line(group)
            if length < BEAM_MIN_LENGTH_M:
                continue
            thickness, bz0, bz1, support, support_indices = _measure_strip(
                points[:, :2], points[:, 2], center, direction, length,
                return_indices=True,
            )
            if support < 5:
                continue
            angle = math.atan2(float(direction[1]), float(direction[0])) % math.pi
            rel_deg = math.degrees(_angle_diff(angle, axis if axis is not None else angle))
            aligned = rel_deg <= ALIGNED_TOL_DEG
            diagonal = DIAGONAL_MIN_DEG <= rel_deg <= DIAGONAL_MAX_DEG
            role = None
            note = ""
            confidence = 0.45
            column_context = _runway_column_context(
                center, direction, length, (bz0 + bz1) / 2, geom.origin, columns or [],
                member_thickness_m=thickness,
            )
            if diagonal:
                if kind in ("crane", "roof") and length >= BRACE_MIN_LENGTH_M:
                    # Width alone is unusable here (it saturates on the roof);
                    # require the points to actually cluster on the line.
                    conc = _line_concentration(
                        points[:, :2], center, direction, length,
                        core_m=BRACE_CORE_M,
                    )
                    if conc >= BRACE_MIN_CONCENTRATION:
                        # Collected, not emitted: thin-slice candidates for the
                        # same member are merged into it first.
                        diag_candidates.append(
                            (center, direction, length, conc, thickness, bz0, bz1, support)
                        )
                continue
            if aligned:
                if kind == "crane" and length >= CRANE_MIN_LENGTH_M and thickness <= BEAM_MAX_THICKNESS_M:
                    if _wall_continued(grid, points[:, :2], center, direction, length, z0):
                        continue  # vertical structure reaching the floor: a wall, not a beam
                    role = "crane_girder"
                    note = (
                        "Осевая балка в промежуточной высотной полосе, "
                        "не продолжается вниз до пола — гипотеза подкрановой балки; "
                        "проверьте привязку к колоннам и крановому пути."
                    )
                    confidence = 0.55 + 0.1 * min(1.0, length / 60.0)
                elif kind == "roof" and length >= 3.0 and thickness <= PURLIN_MAX_THICKNESS_M:
                    role = "purlin"
                    note = "Тонкая осевая балка в полосе верхней кровли — гипотеза прогона."
                    confidence = 0.40 + 0.1 * min(1.0, length / 20.0)
                elif kind == "mid" and length >= FLOOR_BEAM_MIN_LENGTH_M and thickness <= PURLIN_MAX_THICKNESS_M:
                    if _wall_continued(grid, points[:, :2], center, direction, length, z0):
                        continue
                    role = "floor_beam"
                    note = "Балка в полосе промежуточного уровня — гипотеза балки перекрытия."
                    confidence = 0.40
            if role is None:
                continue
            candidate_thickness = max(thickness, 0.08)
            candidate_bbox = _beam_bbox(
                geom, center, direction, length, candidate_thickness, bz0, bz1,
            )
            bbox_min_local = np.asarray(candidate_bbox["min"], dtype=np.float64) - geom.origin
            bbox_max_local = np.asarray(candidate_bbox["max"], dtype=np.float64) - geom.origin
            support_points = points[support_indices]
            evidence_mask = np.all(
                (support_points >= bbox_min_local - 0.04)
                & (support_points <= bbox_max_local + 0.04),
                axis=1,
            )
            evidence_indices = support_indices[evidence_mask]
            evidence_points = points[evidence_indices]
            evidence_rows = source_rows[evidence_indices]
            elements.append(
                _beam_element(
                    geom, center, direction, length,
                    candidate_thickness, bz0, bz1,
                    role=role,
                    role_note=note,
                    confidence=confidence,
                    band_label=label,
                    support=support,
                    source_point_ids=evidence_rows if len(evidence_rows) else None,
                    source_band_point_count=source_band_count,
                    source_band_points_used=len(points),
                    vertical_profile_evidence=_vertical_layer_evidence(
                        points[support_indices, 2]
                    ),
                    terminal_evidence=_beam_terminal_evidence(
                        points[support_indices, :2], center, direction, length,
                    ),
                    joint_gap_evidence=_beam_internal_gap_evidence(
                        evidence_points[:, :2], evidence_rows,
                        center, direction, length,
                    ),
                )
            )
            if role in ("crane_girder", "floor_beam"):
                elements[-1].metadata["column_support_context"] = column_context
                elements[-1].metadata["role_alternatives"] = ["crane_girder", "floor_beam"]
                elements[-1].metadata["notes"] += (
                    " Найдены разнесённые колонны подходящей высоты; опирание и рельс требуют проверки."
                    if column_context["status"] == "supported_hypothesis" else
                    " Связь с двумя колоннами не установлена: назначение балки не подтверждено."
                )
            role_counts[role] = role_counts.get(role, 0) + 1
        # Second, independent source of diagonal candidates: a thin plan slice
        # isolates a bracing member that the full 1 m band dilutes or hides.
        if (
            kind in ("crane", "roof")
            and axis is not None
            and len(points) >= BRACE_SLICE_MIN_POINTS
        ):
            if progress:
                progress(0.885, f"горизонтальные связи в полосе {label}")
            diag_candidates.extend(_diagonals_in_slices(points, axis))
        braces = _emit_horizontal_braces(
            geom, _dedup_brace_candidates(diag_candidates),
            source_points=points, source_rows=source_rows,
            source_points_sampled=source_band_count > len(points),
        )
        if braces:
            elements.extend(braces)
            role_counts["brace_horizontal"] = role_counts.get("brace_horizontal", 0) + len(braces)
    if role_counts.get("crane_girder"):
        warnings.append(
            f"Найдено {role_counts['crane_girder']} подкрановых балок (осевые длинные балки между уровнями) "
            "— класс геометрический, привязку к крановому пути проверьте в редакторе."
        )
    if role_counts.get("brace_horizontal"):
        warnings.append(
            f"Найдено {role_counts['brace_horizontal']} горизонтальных связей "
            "(диагонали в плане в полосах подкрановых балок и кровли) — "
            "крестовые узлы и раскрепления проверьте в редакторе."
        )
    return elements, axis, band_xy, warnings


# ---------------------------------------------------------------- truss stage
def _truss_zone(geom: CloudGeometry, levels: list[dict[str, Any]]) -> tuple[float, float] | None:
    if len(levels) < 3:
        return None
    # The truss bottom chord usually sits at (or just above) the low-roof
    # level, so the zone must start slightly BELOW that level to include it.
    low_roof = float(levels[-2]["z_local"])
    top_roof = float(levels[-1]["z_local"])
    zone = (low_roof - 0.45, top_roof + 0.35)
    if zone[1] - zone[0] < 1.0:
        return None
    return zone


def _collect_zone_with_source_ids(
    geom: CloudGeometry, z0: float, z1: float,
) -> tuple[np.ndarray, np.ndarray, bool]:
    parts: list[np.ndarray] = []
    row_parts: list[np.ndarray] = []
    row_offset = 0
    for chunk in _iter_positions(geom.positions_path):
        mask = (chunk[:, 2] >= z0) & (chunk[:, 2] < z1)
        if mask.any():
            parts.append(chunk[mask])
            row_parts.append(np.flatnonzero(mask).astype(np.int64) + row_offset)
        row_offset += len(chunk)
    if not parts:
        return np.zeros((0, 3), dtype=np.float32), np.zeros(0, dtype=np.int64), False
    points = np.concatenate(parts)
    source_rows = np.concatenate(row_parts)
    sampled = len(points) > TRUSS_ZONE_CAP_POINTS
    if sampled:
        stride = int(math.ceil(len(points) / TRUSS_ZONE_CAP_POINTS))
        points = points[::stride]
        source_rows = source_rows[::stride]
    return points, source_rows, sampled


def _collect_zone(geom: CloudGeometry, z0: float, z1: float) -> np.ndarray:
    """Collect a height band; retained as a compatibility wrapper."""
    points, _source_rows, _sampled = _collect_zone_with_source_ids(geom, z0, z1)
    return points


def _vertical_hough(
    uz: np.ndarray,
    res: float,
    min_len_m: float,
) -> tuple[list[dict[str, Any]], float]:
    """Hough segments in a (u, z) section raster."""
    if len(uz) < 60:
        return []
    lo = uz.min(axis=0) - 0.25
    hi = uz.max(axis=0) + 0.25
    nu = max(1, int(math.ceil((hi[0] - lo[0]) / res)) + 1)
    nz = max(1, int(math.ceil((hi[1] - lo[1]) / res)) + 1)
    mask = np.zeros((nz, nu), dtype=bool)
    iu = np.clip(((uz[:, 0] - lo[0]) / res).astype(np.int64), 0, nu - 1)
    iz = np.clip(((uz[:, 1] - lo[1]) / res).astype(np.int64), 0, nz - 1)
    mask[iz, iu] = True
    if mask.sum() < 40:
        return []
    fill = float(mask.sum()) / (nu * nz)
    skeleton = skeletonize(mask)
    lines = probabilistic_hough_line(
        skeleton,
        threshold=5,
        line_length=max(4, int(min_len_m / res)),
        line_gap=max(2, int(0.4 / res)),
        rng=HOUGH_SEED,
    )
    out: list[dict[str, Any]] = []
    for (x0, z0i), (x1, z1i) in lines:
        p0 = np.array([lo[0] + (x0 + 0.5) * res, lo[1] + (z0i + 0.5) * res])
        p1 = np.array([lo[0] + (x1 + 0.5) * res, lo[1] + (z1i + 0.5) * res])
        delta = p1 - p0
        length = float(np.linalg.norm(delta))
        if length < min_len_m:
            continue
        angle = math.degrees(math.atan2(float(delta[1]), float(delta[0]))) % 180.0
        out.append(
            {
                "p0": p0,
                "p1": p1,
                "mid": (p0 + p1) / 2,
                "dir": np.array(
                    [math.cos(math.radians(angle)), math.sin(math.radians(angle))]
                ),
                "angle": math.radians(angle),
                "angle_deg": angle,
                "length": length,
            }
        )
    return out, fill


def _detect_trusses(
    geom: CloudGeometry,
    zone: tuple[float, float],
    axis: float,
    progress=None,
) -> tuple[list[DetectedElement], list[dict[str, Any]], dict[str, int]]:
    """Truss planes and inter-truss bracing planes, perpendicular to the axis."""
    if progress:
        progress(0.9, "поиск плоскостей ферм и связей")
    points, source_rows, zone_sampled = _collect_zone_with_source_ids(geom, zone[0], zone[1])
    elements: list[DetectedElement] = []
    stats = {
        "truss_count": 0,
        "truss_complete_count": 0,
        "truss_partial_count": 0,
        "brace_vertical": 0,
        "truss_member_untraceable": 0,
    }
    planes_meta: list[dict[str, Any]] = []
    if len(points) < 2000:
        return elements, planes_meta, stats
    direction = np.array([math.cos(axis), math.sin(axis)])
    normal = np.array([-direction[1], direction[0]])
    center2 = points[:, :2].mean(axis=0)
    rel = points[:, :2] - center2
    u = rel @ direction
    v = rel @ normal
    z = points[:, 2]

    # Plane candidates: peaks of the u-histogram.
    bin_w = 0.5
    edges = np.arange(u.min(), u.max() + bin_w, bin_w)
    hist, _ = np.histogram(u, bins=edges)
    if hist.max() <= 0:
        return elements, planes_meta, stats
    from scipy.signal import find_peaks

    peaks, _ = find_peaks(
        hist.astype(np.float64),
        height=max(1200.0, 0.05 * float(hist.max())),
        prominence=max(800.0, 0.03 * float(hist.max())),
        distance=max(1, int(2.5 / bin_w)),
    )
    plane_us = [(edges[i] + edges[i + 1]) / 2 for i in peaks]
    z_mid = (zone[0] + zone[1]) / 2

    for plane_u in plane_us:
        slice_mask = np.abs(u - plane_u) <= 0.45
        if int(slice_mask.sum()) < 300:
            continue
        vz = np.column_stack([v[slice_mask], z[slice_mask]])
        plane_source_rows = source_rows[slice_mask]

        def world_section_point(vz_point: np.ndarray) -> np.ndarray:
            return np.array([
                center2[0] + direction[0] * plane_u + normal[0] * float(vz_point[0]),
                center2[1] + direction[1] * plane_u + normal[1] * float(vz_point[0]),
                float(vz_point[1]),
            ]) + geom.origin

        def emit_truss_member(
            line: tuple[np.ndarray, np.ndarray, float], role: str, member_class: str,
            role_evidence: dict[str, Any] | None = None,
        ) -> str | None:
            center_vz, direction_vz, member_length = line
            member_source_rows = _section_member_source_rows(
                vz, plane_source_rows, center_vz, direction_vz, member_length,
            )
            if len(member_source_rows) < 5:
                stats["truss_member_untraceable"] += 1
                return None
            p0 = world_section_point(center_vz - direction_vz * member_length / 2)
            p1 = world_section_point(center_vz + direction_vz * member_length / 2)
            member_element = _member_element(
                geom, p0, p1, section_m=None, role=role,
                orientation="vertical" if abs(float(direction_vz[0])) < 0.25 else "diagonal",
                confidence=0.55, method="(v,z) section Hough; source rows selected around member axis",
                source_point_ids=member_source_rows,
                source_point_ids_sampled=zone_sampled,
                class_name=member_class,
                role_evidence=role_evidence,
            )
            elements.append(member_element)
            member_proposal_id = member_element.metadata.get("member_proposal_id")
            return str(member_proposal_id) if member_proposal_id else None

        def classify_truss_internal_member_role(
            line: tuple[np.ndarray, np.ndarray, float],
        ) -> tuple[str, dict[str, Any]]:
            section_u = u[slice_mask]
            chord_plane_offsets: list[np.ndarray] = []
            for chord in (*top_chords, *bot_chords):
                chord_center, chord_direction, chord_length = chord
                chord_direction = chord_direction / np.linalg.norm(chord_direction)
                chord_normal = np.array([-chord_direction[1], chord_direction[0]])
                chord_delta = vz - chord_center
                chord_support = (
                    (np.abs(chord_delta @ chord_direction) <= chord_length / 2 + 0.30)
                    & (np.abs(chord_delta @ chord_normal) <= 0.20)
                )
                if chord_support.any():
                    chord_plane_offsets.append(section_u[chord_support])
            reference_plane_u = (
                float(np.median(np.concatenate(chord_plane_offsets)))
                if chord_plane_offsets else float(plane_u)
            )
            center_vz, direction_vz, member_length = line
            offset_vz = vz - center_vz
            direction_vz = direction_vz / np.linalg.norm(direction_vz)
            normal_vz = np.array([-direction_vz[1], direction_vz[0]])
            along = offset_vz @ direction_vz
            across = offset_vz @ normal_vz
            member_support = (
                (np.abs(along) <= member_length / 2 + 0.30)
                & (np.abs(across) <= 0.20)
            )
            plane_offsets = np.abs(section_u[member_support] - reference_plane_u)
            plane_support_p95 = (
                float(np.percentile(plane_offsets, 95)) if len(plane_offsets) else 0.0
            )
            return _classify_truss_internal_member_role(
                line, top_chords, bot_chords,
                plane_support_p95_m=plane_support_p95,
            )
        section, fill = _vertical_hough(vz, res=0.10, min_len_m=0.8)
        if not section:
            continue
        horizontals = [s for s in section if s["angle_deg"] <= 15 or s["angle_deg"] >= 165]
        verticals = [s for s in section if 70 <= s["angle_deg"] <= 110]
        diagonals = [
            s for s in section
            if DIAGONAL_MIN_DEG <= min(s["angle_deg"], 180 - s["angle_deg"]) <= DIAGONAL_MAX_DEG
            and s["length"] >= BRACE_MIN_DIAGONAL_M
        ]
        # Merge collinear diagonal fragments for the SAME reason as chords and
        # posts: one brace leaves the Hough as several overlapping 1-3 m pieces,
        # and emitting every piece puts three or four braces where the hall has
        # one (they overlap, so they are not different members).
        merged_d = [_group_line(g) for g in _group_segments(diagonals)]
        merged_d = [m for m in merged_d if m[2] >= BRACE_MIN_DIAGONAL_M]
        # Merge collinear fragments: a scanned chord comes out of the Hough as
        # 1-3 m pieces with gaps; its real length is the merged extent.
        merged_h: list[tuple[np.ndarray, np.ndarray, float]] = [
            _group_line(g) for g in _group_segments(horizontals)
        ]
        top_chords = [m for m in merged_h if m[0][1] >= z_mid and m[2] >= TRUSS_MIN_CHORD_M]
        bot_chords = [m for m in merged_h if m[0][1] < z_mid and m[2] >= TRUSS_MIN_CHORD_M]
        top_chord_len = max((m[2] for m in top_chords), default=0.0)
        bot_chord_len = max((m[2] for m in bot_chords), default=0.0)
        # Posts: distinct vertical positions after merging collinear pieces.
        merged_v: list[tuple[np.ndarray, np.ndarray, float]] = [
            _group_line(g) for g in _group_segments(verticals)
        ]
        posts = [m for m in merged_v if m[2] >= 0.6]
        has_chords = top_chord_len >= TRUSS_MIN_CHORD_M and bot_chord_len >= TRUSS_MIN_CHORD_M
        has_one_chord = bool(top_chords) != bool(bot_chords)
        internal_lines = [*posts, *merged_d]
        traceable_internal_count = sum(
            len(_section_member_source_rows(vz, plane_source_rows, center, direction_vz, length)) >= 5
            for center, direction_vz, length in internal_lines
        )
        partial_missing_chord = has_one_chord and traceable_internal_count >= 2
        sparse = fill <= TRUSS_MAX_SECTION_FILL
        plane_world_u = float(plane_u + center2 @ direction)

        partial_truss = not has_chords or len(posts) < TRUSS_MIN_POSTS
        has_internal_members = traceable_internal_count >= 1
        if (has_chords and has_internal_members or partial_missing_chord) and sparse:
            span_pts = vz[(vz[:, 1] >= zone[0]) & (vz[:, 1] <= zone[1])]
            v_min = float(np.percentile(span_pts[:, 0], 1))
            v_max = float(np.percentile(span_pts[:, 0], 99))
            span = v_max - v_min
            if span < TRUSS_MIN_SPAN_M:
                continue
            observed_z_min = float(np.percentile(span_pts[:, 1], 1))
            observed_z_max = float(np.percentile(span_pts[:, 1], 99))
            top_chord_z = float(np.median([m[0][1] for m in top_chords])) if top_chords else None
            bottom_chord_z = float(np.median([m[0][1] for m in bot_chords])) if bot_chords else None
            top_z = top_chord_z if top_chord_z is not None else observed_z_max
            bot_z = bottom_chord_z if bottom_chord_z is not None else observed_z_min
            height = max(0.3, top_z - bot_z)
            missing_evidence = []
            if not top_chords:
                missing_evidence.append("top_chord")
            if not bot_chords:
                missing_evidence.append("bottom_chord")
            if len(posts) < TRUSS_MIN_POSTS:
                missing_evidence.append("additional_vertical_posts")
            height_status = (
                "observed_extent_only" if not top_chords or not bot_chords
                else "measured_chord_separation"
            )
            mid_v = (v_min + v_max) / 2
            world_center = np.array(
                [
                    center2[0] + direction[0] * plane_u + normal[0] * mid_v,
                    center2[1] + direction[1] * plane_u + normal[1] * mid_v,
                    (top_z + bot_z) / 2,
                ]
            ) + geom.origin
            angle_truss = math.atan2(float(normal[1]), float(normal[0]))
            ca, sa = math.cos(angle_truss), math.sin(angle_truss)
            corners = []
            for lx, ly in (
                (-span / 2, -0.2),
                (span / 2, -0.2),
                (span / 2, 0.2),
                (-span / 2, 0.2),
            ):
                corners.append((world_center[0] + lx * ca - ly * sa, world_center[1] + lx * sa + ly * ca))
            xs = [c[0] for c in corners]
            ys = [c[1] for c in corners]
            confidence = 0.5 + 0.15 * min(1.0, len(posts) / 4.0) + 0.1 * min(1.0, span / 20.0)
            truss_envelope = DetectedElement(
                class_name="truss",
                geometry={
                    "kind": "oriented_box",
                    "center": [round(float(c), 4) for c in world_center],
                    "sizes": {
                        "length": round(span, 3),
                        "thickness": 0.4,
                        "height": round(height, 3),
                    },
                    "rotation_z": round(angle_truss, 5),
                    "note": "ферма: пояса измерены по горизонтальным сегментам плоскости, стойки — по вертикальным",
                },
                bbox={
                    "min": [round(min(xs), 3), round(min(ys), 3), round(bot_z + float(geom.origin[2]), 3)],
                    "max": [round(max(xs), 3), round(max(ys), 3), round(top_z + float(geom.origin[2]), 3)],
                },
                confidence=round(min(0.85, confidence), 3),
                measured=True,
                inferred=False,
                dimensions={
                    "span_m": round(span, 3),
                    "span_status": "observed_extent_only",
                    "height_m": round(height, 3),
                    "top_chord_z": (
                        round(top_chord_z + float(geom.origin[2]), 3)
                        if top_chord_z is not None else None
                    ),
                    "bottom_chord_z": (
                        round(bottom_chord_z + float(geom.origin[2]), 3)
                        if bottom_chord_z is not None else None
                    ),
                    "panels": len(posts),
                    "observed_panels": len(posts),
                    "required_minimum_posts": TRUSS_MIN_POSTS,
                    "completeness": "partial" if partial_truss else "candidate_complete",
                    "missing_evidence": missing_evidence,
                    "height_status": height_status,
                    "diagonals": len(merged_d),
                    "section_fill": round(fill, 3),
                },
                metadata={
                    "method": "u-histogram peaks + (v,z) section Hough: chords/posts/diagonals",
                    "confidence_kind": "heuristic",
                    "notes": (
                        "Частичный кандидат: отображены только наблюдаемые стержни; "
                        "недостающие элементы не достраиваются."
                        if partial_truss else
                        "Нижний пояс может сливаться с уровнем низкой кровли; "
                        "число раскосов может быть занижено из-за частичной видимости."
                    ),
                    "completeness_status": "partial" if partial_truss else "candidate_complete",
                    "missing_evidence": missing_evidence,
                },
            )
            truss_envelope.metadata.update(_source_row_evidence_for_bbox(
                points[slice_mask],
                plane_source_rows,
                origin=geom.origin,
                bbox_min=np.asarray(truss_envelope.bbox["min"], dtype=np.float64),
                bbox_max=np.asarray(truss_envelope.bbox["max"], dtype=np.float64),
            ))
            truss_envelope.metadata["source_point_ids_sampled"] = bool(
                zone_sampled or truss_envelope.metadata["source_point_ids_sampled"]
            )
            truss_envelope.metadata["source_point_ids_from_processing_sample"] = bool(zone_sampled)
            elements.append(truss_envelope)
            truss_member_start = len(elements)
            truss_member_lines: list[tuple[tuple[np.ndarray, np.ndarray, float], str]] = []
            for line in top_chords:
                proposal_id = emit_truss_member(line, "truss_top_chord", "beam")
                if proposal_id:
                    truss_member_lines.append((line, proposal_id))
            for line in bot_chords:
                proposal_id = emit_truss_member(line, "truss_bottom_chord", "beam")
                if proposal_id:
                    truss_member_lines.append((line, proposal_id))
            accepted_horizontal_ids = {id(line) for line in (*top_chords, *bot_chords)}
            for line in merged_h:
                if id(line) in accepted_horizontal_ids:
                    continue
                # A chord split by occlusion can leave several source-supported
                # horizontal fragments, none long enough to claim as a chord.
                # Keep each visible fragment separately with an unknown role;
                # never bridge the unobserved gap or infer a missing elevation.
                fragment_evidence = {
                    "status": "unknown",
                    "reason": "horizontal_fragment_below_minimum_chord_span",
                    "observed_length_m": round(float(line[2]), 4),
                    "minimum_chord_span_m": TRUSS_MIN_CHORD_M,
                }
                proposal_id = emit_truss_member(
                    line, "unknown", "beam", fragment_evidence,
                )
                if proposal_id:
                    truss_member_lines.append((line, proposal_id))
            for line in posts:
                role, evidence = classify_truss_internal_member_role(line)
                proposal_id = emit_truss_member(line, role, "brace", evidence)
                if proposal_id:
                    truss_member_lines.append((line, proposal_id))
            for line in merged_d:
                role, evidence = classify_truss_internal_member_role(line)
                proposal_id = emit_truss_member(line, role, "brace", evidence)
                if proposal_id:
                    truss_member_lines.append((line, proposal_id))
            truss_envelope.metadata["member_proposal_ids"] = [
                item.metadata["member_proposal_id"]
                for item in elements[truss_member_start:]
                if item.metadata.get("member_proposal_id")
            ]
            truss_envelope.metadata["member_count_traced"] = len(
                truss_envelope.metadata["member_proposal_ids"]
            )
            if truss_envelope.metadata["member_proposal_ids"]:
                node_candidates = []
                for node in _section_node_evidence(
                    truss_member_lines, vz, plane_source_rows,
                    plane_coordinates=u[slice_mask],
                ):
                    world_position = [
                        round(float(value), 4)
                        for value in world_section_point(node["point_vz"])
                    ]
                    node_source_rows = sorted(node["source_point_ids"])
                    if len(node_source_rows) > 512:
                        node_source_rows = [
                            node_source_rows[index]
                            for index in np.linspace(0, len(node_source_rows) - 1, 512, dtype=np.int64)
                        ]
                    node_identity = json.dumps(
                        {
                            "position_m": world_position,
                            "member_ids": sorted(node["candidate_member_proposal_ids"]),
                            "source_point_ids": node_source_rows,
                        }, sort_keys=True, separators=(",", ":"),
                    ).encode("utf-8")
                    node_candidates.append({
                        "id": "node-proposal-" + hashlib.sha256(node_identity).hexdigest()[:24],
                        "position_m": world_position,
                        "candidate_member_proposal_ids": sorted(node["candidate_member_proposal_ids"]),
                        "source_point_ids": node_source_rows,
                        "status": "proposed",
                    })
                truss_envelope.metadata["assembly_proposal"] = build_assembly_proposal(
                    assembly_type=(
                        "roof_truss_partial_missing_top_chord" if partial_missing_chord and not top_chords
                        else "roof_truss_partial_missing_bottom_chord" if partial_missing_chord and not bot_chords
                        else "roof_truss_partial" if partial_truss
                        else "roof_truss"
                    ),
                    member_proposal_ids=truss_envelope.metadata["member_proposal_ids"],
                    node_candidates=node_candidates,
                )
            if partial_truss:
                stats["truss_partial_count"] += 1
            else:
                stats["truss_complete_count"] += 1
            stats["truss_count"] += 1
            planes_meta.append({
                "u": plane_world_u,
                "kind": "truss_partial" if partial_truss else "truss",
                "span": span,
                "posts": len(posts),
                "missing_evidence": missing_evidence,
            })
        elif len(merged_d) >= 2 and fill <= 0.5 and not has_chords:
            # Vertical bracing plane between trusses: emit diagonal members.
            for center_vz, dir_vz, diag_length in merged_d:
                v0 = float(center_vz[0] - dir_vz[0] * diag_length / 2)
                z0d = float(center_vz[1] - dir_vz[1] * diag_length / 2)
                v1 = float(center_vz[0] + dir_vz[0] * diag_length / 2)
                z1d = float(center_vz[1] + dir_vz[1] * diag_length / 2)
                p0 = np.array(
                    [
                        center2[0] + direction[0] * plane_u + normal[0] * v0,
                        center2[1] + direction[1] * plane_u + normal[1] * v0,
                        z0d,
                    ]
                ) + geom.origin
                p1 = np.array(
                    [
                        center2[0] + direction[0] * plane_u + normal[0] * v1,
                        center2[1] + direction[1] * plane_u + normal[1] * v1,
                        z1d,
                    ]
                ) + geom.origin
                elements.append(
                    _member_element(
                        geom, p0, p1,
                        section_m=None,
                        role="brace",
                        orientation="vertical",
                        confidence=0.35 + 0.05 * min(1.0, diag_length / 4.0),
                        method=(
                            "inter-truss (v,z) section Hough, collinear diagonal "
                            "fragments merged, diagonal without chords"
                        ),
                        source_point_ids=plane_source_rows[
                            (
                                np.abs((vz - center_vz) @ dir_vz) <= diag_length / 2 + 0.30
                            )
                            & (
                                np.abs((vz - center_vz) @ np.array([-dir_vz[1], dir_vz[0]]))
                                <= 0.20
                            )
                        ],
                        source_point_ids_sampled=zone_sampled,
                    )
                )
                stats["brace_vertical"] += 1
            planes_meta.append(
                {"u": plane_world_u, "kind": "bracing", "diagonals": len(merged_d)}
            )
    return elements, planes_meta, stats


# ------------------------------------------------------------ column typing
def _footprint_cells(
    center: np.ndarray,
    angle: float,
    length: float,
    thickness: float,
    res: float,
    nu: int,
    nv: int,
) -> np.ndarray:
    """Boolean mask of the column footprint on the grid raster."""
    ca, sa = math.cos(angle), math.sin(angle)
    half_l = length / 2 + res
    half_t = thickness / 2 + res
    mask = np.zeros((nv, nu), dtype=bool)
    # Raster search bounds must enclose the rotated rectangle, including corners.
    radius = max(abs(ca) * half_l + abs(sa) * half_t, abs(sa) * half_l + abs(ca) * half_t)
    rad = int(math.ceil(radius / res)) + 1
    cx = int(round((center[0] - 0) / res))
    cy = int(round((center[1] - 0) / res))
    for iy in range(max(0, cy - rad), min(nv, cy + rad + 1)):
        for ix in range(max(0, cx - rad), min(nu, cx + rad + 1)):
            x = (ix + 0.5) * res
            y = (iy + 0.5) * res
            dx, dy = x - center[0], y - center[1]
            along = dx * ca + dy * sa
            across = -dx * sa + dy * ca
            if abs(along) <= half_l and abs(across) <= half_t:
                mask[iy, ix] = True
    return mask


def _bimodal(values: np.ndarray) -> bool:
    """True when a 1D profile has two peaks with a deep valley between."""
    if len(values) < 6:
        return False
    smooth = ndimage.uniform_filter1d(values.astype(np.float64), size=2)
    peak = float(smooth.max())
    if peak <= 0:
        return False
    left_max = float(smooth[: len(smooth) // 2].max())
    right_max = float(smooth[len(smooth) // 2 :].max())
    if left_max <= 0 or right_max <= 0:
        return False
    valley = float(smooth[len(smooth) // 2 - 1 : len(smooth) // 2 + 2].min())
    return valley <= BIMODAL_VALLEY_RATIO * min(left_max, right_max)


def classify_column_sections(
    grid: dict[str, Any],
    columns: list[DetectedElement],
    origin: np.ndarray,
) -> dict[str, Any]:
    """Measure an area-vs-height profile per column and assign a section type."""
    res = float(grid["res"])
    band_occ = grid["band_occ"]
    counts_shape = band_occ.shape[1:]  # (nv, nu)
    nv, nu = counts_shape
    origin_min = grid["min"]  # local coords, grid[0][0] cell = (0,0) of raster
    typed = 0
    distribution: dict[str, int] = {}
    for element in columns:
        # geometry["center"] is WORLD; the raster origin is LOCAL
        # (= bbox_min - origin), so world -> raster needs BOTH subtractions.
        center_local = np.array(element.geometry["center"][:2], dtype=float) - np.array(
            [float(origin[0]) + float(origin_min[0]), float(origin[1]) + float(origin_min[1])]
        )
        angle = float(element.geometry.get("rotation_z") or 0.0)
        length = float(element.dimensions.get("length_m") or 0.2)
        thickness = float(element.dimensions.get("thickness_m") or 0.2)
        z0 = float(element.bbox["min"][2]) - float(origin[2]) - float(grid_origin_z(grid))
        z1 = float(element.bbox["max"][2]) - float(origin[2]) - float(grid_origin_z(grid))
        b0 = int(max(0, math.floor(z0 / grid_band_height())))
        b1 = int(min(band_occ.shape[0], math.ceil(z1 / grid_band_height()) + 1))
        if b1 - b0 < 2:
            continue
        footprint = _footprint_cells(center_local, angle, length, thickness, res, nu, nv)
        cells = int(footprint.sum())
        if cells < 4:
            continue
        areas: list[tuple[float, float]] = []  # (z_mid_local, occupied_area)
        for b in range(b0, b1):
            occupied = int((band_occ[b] & footprint).sum())
            z_mid = (b + 0.5) * grid_band_height()
            areas.append((z_mid, occupied * res * res))
        if len(areas) < 2:
            continue
        n = len(areas)
        # Columns are only partly visible in a real scan (occlusion, shadows),
        # so most 0.5 m bands inside the footprint are empty. A plain median
        # over ALL bands would be 0 for every partially-seen column and every
        # section would collapse to "undetermined". Take the median over the
        # MEASURED (non-empty) bands only, and report how sparse the profile
        # is so the engineer can judge the assignment.
        measured = [(z, a) for z, a in areas if a > 1e-9]
        coverage = len(measured) / max(1, n)
        if len(measured) < 2:
            continue
        split = max(1, n // 3)
        base_vals = [a for z, a in measured if z < (b0 + split) * grid_band_height()]
        top_vals = [a for z, a in measured if z >= (b1 - split) * grid_band_height()]
        base_area = float(np.median(base_vals)) if base_vals else 0.0
        top_area = float(np.median(top_vals)) if top_vals else 0.0
        mid_b = (b0 + b1) // 2
        mid_cells = int((band_occ[mid_b] & footprint).sum())
        if mid_cells == 0:
            # The middle band is often one of the empty ones; use the densest
            # measured band for the solid/built-up fill signature instead.
            densest_z, densest_a = max(measured, key=lambda za: za[1])
            mid_b = min(b1 - 1, max(b0, int(densest_z / grid_band_height())))
            mid_cells = int(densest_a / (res * res))
        fill = mid_cells / max(1, cells)
        # Bimodal flange signature on the mid band, projected on both axes.
        iy_grid, ix_grid = np.nonzero(band_occ[mid_b] & footprint)
        bimodal = False
        if len(iy_grid) >= 8:
            xs = (ix_grid + 0.5) * res
            ys = (iy_grid + 0.5) * res
            ca, sa = math.cos(angle), math.sin(angle)
            across = -xs * sa + ys * ca
            along = xs * ca + ys * sa
            for proj in (across, along):
                span = float(np.ptp(proj)) if len(proj) else 0.0
                if span < BIMODAL_SEPARATION_M * 2:
                    continue
                bins = np.arange(proj.min(), proj.max() + res, res)
                histv, _ = np.histogram(proj, bins=bins)
                if _bimodal(histv):
                    bimodal = True
                    break
        if top_area < STEPPED_AREA_RATIO * base_area and base_area >= 0.04:
            column_type = COLUMN_TYPE_STEPPED
        elif bimodal and fill < 0.60:
            column_type = COLUMN_TYPE_BUILT_UP
        elif fill >= 0.55:
            column_type = COLUMN_TYPE_SOLID
        else:
            column_type = COLUMN_TYPE_OTHER
        element.dimensions["column_type"] = column_type
        element.dimensions["column_type_label"] = {
            COLUMN_TYPE_STEPPED: "с уступом (подкрановая)",
            COLUMN_TYPE_BUILT_UP: "сборная (двутавр/решетчатая)",
            COLUMN_TYPE_SOLID: "сплошная прямоугольная",
            COLUMN_TYPE_OTHER: "сечение не определено",
        }[column_type]
        element.dimensions["section_profile"] = [
            {"z": round(float(origin[2]) + float(grid_origin_z(grid)) + z, 2), "area_m2": round(a, 3)}
            for z, a in areas[:: max(1, n // 6)]
        ]
        element.dimensions["base_area_m2"] = round(base_area, 3)
        element.dimensions["top_area_m2"] = round(top_area, 3)
        element.dimensions["section_fill"] = round(fill, 3)
        element.dimensions["section_coverage"] = round(coverage, 3)
        element.metadata["section_method"] = (
            "area-vs-height profile from 0.5 m occupancy bands inside the column footprint; "
            "median over non-empty bands only (occlusion makes most bands empty); "
            "bimodal projection => built-up section"
        )
        typed += 1
        distribution[column_type] = distribution.get(column_type, 0) + 1
    return {"columns_typed": typed, "column_types": distribution}


def measure_column_sections(
    geom: CloudGeometry,
    columns: list[DetectedElement],
    levels: list[dict[str, Any]] | None = None,
) -> dict[int, dict[str, Any]]:
    """Measure every column section from the cloud points at 2 cm.

    One extra streaming pass fills a local raster per column (windows are
    sparse, so most points are rejected by a 0.5 m cell lookup). The section
    is then measured on that raster: weighted PCA for the orientation, 1/99
    percentiles for the two outer dimensions, and side support for completing
    a partially scanned rectangle. Returns one record per column index.
    """
    if not columns:
        return {}
    res = COLUMN_MEASURE_RES
    minx = float(geom.bbox_min[0] - geom.origin[0])
    miny = float(geom.bbox_min[1] - geom.origin[1])
    # Floor slabs and roof planes run through every window; measuring on them
    # turns a column into a 1.2 m blob. Their levels are skipped.
    level_z = [
        float(level["z_local"])
        for level in (levels or [])
        if level.get("z_local") is not None
    ]
    coarse = 0.5
    ncx = int(math.ceil((float(geom.bbox_max[0] - geom.origin[0]) - minx) / coarse)) + 2
    ncy = int(math.ceil((float(geom.bbox_max[1] - geom.origin[1]) - miny) / coarse)) + 2
    owner = np.full(ncx * ncy, -1, dtype=np.int32)
    windows: list[dict[str, float]] = []
    for index, element in enumerate(columns):
        cx = float(element.geometry["center"][0]) - float(geom.origin[0])
        cy = float(element.geometry["center"][1]) - float(geom.origin[1])
        length = float(element.dimensions.get("length_m") or 0.2)
        thickness = float(element.dimensions.get("thickness_m") or 0.2)
        half = 0.5 * max(length, thickness) + 0.35
        cells = max(10, int(math.ceil(2.0 * half / res)) + 1)
        ox = cx - half
        oy = cy - half
        # Only the column's own height: the floor slab and the beam above run
        # through the same plan window and would otherwise define the section.
        z0 = float(element.bbox["min"][2]) - float(geom.origin[2])
        z1 = float(element.bbox["max"][2]) - float(geom.origin[2])
        inset = min(0.35, 0.25 * max(0.0, z1 - z0))
        windows.append(
            {
                "ox": ox,
                "oy": oy,
                "n": cells,
                "cx": cx,
                "cy": cy,
                "z0": z0 + inset,
                "z1": z1 - inset,
            }
        )
        ix0 = max(0, int((ox - minx) / coarse))
        ix1 = min(ncx - 1, int((ox + cells * res - minx) / coarse))
        iy0 = max(0, int((oy - miny) / coarse))
        iy1 = min(ncy - 1, int((oy + cells * res - miny) / coarse))
        for ix in range(ix0, ix1 + 1):
            for iy in range(iy0, iy1 + 1):
                flat = ix * ncy + iy
                if owner[flat] == -1:
                    owner[flat] = index
    sizes = [int(w["n"]) ** 2 for w in windows]
    offsets = np.cumsum([0] + sizes)
    total_cells = int(offsets[-1])
    counts = np.zeros(total_cells, dtype=np.int64)
    ox_arr = np.array([w["ox"] for w in windows], dtype=np.float64)
    oy_arr = np.array([w["oy"] for w in windows], dtype=np.float64)
    n_arr = np.array([int(w["n"]) for w in windows], dtype=np.int64)
    z0_arr = np.array([float(w["z0"]) for w in windows], dtype=np.float64)
    z1_arr = np.array([float(w["z1"]) for w in windows], dtype=np.float64)
    for chunk in _iter_positions(geom.positions_path):
        x = chunk[:, 0].astype(np.float64)
        y = chunk[:, 1].astype(np.float64)
        z = chunk[:, 2].astype(np.float64)
        ix = ((x - minx) / coarse).astype(np.int64)
        iy = ((y - miny) / coarse).astype(np.int64)
        inside = (ix >= 0) & (ix < ncx) & (iy >= 0) & (iy < ncy)
        if not inside.any():
            continue
        flat = ix[inside] * ncy + iy[inside]
        column_index = owner[flat]
        hit = column_index >= 0
        if not hit.any():
            continue
        column_index = column_index[hit]
        px = x[inside][hit]
        py = y[inside][hit]
        pz = z[inside][hit]
        lx = ((px - ox_arr[column_index]) / res).astype(np.int64)
        ly = ((py - oy_arr[column_index]) / res).astype(np.int64)
        local = (lx >= 0) & (ly >= 0) & (lx < n_arr[column_index]) & (ly < n_arr[column_index])
        local &= (pz >= z0_arr[column_index]) & (pz <= z1_arr[column_index])
        for level in level_z:
            local &= np.abs(pz - level) > 0.35
        if not local.any():
            continue
        column_index = column_index[local]
        cell = offsets[column_index] + ly[local] * n_arr[column_index] + lx[local]
        counts += np.bincount(cell, minlength=total_cells)

    measured: dict[int, dict[str, Any]] = {}
    for index, window in enumerate(windows):
        cells = int(window["n"])
        raster = counts[offsets[index] : offsets[index] + cells * cells].reshape(cells, cells)
        occupied = raster >= COLUMN_MEASURE_CELL_MIN
        if int(raster.sum()) < COLUMN_MEASURE_MIN_POINTS or int(occupied.sum()) < 8:
            continue
        iy, ix = np.nonzero(occupied)
        weights = raster[iy, ix].astype(np.float64)
        xs = (ix + 0.5) * res + float(window["ox"]) - float(window["cx"])
        ys = (iy + 0.5) * res + float(window["oy"]) - float(window["cy"])
        # Crop to the footprint the coarse stage found (plus one grid cell of
        # slack): the window also catches a wall crossing it, and a wall would
        # otherwise define the section. A hollow column keeps its faces.
        element = columns[index]
        coarse_angle = float(element.geometry.get("rotation_z") or 0.0)
        coarse_length = float(element.dimensions.get("length_m") or 0.2)
        coarse_thickness = float(element.dimensions.get("thickness_m") or 0.2)
        cca, csa = math.cos(coarse_angle), math.sin(coarse_angle)
        crop = (np.abs(xs * cca + ys * csa) <= coarse_length / 2 + 0.15) & (
            np.abs(-xs * csa + ys * cca) <= coarse_thickness / 2 + 0.15
        )
        if int(crop.sum()) >= 8:
            xs = xs[crop]
            ys = ys[crop]
            weights = weights[crop]
        weight_sum = float(weights.sum())
        mx = float((xs * weights).sum() / weight_sum)
        my = float((ys * weights).sum() / weight_sum)
        cxx = float((weights * (xs - mx) ** 2).sum() / weight_sum)
        cyy = float((weights * (ys - my) ** 2).sum() / weight_sum)
        cxy = float((weights * (xs - mx) * (ys - my)).sum() / weight_sum)
        angle = 0.5 * math.atan2(2.0 * cxy, cxx - cyy)
        ca, sa = math.cos(angle), math.sin(angle)
        along = (xs - mx) * ca + (ys - my) * sa
        across = -(xs - mx) * sa + (ys - my) * ca
        # Cell centres, so the measured extent is at most half a cell short of
        # the outer surface on each side; inflating it by a whole cell instead
        # made every section 20 mm too large and split one type into many.
        a0, a1 = (float(v) for v in np.percentile(along, [0.5, 99.5]))
        c0, c1 = (float(v) for v in np.percentile(across, [0.5, 99.5]))
        length = max(res, a1 - a0)
        thickness = max(res, c1 - c0)
        u_mid = (a0 + a1) / 2
        v_mid = (c0 + c1) / 2
        # ``mx``/``my`` are in window coordinates, so the window centre must be
        # added back: without it every column lands on the cloud origin.
        center_x = float(window["cx"]) + mx + u_mid * ca - v_mid * sa + float(geom.origin[0])
        center_y = float(window["cy"]) + my + u_mid * sa + v_mid * ca + float(geom.origin[1])
        bbox_cells = max(1.0, (a1 - a0) / res) * max(1.0, (c1 - c0) / res)
        fill = min(1.0, float(len(xs)) / bbox_cells)
        if fill > COLUMN_SECTION_MAX_FILL:
            # The window is filled solid: a hollow column leaves its interior
            # empty, so this is clutter (equipment, stored goods, merged
            # geometry) and its "faces" mean nothing.
            faces_along = faces_across = 0
        else:
            faces_along, faces_across = _section_faces(along, across, res, length, thickness)
        measured[index] = {
            "center": (center_x, center_y),
            "angle": angle,
            "length": length,
            "thickness": thickness,
            "faces_along": faces_along,
            "faces_across": faces_across,
            "fill": round(fill, 3),
            "points": int(raster.sum()),
        }

    # A near-square section has no stable principal direction (PCA on a square
    # is arbitrary), and a hall builds all its columns on one grid: take the
    # common orientation from the rectangular columns and use it for those.
    rectangular = [
        record for record in measured.values()
        if abs(record["length"] - record["thickness"]) >= 0.08
    ]
    if rectangular:
        s = sum(math.sin(2 * record["angle"]) for record in rectangular)
        c = sum(math.cos(2 * record["angle"]) for record in rectangular)
        if abs(s) + abs(c) > 1e-9:
            reference = 0.5 * math.atan2(s, c)
            for record in measured.values():
                square = abs(record["length"] - record["thickness"]) < 0.08
                if square or _angle_diff(record["angle"], reference) <= math.radians(20):
                    record["angle"] = reference
    return measured


def _column_plan_cells(
    plan_occ: np.ndarray,
    res: float,
    min_xy: tuple[float, float],
    element: DetectedElement,
    origin: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Occupied plan cells around one column, in the column's own axes.

    ``plan_occ`` is the plan projection of the occupancy raster (one flag per
    cell, any height). Cells are returned as (along, across) distances from
    the column centre, so a side can be tested independently of rotation.
    """
    nv, nu = int(plan_occ.shape[0]), int(plan_occ.shape[1])
    center = np.array(element.geometry["center"][:2], dtype=float) - np.array(
        [float(origin[0]) + min_xy[0], float(origin[1]) + min_xy[1]]
    )
    angle = float(element.geometry.get("rotation_z") or 0.0)
    length = float(element.dimensions.get("length_m") or 0.2)
    thickness = float(element.dimensions.get("thickness_m") or 0.2)
    radius = 0.5 * math.hypot(length, thickness) + 3.0 * res
    ix0 = max(0, int(math.floor((center[0] - radius) / res)))
    ix1 = min(nu, int(math.floor((center[0] + radius) / res)) + 1)
    iy0 = max(0, int(math.floor((center[1] - radius) / res)))
    iy1 = min(nv, int(math.floor((center[1] + radius) / res)) + 1)
    if ix1 <= ix0 or iy1 <= iy0:
        return np.zeros(0, dtype=float), np.zeros(0, dtype=float)
    iy, ix = np.nonzero(plan_occ[iy0:iy1, ix0:ix1])
    if len(ix) == 0:
        return np.zeros(0, dtype=float), np.zeros(0, dtype=float)
    xs = (ix0 + ix + 0.5) * res
    ys = (iy0 + iy + 0.5) * res
    ca, sa = math.cos(angle), math.sin(angle)
    dx = xs - center[0]
    dy = ys - center[1]
    along = dx * ca + dy * sa
    across = -dx * sa + dy * ca
    margin = 2.0 * res
    keep = (np.abs(along) <= length / 2 + margin) & (np.abs(across) <= thickness / 2 + margin)
    return along[keep], across[keep]


def _side_visible(
    primary: np.ndarray,
    secondary: np.ndarray,
    edge: float,
    band: float,
    res: float,
    expected: float,
) -> bool:
    """True when one section side is actually scanned.

    The middle of the side is required: cells belonging to the PERPENDICULAR
    face lie at this side's extreme and would otherwise make a corner look
    like three or four visible sides.
    """
    near = np.abs(primary - edge) <= band
    if not near.any():
        return False
    sec = secondary[near]
    slots = np.unique(np.round(sec / res).astype(np.int64))
    if len(slots) < COLUMN_SIDE_MIN_COVERAGE * max(1.0, expected / res):
        return False
    lo, hi = float(secondary.min()), float(secondary.max())
    if hi - lo <= res:
        return True
    mid_lo = lo + 0.30 * (hi - lo)
    mid_hi = hi - 0.30 * (hi - lo)
    return bool(((sec >= mid_lo) & (sec <= mid_hi)).any())


def _section_faces(
    along: np.ndarray,
    across: np.ndarray,
    res: float,
    length: float,
    thickness: float,
) -> tuple[int, int]:
    """How many of the two faces are visible per section axis."""
    if len(along) == 0:
        return 0, 0
    band = COLUMN_SIDE_BAND_CELLS * res
    along0, along1 = float(along.min()), float(along.max())
    across0, across1 = float(across.min()), float(across.max())
    faces_along = int(_side_visible(along, across, along0, band, res, thickness)) + int(
        _side_visible(along, across, along1, band, res, thickness)
    )
    faces_across = int(_side_visible(across, along, across0, band, res, length)) + int(
        _side_visible(across, along, across1, band, res, length)
    )
    # One cell row cannot show two opposite faces: both "sides" would be the
    # same cells, and an occluded axis would look fully measured.
    if along1 - along0 <= 1.5 * res:
        faces_along = min(faces_along, 1)
    if across1 - across0 <= 1.5 * res:
        faces_across = min(faces_across, 1)
    return faces_along, faces_across


def _cluster_sections(
    sizes: list[tuple[float, float]],
    tolerance: float,
) -> list[list[tuple[float, float]]]:
    """Group measured sections with pairwise agreement on both dimensions.

    Complete-link membership prevents a sequence of noisy measurements from
    bridging two genuinely different sizes. Sorting first also makes the
    resulting partition independent of recognition/input order.
    """
    ordered = sorted((float(length), float(thickness)) for length, thickness in sizes)
    clusters: list[list[tuple[float, float]]] = []
    epsilon = max(1e-12, abs(tolerance) * 1e-12)

    def compatible(left: tuple[float, float], right: tuple[float, float]) -> bool:
        return all(abs(a - b) <= tolerance + epsilon for a, b in zip(left, right))

    for size in ordered:
        matches = [
            (index, cluster)
            for index, cluster in enumerate(clusters)
            if all(compatible(size, member) for member in cluster)
        ]
        if not matches:
            clusters.append([size])
            continue
        # If several groups are compatible, attach to the closest median, with
        # the stable cluster index breaking exact ties deterministically.
        def distance(item: tuple[int, list[tuple[float, float]]]) -> tuple[float, int]:
            index, cluster = item
            representative = np.median(np.asarray(cluster, dtype=np.float64), axis=0)
            scale = max(tolerance, 1e-12)
            residual = sum(abs(size[axis] - representative[axis]) / scale for axis in (0, 1))
            return float(residual), index

        _, best = min(matches, key=distance)
        best.append(size)

    # Merge only if every cross-pair remains within tolerance; never merge by
    # representative distance alone, which can recreate a transitive bridge.
    merged = True
    while merged and len(clusters) > 1:
        merged = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                if all(compatible(left, right) for left in clusters[i] for right in clusters[j]):
                    clusters[i].extend(clusters.pop(j))
                    clusters[i].sort()
                    merged = True
                    break
            if merged:
                break
    return clusters


def _apply_column_section(element: DetectedElement, length: float, thickness: float) -> None:
    """Rewrite the column footprint to the completed / nominal section."""
    angle = float(element.geometry.get("rotation_z") or 0.0)
    center = element.geometry["center"]
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
    element.geometry.setdefault("sizes", {})
    element.geometry["sizes"]["length"] = round(length, 3)
    element.geometry["sizes"]["thickness"] = round(thickness, 3)
    element.dimensions["length_m"] = round(length, 3)
    element.dimensions["thickness_m"] = round(thickness, 3)
    element.dimensions["footprint_area_m2"] = round(length * thickness, 3)
    element.bbox["min"][0] = round(min(xs), 3)
    element.bbox["min"][1] = round(min(ys), 3)
    element.bbox["max"][0] = round(max(xs), 3)
    element.bbox["max"][1] = round(max(ys), 3)


def typify_column_sections(
    grid: dict[str, Any],
    columns: list[DetectedElement],
    origin: np.ndarray,
    measured: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Record point-supported column sides and propose repeated sections.

    Both section axes must have point-supported visible faces before a full
    section is measured. Repeated sizes stay proposals; they never replace a
    member's measured dimensions without explicit review.
    """
    if not columns:
        return {"column_section_types": [], "column_sections_total": 0}
    res = float(grid["res"])
    plan_occ = grid["band_occ"].any(axis=0)
    min_xy = (float(grid["min"][0]), float(grid["min"][1]))
    measurements: list[dict[str, Any]] = []
    for index, element in enumerate(columns):
        record = measured.get(index) if measured else None
        if record is not None:
            length = float(record["length"])
            thickness = float(record["thickness"])
            faces_along = int(record["faces_along"])
            faces_across = int(record["faces_across"])
            # Refined geometry from the points: the coarse grid centre and its
            # PCA angle are off by up to a cell and ten degrees.
            element.geometry["center"][0] = round(float(record["center"][0]), 4)
            element.geometry["center"][1] = round(float(record["center"][1]), 4)
            element.geometry["rotation_z"] = round(float(record["angle"]), 5)
        else:
            length = float(element.dimensions.get("length_m") or 0.0)
            thickness = float(element.dimensions.get("thickness_m") or 0.0)
            if length <= 0 or thickness <= 0:
                continue
            along, across = _column_plan_cells(plan_occ, res, min_xy, element, origin)
            faces_along, faces_across = _section_faces(along, across, res, length, thickness)
        visible = faces_along + faces_across
        # The coarse occupancy grid can help locate visible faces, but its
        # 10 cm cell dimensions are not a section measurement. Only the local
        # point-derived record can supply measured side lengths.
        length_measured = record is not None and faces_across > 0
        thickness_measured = record is not None and faces_along > 0
        both_dimensions_measured = length_measured and thickness_measured
        measured_axes = {
            "length": round(length, 3) if length_measured else None,
            "thickness": round(thickness, 3) if thickness_measured else None,
        }
        if record is None:
            status = "coarse_grid_only" if visible else "unconfirmed"
        elif both_dimensions_measured and visible == 4:
            status = "measured_4_sides"
        elif both_dimensions_measured and visible == 3:
            status = "measured_3_sides"
        elif both_dimensions_measured:
            status = "measured_2_axes"
        else:
            status = "partial_one_axis" if length_measured or thickness_measured else "unconfirmed"
        element.dimensions["sides_visible"] = visible
        element.dimensions["section_status"] = status
        element.dimensions["measured_section_axes_m"] = measured_axes
        if both_dimensions_measured:
            element.dimensions["measured_section_m"] = [round(length, 3), round(thickness, 3)]
            element.dimensions["section_source"] = "measured"
            # Only point-derived dimensions with visible evidence on both axes
            # may replace the coarse recognition footprint.
            if record is not None:
                _apply_column_section(element, length, thickness)
        else:
            element.dimensions.pop("measured_section_m", None)
            element.dimensions["section_source"] = (
                "partial_measurement" if record is not None and visible
                else "coarse_grid" if visible
                else "unknown"
            )
        measurements.append(
            {
                "element": element,
                "length": length,
                "thickness": thickness,
                "sides": visible,
                "both_dimensions_measured": both_dimensions_measured,
                "status": status,
            }
        )

    reliable = [
        (m["length"], m["thickness"])
        for m in measurements
        if m["both_dimensions_measured"]
        and min(m["length"], m["thickness"]) >= 0.15
        and m["length"] * m["thickness"] >= 0.05
    ]
    clusters = _cluster_sections(reliable, COLUMN_SECTION_TOLERANCE_M) if reliable else []
    # A size seen on ONE column is an outlier (mis-measurement or a genuinely
    # single column), not a hall type: it cannot define a nominal size.
    clusters = [cluster for cluster in clusters if len(cluster) >= 2]
    clusters.sort(key=lambda c: (-len(c), -float(np.median([s[0] for s in c]))))
    types: list[dict[str, Any]] = []
    for index, members in enumerate(clusters):
        nominal_length = (
            round(float(np.median([s[0] for s in members])) / COLUMN_NOMINAL_ROUND_M)
            * COLUMN_NOMINAL_ROUND_M
        )
        nominal_thickness = (
            round(float(np.median([s[1] for s in members])) / COLUMN_NOMINAL_ROUND_M)
            * COLUMN_NOMINAL_ROUND_M
        )
        types.append(
            {
                "id": f"proposal-{index + 1}",
                "length": nominal_length,
                "thickness": nominal_thickness,
                "member_count": len(members),
                "status": "proposed",
            }
        )

    unique = 0
    for m in measurements:
        element = m["element"]
        length = float(m["length"])
        thickness = float(m["thickness"])
        if not m["both_dimensions_measured"]:
            continue
        best = None
        best_residual = None
        for column_type in types:
            residual = max(
                abs(length - column_type["length"]),
                abs(thickness - column_type["thickness"]),
            )
            if best_residual is None or residual < best_residual:
                best, best_residual = column_type, residual
        assignment_limit = min(COLUMN_SECTION_TOLERANCE_M, COLUMN_SECTION_MAX_RESIDUAL_M)
        if best is not None and best_residual is not None and best_residual <= assignment_limit:
            element.dimensions["section_type_proposal_id"] = best["id"]
            element.dimensions["section_residual_mm"] = int(round(best_residual * 1000))
        else:
            element.dimensions["section_source"] = "measured"
            if types and m["status"] != "unconfirmed":
                element.dimensions["section_status"] = "unique_section"
            unique += 1

    return {
        "column_section_types": [
            {
                "id": t["id"],
                "length_m": round(t["length"], 3),
                "thickness_m": round(t["thickness"], 3),
                "label_mm": (
                    f"{int(round(t['length'] * 1000))}×{int(round(t['thickness'] * 1000))}"
                ),
                "member_count": t["member_count"],
                "status": t["status"],
            }
            for t in types
        ],
        "column_sections_total": len(measurements),
        "column_sections_snapped": 0,
        "column_sections_type_proposals": len(types),
        "column_sections_unique": unique,
        "column_sections_two_axes_measured": sum(
            1 for m in measurements if m["both_dimensions_measured"]
        ),
        "column_sections_partial": sum(
            1 for m in measurements if m["status"] == "partial_one_axis"
        ),
        "column_sections_unconfirmed": sum(
            1 for m in measurements if m["status"] in {"coarse_grid_only", "unconfirmed"}
        ),
        "column_section_tolerance_m": COLUMN_SECTION_TOLERANCE_M,
    }


_GRID_STATE: dict[str, float] = {}


def grid_band_height() -> float:
    return _GRID_STATE.get("band", 0.5)


def grid_origin_z(grid: dict[str, Any]) -> float:
    return float(grid["min"][2])


def _set_grid_state(grid: dict[str, Any]) -> None:
    _GRID_STATE["band"] = float(grid.get("assumed_band_height", 0.5))


# ------------------------------------------------------------------ entrypoint
def detect_structural_frame(
    geom: CloudGeometry,
    levels: list[dict[str, Any]],
    grid: dict[str, Any],
    columns: list[DetectedElement],
    progress=None,
) -> tuple[list[DetectedElement], dict[str, Any], list[str]]:
    """Full steel-frame stage: horizontal members, trusses, braces, typing."""
    warnings: list[str] = []
    stats: dict[str, Any] = {}
    elements: list[DetectedElement] = []
    if len(levels) < 3 or grid["total"] < 10_000:
        stats["steel_stage"] = "skipped (нужно >= 3 уровней и >= 10 000 точек)"
        return elements, stats, warnings

    if progress:
        progress(0.86, "распознавание горизонтальных балок по уровням")
    _set_grid_state(grid)
    beams, axis, _band_xy, h_warnings = _horizontal_members(geom, levels, grid, progress, columns=columns)
    warnings.extend(h_warnings)
    elements.extend(beams)
    stats["hall_axis_deg"] = round(math.degrees(axis), 4) if axis is not None else None
    stats["hall_axis_method"] = "measured orthogonal line consensus; PCA chooses longitudinal direction"

    if axis is not None:
        zone = _truss_zone(geom, levels)
        if zone:
            truss_elements, planes, truss_stats = _detect_trusses(geom, zone, axis, progress)
            elements.extend(truss_elements)
            stats.update(truss_stats)
            stats["truss_planes_total"] = len(planes)
            if truss_stats.get("brace_vertical"):
                warnings.append(
                    f"Найдено {truss_stats['brace_vertical']} вертикальных связей "
                    "(диагонали в плоскостях между фермами)."
                )
        else:
            warnings.append("Полоса ферм не выделена (мало уровней или кровли слились).")
    else:
        warnings.append("Фермы и связи не распознаны: ось зала не определена.")

    # Sections are measured from the points (2 cm local raster). Repeated
    # sizes remain review proposals; only point-supported dimensions update
    # the footprint and no nominal type silently replaces the measurement.
    if progress:
        progress(0.955, "измерение сечений колонн по точкам")
    measured_sections = measure_column_sections(geom, columns, levels)
    if progress:
        progress(0.965, "типоразмеры сечений колонн")
    sections = typify_column_sections(grid, columns, geom.origin, measured_sections)
    stats.update(sections)
    if sections.get("column_section_types"):
        labels = ", ".join(
            f"{t['id']} {t['label_mm']} мм — {t['member_count']} колонн"
            for t in sections["column_section_types"]
        )
        warnings.append(
            f"Предложены {len(sections['column_section_types'])} повторяющиеся группы "
            f"сечений (допуск группировки {int(sections['column_section_tolerance_m'] * 1000)} мм): "
            f"{labels}. Геометрия осталась измеренной; типы требуют проверки. "
            f"Сечения с измерениями по обеим осям: {sections['column_sections_two_axes_measured']}; "
            f"частично измерено: {sections['column_sections_partial']}; "
            f"сечение неизвестно или видно только на грубой сетке: "
            f"{sections['column_sections_unconfirmed']}."
        )

    if progress:
        progress(0.97, "типизация сечений колонн")
    typing = classify_column_sections(grid, columns, geom.origin)
    stats.update(typing)

    role_counts: dict[str, int] = {}
    for element in elements:
        if element.class_name == "beam":
            role = element.dimensions.get("role", "beam")
            role_counts[role] = role_counts.get(role, 0) + 1
    stats["beam_roles"] = role_counts
    stats["steel_members"] = len(elements)
    stats["method"] = (
        "thin-band plan Hough (beams) + u-plane (v,z) section Hough (trusses, braces) "
        "+ occupancy-band column typing"
    )
    return elements, stats, warnings
