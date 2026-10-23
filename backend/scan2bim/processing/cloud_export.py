"""Export a stored point cloud to interchange formats (E57, LAS/LAZ, PLY, XYZ).

Every export is *verified*: the written file is read back with SCAN's own
readers and the coordinates are compared to the source within a per-format
tolerance. The result reports the measured maximum deviation instead of a
claim, so a file that silently loses precision cannot pass as an export.

The source ``positions.npy`` is opened read-only and never rewritten; the
export is written to a fresh directory like every other derived artefact.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..formats.readers import read_cloud

Progress = Callable[[float, str], None] | None

EXPORT_FORMATS = ("e57", "las", "laz", "ply", "xyz")

# Measured maximum coordinate deviation tolerated when the export is read
# back with SCAN's own readers, in metres.
TOLERANCE_M = {
    "e57": 1e-9,   # float64 cartesian storage
    "las": 1e-5,   # int32 storage with 1e-6 scale/offset
    "laz": 1e-5,
    "ply": 1e-5,   # float32 storage
    "xyz": 1e-3,   # text with 4 decimal places
}

CHUNK = 1_000_000


class CloudExportError(ValueError):
    """The export cannot be performed with the requested parameters."""


def _notify(progress: Progress, value: float, message: str) -> None:
    if progress:
        progress(float(value), message)


def _load(positions_path: Path, colors_path: Path | None, intensity_path: Path | None):
    positions = np.load(positions_path, mmap_mode="r")
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise CloudExportError("cloud positions must have shape (N, 3)")
    n = int(positions.shape[0])
    colors = np.load(colors_path, mmap_mode="r") if colors_path and colors_path.is_file() else None
    if colors is not None and len(colors) != n:
        colors = None
    intensity = (
        np.load(intensity_path, mmap_mode="r")
        if intensity_path and intensity_path.is_file()
        else None
    )
    if intensity is not None and len(intensity) != n:
        intensity = None
    finite = np.isfinite(np.asarray(positions[: min(n, 1000)])).all()
    if not finite:
        mask = np.isfinite(positions).all(axis=1)
        positions = np.asarray(positions[mask])
        if colors is not None:
            colors = np.asarray(colors)[mask]
        if intensity is not None:
            intensity = np.asarray(intensity)[mask]
    return positions, colors, intensity


def write_las(
    positions: np.ndarray,
    out_path: Path,
    *,
    colors: np.ndarray | None = None,
    intensity: np.ndarray | None = None,
    compress: bool = False,
) -> Path:
    """Write LAS/LAZ (point format 3, 1e-6 m scale, min-corner offset)."""
    try:
        import laspy
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise CloudExportError("laspy is not installed; install it to export LAS/LAZ") from exc

    points = np.asarray(positions, dtype=np.float64)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = np.array([1e-6, 1e-6, 1e-6])
    header.offsets = points.min(axis=0) if len(points) else np.zeros(3)
    las = laspy.LasData(header)
    las.x = points[:, 0]
    las.y = points[:, 1]
    las.z = points[:, 2]
    if colors is not None and len(colors) == len(points):
        rgb = np.asarray(colors)
        if rgb.dtype != np.uint8:
            if rgb.max() <= 1.0:
                rgb = rgb * 255.0
            rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        # LAS stores 16-bit colour; 8-bit values are expanded to the full range.
        las.red = rgb[:, 0].astype(np.uint16) * 257
        las.green = rgb[:, 1].astype(np.uint16) * 257
        las.blue = rgb[:, 2].astype(np.uint16) * 257
    if intensity is not None and len(intensity) == len(points):
        las.intensity = np.clip(np.asarray(intensity, dtype=np.float64), 0, 65535).astype(np.uint16)
    las.write(str(out_path), do_compress=compress)
    return out_path


def write_e57(
    positions: np.ndarray,
    out_path: Path,
    *,
    colors: np.ndarray | None = None,
    intensity: np.ndarray | None = None,
) -> Path:
    """Write a single-scan E57 with float64 cartesian coordinates."""
    try:
        import pye57
    except ImportError as exc:  # pragma: no cover
        raise CloudExportError("pye57 is not installed; install it to export E57") from exc

    points = np.asarray(positions, dtype=np.float64)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "cartesianX": points[:, 0],
        "cartesianY": points[:, 1],
        "cartesianZ": points[:, 2],
    }
    if colors is not None and len(colors) == len(points):
        rgb = np.asarray(colors)
        if rgb.dtype != np.uint8:
            if rgb.max() <= 1.0:
                rgb = rgb * 255.0
            rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        data["colorRed"] = rgb[:, 0].astype(np.float64)
        data["colorGreen"] = rgb[:, 1].astype(np.float64)
        data["colorBlue"] = rgb[:, 2].astype(np.float64)
    if intensity is not None and len(intensity) == len(points):
        data["intensity"] = np.asarray(intensity, dtype=np.float64)
    e57 = pye57.E57(str(out_path), mode="w")
    try:
        e57.write_scan_raw(data)
    finally:
        e57.close()
    return out_path


def export_cloud(
    positions_path: Path,
    out_path: Path,
    fmt: str,
    *,
    colors_path: Path | None = None,
    intensity_path: Path | None = None,
    progress: Progress = None,
    verify: bool = True,
) -> dict[str, Any]:
    """Export a stored cloud to ``fmt`` and verify the written file.

    Returns a meta dict with point counts, file size and the *measured*
    maximum coordinate deviation of a read-back of the written file.
    """
    fmt = str(fmt).lower()
    if fmt not in EXPORT_FORMATS:
        raise CloudExportError(f"unknown export format: {fmt}")
    started = time.perf_counter()
    _notify(progress, 0.05, "чтение облака")
    positions, colors, intensity = _load(positions_path, colors_path, intensity_path)
    count = int(len(positions))

    _notify(progress, 0.3, f"запись {fmt.upper()}")
    if fmt == "ply":
        from .cleanup import write_ply

        write_ply(positions, colors, out_path)
    elif fmt == "xyz":
        from .cleanup import write_xyz

        write_xyz(positions, out_path)
    elif fmt in ("las", "laz"):
        write_las(positions, out_path, colors=colors, intensity=intensity, compress=(fmt == "laz"))
    else:
        write_e57(positions, out_path, colors=colors, intensity=intensity)

    meta: dict[str, Any] = {
        "format": fmt,
        "point_count": count,
        "has_color": colors is not None,
        "has_intensity": intensity is not None,
        "size_bytes": out_path.stat().st_size,
        "verified": False,
    }
    if not verify:
        meta["elapsed_s"] = round(time.perf_counter() - started, 3)
        return meta

    _notify(progress, 0.8, "проверка записанного файла")
    try:
        back = read_cloud(out_path, max_points=0)
    except Exception as exc:
        raise CloudExportError(f"exported {fmt} file cannot be read back: {exc}") from exc
    if len(back.xyz) != count:
        raise CloudExportError(
            f"exported {fmt} file has {len(back.xyz)} points, expected {count}"
        )
    if count:
        src = np.asarray(positions, dtype=np.float64)
        deviation = float(np.abs(back.xyz - src).max())
    else:
        deviation = 0.0
    tolerance = TOLERANCE_M[fmt]
    meta.update(
        {
            "verified": True,
            "max_deviation_m": deviation,
            "tolerance_m": tolerance,
            "read_back_has_color": back.rgb is not None,
        }
    )
    if deviation > tolerance:
        raise CloudExportError(
            f"exported {fmt} file lost precision: max deviation "
            f"{deviation:.2e} m exceeds tolerance {tolerance:.0e} m"
        )
    _notify(progress, 1.0, "экспорт проверен")
    meta["elapsed_s"] = round(time.perf_counter() - started, 3)
    return meta
