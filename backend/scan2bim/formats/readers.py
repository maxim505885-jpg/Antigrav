"""Point-cloud readers.

Supported natively: E57, LAS, LAZ, PLY, PCD, PTS, XYZ/TXT/CSV (whitespace).
RCS point data is read through the installed Autodesk ReCap library in an
isolated process. RCP is a ZIP/XML project manifest linking one or more RCS
files; the API resolves a single linked scan before sending its RCS to the
licensed reader. The original files are opened read-only.
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
        "RCS points require Autodesk ReCap; RCP projects link separate RCS files."
    )


def supported_formats() -> dict[str, Any]:
    return {
        "native": sorted(NATIVE_FORMATS),
        "proprietary_conversion_required": ["rcs"],
        "project_containers": ["rcp"],
        "notes": {
            "rcs": "proprietary point data read via the installed Autodesk ReCap DLL in an isolated process",
            "rcp": "ZIP/XML project manifest; import-path resolves a single linked RCS and preserves the station transform as metadata",
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
            "RCS — закрытый (proprietary) формат точек. RCP — проектный ZIP/XML-манифест, "
            "содержащий ссылки и преобразования отдельных станций RCS. Приложение не реализует "
            "кодек RCS. На машине с установленным Autodesk ReCap точки читаются через локальную "
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
            "Если ReCap установлен: импортируйте .rcs напрямую; односкановый .rcp разрешается в связанный .rcs с сохранением метаданных проекта.",
            "Если ReCap нет: откройте проект .rcp в ReCap и экспортируйте в E57 (или LAS) в полном разрешении.",
            "Импортируйте полученный .e57/.las в это приложение.",
            "Либо задайте S2B_RCS_CONVERTER с разрешённой командой конвертации и повторите импорт.",
        ],
        "command_template": "S2B_RCS_CONVERTER='tool --in {input} --out {output}'",
        "warning": (
            "Интерфейс DLL — недокументированный внутренний API Autodesk. Формулировка "
            "должна быть «читается через установленный Autodesk ReCap», а не «нативная поддержка RCS». "
            "Трансформации RCP сохраняются отдельно и не применяются до независимой проверки конвенции."
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


_PLY_SCALAR_TYPES = {
    "char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1",
    "short": "i2", "int16": "i2", "ushort": "u2", "uint16": "u2",
    "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
    "float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
}


def iter_ply_chunks(
    path: str | Path,
    chunk_points: int = 500_000,
    progress: Progress = None,
) -> Iterator[tuple[np.ndarray, np.ndarray | None, np.ndarray | None]]:
    """Yield bounded PLY vertex blocks; binary vertex records are memory-mapped."""
    path = Path(path)
    if chunk_points <= 0:
        raise ValueError("chunk_points must be a positive integer")
    try:
        vertex_count = None
        properties: list[tuple[str, str]] = []
        elements: list[str] = []
        current_element = None
        data_offset = None
        format_name = None
        with path.open("rb") as fh:
            if fh.readline().strip() != b"ply":
                raise FormatError("invalid PLY magic header")
            header_lines = 1
            while True:
                raw_line = fh.readline()
                if not raw_line:
                    raise FormatError("truncated PLY header")
                header_lines += 1
                line = raw_line.decode("ascii", "replace").strip()
                parts = line.split()
                if not parts or parts[0] in {"comment", "obj_info"}:
                    continue
                if parts[0] == "format":
                    format_name = parts[1].lower()
                elif parts[0] == "element":
                    current_element = parts[1]
                    elements.append(current_element)
                    if current_element == "vertex":
                        if len(elements) != 1:
                            raise UnsupportedFormat("streaming PLY requires vertex to be the first element")
                        vertex_count = int(parts[2])
                elif parts[0] == "property" and current_element == "vertex":
                    if len(parts) >= 3 and parts[1] != "list":
                        properties.append((parts[2].lower(), parts[1].lower()))
                    else:
                        raise UnsupportedFormat("list-valued PLY vertex properties are not supported")
                elif parts[0] == "end_header":
                    data_offset = fh.tell()
                    break
        if vertex_count is None or vertex_count <= 0 or data_offset is None:
            raise FormatError("PLY contains no vertex points")
        names = [name for name, _ in properties]
        if not {"x", "y", "z"} <= set(names):
            raise FormatError("PLY vertex element has no x/y/z properties")
        if any(names.count(axis) != 1 for axis in ("x", "y", "z")):
            raise FormatError("PLY x/y/z properties must be unique")
        color_names = next((candidate for candidate in (
            ("red", "green", "blue"), ("r", "g", "b"),
            ("diffuse_red", "diffuse_green", "diffuse_blue"),
        ) if set(candidate) <= set(names)), None)
        scalar_types = {name: _PLY_SCALAR_TYPES.get(scalar_type) for name, scalar_type in properties}
        integer_color = bool(color_names) and all(
            (scalar_types.get(name) or "f")[0] in "iu" for name in color_names
        )
        intensity_name = next((name for name in ("intensity", "scalar_intensity", "quality") if name in names), None)

        def color_array(values: np.ndarray) -> np.ndarray | None:
            if color_names is None:
                return None
            channels = np.column_stack([values[name] for name in color_names])
            if integer_color:
                return np.clip(np.nan_to_num(channels), 0, 255).astype(np.uint8)
            return normalize_rgb(channels)

        if format_name == "ascii":
            try:
                import pandas as pd
            except ImportError as exc:  # pragma: no cover
                raise UnsupportedFormat("pandas is required for PLY ASCII") from exc
            reader = pd.read_csv(
                path, sep=r"\s+", header=None, skiprows=header_lines, nrows=vertex_count,
                engine="c", chunksize=chunk_points, on_bad_lines="skip", dtype=np.float64,
            )
            rows_read = 0
            for chunk in reader:
                if chunk.shape[1] < len(properties):
                    raise FormatError("PLY ASCII vertex row width does not match properties")
                values = chunk.to_numpy(dtype=np.float64, copy=False)
                indices = {name: index for index, (name, _type) in enumerate(properties)}
                xyz = np.column_stack([values[:, indices[name]] for name in ("x", "y", "z")])
                rgb = color_array({name: values[:, indices[name]] for name in names})
                intensity = values[:, indices[intensity_name]].astype(np.float32) if intensity_name else None
                rows_read += len(xyz)
                if progress:
                    progress(rows_read / vertex_count, "reading PLY ASCII")
                if len(xyz):
                    yield xyz, rgb, intensity
            if rows_read != vertex_count:
                raise FormatError(f"PLY vertex count mismatch: header has {vertex_count}, read {rows_read}")
            return

        if format_name not in {"binary_little_endian", "binary_big_endian"}:
            raise UnsupportedFormat(f"PLY format {format_name!r} is not supported")
        endian = "<" if format_name == "binary_little_endian" else ">"
        dtype_fields = []
        for name, scalar_type in properties:
            base = _PLY_SCALAR_TYPES.get(scalar_type)
            if base is None:
                raise UnsupportedFormat(f"PLY scalar type {scalar_type!r} is not supported")
            dtype_fields.append((name, f"{endian}{base}"))
        dtype = np.dtype(dtype_fields)
        if path.stat().st_size - data_offset < vertex_count * dtype.itemsize:
            raise FormatError("truncated PLY binary vertex data")
        mapped = np.memmap(path, mode="r", dtype=dtype, offset=data_offset, shape=(vertex_count,))
        try:
            indices = {name: index for index, (name, _type) in enumerate(properties)}
            for start in range(0, vertex_count, chunk_points):
                end = min(start + chunk_points, vertex_count)
                block = mapped[start:end]
                xyz = np.column_stack([block[name] for name in ("x", "y", "z")]).astype(np.float64)
                rgb = color_array({name: block[name] for name in names})
                intensity = np.asarray(block[intensity_name], dtype=np.float32).copy() if intensity_name else None
                if progress:
                    progress(end / vertex_count, "reading PLY binary")
                yield xyz, rgb, intensity
        finally:
            mapped._mmap.close()
    except (FormatError, UnsupportedFormat):
        raise
    except Exception as exc:
        raise FormatError(f"cannot read PLY stream: {exc}") from exc


def read_ply(path: Path, max_points: int, progress: Progress = None) -> RawCloud:
    """Read PLY vertices in chunks, combining only for the regular array API."""
    xyz_parts, rgb_parts, intensity_parts = [], [], []
    for xyz, rgb, intensity in iter_ply_chunks(path, progress=progress):
        xyz_parts.append(xyz)
        if rgb is not None:
            rgb_parts.append(rgb)
        if intensity is not None:
            intensity_parts.append(intensity)
    if not xyz_parts:
        raise FormatError("PLY contains no numeric vertices")
    xyz = np.concatenate(xyz_parts)
    rgb = np.concatenate(rgb_parts) if rgb_parts else None
    intensity = np.concatenate(intensity_parts) if intensity_parts else None
    total = len(xyz)
    xyz, rgb, intensity, _, decimated = _decimate_arrays(xyz, rgb, intensity, None, max_points)
    return RawCloud(
        xyz, rgb, intensity,
        metadata={"reader": "ply-chunk", "source_point_count": total, "decimated": decimated, "elements": ["vertex"]},
    )


def _pcd_header(path: str | Path) -> tuple[dict[str, list[str]], int, int]:
    header: dict[str, list[str]] = {}
    header_lines = 0
    with Path(path).open("rb") as fh:
        while True:
            line = fh.readline()
            if not line:
                raise FormatError("truncated PCD header")
            header_lines += 1
            text = line.decode("ascii", "replace").strip()
            if not text or text.startswith("#"):
                continue
            parts = text.split()
            key = parts[0].upper()
            header[key] = parts[1:]
            if key == "DATA":
                return header, fh.tell(), header_lines


def _pcd_layout(header: dict[str, list[str]]) -> tuple[list[str], list[int], list[str], list[int], int]:
    fields = [field.lower() for field in header.get("FIELDS", header.get("FIELD", []))]
    sizes = [int(value) for value in header.get("SIZE", [])]
    types = [value.upper() for value in header.get("TYPE", [])]
    counts = [int(value) for value in header.get("COUNT", ["1"] * len(fields))]
    if not fields or not {"x", "y", "z"} <= set(fields):
        raise FormatError("PCD has no x/y/z fields")
    if not sizes or not types or len(sizes) != len(fields) or len(types) != len(fields) or len(counts) != len(fields):
        raise FormatError("PCD SIZE/TYPE/COUNT metadata does not match FIELDS")
    if any(size not in {1, 2, 4, 8} for size in sizes) or any(count <= 0 for count in counts):
        raise FormatError("PCD field sizes/counts are invalid")
    width = int((header.get("WIDTH") or ["0"])[0])
    height = int((header.get("HEIGHT") or ["1"])[0])
    point_count = int((header.get("POINTS") or [str(width * height)])[0])
    if point_count <= 0:
        raise FormatError("PCD contains no points")
    return fields, sizes, types, counts, point_count


def _pcd_rgb(packed: np.ndarray, field_type: str) -> np.ndarray:
    values = np.asarray(packed)
    if field_type == "F":
        floats = values.astype("<f4", copy=False)
        bits = floats.view("<u4")
        # Some non-PCL writers serialize the packed integer as a decimal float.
        decimal = np.isfinite(floats) & (np.abs(floats) > 65535)
        if decimal.any():
            bits = bits.copy()
            bits[decimal] = np.clip(floats[decimal], 0, 0xFFFFFFFF).astype(np.uint32)
    else:
        bits = values.astype(np.uint32)
    return np.column_stack([(bits >> 16) & 255, (bits >> 8) & 255, bits & 255]).astype(np.uint8)


def iter_pcd_chunks(
    path: str | Path,
    chunk_points: int = 500_000,
    progress: Progress = None,
) -> Iterator[tuple[np.ndarray, np.ndarray | None, np.ndarray | None]]:
    """Yield bounded PCD blocks; binary payloads are memory-mapped, not copied."""
    path = Path(path)
    if chunk_points <= 0:
        raise ValueError("chunk_points must be a positive integer")
    try:
        header, data_offset, header_lines = _pcd_header(path)
        fields, sizes, types, counts, point_count = _pcd_layout(header)
        data_kind = (header.get("DATA", [""])[0] or "").lower()
        if data_kind not in {"ascii", "binary"}:
            raise UnsupportedFormat(f"PCD DATA {data_kind} is not supported (ascii/binary only)")
        offsets: dict[str, int] = {}
        column_offset = 0
        for field_name, count in zip(fields, counts):
            offsets[field_name] = column_offset
            column_offset += count
        if any(counts[fields.index(name)] != 1 for name in ("x", "y", "z")):
            raise FormatError("PCD x/y/z fields must be scalar")
        rgb_names = {"r", "g", "b"} <= set(fields)
        packed_name = "rgb" if "rgb" in fields else "rgba" if "rgba" in fields else None
        has_color = rgb_names or packed_name is not None
        has_intensity = "intensity" in fields

        if data_kind == "ascii":
            try:
                import pandas as pd
            except ImportError as exc:  # pragma: no cover
                raise UnsupportedFormat("pandas is required for PCD ASCII") from exc
            reader = pd.read_csv(
                path, sep=r"\s+", header=None, skiprows=header_lines, engine="c",
                chunksize=chunk_points, on_bad_lines="skip", comment="#", dtype=np.float64,
            )
            rows_read = 0
            for chunk in reader:
                if chunk.shape[1] < column_offset:
                    raise FormatError("PCD ASCII row width does not match FIELDS/COUNT")
                values = chunk.to_numpy(dtype=np.float64, copy=False)
                xyz = np.column_stack([values[:, offsets[name]] for name in ("x", "y", "z")])
                rgb = None
                if packed_name:
                    rgb = _pcd_rgb(values[:, offsets[packed_name]], types[fields.index(packed_name)])
                elif rgb_names:
                    rgb = normalize_rgb(np.column_stack([values[:, offsets[name]] for name in ("r", "g", "b")]))
                intensity = values[:, offsets["intensity"]].astype(np.float32) if has_intensity else None
                rows_read += len(xyz)
                if progress:
                    progress(min(1.0, rows_read / max(1, point_count)), "reading PCD ASCII")
                if len(xyz):
                    yield xyz, rgb, intensity
            if rows_read != point_count:
                raise FormatError(f"PCD point count mismatch: header has {point_count}, read {rows_read}")
            return

        dtype_fields = []
        for field_name, size, field_type, count in zip(fields, sizes, types, counts):
            base = {"F": "f", "U": "u", "I": "i"}.get(field_type)
            if base is None:
                raise FormatError(f"unsupported PCD field type {field_type}")
            dtype_fields.append((field_name, f"<{base}{size}", (count,)) if count > 1 else (field_name, f"<{base}{size}"))
        dtype = np.dtype(dtype_fields)
        expected_bytes = point_count * dtype.itemsize
        if path.stat().st_size - data_offset < expected_bytes:
            raise FormatError("truncated PCD binary payload")
        mapped = np.memmap(path, mode="r", dtype=dtype, offset=data_offset, shape=(point_count,))
        try:
            for start in range(0, point_count, chunk_points):
                end = min(start + chunk_points, point_count)
                block = mapped[start:end]
                xyz = np.column_stack([block[name] for name in ("x", "y", "z")]).astype(np.float64)
                rgb = None
                if packed_name:
                    rgb = _pcd_rgb(block[packed_name], types[fields.index(packed_name)])
                elif rgb_names:
                    rgb = normalize_rgb(np.column_stack([block[name] for name in ("r", "g", "b")]))
                intensity = np.asarray(block["intensity"], dtype=np.float32).copy() if has_intensity else None
                if progress:
                    progress(end / max(1, point_count), "reading PCD binary")
                yield xyz, rgb, intensity
        finally:
            mapped._mmap.close()
    except (FormatError, UnsupportedFormat):
        raise
    except Exception as exc:
        raise FormatError(f"cannot read PCD stream: {exc}") from exc


def read_pcd(path: Path, max_points: int, progress: Progress = None) -> RawCloud:
    """Read ASCII or binary PCD in bounded blocks for the regular array API."""
    xyz_parts, rgb_parts, intensity_parts = [], [], []
    for xyz, rgb, intensity in iter_pcd_chunks(path, progress=progress):
        xyz_parts.append(xyz)
        if rgb is not None:
            rgb_parts.append(rgb)
        if intensity is not None:
            intensity_parts.append(intensity)
    if not xyz_parts:
        raise FormatError("PCD contains no numeric points")
    xyz = np.concatenate(xyz_parts)
    rgb = np.concatenate(rgb_parts) if rgb_parts else None
    intensity = np.concatenate(intensity_parts) if intensity_parts else None
    total = len(xyz)
    xyz, rgb, intensity, _, decimated = _decimate_arrays(xyz, rgb, intensity, None, max_points)
    return RawCloud(
        xyz, rgb, intensity,
        metadata={"reader": "pcd", "source_point_count": total, "decimated": decimated},
    )


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


def iter_text_chunks(
    path: str | Path,
    fmt: str,
    chunk_points: int = 500_000,
    progress: Progress = None,
) -> Iterator[tuple[np.ndarray, np.ndarray | None, np.ndarray | None]]:
    """Yield bounded source XYZ/color/intensity blocks from a text point cloud."""
    path = Path(path)
    if chunk_points <= 0:
        raise ValueError("chunk_points must be a positive integer")
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
    widths = [len(row.split(",") if sep == "," else row.split()) for row in sample] or [3]
    ncols = max(widths)
    has_intensity, has_rgb = _text_columns(ncols, fmt)

    usecols = list(range(3 + (1 if has_intensity else 0) + (3 if has_rgb else 0)))
    if has_rgb:
        color_start = 4 if has_intensity else 3
        rgb_cols = [color_start, color_start + 1, color_start + 2]
    else:
        rgb_cols = []

    total = 0
    try:
        reader = pd.read_csv(
            path,
            sep=sep,
            header=None,
            skiprows=skiprows,
            engine="c",
            chunksize=chunk_points,
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
            rgb = normalize_rgb(values[:, rgb_cols]) if has_rgb else None
            intensity = values[:, 3].astype(np.float32) if has_intensity else None
            if progress:
                progress(0.1 + 0.8 * min(1.0, total / max(1, path.stat().st_size // 40)), "parsing text cloud")
            if len(xyz):
                yield xyz, rgb, intensity
    except Exception as exc:
        if isinstance(exc, (FormatError, UnsupportedFormat)):
            raise
        raise FormatError(f"cannot parse text point cloud: {exc}") from exc


def read_text(path: Path, fmt: str, max_points: int, progress: Progress = None) -> RawCloud:
    """Read XYZ/PTS/TXT/CSV in chunks, combining only for the regular array API."""
    xyz_parts, rgb_parts, int_parts = [], [], []
    with path.open("rb") as fh:
        head = fh.read(65536).decode("utf-8", "replace")
    lines = [ln for ln in head.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    skiprows = bool(lines and len(lines[0].split()) == 1 and lines[0].split()[0].replace(".", "").isdigit())
    sample = lines[1 if skiprows else 0 : 6 if skiprows else 5]
    comma_separated = fmt == "csv" and bool(sample) and all("," in row for row in sample)
    ncols = max((len(row.split(",") if comma_separated else row.split()) for row in sample), default=3)
    for xyz, rgb, intensity in iter_text_chunks(path, fmt, progress=progress):
        xyz_parts.append(xyz)
        if rgb is not None:
            rgb_parts.append(rgb)
        if intensity is not None:
            int_parts.append(intensity)

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
