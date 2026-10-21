"""Point-cloud readers.

Supported natively: E57, LAS, LAZ, PLY, PCD, PTS, XYZ/TXT/CSV (whitespace).
RCS/RCP are Autodesk proprietary containers: they are detected and routed to a
documented conversion path, never parsed in-process. The original file is only
ever opened read-only.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np

from ..config import MAX_INGEST_POINTS

Progress = Callable[[float, str], None] | None

TEXT_FORMATS = {"pts", "xyz", "txt", "csv"}
NATIVE_FORMATS = {"e57", "las", "laz", "ply", "pcd"} | TEXT_FORMATS


class FormatError(RuntimeError):
    """The file looks like a supported format but could not be decoded."""


class UnsupportedFormat(FormatError):
    """Format is not supported (yet)."""


class RcsConversionRequired(UnsupportedFormat):
    """Autodesk RCS/RCP requires an explicit, licensed conversion step."""

    def __init__(self, path: Path, message: str = ""):
        self.path = str(path)
        self.guidance = rcs_guidance(path)
        super().__init__(message or self.guidance["summary"])


@dataclass
class RawCloud:
    xyz: np.ndarray
    rgb: np.ndarray | None = None
    intensity: np.ndarray | None = None
    classification: np.ndarray | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.xyz = np.asarray(self.xyz, dtype=np.float64)
        if self.xyz.ndim != 2 or self.xyz.shape[1] != 3:
            raise FormatError(f"reader returned invalid xyz shape {self.xyz.shape}")
        finite = np.isfinite(self.xyz).all(axis=1)
        if not finite.all():
            self.xyz = self.xyz[finite]
            if self.rgb is not None:
                self.rgb = np.asarray(self.rgb)[finite]
            if self.intensity is not None:
                self.intensity = np.asarray(self.intensity)[finite]
            if self.classification is not None:
                self.classification = np.asarray(self.classification)[finite]
            self.metadata["dropped_non_finite"] = int((~finite).sum())
        if self.rgb is not None:
            self.rgb = normalize_rgb(self.rgb)
            self.metadata.setdefault("has_color", True)
        if self.intensity is not None:
            self.intensity = np.asarray(self.intensity, dtype=np.float32)
            self.metadata.setdefault("has_intensity", True)


def normalize_rgb(rgb: np.ndarray) -> np.ndarray:
    arr = np.asarray(rgb)
    if arr.ndim != 2 or arr.shape[1] < 3:
        raise FormatError("color array must be N x 3")
    arr = arr[:, :3]
    if arr.dtype.kind == "f":
        # E57 and some PLY files store normalized float colors.
        if arr.size and float(np.nanmax(arr)) <= 1.0:
            arr = arr * 255.0
        arr = np.clip(np.nan_to_num(arr), 0, 255)
    return arr.astype(np.uint8)


def detect_format(path: str | Path) -> str:
    p = Path(path)
    ext = p.suffix.lower().lstrip(".")
    if ext in {"rcs", "rcp"}:
        return ext
    if p.is_dir():
        raise UnsupportedFormat(f"{p} is a directory, not a point cloud file")
    if not p.exists():
        raise FormatError(f"file does not exist: {p}")
    if ext in NATIVE_FORMATS:
        return ext
    # Fall back to magic bytes for common containers with unusual extensions.
    with p.open("rb") as fh:
        head = fh.read(256)
    if head.startswith(b"ply"):
        return "ply"
    if head.startswith(b"LASF"):
        return "las"
    if head.startswith(b"E57"):
        return "e57"
    if head.startswith(b"# .PCD"):
        return "pcd"
    raise UnsupportedFormat(
        f"unsupported extension '.{ext}'. Supported: E57, LAS, LAZ, PLY, PCD, PTS, XYZ. "
        "RCS/RCP require conversion (see docs/FORMATS_RCS.md)."
    )


def supported_formats() -> dict[str, Any]:
    return {
        "native": sorted(NATIVE_FORMATS),
        "proprietary_conversion_required": ["rcs", "rcp"],
        "notes": {
            "e57": "pye57; all scans in the file are merged in world coordinates",
            "las/laz": "laspy + lazrs",
            "ply": "plyfile; vertex x/y/z and red/green/blue",
            "pcd": "ascii and binary x/y/z[/rgb]",
            "pts": "x y z [intensity r g b]",
            "xyz/txt/csv": "x y z [r g b]",
        },
    }


def rcs_guidance(path: str | Path) -> dict[str, Any]:
    from ..config import RCS_CONVERTER_CMD, RECAP_EXE

    native = {"dll_exists": False}
    try:
        from .rcs_native import native_available

        native = native_available()
    except Exception:  # pragma: no cover - defensive
        pass

    return {
        "summary": (
            "Autodesk RCS/RCP — закрытый (proprietary) формат. Приложение не реализует его "
            "кодек. На машине с установленным Autodesk ReCap точки читаются через локальную "
            "библиотеку Autodesk AdskRcExport.dll в отдельном процессе (только чтение; "
            "исходный файл никогда не изменяется). Без ReCap конвертируйте файл один раз "
            "в E57 (рекомендуется) или LAS лицензированным инструментом Autodesk."
        ),
        "file": str(path),
        "native_reader_available": bool(native.get("dll_exists")),
        "native_reader": native,
        "recap_installed": RECAP_EXE.exists(),
        "recap_path": str(RECAP_EXE),
        "converter_configured": bool(RCS_CONVERTER_CMD),
        "steps": [
            "Если ReCap установлен: импортируйте .rcs/.rcp напрямую — точки читает локальная библиотека ReCap.",
            "Если ReCap нет: откройте проект .rcp в ReCap и экспортируйте в E57 (или LAS) в полном разрешении.",
            "Импортируйте полученный .e57/.las в это приложение.",
            "Либо задайте S2B_RCS_CONVERTER с разрешённой командой конвертации и повторите импорт.",
        ],
        "command_template": "S2B_RCS_CONVERTER='tool --in {input} --out {output}'",
        "warning": (
            "Интерфейс DLL — недокументированный внутренний API Autodesk. Формулировка "
            "должна быть «читается через установленный Autodesk ReCap», а не «нативная поддержка RCS»."
        ),
    }


def read_cloud(path: str | Path, max_points: int | None = None, progress: Progress = None) -> RawCloud:
    p = Path(path)
    if not p.exists():
        raise FormatError(f"file does not exist: {p}")
    limit = MAX_INGEST_POINTS if max_points is None else max_points
    fmt = detect_format(p)

    if fmt in {"rcs", "rcp"}:
        # 1) Native local reader: the ReCap DLL, isolated in a subprocess.
        #    Verified working on a real 7.2 GB ADOCT v3 .rcs (297M points).
        #    Never claim this without the smoke test passing.
        from .rcs import convert_rcs
        from .rcs_native import native_available, read_rcs_native

        if native_available()["dll_exists"]:
            try:
                return read_rcs_native(p, limit, progress=progress)
            except Exception as exc:  # fall through to the documented path
                if progress:
                    progress(0.01, f"native RCS reader unavailable ({exc}); using converter path")

        # 2) Documented, licensed conversion command (if the user configured one).
        converted = convert_rcs(p, progress=progress)
        if converted is None:
            raise RcsConversionRequired(p)
        return read_cloud(converted, max_points=limit, progress=progress)

    if progress:
        progress(0.02, f"чтение файла {fmt.upper()}")
    if fmt == "e57":
        return read_e57(p, limit, progress)
    if fmt in {"las", "laz"}:
        return read_las(p, limit, progress)
    if fmt == "ply":
        return read_ply(p, limit, progress)
    if fmt == "pcd":
        return read_pcd(p, limit, progress)
    if fmt in TEXT_FORMATS:
        return read_text(p, fmt, limit, progress)
    raise UnsupportedFormat(f"no reader for .{fmt}")


def _sample_mask(n: int, max_points: int, rng: np.random.Generator) -> np.ndarray | None:
    if max_points <= 0 or n <= max_points:
        return None
    return rng.random(n) < (max_points / float(n))


def _decimate_arrays(
    xyz: np.ndarray,
    rgb: np.ndarray | None,
    intensity: np.ndarray | None,
    classification: np.ndarray | None,
    max_points: int,
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None, np.ndarray | None, bool]:
    n = len(xyz)
    if max_points <= 0 or n <= max_points:
        return xyz, rgb, intensity, classification, False
    idx = np.random.default_rng(20240517).choice(n, size=max_points, replace=False)
    idx.sort()
    return (
        xyz[idx],
        rgb[idx] if rgb is not None else None,
        intensity[idx] if intensity is not None else None,
        classification[idx] if classification is not None else None,
        True,
    )


def _first(data: dict, *names: str) -> np.ndarray | None:
    """First present field among aliases (pye57 mixes E57 and short names)."""
    for name in names:
        value = data.get(name)
        if value is not None and len(value):
            return np.asarray(value)
    return None


def iter_e57_chunks(
    path: str | Path,
    chunk_points: int = 1_000_000,
    progress: Progress = None,
) -> Iterator[tuple[np.ndarray, np.ndarray | None, np.ndarray | None]]:
    """Yield bounded E57 point chunks transformed into the source-world frame.

    The pye57 high-level ``read_scan`` allocates an array for an entire scan.
    Its lower-level compressed-vector reader accepts fixed-capacity NumPy
    buffers, so this iterator keeps point memory proportional to
    ``chunk_points``. Current pye57/libE57Format builds can read sequential
    chunks but may not implement ``CompressedVectorReader.seek``; callers that
    resume a checkpoint must replay the committed prefix from the start.
    """
    if chunk_points <= 0:
        raise ValueError("chunk_points must be a positive integer")
    try:
        import pye57
        from pye57.e57 import COORDINATE_SYSTEMS
        from pye57.utils import convert_spherical_to_cartesian
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise UnsupportedFormat("pye57 is not installed; install it to read E57 files") from exc

    try:
        e57 = pye57.E57(str(path))
    except Exception as exc:
        raise FormatError(f"cannot open E57 file: {exc}") from exc

    try:
        scan_count = int(e57.scan_count)
        headers = [e57.get_header(index) for index in range(scan_count)]
        total_points = sum(int(header.point_count) for header in headers)
        points_read = 0
        for scan_index, header in enumerate(headers):
            try:
                coordinate_system = header.get_coordinate_system(COORDINATE_SYSTEMS)
                coordinate_fields = list(coordinate_system.value)
            except Exception as exc:
                raise FormatError(f"E57 scan {scan_index} has unsupported coordinates: {exc}") from exc

            valid_field = (
                "cartesianInvalidState"
                if coordinate_system is COORDINATE_SYSTEMS.CARTESIAN
                else "sphericalInvalidState"
            )
            fields = coordinate_fields.copy()
            if "intensity" in header.point_fields:
                fields.append("intensity")
            color_fields = ("colorRed", "colorGreen", "colorBlue")
            has_color = all(name in header.point_fields for name in color_fields)
            if has_color:
                fields.extend(color_fields)
            if valid_field in header.point_fields:
                fields.append(valid_field)

            arrays, buffers = e57.make_buffers(fields, chunk_points)
            reader = header.node["points"].reader(buffers)
            scan_read = 0
            try:
                while True:
                    count = int(reader.read(buffers))
                    if count <= 0:
                        break
                    if coordinate_system is COORDINATE_SYSTEMS.CARTESIAN:
                        xyz = np.column_stack(
                            [arrays["cartesianX"][:count], arrays["cartesianY"][:count], arrays["cartesianZ"][:count]]
                        ).astype(np.float64, copy=False)
                    else:
                        spherical = np.column_stack(
                            [arrays["sphericalRange"][:count], arrays["sphericalAzimuth"][:count], arrays["sphericalElevation"][:count]]
                        )
                        xyz = convert_spherical_to_cartesian(spherical)
                    if header.has_pose():
                        xyz = e57.to_global(xyz, header.rotation, header.translation)

                    keep = np.isfinite(xyz).all(axis=1)
                    if valid_field in arrays:
                        keep &= ~arrays[valid_field][:count].astype(bool)
                    xyz = xyz[keep]
                    rgb = None
                    if has_color:
                        colors = np.column_stack([arrays[name][:count] for name in color_fields])
                        rgb = normalize_rgb(colors[keep])
                    intensity = None
                    if "intensity" in arrays:
                        intensity = np.asarray(arrays["intensity"][:count][keep], dtype=np.float32)

                    scan_read += count
                    points_read += count
                    if progress:
                        progress(
                            0.05 + 0.85 * min(1.0, points_read / max(1, total_points)),
                            f"чтение E57 блоками: скан {scan_index + 1}/{scan_count}, {scan_read:,}/{header.point_count:,}",
                        )
                    if len(xyz):
                        yield xyz, rgb, intensity
            except Exception as exc:
                if isinstance(exc, (FormatError, UnsupportedFormat)):
                    raise
                raise FormatError(f"E57 scan {scan_index} could not be streamed: {exc}") from exc
            finally:
                reader.close()
    finally:
        try:
            e57.close()
        except Exception:
            pass


def e57_stream_info(path: str | Path) -> dict[str, Any]:
    """Read small E57 headers only, without materializing scan point arrays."""
    try:
        import pye57
        from pye57.e57 import COORDINATE_SYSTEMS
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise UnsupportedFormat("pye57 is not installed; install it to read E57 files") from exc
    try:
        e57 = pye57.E57(str(path))
    except Exception as exc:
        raise FormatError(f"cannot open E57 file: {exc}") from exc
    try:
        scans = []
        for index in range(int(e57.scan_count)):
            header = e57.get_header(index)
            try:
                coordinate_system = header.get_coordinate_system(COORDINATE_SYSTEMS).name.lower()
            except Exception as exc:
                raise FormatError(f"E57 scan {index} has unsupported coordinates: {exc}") from exc
            scans.append(
                {
                    "index": index,
                    "point_count": int(header.point_count),
                    "guid": str(getattr(header, "guid", "") or ""),
                    "name": str(getattr(header, "name", "") or ""),
                    "coordinate_system": coordinate_system,
                    "has_color": all(
                        name in header.point_fields for name in ("colorRed", "colorGreen", "colorBlue")
                    ),
                    "has_intensity": "intensity" in header.point_fields,
                }
            )
        if not scans:
            raise FormatError("E57 file contains no readable scans")
        return {
            "reader": "pye57",
            "scan_count": len(scans),
            "source_point_count": sum(scan["point_count"] for scan in scans),
            "scans": scans,
            "has_color": all(scan["has_color"] for scan in scans),
            "has_intensity": all(scan["has_intensity"] for scan in scans),
        }
    finally:
        try:
            e57.close()
        except Exception:
            pass


def read_e57(path: Path, max_points: int, progress: Progress = None) -> RawCloud:
    try:
        import pye57
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise UnsupportedFormat("pye57 is not installed; install it to read E57 files") from exc

    try:
        e57 = pye57.E57(str(path))
    except Exception as exc:
        raise FormatError(f"cannot open E57 file: {exc}") from exc

    try:
        scan_count = int(e57.scan_count)
        headers = []
        total = 0
        for i in range(scan_count):
            header = e57.get_header(i)
            n = int(getattr(header, "point_count", 0) or 0)
            headers.append((header, n))
            total += n
        probability = 1.0 if max_points <= 0 or total <= max_points else max_points / total
        rng = np.random.default_rng(20240517)

        xyz_parts: list[np.ndarray] = []
        rgb_parts: list[np.ndarray] = []
        keep_kinds = 0
        for i, (header, n) in enumerate(headers):
            if progress:
                progress(0.05 + 0.8 * (i / max(1, scan_count)), f"чтение скана E57 {i + 1}/{scan_count}")
            try:
                data = e57.read_scan(
                    i,
                    intensity=True,
                    colors=True,
                    transform=True,
                    ignore_missing_fields=True,
                )
            except Exception as exc:
                raise FormatError(f"E57 scan {i} could not be decoded: {exc}") from exc
            # pye57 exposes E57 record names, so a Cartesian scan comes back as
            # cartesianX/Y/Z (colour as colorRed/Green/Blue). Accept both
            # spellings: requiring only "x" made every real E57 look empty.
            cx = _first(data, "x", "cartesianX")
            cy = _first(data, "y", "cartesianY")
            cz = _first(data, "z", "cartesianZ")
            if cx is None or cy is None or cz is None:
                raise FormatError(
                    f"E57 scan {i} has no Cartesian coordinates; fields present: "
                    f"{sorted(k for k in (data or {}) if isinstance(k, str))}"
                )
            xyz = np.column_stack([cx, cy, cz]).astype(np.float64, copy=False)
            if probability < 1.0 and len(xyz):
                mask = rng.random(len(xyz)) < probability
                xyz = xyz[mask]
            else:
                mask = None
            colors = None
            cr = _first(data, "red", "colorRed")
            cg = _first(data, "green", "colorGreen")
            cb = _first(data, "blue", "colorBlue")
            if cr is not None and cg is not None and cb is not None:
                colors = np.column_stack([cr, cg, cb])
                if mask is not None:
                    colors = colors[mask]
                keep_kinds |= 1
            xyz_parts.append(xyz)
            if colors is not None:
                rgb_parts.append(normalize_rgb(colors))
        if not xyz_parts:
            raise FormatError("E57 file contains no readable scans")
        xyz = np.concatenate(xyz_parts, axis=0)
        rgb = np.concatenate(rgb_parts, axis=0) if rgb_parts and len(rgb_parts) == len(xyz_parts) else None
        decimated = bool(probability < 1.0 and total > max_points)
        meta = {
            "reader": "pye57",
            "scan_count": scan_count,
            "source_point_count": int(total if total else len(xyz)),
            "decimated": decimated,
            "scans": [
                {
                    "index": i,
                    "point_count": n,
                    "guid": str(getattr(header, "guid", "") or ""),
                    "name": str(getattr(header, "name", "") or ""),
                }
                for i, (header, n) in enumerate(headers)
            ],
        }
        return RawCloud(xyz, rgb, metadata=meta)
    finally:
        try:
            e57.close()
        except Exception:
            pass


def read_las(path: Path, max_points: int, progress: Progress = None) -> RawCloud:
    try:
        import laspy
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedFormat("laspy is not installed; install it to read LAS/LAZ") from exc

    try:
        with laspy.open(str(path)) as fh:
            header = fh.header
            total = int(header.point_count)
            probability = 1.0 if max_points <= 0 or total <= max_points else max_points / total
            rng = np.random.default_rng(20240517)
            dims = set(header.point_format.dimension_names)
            has_rgb = {"red", "green", "blue"} <= dims
            has_intensity = "intensity" in dims
            has_class = "classification" in dims

            xyz_parts, rgb_parts, int_parts, cls_parts = [], [], [], []
            read = 0
            for chunk in fh.chunk_iterator(5_000_000):
                read += len(chunk)
                mask = None
                if probability < 1.0:
                    mask = rng.random(len(chunk)) < probability
                xyz = np.column_stack(
                    [np.asarray(chunk.x), np.asarray(chunk.y), np.asarray(chunk.z)]
                ).astype(np.float64, copy=False)
                if mask is not None:
                    xyz = xyz[mask]
                xyz_parts.append(xyz)
                if has_rgb:
                    rgb = np.column_stack(
                        [
                            np.asarray(chunk.red),
                            np.asarray(chunk.green),
                            np.asarray(chunk.blue),
                        ]
                    )
                    # LAS colors are 16-bit; normalize via the 8-bit high byte.
                    if rgb.size and rgb.max() > 255:
                        rgb = (rgb / 256.0).astype(np.uint8)
                    if mask is not None:
                        rgb = rgb[mask]
                    rgb_parts.append(rgb.astype(np.uint8))
                if has_intensity:
                    inten = np.asarray(chunk.intensity, dtype=np.float32)
                    int_parts.append(inten[mask] if mask is not None else inten)
                if has_class:
                    cls_parts.append(
                        (np.asarray(chunk.classification)[mask] if mask is not None else np.asarray(chunk.classification))
                    )
                if progress:
                    progress(0.05 + 0.85 * min(1.0, read / max(1, total)), "reading LAS/LAZ")
            if not xyz_parts:
                raise FormatError("LAS/LAZ file contains no points")
            xyz = np.concatenate(xyz_parts)
            rgb = np.concatenate(rgb_parts) if has_rgb and len(rgb_parts) == len(xyz_parts) else None
            intensity = np.concatenate(int_parts) if has_intensity and len(int_parts) == len(xyz_parts) else None
            classification = (
                np.concatenate(cls_parts) if has_class and len(cls_parts) == len(xyz_parts) else None
            )
            meta = {
                "reader": "laspy",
                "source_point_count": total,
                "decimated": bool(probability < 1.0 and total > max_points),
                "las_version": str(header.version),
                "point_format": int(header.point_format.id),
                "crs": str(header.parse_crs()) if header.parse_crs() else None,
            }
            return RawCloud(xyz, rgb, intensity, classification, meta)
    except (FormatError, UnsupportedFormat):
        raise
    except Exception as exc:
        raise FormatError(f"cannot read LAS/LAZ file: {exc}") from exc


def las_stream_info(path: str | Path) -> dict[str, Any]:
    """Read LAS/LAZ header fields without materializing point records."""
    try:
        import laspy
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedFormat("laspy is not installed; install it to read LAS/LAZ") from exc
    try:
        with laspy.open(str(path)) as fh:
            header = fh.header
            dims = set(header.point_format.dimension_names)
            return {
                "reader": "laspy",
                "source_point_count": int(header.point_count),
                "las_version": str(header.version),
                "point_format": int(header.point_format.id),
                "has_color": {"red", "green", "blue"} <= dims,
                "has_intensity": "intensity" in dims,
                "crs": str(header.parse_crs()) if header.parse_crs() else None,
            }
    except UnsupportedFormat:
        raise
    except Exception as exc:
        raise FormatError(f"cannot read LAS/LAZ header: {exc}") from exc


def iter_las_chunks(
    path: str | Path,
    chunk_points: int = 500_000,
    progress: Progress = None,
) -> Iterator[tuple[np.ndarray, np.ndarray | None, np.ndarray | None]]:
    """Yield bounded world-coordinate LAS/LAZ chunks as XYZ, RGB and intensity."""
    if chunk_points <= 0:
        raise ValueError("chunk_points must be positive")
    try:
        import laspy
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedFormat("laspy is not installed; install it to read LAS/LAZ") from exc

    try:
        with laspy.open(str(path)) as fh:
            total = int(fh.header.point_count)
            dims = set(fh.header.point_format.dimension_names)
            has_rgb = {"red", "green", "blue"} <= dims
            has_intensity = "intensity" in dims
            read = 0
            for chunk in fh.chunk_iterator(chunk_points):
                read += len(chunk)
                xyz = np.column_stack([chunk.x, chunk.y, chunk.z]).astype(np.float64, copy=False)
                finite = np.isfinite(xyz).all(axis=1)
                if not finite.any():
                    if progress:
                        progress(min(1.0, read / max(1, total)), "reading LAS/LAZ")
                    continue
                xyz = xyz[finite]
                rgb = None
                if has_rgb:
                    values = np.column_stack([chunk.red, chunk.green, chunk.blue])
                    if values.size and values.max() > 255:
                        values = values / 256.0
                    rgb = np.clip(values[finite], 0, 255).astype(np.uint8)
                intensity = None
                if has_intensity:
                    intensity = np.asarray(chunk.intensity, dtype=np.float32)[finite]
                if progress:
                    progress(min(1.0, read / max(1, total)), "reading LAS/LAZ")
                yield xyz, rgb, intensity
    except (FormatError, UnsupportedFormat):
        raise
    except Exception as exc:
        raise FormatError(f"cannot read LAS/LAZ stream: {exc}") from exc


def read_ply(path: Path, max_points: int, progress: Progress = None) -> RawCloud:
    try:
        from plyfile import PlyData
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedFormat("plyfile is not installed") from exc
    if progress:
        progress(0.2, "reading PLY")
    try:
        ply = PlyData.read(str(path))
        vertex = ply["vertex"]
        names = vertex.data.dtype.names or ()
        if not {"x", "y", "z"} <= set(names):
            raise FormatError("PLY vertex element has no x/y/z properties")
        xyz = np.column_stack([vertex["x"], vertex["y"], vertex["z"]]).astype(np.float64)
        rgb = None
        color_names = None
        for candidate in (
            ("red", "green", "blue"),
            ("r", "g", "b"),
            ("diffuse_red", "diffuse_green", "diffuse_blue"),
        ):
            if set(candidate) <= set(names):
                color_names = candidate
                break
        if color_names:
            rgb = np.column_stack([vertex[c] for c in color_names])
        intensity = None
        for name in ("intensity", "scalar_intensity", "quality"):
            if name in names:
                intensity = np.asarray(vertex[name], dtype=np.float32)
                break
        total = len(xyz)
        xyz, rgb, intensity, _, decimated = _decimate_arrays(xyz, rgb, intensity, None, max_points)
        if progress:
            progress(0.9, "PLY loaded")
        return RawCloud(
            xyz,
            rgb,
            intensity,
            metadata={
                "reader": "plyfile",
                "source_point_count": total,
                "decimated": decimated,
                "elements": [el.name for el in ply.elements],
            },
        )
    except (FormatError, UnsupportedFormat):
        raise
    except Exception as exc:
        raise FormatError(f"cannot read PLY file: {exc}") from exc


def read_pcd(path: Path, max_points: int, progress: Progress = None) -> RawCloud:
    """Minimal PCD reader (ascii / binary, xyz + packed or separate rgb)."""
    try:
        with path.open("rb") as fh:
            header: dict[str, list[str]] = {}
            while True:
                line = fh.readline()
                if not line:
                    raise FormatError("truncated PCD header")
                text = line.decode("ascii", "replace").strip()
                if not text or text.startswith("#"):
                    continue
                parts = text.split()
                key = parts[0].upper()
                header[key] = parts[1:]
                if key == "DATA":
                    break
            data_start = fh.tell()
            payload = path.read_bytes()[data_start:]
        fields = header.get("FIELDS", [])
        sizes = [int(x) for x in header.get("SIZE", [])]
        types = header.get("TYPE", [])
        counts = [int(x) for x in header.get("COUNT", ["1"] * len(fields))]
        data_kind = (header.get("DATA", ["ascii"])[0] or "ascii").lower()
        if not {"x", "y", "z"} <= set(fields):
            raise FormatError("PCD has no x/y/z fields")

        def index_of(name: str) -> int | None:
            return fields.index(name) if name in fields else None

        if data_kind == "ascii":
            import io

            import pandas as pd

            text = payload.decode("ascii", "replace")
            try:
                frame = pd.read_csv(
                    io.StringIO(text),
                    sep=r"\s+",
                    header=None,
                    comment="#",
                    engine="python",
                    on_bad_lines="skip",
                )
            except Exception as exc:
                raise FormatError(f"cannot parse PCD ascii payload: {exc}") from exc
            if frame.shape[1] < sum(counts):
                raise FormatError("PCD ascii row width does not match FIELDS/COUNT")
            values = frame.apply(lambda col: pd.to_numeric(col, errors="coerce")).to_numpy(dtype=float)
            values = values[~np.isnan(values).all(axis=1)]
            cols = []
            offset = 0
            for f, c in zip(fields, counts):
                cols.append(values[:, offset : offset + c])
                offset += c
            xyz = np.column_stack([cols[index_of("x")][:, 0], cols[index_of("y")][:, 0], cols[index_of("z")][:, 0]])
            rgb = None
            if "rgb" in fields:
                packed = cols[index_of("rgb")][:, 0].astype(np.uint32)
                rgb = np.column_stack([(packed >> 16) & 255, (packed >> 8) & 255, packed & 255])
            elif {"r", "g", "b"} <= set(fields):
                rgb = np.column_stack(
                    [cols[index_of("r")][:, 0], cols[index_of("g")][:, 0], cols[index_of("b")][:, 0]]
                )
            intensity = None
            if "intensity" in fields:
                intensity = cols[index_of("intensity")][:, 0].astype(np.float32)
            total = len(xyz)
            xyz, rgb, intensity, _, decimated = _decimate_arrays(xyz, rgb, intensity, None, max_points)
            return RawCloud(
                xyz,
                rgb,
                intensity,
                metadata={"reader": "pcd", "source_point_count": total, "decimated": decimated},
            )

        if data_kind == "binary":
            if not sizes or not types:
                raise FormatError("binary PCD requires SIZE and TYPE")
            dtype_fields = []
            for f, size, typ, count in zip(fields, sizes, types, counts):
                base = {"F": "f", "U": "u", "I": "i"}.get(typ.upper())
                if base is None:
                    raise FormatError(f"unsupported PCD field type {typ}")
                dtype_fields.append((f, f"<{base}{size}", (count,)) if count > 1 else (f, f"<{base}{size}"))
            dtype = np.dtype(dtype_fields)
            arr = np.frombuffer(payload, dtype=dtype)
            xyz = np.column_stack([arr["x"], arr["y"], arr["z"]]).astype(np.float64)
            rgb = None
            if "rgb" in fields:
                packed = arr["rgb"].astype(np.uint32)
                rgb = np.column_stack([(packed >> 16) & 255, (packed >> 8) & 255, packed & 255])
            elif {"r", "g", "b"} <= set(fields):
                rgb = np.column_stack([arr["r"], arr["g"], arr["b"]])
            intensity = arr["intensity"].astype(np.float32) if "intensity" in fields else None
            total = len(xyz)
            xyz, rgb, intensity, _, decimated = _decimate_arrays(xyz, rgb, intensity, None, max_points)
            return RawCloud(
                xyz,
                rgb,
                intensity,
                metadata={"reader": "pcd", "source_point_count": total, "decimated": decimated},
            )
        raise UnsupportedFormat(f"PCD DATA {data_kind} is not supported (ascii/binary only)")
    except (FormatError, UnsupportedFormat):
        raise
    except Exception as exc:
        raise FormatError(f"cannot read PCD file: {exc}") from exc


def _text_columns(ncols: int, fmt: str) -> tuple[bool, bool]:
    """Return (has_intensity, has_rgb) for a text row width."""
    if fmt == "pts":
        if ncols >= 7:
            return True, True
        if ncols >= 6:
            return False, True
        return False, False
    if ncols >= 6:
        return False, True
    return False, False


def read_text(path: Path, fmt: str, max_points: int, progress: Progress = None) -> RawCloud:
    """Chunked whitespace reader for XYZ/PTS/TXT/CSV.

    Uses the pandas C parser for space/tab separated files and falls back to
    numpy for unusual whitespace. For multi-gigabyte text clouds conversion to
    LAS/E57 is strongly recommended (and reported in metadata).
    """
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover
        raise UnsupportedFormat("pandas is required for text point clouds") from exc

    # Detect delimiter and skip an optional PTS count header.
    with path.open("rb") as fh:
        head = fh.read(65536).decode("utf-8", "replace")
    lines = [ln for ln in head.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    skiprows = 0
    if lines:
        first = lines[0].split()
        if len(first) == 1 and first[0].replace(".", "").isdigit():
            skiprows = 1
    sample = lines[skiprows : skiprows + 5]
    tabbed = bool(sample) and all("\t" in row for row in sample)
    if fmt == "csv" and sample and all("," in row for row in sample):
        sep = ","
    else:
        sep = "\t" if tabbed else " "
    widths = [len(row.split()) for row in sample] or [3]
    ncols = max(widths)
    has_intensity, has_rgb = _text_columns(ncols, fmt)

    usecols = list(range(3 + (1 if has_intensity else 0) + (3 if has_rgb else 0)))
    if has_rgb:
        color_start = 4 if has_intensity else 3
        rgb_cols = [color_start, color_start + 1, color_start + 2]
    else:
        rgb_cols = []

    xyz_parts, rgb_parts, int_parts = [], [], []
    total = 0
    try:
        reader = pd.read_csv(
            path,
            sep=sep,
            header=None,
            skiprows=skiprows,
            engine="c",
            chunksize=2_000_000,
            on_bad_lines="skip",
            skipinitialspace=True,
            comment="#",
            dtype=np.float64,
        )
        for chunk in reader:
            if chunk.shape[1] <= max(usecols):
                continue
            total += len(chunk)
            values = chunk.to_numpy(dtype=np.float64, copy=False)
            xyz = values[:, :3]
            xyz_parts.append(xyz)
            if has_intensity:
                int_parts.append(values[:, 3].astype(np.float32))
            if has_rgb:
                rgb_parts.append(normalize_rgb(values[:, rgb_cols]))
            if progress:
                progress(0.1 + 0.8 * min(1.0, total / max(1, path.stat().st_size // 40)), "parsing text cloud")
    except Exception as exc:
        raise FormatError(f"cannot parse text point cloud: {exc}") from exc

    if not xyz_parts:
        raise FormatError("text point cloud contains no numeric rows")
    xyz = np.concatenate(xyz_parts)
    rgb = np.concatenate(rgb_parts) if rgb_parts else None
    intensity = np.concatenate(int_parts) if int_parts else None
    source_total = len(xyz)
    xyz, rgb, intensity, _, decimated = _decimate_arrays(xyz, rgb, intensity, None, max_points)
    if progress:
        progress(0.9, "text cloud loaded")
    return RawCloud(
        xyz,
        rgb,
        intensity,
        metadata={
            "reader": "pandas",
            "source_point_count": source_total,
            "decimated": decimated,
            "columns": ncols,
            "skip_header_line": skiprows,
        },
    )
