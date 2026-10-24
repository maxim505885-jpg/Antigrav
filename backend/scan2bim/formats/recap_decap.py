"""Adapter for Autodesk's installed DeCap import tool.

DeCap creates the proprietary RCP and indexed support folder. SCAN does not
write or emulate Autodesk's project format itself.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import locale
import uuid
from pathlib import Path
from typing import Any, Mapping


def find_decap() -> Path | None:
    configured = os.environ.get("S2B_DECAP_EXE")
    candidates = [Path(configured)] if configured else []
    candidates += [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Autodesk" / "Autodesk ReCap" / "DeCap.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Autodesk" / "Autodesk ReCap" / "DeCap.exe",
    ]
    return next((p for p in candidates if p.is_file()), None)


def _new_staging_dir(parent: Path, prefix: str) -> Path:
    """Create a unique staging directory with inherited output-folder permissions."""
    for _attempt in range(5):
        candidate = parent / f"{prefix}{uuid.uuid4().hex}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise FileExistsError(f"Could not reserve a staging directory in {parent}")


def _short_windows_path(path: Path) -> str | None:
    """Return an ASCII 8.3 path when Windows provides one for legacy DeCap parsing."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        get_short_path = ctypes.windll.kernel32.GetShortPathNameW
        get_short_path.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        get_short_path.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        length = get_short_path(str(path), buffer, len(buffer))
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    if not length or length >= len(buffer):
        return None
    short_path = buffer.value
    return short_path if short_path.isascii() else None


def _decap_compatible_path(path: Path) -> str:
    """Avoid Unicode paths where the installed DeCap command-line parser cannot handle them."""
    value = str(path)
    if value.isascii():
        return value
    return _short_windows_path(path) or value


def create_recap_project(output_root: Path, project_name: str,
                         scans: list[Mapping[str, Any]], *, timeout: int = 3600) -> dict[str, Any]:
    if not re.fullmatch(r"[\w .()\-]{1,80}", project_name, flags=re.UNICODE) or project_name in {".", ".."}:
        raise ValueError("Invalid ReCap project name")
    if not scans:
        raise ValueError("At least one scan file is required")
    inputs = []
    for scan in scans:
        path = Path(str(scan.get("path", ""))).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() not in {".rcs", ".e57", ".fls", ".fws", ".las", ".laz", ".pts", ".ptx", ".ply", ".xyz"}:
            raise ValueError(f"Unsupported or missing ReCap scan source: {path}")
        inputs.append(path)
    decap = find_decap()
    if decap is None:
        raise FileNotFoundError("DeCap.exe was not found; install Autodesk ReCap Pro or set S2B_DECAP_EXE")
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    staging = _new_staging_dir(output_root, ".s2b_decap_")
    command = [
        str(decap), "--importWithLicense", _decap_compatible_path(staging),
        project_name, "--controlFile",
    ]
    control = staging / "scan-list.txt"
    try:
        control.write_text(
            "\n".join(_decap_compatible_path(path) for path in inputs),
            encoding=locale.getpreferredencoding(False),
        )
        result = subprocess.run(
            command + [_decap_compatible_path(control)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=str(decap.parent),
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError(f"DeCap exceeded the {timeout} second time limit") from exc
    except UnicodeEncodeError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError(
            "DeCap cannot encode a scan path in the current Windows code page; "
            "move the scan under an ASCII-only path or enable Windows 8.3 short names"
        ) from exc
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError(f"Could not start DeCap or prepare its control file: {exc}") from exc
    rcp_candidates = list(staging.rglob(f"{project_name}.rcp"))
    rcp = rcp_candidates[0] if len(rcp_candidates) == 1 else None
    support = rcp.parent / f"{project_name} Support" if rcp else None
    failed_match = re.search(r"\[(?:P|p)\]\[(\d+) Failed\]", result.stdout)
    failed_scans = int(failed_match.group(1)) if failed_match else None
    if result.returncode or failed_scans not in (None, 0) or rcp is None or not support.is_dir():
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError(f"DeCap did not produce a complete RCP bundle (exit {result.returncode}, failed scans {failed_scans}): {result.stdout[-2000:]} {result.stderr[-2000:]}")
    linked_scans = list(support.rglob("*.rcs"))
    if not linked_scans:
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError("DeCap created no linked RCS scans in the Support folder")
    package_files = [rcp, *linked_scans]
    empty_files = [str(path.relative_to(staging)) for path in package_files if path.stat().st_size == 0]
    if empty_files:
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError(f"DeCap created empty files in the RCP bundle: {', '.join(empty_files)}")
    destination = output_root / project_name
    if destination.exists():
        shutil.rmtree(staging, ignore_errors=True)
        raise FileExistsError("A ReCap project with this name already exists; choose another name")
    bundle_staging = _new_staging_dir(output_root, f".{project_name}_")
    try:
        shutil.move(str(support), str(bundle_staging / support.name))
        final_rcp = bundle_staging / rcp.name
        shutil.move(str(rcp), str(final_rcp))
        bundle_staging.replace(destination)
        final_rcp = destination / rcp.name
        final_support = destination / support.name
    except OSError:
        shutil.rmtree(bundle_staging, ignore_errors=True)
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(staging, ignore_errors=True)
    return {
        "status": "created_by_autodesk_decap",
        "package_verified": True,
        "rcp_path": str(final_rcp),
        "support_dir": str(final_support),
        "input_scan_count": len(inputs),
        "linked_rcs_count": len(linked_scans),
        "rcp_size_bytes": final_rcp.stat().st_size,
        "linked_rcs_size_bytes": sum(path.stat().st_size for path in final_support.rglob("*.rcs")),
        "decap_output": result.stdout[-4000:],
    }
