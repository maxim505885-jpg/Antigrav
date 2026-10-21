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

import math
from typing import Any

import numpy as np
from scipy import ndimage
from skimage.morphology import skeletonize
from skimage.transform import probabilistic_hough_line

from ..geometry.section import CloudGeometry
from .geometric import CHUNK, DetectedElement, _iter_positions

# Physical thresholds. They encode what a structural engineer recognises as a
# frame member, not merely "a line of points".
BEAM_MIN_LENGTH_M = 2.5
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
# A (v, z) section of a truss is mostly empty space; a wall-like plane fills
# more than this share of its raster and is rejected as a truss.
TRUSS_MAX_SECTION_FILL = 0.35

BAND_CAP_POINTS = 3_000_000
HOUGH_SEED = 20261020

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


def _bands_points(geom: CloudGeometry, bands: list[tuple[float, float]]) -> list[np.ndarray]:
    """Points of the cloud inside several local z bands in ONE pass."""
    collectors: list[list[np.ndarray]] = [[] for _ in bands]
    for chunk in _iter_positions(geom.positions_path):
        z = chunk[:, 2]
        for index, (z0, z1) in enumerate(bands):
            mask = (z >= z0) & (z < z1)
            if mask.any():
                collectors[index].append(chunk[mask])
    out: list[np.ndarray] = []
    for parts in collectors:
        if not parts:
            out.append(np.zeros((0, 3), dtype=np.float32))
            continue
        points = np.concatenate(parts)
        if len(points) > BAND_CAP_POINTS:
            stride = int(math.ceil(len(points) / BAND_CAP_POINTS))
            points = points[::stride]
        out.append(points)
    return out


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
) -> tuple[float, float, float, int]:
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
    return thickness, z0, z1, int(selected.sum())


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
    xs = [c[0] + float(geom.origin[0]) for c in corners]
    ys = [c[1] + float(geom.origin[1]) for c in corners]
    label = {
        "crane_girder": "подкрановая балка",
        "purlin": "прогон",
        "floor_beam": "балка перекрытия",
    }.get(role, role)
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
        bbox={
            "min": [round(min(xs), 3), round(min(ys), 3), round(z0_local + float(geom.origin[2]), 3)],
            "max": [round(max(xs), 3), round(max(ys), 3), round(z1_local + float(geom.origin[2]), 3)],
        },
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
        metadata={
            "method": "thin-band plan raster + skeleton + probabilistic Hough + collinear merge",
            "band_label": band_label,
            "support_points": support,
            "confidence_kind": "heuristic",
            "notes": role_note,
        },
    )


def _member_element(
    geom: CloudGeometry,
    p0_world: np.ndarray,
    p1_world: np.ndarray,
    section_m: float,
    role: str,
    orientation: str,
    confidence: float,
    method: str,
) -> DetectedElement:
    length = float(np.linalg.norm(p1_world - p0_world))
    mid = (p0_world + p1_world) / 2
    label = {
        "brace": "связь",
    }.get(role, role)
    return DetectedElement(
        class_name="brace",
        geometry={
            "kind": "member",
            "p0": [round(float(v), 4) for v in p0_world],
            "p1": [round(float(v), 4) for v in p1_world],
            "section_m": round(section_m, 3),
            "note": f"diagonal member measured between two points ({orientation} bracing)",
        },
        bbox={
            "min": [round(min(p0_world[0], p1_world[0]) - section_m / 2, 3),
                    round(min(p0_world[1], p1_world[1]) - section_m / 2, 3),
                    round(min(p0_world[2], p1_world[2]) - section_m / 2, 3)],
            "max": [round(max(p0_world[0], p1_world[0]) + section_m / 2, 3),
                    round(max(p0_world[1], p1_world[1]) + section_m / 2, 3),
                    round(max(p0_world[2], p1_world[2]) + section_m / 2, 3)],
        },
        confidence=round(float(max(0.2, min(0.9, confidence))), 3),
        measured=True,
        inferred=False,
        dimensions={
            "length_m": round(length, 3),
            "role": role,
            "role_label": label,
            "orientation": orientation,
        },
        metadata={
            "method": method,
            "confidence_kind": "heuristic",
            "notes": "диагональная распорка; класс — гипотеза, проверьте в редакторе",
        },
    )


# ------------------------------------------------------------- horizontal stage
def _horizontal_members(
    geom: CloudGeometry,
    levels: list[dict[str, Any]],
    grid: dict[str, Any],
    progress=None,
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
    band_points = _bands_points(geom, [(z0, z1) for z0, z1, *_ in band_data])
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
    for (z0, z1, label, kind), points, segments in zip(band_data, band_points, segments_by_band):
        if progress:
            progress(0.88, f"горизонтальные члены в полосе {label}")
        band_xy.append(points[:, :2])
        if len(points) < 500:
            continue
        groups = _group_segments(segments)
        for group in groups:
            center, direction, length = _group_line(group)
            if length < BEAM_MIN_LENGTH_M:
                continue
            thickness, bz0, bz1, support = _measure_strip(
                points[:, :2], points[:, 2], center, direction, length
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
            if diagonal and kind in ("crane", "roof"):
                if length >= BRACE_MIN_LENGTH_M:
                    # Width alone is unusable here (it saturates on the roof);
                    # require the points to actually cluster on the line.
                    conc = _line_concentration(
                        points[:, :2], center, direction, length,
                        core_m=BRACE_CORE_M,
                    )
                    if conc >= BRACE_MIN_CONCENTRATION:
                        p0 = np.array([center[0] - direction[0] * length / 2, center[1] - direction[1] * length / 2, (bz0 + bz1) / 2]) + geom.origin
                        p1 = np.array([center[0] + direction[0] * length / 2, center[1] + direction[1] * length / 2, (bz0 + bz1) / 2]) + geom.origin
                        elements.append(
                            _member_element(
                                geom, p0, p1,
                                section_m=max(0.10, min(thickness, 0.4)),
                                role="brace",
                                orientation="horizontal",
                                confidence=0.35 + 0.1 * min(1.0, length / 10.0) + 0.15 * min(1.0, (conc - BRACE_MIN_CONCENTRATION) / 0.25),
                                method="thin-band plan Hough + line concentration, diagonal 25..65 deg from hall axis",
                            )
                        )
                        role_counts["brace_horizontal"] = role_counts.get("brace_horizontal", 0) + 1
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
            elements.append(
                _beam_element(
                    geom, center, direction, length,
                    max(thickness, 0.08), bz0, bz1,
                    role=role,
                    role_note=note,
                    confidence=confidence,
                    band_label=label,
                    support=support,
                )
            )
            role_counts[role] = role_counts.get(role, 0) + 1
    if role_counts.get("crane_girder"):
        warnings.append(
            f"Найдено {role_counts['crane_girder']} подкрановых балок (осевые длинные балки между уровнями) "
            "— класс геометрический, привязку к крановому пути проверьте в редакторе."
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


def _collect_zone(geom: CloudGeometry, z0: float, z1: float) -> np.ndarray:
    parts: list[np.ndarray] = []
    total = 0
    for chunk in _iter_positions(geom.positions_path):
        mask = (chunk[:, 2] >= z0) & (chunk[:, 2] < z1)
        if mask.any():
            parts.append(chunk[mask])
            total += int(mask.sum())
    if not parts:
        return np.zeros((0, 3), dtype=np.float32)
    points = np.concatenate(parts)
    if len(points) > 6_000_000:
        stride = int(math.ceil(len(points) / 6_000_000))
        points = points[::stride]
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
    points = _collect_zone(geom, zone[0], zone[1])
    elements: list[DetectedElement] = []
    stats = {"truss_count": 0, "brace_vertical": 0}
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
        sparse = fill <= TRUSS_MAX_SECTION_FILL
        plane_world_u = float(plane_u + center2 @ direction)

        if has_chords and len(posts) >= TRUSS_MIN_POSTS and sparse:
            span_pts = vz[(vz[:, 1] >= zone[0]) & (vz[:, 1] <= zone[1])]
            v_min = float(np.percentile(span_pts[:, 0], 1))
            v_max = float(np.percentile(span_pts[:, 0], 99))
            span = v_max - v_min
            if span < TRUSS_MIN_SPAN_M:
                continue
            top_z = float(np.median([m[0][1] for m in top_chords])) if top_chords else zone[1] - 0.3
            bot_z = float(np.median([m[0][1] for m in bot_chords])) if bot_chords else zone[0] + 0.3
            height = max(0.3, top_z - bot_z)
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
            elements.append(
                DetectedElement(
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
                        "height_m": round(height, 3),
                        "top_chord_z": round(top_z + float(geom.origin[2]), 3),
                        "bottom_chord_z": round(bot_z + float(geom.origin[2]), 3),
                        "panels": len(posts),
                        "diagonals": len(diagonals),
                        "section_fill": round(fill, 3),
                    },
                    metadata={
                        "method": "u-histogram peaks + (v,z) section Hough: chords/posts/diagonals",
                        "confidence_kind": "heuristic",
                        "notes": (
                            "Нижний пояс часто сливается с уровнем низкой кровли; "
                            "число раскосов может быть занижено из-за частичной видимости."
                        ),
                    },
                )
            )
            stats["truss_count"] += 1
            planes_meta.append({"u": plane_world_u, "kind": "truss", "span": span, "posts": len(posts)})
        elif diagonals and len(diagonals) >= 2 and fill <= 0.5 and not has_chords:
            # Vertical bracing plane between trusses: emit diagonal members.
            for diag in diagonals:
                v0, z0d = diag["p0"]
                v1, z1d = diag["p1"]
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
                        section_m=0.15,
                        role="brace",
                        orientation="vertical",
                        confidence=0.35 + 0.05 * min(1.0, diag["length"] / 4.0),
                        method="inter-truss (v,z) section Hough, diagonal without chords",
                    )
                )
                stats["brace_vertical"] += 1
            planes_meta.append({"u": plane_world_u, "kind": "bracing", "diagonals": len(diagonals)})
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
    beams, axis, _band_xy, h_warnings = _horizontal_members(geom, levels, grid, progress)
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

    if progress:
        progress(0.96, "типизация сечений колонн")
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
