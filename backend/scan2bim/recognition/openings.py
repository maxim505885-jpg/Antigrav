"""Opening detection: doors and windows as gaps in well-observed walls.

For every wall the point cloud is rastered in the wall's own frame: ``u``
along the centreline, ``z`` from the storey floor. A door is a vertical strip
that is empty from the floor up to the lintel while the wall above it is
scanned; a window is the same strip with a scanned sill below. The lintel
requirement is what separates a real opening from a face that was never
scanned: occlusion removes the wall above the gap too.

The result is a review hypothesis, not a construction document: an unpainted
or glazed face, a hole in the scan, and a real opening look alike.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from ..geometry.section import CloudGeometry
from .geometric import CHUNK, DetectedElement

OWNER_RES = 0.50           # coarse ownership grid for wall attribution, m
OWNER_PAD_M = 0.30         # tolerance around the wall footprint, m
U_RES = 0.10               # raster along the wall, m
Z_RES = 0.10               # raster in height, m

STOREY_BAND_M = 2.60       # analysed height above a floor, m
CHECK_BAND_M = 0.40        # solidity band below a sill and above a head, m

WALL_FILL_MIN = 0.18       # share of the wall face that must be observed
LINTEL_FILL_MIN = 0.50
SILL_FILL_MIN = 0.50
FRAME_FILL_MIN = 0.40      # the wall must be solid on both sides of the gap

DOOR_MIN_WIDTH_M = 0.65
DOOR_MAX_WIDTH_M = 2.60
WINDOW_MIN_WIDTH_M = 0.40
WINDOW_MAX_WIDTH_M = 3.60
MIN_OPENING_HEIGHT_M = 1.50   # doors
MIN_WINDOW_HEIGHT_M = 0.50
END_MARGIN_M = 0.30           # gaps touching the wall ends are not openings

# Height bands are measured up from the candidate storey floor. The lower
# zone is searched for door/window gaps; the upper zone must contain observed
# wall points so an unscanned strip is not mistaken for an opening.
DOOR_ZONE = (0.0, 2.10)
LINTEL_ZONE = (2.10, 2.60)
SILL_ZONE = (0.0, 1.00)
OCCUPIED_FRACTION = 0.35


def _iter_positions(path):
    arr = np.load(path, mmap_mode="r")
    for start in range(0, arr.shape[0], CHUNK):
        yield np.asarray(arr[start : start + CHUNK])


def _wall_frames(geom: CloudGeometry, walls: list[DetectedElement]) -> list[dict[str, Any]]:
    origin = geom.origin
    frames: list[dict[str, Any]] = []
    for wall in sorted(walls, key=lambda e: -float(e.dimensions.get("length_m", 0.0))):
        g = wall.geometry
        if g.get("kind") != "oriented_box":
            continue
        sizes = g.get("sizes") or {}
        try:
            length = float(sizes["length"])
            thickness = float(sizes["thickness"])
            height = float(sizes["height"])
            cx = float(g["center"][0]) - float(origin[0])
            cy = float(g["center"][1]) - float(origin[1])
            cz = float(g["center"][2]) - float(origin[2])
            angle = float(g.get("rotation_z", 0.0))
        except (KeyError, TypeError, ValueError):
            continue
        if length <= 0 or thickness <= 0 or height <= 0:
            continue
        frames.append(
            {
                "wall": wall,
                "cx": cx,
                "cy": cy,
                "ca": math.cos(angle),
                "sa": math.sin(angle),
                "length": length,
                "thickness": thickness,
                "z0": cz - height / 2.0,
                "z1": cz + height / 2.0,
                "angle": angle,
            }
        )
    return frames


def _owner_map(frames: list[dict[str, Any]], local_min: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Assign coarse plan cells to walls (first long wall wins)."""
    owner = np.full(shape, -1, dtype=np.int32)
    nx, ny = shape[1], shape[0]
    for index, frame in enumerate(frames):
        half_l = frame["length"] / 2.0 + OWNER_PAD_M
        half_t = frame["thickness"] / 2.0 + OWNER_PAD_M
        ca, sa = frame["ca"], frame["sa"]
        corners = []
        for lu, lv in ((-half_l, -half_t), (half_l, -half_t), (half_l, half_t), (-half_l, half_t)):
            corners.append((frame["cx"] + lu * ca - lv * sa, frame["cy"] + lu * sa + lv * ca))
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        ix0 = max(0, int(math.floor((min(xs) - local_min[0]) / OWNER_RES)))
        ix1 = min(nx - 1, int(math.ceil((max(xs) - local_min[0]) / OWNER_RES)))
        iy0 = max(0, int(math.floor((min(ys) - local_min[1]) / OWNER_RES)))
        iy1 = min(ny - 1, int(math.ceil((max(ys) - local_min[1]) / OWNER_RES)))
        if ix1 < ix0 or iy1 < iy0:
            continue
        gx = local_min[0] + (np.arange(ix0, ix1 + 1) + 0.5) * OWNER_RES
        gy = local_min[1] + (np.arange(iy0, iy1 + 1) + 0.5) * OWNER_RES
        gxm, gym = np.meshgrid(gx, gy)
        du = (gxm - frame["cx"]) * ca + (gym - frame["cy"]) * sa
        dv = -(gxm - frame["cx"]) * sa + (gym - frame["cy"]) * ca
        inside = (np.abs(du) <= half_l) & (np.abs(dv) <= half_t)
        sub = owner[iy0 : iy1 + 1, ix0 : ix1 + 1]
        sub[inside & (sub < 0)] = index
    return owner


def _frame_rasters(geom: CloudGeometry, frames: list[dict[str, Any]]) -> None:
    local_min = geom.bbox_min - geom.origin
    local_max = geom.bbox_max - geom.origin
    nx = max(1, int(math.ceil((float(local_max[0] - local_min[0])) / OWNER_RES)) + 1)
    ny = max(1, int(math.ceil((float(local_max[1] - local_min[1])) / OWNER_RES)) + 1)
    owner = _owner_map(frames, local_min, (ny, nx))

    for frame in frames:
        frame["nu"] = max(2, int(math.ceil(frame["length"] / U_RES)) + 1)
        frame["nz"] = max(2, int(math.ceil((frame["z1"] - frame["z0"]) / Z_RES)) + 1)
        frame["counts"] = np.zeros(frame["nu"] * frame["nz"], dtype=np.int32)

    if not frames:
        return
    for chunk in _iter_positions(geom.positions_path):
        x = chunk[:, 0]
        y = chunk[:, 1]
        ix = np.floor((x - local_min[0]) / OWNER_RES).astype(np.int64)
        iy = np.floor((y - local_min[1]) / OWNER_RES).astype(np.int64)
        valid = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny)
        if not valid.any():
            continue
        own = owner[iy[valid], ix[valid]]
        keep = own >= 0
        if not keep.any():
            continue
        xs = x[valid][keep]
        ys = y[valid][keep]
        zs = chunk[:, 2][valid][keep]
        own = own[keep]
        order = np.argsort(own, kind="stable")
        own = own[order]
        xs, ys, zs = xs[order], ys[order], zs[order]
        bounds = np.nonzero(np.diff(own))[0] + 1
        starts = np.concatenate(([0], bounds))
        ends = np.concatenate((bounds, [len(own)]))
        for start, end in zip(starts, ends):
            frame = frames[int(own[start])]
            px = xs[start:end]
            py = ys[start:end]
            pz = zs[start:end]
            u = (px - frame["cx"]) * frame["ca"] + (py - frame["cy"]) * frame["sa"] + frame["length"] / 2.0
            v = -(px - frame["cx"]) * frame["sa"] + (py - frame["cy"]) * frame["ca"]
            band = frame["thickness"] / 2.0 + 0.20
            m = (
                (np.abs(v) <= band)
                & (u >= 0.0)
                & (u <= frame["length"])
                & (pz >= frame["z0"])
                & (pz < frame["z1"])
            )
            if not m.any():
                continue
            iu = np.floor(u[m] / U_RES).astype(np.int64)
            iz = np.floor((pz[m] - frame["z0"]) / Z_RES).astype(np.int64)
            ok = (iu >= 0) & (iu < frame["nu"]) & (iz >= 0) & (iz < frame["nz"])
            if not ok.any():
                continue
            flat = iz[ok] * frame["nu"] + iu[ok]
            frame["counts"] += np.bincount(flat, minlength=frame["nu"] * frame["nz"]).astype(np.int32)


def _fill(occ: np.ndarray) -> float:
    return float(occ.mean()) if occ.size else 0.0


def _floors_for(frame: dict[str, Any], levels: list[dict[str, Any]]) -> list[float]:
    floors = []
    for level in levels:
        z = level.get("z_local")
        if z is None:
            continue
        z = float(z)
        if frame["z0"] - 0.15 <= z <= frame["z1"] - 1.20:
            floors.append(z)
    if not floors:
        floors = [frame["z0"]]
    return sorted(set(round(z, 2) for z in floors))


def _opening_element(
    frame: dict[str, Any],
    u0: float,
    u1: float,
    z_bottom: float,
    z_top: float,
    floor_z: float,
    origin: np.ndarray,
    kind: str,
    wall_fill: float,
    lintel_fill: float,
    sill_fill: float,
) -> DetectedElement:
    width = max(0.05, u1 - u0)
    height = max(0.05, z_top - z_bottom)
    uc = (u0 + u1) / 2.0 - frame["length"] / 2.0
    ca, sa = frame["ca"], frame["sa"]
    cx = frame["cx"] + uc * ca
    cy = frame["cy"] + uc * sa
    zc = (z_bottom + z_top) / 2.0
    corners = []
    for lu, lv in (
        (-width / 2, -frame["thickness"] / 2),
        (width / 2, -frame["thickness"] / 2),
        (width / 2, frame["thickness"] / 2),
        (-width / 2, frame["thickness"] / 2),
    ):
        corners.append((cx + lu * ca - lv * sa, cy + lu * sa + lv * ca))
    xs = [c[0] + float(origin[0]) for c in corners]
    ys = [c[1] + float(origin[1]) for c in corners]
    confidence = 0.30 + 0.25 * min(1.0, wall_fill / 0.6) + 0.20 * lintel_fill + 0.10 * min(1.0, width)
    return DetectedElement(
        class_name="opening",
        geometry={
            "kind": "oriented_box",
            "center": [
                round(cx + float(origin[0]), 4),
                round(cy + float(origin[1]), 4),
                round(zc + float(origin[2]), 4),
            ],
            "sizes": {
                "length": round(width, 3),
                "thickness": round(frame["thickness"], 3),
                "height": round(height, 3),
            },
            "rotation_z": round(float(frame["angle"]), 5),
            "note": "void in a scanned wall between observed faces",
        },
        bbox={
            "min": [round(min(xs), 3), round(min(ys), 3), round(z_bottom + float(origin[2]), 3)],
            "max": [round(max(xs), 3), round(max(ys), 3), round(z_top + float(origin[2]), 3)],
        },
        confidence=round(float(max(0.2, min(0.85, confidence))), 3),
        measured=True,
        inferred=True,
        dimensions={
            "opening_kind": kind,
            "width_m": round(width, 3),
            "height_m": round(height, 3),
            "sill_m": round(max(0.0, z_bottom - floor_z), 3),
            "head_m": round(z_top - floor_z, 3),
            "storey_z": round(floor_z + float(origin[2]), 3),
        },
        metadata={
            "method": "wall-face-gap-v1",
            "host_wall_center": list(frame["wall"].geometry.get("center") or []),
            "host_wall_rotation_z": round(float(frame["angle"]), 5),
            "wall_fill": round(wall_fill, 3),
            "lintel_fill": round(lintel_fill, 3),
            "sill_fill": round(sill_fill, 3),
            "confidence_kind": "heuristic",
            "notes": "gap in the scanned wall face; a scan hole looks the same - verify",
        },
    )


def _empty_runs(occupied: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous runs of empty z-bins as [start, end)."""
    runs = []
    start = None
    for i, flag in enumerate(occupied):
        if not flag and start is None:
            start = i
        elif flag and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(occupied)))
    return runs


def _column_candidates(occupied: np.ndarray) -> list[tuple[str, float, float]]:
    """Door/window z-ranges visible in one u column of the wall face."""
    nz = len(occupied)
    candidates = []
    for start, end in _empty_runs(occupied):
        if end >= nz:
            # Empty up to the top of the analysed band: either the wall ends
            # here or the face was not scanned. Both are not openings.
            continue
        z_low = start * Z_RES
        z_high = end * Z_RES
        if start == 0 or z_low <= 0.30:
            if z_high >= MIN_OPENING_HEIGHT_M:
                candidates.append(("door", 0.0, z_high))
        elif 0.30 <= z_low <= 1.50 and z_high >= 1.50:
            candidates.append(("window", z_low, z_high))
    return candidates


def _gaps_in_wall(
    frame: dict[str, Any], floor_z: float
) -> list[tuple[str, float, float, float, float, float, float]]:
    counts = frame["counts"].reshape(frame["nz"], frame["nu"])
    nu = frame["nu"]
    z0 = frame["z0"]
    band_top = min(frame["z1"], floor_z + STOREY_BAND_M)
    iz_lo = max(0, int(math.floor((floor_z - z0) / Z_RES)))
    iz_hi = min(frame["nz"], int(math.ceil((band_top - z0) / Z_RES)))
    if iz_hi - iz_lo < 8:
        return []
    band = counts[iz_lo:iz_hi, :] > 0
    base_z = z0 + iz_lo * Z_RES

    u_margin_bins = max(1, int(round(END_MARGIN_M / U_RES)))
    inner = band[:, u_margin_bins : max(u_margin_bins + 1, nu - u_margin_bins)]
    wall_fill = _fill(inner)
    if wall_fill < WALL_FILL_MIN:
        return []

    groups: list[dict[str, Any]] = []
    for iu in range(nu):
        for kind, z_low, z_high in _column_candidates(band[:, iu]):
            match = None
            for group in groups:
                if group["last"] != iu - 1 or group["kind"] != kind:
                    continue
                if (
                    abs(group["z_low"][-1] - z_low) <= 0.15
                    and abs(group["z_high"][-1] - z_high) <= 0.15
                ):
                    match = group
                    break
            if match is None:
                groups.append(
                    {
                        "kind": kind,
                        "first": iu,
                        "last": iu,
                        "z_low": [z_low],
                        "z_high": [z_high],
                    }
                )
            else:
                match["last"] = iu
                match["z_low"].append(z_low)
                match["z_high"].append(z_high)

    check_bins = max(1, int(round(CHECK_BAND_M / Z_RES)))
    results = []
    for group in groups:
        a, b = int(group["first"]), int(group["last"]) + 1
        if a < u_margin_bins or b > nu - u_margin_bins:
            continue
        width = (b - a) * U_RES
        kind = str(group["kind"])
        z_bottom = base_z + float(np.median(group["z_low"]))
        z_top = base_z + float(np.median(group["z_high"]))
        if kind == "door":
            if width < DOOR_MIN_WIDTH_M or width > DOOR_MAX_WIDTH_M:
                continue
            if z_top - floor_z < MIN_OPENING_HEIGHT_M:
                continue
        else:
            if width < WINDOW_MIN_WIDTH_M or width > WINDOW_MAX_WIDTH_M:
                continue
            if z_top - z_bottom < MIN_WINDOW_HEIGHT_M:
                continue

        lo = max(0, int(round((z_bottom - z0) / Z_RES)) - iz_lo)
        hi = min(band.shape[0], int(round((z_top - z0) / Z_RES)) - iz_lo)
        if hi <= lo:
            continue
        left = band[lo:hi, a - 1]
        right = band[lo:hi, b]
        if _fill(left) < FRAME_FILL_MIN or _fill(right) < FRAME_FILL_MIN:
            continue
        lintel = band[hi : min(band.shape[0], hi + check_bins), a:b]
        lintel_fill = _fill(lintel)
        if lintel_fill < LINTEL_FILL_MIN:
            continue
        sill = band[max(0, lo - check_bins) : lo, a:b]
        sill_fill = _fill(sill)
        if kind == "window" and sill_fill < SILL_FILL_MIN:
            continue
        results.append(
            (kind, a * U_RES, b * U_RES, z_bottom, z_top, lintel_fill, sill_fill)
        )
    return results


def detect_openings(
    geom: CloudGeometry, walls: list[DetectedElement], levels: list[dict[str, Any]]
) -> list[DetectedElement]:
    """Detect door and window voids in the consolidated wall elements."""
    frames = _wall_frames(geom, walls)
    if not frames:
        return []
    _frame_rasters(geom, frames)
    origin = geom.origin
    elements: list[DetectedElement] = []
    for frame in frames:
        if frame["z1"] - frame["z0"] < 1.6:
            continue
        floors = _floors_for(frame, levels)
        for floor_z in floors:
            if floor_z > frame["z1"] - 1.0:
                continue
            counts = frame["counts"].reshape(frame["nz"], frame["nu"])
            band = counts[
                max(0, int(math.floor((floor_z - frame["z0"]) / Z_RES))) : min(
                    frame["nz"], int(math.ceil((min(frame["z1"], floor_z + STOREY_BAND_M) - frame["z0"]) / Z_RES))
                ),
                :,
            ]
            wall_fill = _fill(band > 0)
            found = _gaps_in_wall(frame, floor_z)
            for kind, u0, u1, zb, zt, lintel_fill, sill_fill in found:
                if kind == "door":
                    zb = floor_z
                elements.append(
                    _opening_element(
                        frame, u0, u1, zb, zt, floor_z, origin,
                        kind, wall_fill, lintel_fill, sill_fill,
                    )
                )
    return elements
