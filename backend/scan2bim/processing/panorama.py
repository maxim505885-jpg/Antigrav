"""Scan station panoramas: catalogue, real images, depth picking and measurement.

Everything here is derived from stored geometry. A panorama rendered from the
cloud is a *view of measured points*, not a scanner photograph: it is reported
as ``source="point_cloud"`` and never presented as a photo. A photograph is
only reported when the user supplied an equirectangular image, and then it is
reported as ``source="photo"`` together with its checksum.

Measurement is the part that must never be faked. A screen pixel is converted
to a direction, the direction is looked up in the depth panorama rendered from
the cloud, and the distance comes from that depth sample. Where the depth has
no point in that direction the answer is "not measured", never a guess.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

# Rendering bounds. A panorama is a preview artefact: 4096 x 2048 is the widest
# equirectangular sheet we keep, and we never project more than 8M points at
# once (a stride subsample is used above that, and the stride is reported).
MIN_PANO_WIDTH = 256
MAX_PANO_WIDTH = 4096
DEFAULT_PANO_WIDTH = 2048
DEFAULT_PANO_HEIGHT = 1024
MAX_RENDER_POINTS = 4_000_000
# Streaming renderer: rows read per block. 8M rows is ~200 MB of float64 and
# keeps peak memory far below the size of a 300M-point station.
STREAM_BLOCK_ROWS = 8_000_000
# Bumped whenever the rendered sheet or depth map changes meaning, so cached
# panoramas from an older renderer are not served as if they were current.
PANORAMA_RENDER_VERSION = "streaming-1"
MIN_RENDER_RANGE_M = 0.5
MAX_RENDER_RANGE_M = 500.0
DEFAULT_RENDER_RANGE_M = 60.0
# Points too close to the projection centre say nothing about direction.
MIN_POINT_DISTANCE_M = 0.02


def project_uv_to_ray(u: float, v: float) -> np.ndarray:
    """Map equirectangular UV coordinates [0..1] to a normalized 3D ray direction.

    u in [0, 1] -> azimuth phi in [-pi, pi]
    v in [0, 1] -> elevation theta in [-pi/2, pi/2]
    """
    if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        raise ValueError(f"UV coordinates must be in [0, 1], got u={u}, v={v}")

    phi = (u - 0.5) * 2.0 * math.pi
    theta = (0.5 - v) * math.pi

    x = math.cos(theta) * math.sin(phi)
    y = math.cos(theta) * math.cos(phi)
    z = math.sin(theta)

    ray = np.array([x, y, z], dtype=np.float64)
    norm = np.linalg.norm(ray)
    return ray / norm if norm > 0 else np.array([0.0, 1.0, 0.0])


def project_point_to_uv(point: np.ndarray, station_center: np.ndarray) -> tuple[float, float, float]:
    """Map 3D world point to equirectangular UV coordinates relative to station center.

    Returns (u, v, distance).
    """
    diff = np.asarray(point, dtype=np.float64) - np.asarray(station_center, dtype=np.float64)
    distance = float(np.linalg.norm(diff))
    if distance < 1e-6:
        return 0.5, 0.5, 0.0

    x, y, z = diff
    phi = math.atan2(x, y)  # in [-pi, pi]
    theta = math.asin(np.clip(z / distance, -1.0, 1.0))  # in [-pi/2, pi/2]

    u = (phi / (2.0 * math.pi)) + 0.5
    v = 0.5 - (theta / math.pi)
    return float(np.clip(u, 0.0, 1.0)), float(np.clip(v, 0.0, 1.0)), distance


def _project_batch(diff: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorised world-offset -> (u, v, distance) for N x 3 offsets."""
    dist = np.linalg.norm(diff, axis=1)
    safe = np.maximum(dist, 1e-9)
    phi = np.arctan2(diff[:, 0], diff[:, 1])
    theta = np.arcsin(np.clip(diff[:, 2] / safe, -1.0, 1.0))
    u = phi / (2.0 * np.pi) + 0.5
    v = 0.5 - theta / np.pi
    return u, v, dist


def generate_station_depth_panorama(
    points: np.ndarray,
    station_center: np.ndarray,
    width: int = 1024,
    height: int = 512,
    max_range_m: float = 50.0,
) -> np.ndarray:
    """Generate equirectangular depth map (height x width, float32) from 3D points.

    Pixels without points contain np.nan. The nearest point wins the pixel, so
    the map is a true z-buffer, not a nearest-neighbour smear.
    """
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError("points must be an N×3 array")
    if width <= 0 or height <= 0:
        raise ValueError("panorama width and height must be positive")

    diff = pts - np.asarray(station_center, dtype=np.float64)
    u, v, dist = _project_batch(diff)
    valid = (dist > MIN_POINT_DISTANCE_M) & (dist <= max_range_m) & np.isfinite(dist)
    if not valid.any():
        return np.full((height, width), np.nan, dtype=np.float32)

    u, v, dist = u[valid], v[valid], dist[valid]
    px = np.clip((u * width).astype(np.int64), 0, width - 1)
    py = np.clip((v * height).astype(np.int64), 0, height - 1)

    flat = py * width + px
    depth = np.full(width * height, np.inf, dtype=np.float64)
    # Sorting far-to-near lets the nearest sample write last, which keeps the
    # operation vectorised and deterministic (ties break by input order).
    order = np.argsort(dist)[::-1]
    depth[flat[order]] = dist[order]

    depth[depth == np.inf] = np.nan
    return depth.reshape(height, width).astype(np.float32)


def _height_ramp(z: np.ndarray, z_min: float, z_max: float) -> np.ndarray:
    """Dark blue -> teal -> amber ramp used when the cloud carries no colour."""
    span = max(z_max - z_min, 1e-9)
    t = np.clip((z - z_min) / span, 0.0, 1.0)
    stops = np.array(
        [
            [24, 32, 54],
            [30, 92, 133],
            [46, 158, 150],
            [214, 168, 82],
            [244, 226, 176],
        ],
        dtype=np.float64,
    )
    pos = np.linspace(0.0, 1.0, len(stops))
    out = np.empty((t.size, 3), dtype=np.float64)
    for channel in range(3):
        out[:, channel] = np.interp(t, pos, stops[:, channel])
    return np.clip(out, 0, 255).astype(np.uint8)


def render_cloud_panorama(
    points: np.ndarray,
    anchor: np.ndarray,
    width: int = DEFAULT_PANO_WIDTH,
    height: int = DEFAULT_PANO_HEIGHT,
    max_range_m: float = DEFAULT_RENDER_RANGE_M,
    colors: np.ndarray | None = None,
    background: tuple[int, int, int] = (10, 14, 20),
) -> dict[str, Any]:
    """Render an equirectangular RGB panorama from measured cloud points.

    Returns a dict with the RGB array (height x width x 3, uint8), the depth map
    (float32, nan where empty), coverage statistics and how many points were
    actually projected. Empty area is left at ``background`` colour; it is never
    filled with invented geometry.
    """
    if width < MIN_PANO_WIDTH or width > MAX_PANO_WIDTH or width % 2:
        raise ValueError(f"panorama width must be even and between {MIN_PANO_WIDTH} and {MAX_PANO_WIDTH}")
    if height < MIN_PANO_WIDTH // 2 or height > MAX_PANO_WIDTH // 2:
        raise ValueError("panorama height out of supported range")
    if not (MIN_RENDER_RANGE_M <= max_range_m <= MAX_RENDER_RANGE_M):
        raise ValueError(f"max_range_m must be between {MIN_RENDER_RANGE_M} and {MAX_RENDER_RANGE_M}")

    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] < 3 or len(pts) == 0:
        raise ValueError("points must be a non-empty N×3 array")
    pts = pts[:, :3]

    stride = int(math.ceil(len(pts) / MAX_RENDER_POINTS))
    if stride > 1:
        pts = pts[::stride]
        if colors is not None:
            colors = np.asarray(colors)[::stride]

    anchor = np.asarray(anchor, dtype=np.float64).reshape(3)
    diff = pts - anchor
    u, v, dist = _project_batch(diff)
    beyond_range = int(np.count_nonzero(dist > max_range_m))
    valid = (dist > MIN_POINT_DISTANCE_M) & (dist <= max_range_m) & np.isfinite(dist)
    u, v, dist = u[valid], v[valid], dist[valid]
    if colors is not None:
        colors = np.asarray(colors)
        if colors.shape[0] != valid.size:
            colors = None
        else:
            colors = colors[valid]

    px = np.clip((u * width).astype(np.int64), 0, width - 1)
    py = np.clip((v * height).astype(np.int64), 0, height - 1)
    flat = py * width + px

    depth = np.full(width * height, np.inf, dtype=np.float64)
    rgb = np.empty((width * height, 3), dtype=np.uint8)
    rgb[:] = background

    if dist.size:
        order = np.argsort(dist)[::-1]
        depth[flat[order]] = dist[order]
        if colors is not None:
            rgb[flat[order]] = np.clip(colors[order][:, :3], 0, 255).astype(np.uint8)
        else:
            z = pts[valid][:, 2]
            rgb[flat[order]] = _height_ramp(z, float(np.min(z)), float(np.max(z)))[order]

    filled = np.isfinite(depth)
    depth[~filled] = np.nan
    coverage = float(filled.sum()) / float(width * height)

    return {
        "rgb": rgb.reshape(height, width, 3),
        "depth": depth.reshape(height, width).astype(np.float32),
        "coverage": coverage,
        "rendered_points": int(dist.size),
        "source_points": int(len(pts)),
        "beyond_range_points": beyond_range,
        "stride": stride,
        "width": width,
        "height": height,
        "max_range_m": max_range_m,
        "color_source": "cloud_rgb" if colors is not None else "height_ramp",
    }


def _validate_panorama_geometry(width: int, height: int, max_range_m: float) -> None:
    if width < MIN_PANO_WIDTH or width > MAX_PANO_WIDTH or width % 2:
        raise ValueError(f"panorama width must be even and between {MIN_PANO_WIDTH} and {MAX_PANO_WIDTH}")
    if height < MIN_PANO_WIDTH // 2 or height > MAX_PANO_WIDTH // 2:
        raise ValueError("panorama height out of supported range")
    if not (MIN_RENDER_RANGE_M <= max_range_m <= MAX_RENDER_RANGE_M):
        raise ValueError(f"max_range_m must be between {MIN_RENDER_RANGE_M} and {MAX_RENDER_RANGE_M}")


def render_cloud_panorama_streaming(
    positions_path: Path,
    entry: Mapping[str, Any],
    width: int = DEFAULT_PANO_WIDTH,
    height: int = DEFAULT_PANO_HEIGHT,
    max_range_m: float = DEFAULT_RENDER_RANGE_M,
    colors_path: Path | None = None,
    block_rows: int = STREAM_BLOCK_ROWS,
    background: tuple[int, int, int] = (10, 14, 20),
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Render a panorama from *every* station point, reading the cloud in blocks.

    A 300M-point cloud cannot be projected in one array, and subsampling it to
    ``MAX_RENDER_POINTS`` leaves the sheet visibly sparse: at 2048 px only a
    quarter of the sphere received a sample. This renderer streams the station
    rows from the memory-mapped file and keeps only the nearest depth (and its
    colour) per pixel, so angular density is that of the whole cloud while peak
    memory stays bounded by one block plus the two pixel buffers.

    Empty directions stay at the background colour — no gap is filled with
    invented geometry — and ``coverage`` reports exactly how much was measured.
    """
    _validate_panorama_geometry(width, height, max_range_m)
    positions_path = Path(positions_path)
    if not positions_path.is_file():
        raise FileNotFoundError(f"positions file missing: {positions_path}")
    if block_rows <= 0:
        raise ValueError("block_rows must be positive")

    array = np.load(positions_path, mmap_mode="r")
    start = int(entry["row_start"])
    end = int(entry["row_end"])
    if not (0 <= start < end <= len(array)):
        raise ValueError(f"station rows {start}:{end} are outside the stored cloud of {len(array)} points")
    anchor = np.asarray(entry["anchor_local"], dtype=np.float64).reshape(-1)
    if anchor.shape != (3,):
        raise ValueError("station anchor must be a 3D point")
    if not np.isfinite(anchor).all():
        raise ValueError("station anchor contains non-finite coordinates")

    colors_array = None
    if colors_path is not None:
        candidate = Path(colors_path)
        if candidate.is_file():
            loaded = np.load(candidate, mmap_mode="r")
            if len(loaded) >= end:
                colors_array = loaded

    pixel_count = width * height
    depth = np.full(pixel_count, np.inf, dtype=np.float64)
    rgb = np.empty((pixel_count, 3), dtype=np.uint8)
    rgb[:] = background
    pixel_z = np.full(pixel_count, np.nan, dtype=np.float32) if colors_array is None else None

    examined = 0
    projected = 0
    blocks = 0
    beyond_range = 0
    block_min = np.full(pixel_count, np.inf, dtype=np.float64)
    total_blocks = max(1, math.ceil((end - start) / block_rows))
    for block_index, row_start in enumerate(range(start, end, block_rows)):
        if progress is not None:
            progress(
                block_index / total_blocks,
                f"Панорама: блок {block_index + 1}/{total_blocks}",
            )
        row_end = min(end, row_start + block_rows)
        block = np.asarray(array[row_start:row_end], dtype=np.float64)
        if block.ndim != 2 or block.shape[1] < 3:
            raise ValueError("positions.npy must contain an N x >=3 point array")
        block = block[:, :3]
        colors_block = None
        if colors_array is not None:
            colors_block = np.asarray(colors_array[row_start:row_end])
            if len(colors_block) != len(block):
                raise ValueError("colour rows do not align with the position rows of this block")

        finite = np.isfinite(block).all(axis=1)
        if not finite.all():
            block = block[finite]
            if colors_block is not None:
                colors_block = colors_block[finite]
        examined += int(len(block))
        if not len(block):
            blocks += 1
            continue

        u, v, dist = _project_batch(block - anchor)
        beyond_range += int(np.count_nonzero(dist > max_range_m))
        valid = (dist > MIN_POINT_DISTANCE_M) & (dist <= max_range_m) & np.isfinite(dist)
        if colors_block is not None:
            colors_block = np.clip(colors_block[valid][:, :3], 0, 255).astype(np.uint8)
        block = block[valid]
        u, v, dist = u[valid], v[valid], dist[valid]
        blocks += 1
        if not dist.size:
            continue
        projected += int(dist.size)

        px = np.clip((u * width).astype(np.int64), 0, width - 1)
        py = np.clip((v * height).astype(np.int64), 0, height - 1)
        flat = py * width + px
        # Exact nearest-sample z-buffer without sorting the block: the minimum
        # distance per pixel is accumulated with ``minimum.at`` (an order of
        # magnitude faster than an 8M-element argsort), then only the samples
        # that actually achieved that minimum are written to depth and colour.
        # A sample that is not its pixel's minimum inside the block cannot be
        # the global minimum either, because a closer in-block sample exists.
        block_min[:] = np.inf
        np.minimum.at(block_min, flat, dist)
        keep = dist == block_min[flat]
        if not keep.any():
            continue
        sel_flat = flat[keep]
        sel_dist = dist[keep]
        closer = sel_dist < depth[sel_flat]
        if not closer.any():
            continue
        targets = sel_flat[closer]
        depth[targets] = sel_dist[closer]
        if colors_block is not None:
            rgb[targets] = colors_block[keep][closer]
        else:
            pixel_z[targets] = block[keep][closer, 2]

    if progress is not None:
        progress(1.0, f"Панорама: обработано блоков {total_blocks}/{total_blocks}")

    filled = np.isfinite(depth)
    if colors_array is None:
        if filled.any():
            z_values = pixel_z[filled]
            ramp = _height_ramp(z_values, float(np.min(z_values)), float(np.max(z_values)))
            rgb[filled] = ramp
    color_source = "cloud_rgb" if colors_array is not None else "height_ramp"
    coverage = float(filled.sum()) / float(pixel_count)
    depth_out = depth.reshape(height, width).astype(np.float32)
    depth_out[~filled.reshape(height, width)] = np.nan

    return {
        "rgb": rgb.reshape(height, width, 3),
        "depth": depth_out,
        "coverage": coverage,
        "rendered_points": projected,
        "source_points": int(len(array)),
        "station_points": int(end - start),
        "points_examined": examined,
        "beyond_range_points": beyond_range,
        "blocks": blocks,
        "block_rows": block_rows,
        "stride": 1,
        "full_resolution": True,
        "width": width,
        "height": height,
        "max_range_m": max_range_m,
        "color_source": color_source,
    }


def angular_resolution_deg(width: int, height: int) -> tuple[float, float]:
    """Horizontal / vertical pixel size of an equirectangular sheet, in degrees."""
    if width <= 0 or height <= 0:
        raise ValueError("panorama size must be positive")
    return 360.0 / float(width), 180.0 / float(height)


def panorama_pick(
    depth: np.ndarray,
    anchor: np.ndarray,
    u: float,
    v: float,
    search_px: int = 2,
) -> dict[str, Any]:
    """Resolve one panorama pixel to a measured 3D point.

    The nearest finite depth sample inside a small search window is taken, so a
    single-pixel miss does not turn into "no data". If the window holds no
    points the result is unresolved and carries the reason — no distance is
    invented.
    """
    depth = np.asarray(depth, dtype=np.float32)
    if depth.ndim != 2:
        raise ValueError("depth must be a 2D array")
    if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        raise ValueError("UV coordinates must be in [0, 1]")
    height, width = depth.shape
    px = int(round(u * (width - 1)))
    py = int(round(v * (height - 1)))
    x0, x1 = max(0, px - search_px), min(width, px + search_px + 1)
    y0, y1 = max(0, py - search_px), min(height, py + search_px + 1)
    window = depth[y0:y1, x0:x1]

    if not np.isfinite(window).any():
        return {
            "resolved": False,
            "reason": "no points in this direction",
            "u": float(u),
            "v": float(v),
            "pixel": [int(px), int(py)],
        }

    finite_window = window[np.isfinite(window)].astype(np.float64)
    values = np.where(np.isfinite(window), window, np.inf)
    dy, dx = np.unravel_index(int(np.argmin(values)), values.shape)
    distance = float(values[dy, dx])
    sample_u = (x0 + dx + 0.5) / float(width)
    sample_v = (y0 + dy + 0.5) / float(height)
    ray = project_uv_to_ray(sample_u, sample_v)
    point = np.asarray(anchor, dtype=np.float64).reshape(3) + ray * distance

    horizontal_deg, vertical_deg = angular_resolution_deg(width, height)
    # Lateral precision of a depth sample grows with distance to the point.
    precision_m = distance * math.radians(max(horizontal_deg, vertical_deg))

    # A pixel that straddles a thin member or a surface edge has depth samples
    # on two different surfaces, and a measurement there depends on which one
    # the ray happens to hit: on a real workshop sheet that moved a distance by
    # metres between 2048 and 4096 px. A large *gap* between consecutive
    # depths says "two surfaces"; a large spread alone does not, because a
    # slanted plane also spans a wide range while staying continuous.
    spread_m = float(finite_window.max() - finite_window.min()) if finite_window.size else 0.0
    max_gap_m = 0.0
    if finite_window.size >= 3:
        max_gap_m = float(np.diff(np.sort(finite_window)).max())
    stability_tolerance = max(0.05, 3.0 * precision_m)
    stable = max_gap_m <= stability_tolerance
    return {
        "resolved": True,
        "u": float(sample_u),
        "v": float(sample_v),
        "pixel": [int(x0 + dx), int(y0 + dy)],
        "distance_m": distance,
        "point": [float(point[0]), float(point[1]), float(point[2])],
        "depth_source": "point_cloud",
        "angular_resolution_deg": [horizontal_deg, vertical_deg],
        "lateral_precision_m": precision_m,
        "stable": stable,
        "stability": "continuous_surface" if stable else "depth_discontinuity",
        "depth_spread_m": spread_m,
        "max_depth_gap_m": max_gap_m,
        "stability_tolerance_m": stability_tolerance,
    }


def measure_between(
    depth: np.ndarray,
    anchor: np.ndarray,
    first: tuple[float, float],
    second: tuple[float, float],
    search_px: int = 2,
) -> dict[str, Any]:
    """Measure the 3D distance between two panorama pixels of a depth map."""
    a = panorama_pick(depth, anchor, first[0], first[1], search_px=search_px)
    b = panorama_pick(depth, anchor, second[0], second[1], search_px=search_px)
    result: dict[str, Any] = {"a": a, "b": b, "resolved": False}
    if not (a["resolved"] and b["resolved"]):
        missing = [name for name, pick in (("a", a), ("b", b)) if not pick["resolved"]]
        result["reason"] = "no depth data at " + ", ".join(missing)
        return result

    point_a = np.asarray(a["point"], dtype=np.float64)
    point_b = np.asarray(b["point"], dtype=np.float64)
    distance = float(np.linalg.norm(point_b - point_a))
    precision = math.hypot(a["lateral_precision_m"], b["lateral_precision_m"])
    unstable = [name for name, pick in (("a", a), ("b", b)) if not pick.get("stable", True)]
    result.update(
        {
            "resolved": True,
            "distance_m": distance,
            "distance_mm": distance * 1000.0,
            "precision_mm": precision * 1000.0,
            "depth_source": "point_cloud",
            "reliable": not unstable,
        }
    )
    if unstable:
        # The distance is still the distance between two measured points, but a
        # point on a depth discontinuity is not a stable place to measure from,
        # so the caller is told instead of being handed a bare number.
        result["unstable_endpoints"] = unstable
        result["warning"] = (
            "Точка " + ", ".join(unstable) + " стоит на разрыве глубин (тонкая "
            "конструкция или край поверхности). Замер действителен, но при "
            "сдвиге пикселя на один он может измениться: выберите ровный участок."
        )
    return result


def _station_anchor(points: np.ndarray, chunk: int = 1_000_000) -> np.ndarray:
    """Median-free centroid of a station's own points, computed in chunks.

    It is a measured point of the station footprint, not the scanner's optical
    centre (that is not stored by the readers), and the API says so.
    """
    total = 0
    acc = np.zeros(3, dtype=np.float64)
    for start in range(0, len(points), chunk):
        block = np.asarray(points[start:start + chunk], dtype=np.float64)[:, :3]
        if not np.isfinite(block).all():
            block = block[np.isfinite(block).all(axis=1)]
            if not block.size:
                continue
        acc += block.sum(axis=0)
        total += len(block)
    if not total:
        raise ValueError("station has no finite points to anchor a panorama on")
    return acc / float(total)


def station_catalog(
    positions_path: Path,
    metadata: Mapping[str, Any] | None = None,
    max_anchor_points: int = 2_000_000,
) -> list[dict[str, Any]]:
    """List the scan stations a cloud actually contains.

    Stations come from ``station_row_ranges`` written by the multi-station
    readers. A cloud imported as one station yields a single entry covering all
    points, marked ``station_source="cloud"`` so nobody mistakes it for a
    recovered scanner station.
    """
    positions_path = Path(positions_path)
    if not positions_path.is_file():
        raise FileNotFoundError(f"positions file missing: {positions_path}")
    array = np.load(positions_path, mmap_mode="r")
    total = int(len(array))
    if total == 0:
        return []

    metadata = metadata or {}
    raw_ranges = metadata.get("station_row_ranges")
    entries: list[dict[str, Any]] = []

    if isinstance(raw_ranges, list) and raw_ranges:
        for index, row in enumerate(raw_ranges):
            if not isinstance(row, Mapping):
                raise ValueError("station row ranges must be objects")
            station_id = str(row.get("station_id") or f"station_{index + 1}")
            start = int(row.get("source_row_start", 0))
            end = int(row.get("source_row_end_exclusive", 0))
            if start < 0 or end > total or end <= start:
                raise ValueError(f"station {station_id} row range {start}:{end} is outside the stored cloud")
            entries.append(
                {
                    "station_id": station_id,
                    "name": station_id,
                    "row_start": start,
                    "row_end": end,
                    "point_count": end - start,
                    "station_source": "station_row_ranges",
                }
            )
    else:
        entries.append(
            {
                "station_id": "cloud",
                "name": "Единое облако",
                "row_start": 0,
                "row_end": total,
                "point_count": total,
                "station_source": "cloud",
            }
        )

    origin = np.asarray(metadata.get("origin") or [0.0, 0.0, 0.0], dtype=np.float64).reshape(3)
    for entry in entries:
        start, end = entry["row_start"], entry["row_end"]
        step = max(1, (end - start) // max_anchor_points + 1)
        block = np.asarray(array[start:end:step], dtype=np.float64)
        anchor = _station_anchor(block)
        finite = block[np.isfinite(block).all(axis=1)]
        local_min = finite.min(axis=0) if len(finite) else np.zeros(3)
        local_max = finite.max(axis=0) if len(finite) else np.zeros(3)
        entry["anchor_local"] = [float(v) for v in anchor]
        entry["anchor"] = [float(v) for v in anchor + origin]
        entry["anchor_kind"] = "point_centroid"
        entry["bbox_min"] = [float(v) for v in local_min + origin]
        entry["bbox_max"] = [float(v) for v in local_max + origin]
        entry["sampled_rows"] = int(len(block))
    return entries


def find_station(entries: list[dict[str, Any]], station_id: str) -> dict[str, Any]:
    for entry in entries:
        if entry["station_id"] == station_id:
            return entry
    raise KeyError(station_id)


def station_points(
    positions_path: Path,
    entry: Mapping[str, Any],
    max_points: int = MAX_RENDER_POINTS,
) -> tuple[np.ndarray, int]:
    """Load a station slice (strided above ``max_points``) as float64.

    The stride is returned so callers can slice aligned arrays (colours) with
    exactly the same rows and never silently misalign colour and position.
    """
    array = np.load(Path(positions_path), mmap_mode="r")
    start = int(entry["row_start"])
    end = int(entry["row_end"])
    count = max(end - start, 1)
    step = max(1, int(math.ceil(count / max_points)))
    block = np.asarray(array[start:end:step], dtype=np.float64)
    return block[:, :3], step


def image_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_panorama_meta(path: Path, payload: Mapping[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
