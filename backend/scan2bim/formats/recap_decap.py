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

from .rcp_manifest import RcpManifestError, read_rcp_manifest

RCP_OUTPUT_FREE_SPACE_RESERVE_BYTES = 1024**3


class InsufficientStorageError(RuntimeError):
    def __init__(self, *, available_bytes: int, required_bytes: int, source_bytes: int):
        self.available_bytes = available_bytes
        self.required_bytes = required_bytes
        self.source_bytes = source_bytes
        super().__init__(
            f"Insufficient free disk space for a non-destructive ReCap project copy "
            f"(available {available_bytes} bytes; at least {required_bytes} bytes required "
            f"for {source_bytes} bytes of station sources plus a "
            f"{RCP_OUTPUT_FREE_SPACE_RESERVE_BYTES}-byte reserve)"
        )


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


def _stage_inputs_in_support(inputs: list[Path], support_dir: Path) -> list[Path]:
    """Copy every input into the project Support folder and return its staged path."""
    support_dir.mkdir(parents=True, exist_ok=True)
    staged: list[Path] = []
    used_names: set[str] = set()
    for index, source in enumerate(inputs, start=1):
        filename = source.name if source.name.isascii() else f"station_{index:04d}{source.suffix.lower()}"
        if filename.casefold() in used_names:
            filename = f"station_{index:04d}{source.suffix.lower()}"
        stem, suffix = Path(filename).stem, Path(filename).suffix
        unique = filename
        serial = 2
        while unique.casefold() in used_names:
            unique = f"{stem}_{serial}{suffix}"
            serial += 1
        used_names.add(unique.casefold())
        destination = support_dir / unique
        shutil.copyfile(source, destination)
        if destination.stat().st_size != source.stat().st_size:
            raise OSError(f"Staged ReCap Support copy size mismatch for {source.name}")
        staged.append(destination)
    return staged


def _cleanup_failed_attempt(staging: Path) -> None:
    shutil.rmtree(staging, ignore_errors=True)


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
    source_bytes = sum(path.stat().st_size for path in inputs)
    required_bytes = source_bytes + RCP_OUTPUT_FREE_SPACE_RESERVE_BYTES
    available_bytes = shutil.disk_usage(output_root).free
    if available_bytes < required_bytes:
        raise InsufficientStorageError(
            available_bytes=available_bytes,
            required_bytes=required_bytes,
            source_bytes=source_bytes,
        )
    staging = _new_staging_dir(output_root, ".s2b_decap_")
    try:
        decap_inputs = _stage_inputs_in_support(inputs, staging / f"{project_name} Support")
    except Exception:
        _cleanup_failed_attempt(staging)
        raise
    command = [
        str(decap), "--importWithLicense", _decap_compatible_path(staging),
        project_name, "--controlFile",
    ]
    control = staging / "scan-list.txt"
    try:
        control.write_text(
            "\n".join(str(path.relative_to(staging)) for path in decap_inputs),
            encoding=locale.getpreferredencoding(False),
        )
        result = subprocess.run(
            command + [_decap_compatible_path(control)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            cwd=_decap_compatible_path(staging),
        )
    except subprocess.TimeoutExpired as exc:
        _cleanup_failed_attempt(staging)
        raise RuntimeError(f"DeCap exceeded the {timeout} second time limit") from exc
    except UnicodeEncodeError as exc:
        _cleanup_failed_attempt(staging)
        raise RuntimeError(
            "DeCap cannot encode the project Support path in the current Windows code page; "
            "choose an ASCII project name or a compatible Windows code page"
        ) from exc
    except OSError as exc:
        _cleanup_failed_attempt(staging)
        raise RuntimeError(f"Could not start DeCap or prepare its control file: {exc}") from exc
    rcp_candidates = list(staging.rglob(f"{project_name}.rcp"))
    rcp = rcp_candidates[0] if len(rcp_candidates) == 1 else None
    support = rcp.parent / f"{project_name} Support" if rcp else None
    failed_match = re.search(r"\[(?:P|p)\]\[(\d+) Failed\]", result.stdout)
    failed_scans = int(failed_match.group(1)) if failed_match else None
    if result.returncode or failed_scans not in (None, 0) or rcp is None or not support.is_dir():
        _cleanup_failed_attempt(staging)
        raise RuntimeError(f"DeCap did not produce a complete RCP bundle (exit {result.returncode}, failed scans {failed_scans}): {result.stdout[-2000:]} {result.stderr[-2000:]}")
    linked_scans = list(support.rglob("*.rcs"))
    package_files = [rcp, *linked_scans]
    empty_files = [str(path.relative_to(staging)) for path in package_files if path.stat().st_size == 0]
    if empty_files:
        _cleanup_failed_attempt(staging)
        raise RuntimeError(f"DeCap created empty files in the RCP bundle: {', '.join(empty_files)}")
    try:
        manifest = read_rcp_manifest(rcp)
    except RcpManifestError as exc:
        _cleanup_failed_attempt(staging)
        raise RuntimeError(f"DeCap created an unreadable RCP project: {exc}") from exc
    if len(manifest["nodes"]) < len(inputs):
        _cleanup_failed_attempt(staging)
        raise RuntimeError(
            f"DeCap RCP contains {len(manifest['nodes'])} scan nodes for {len(inputs)} input stations"
        )

    known_source_paths = {
        str(path.resolve()).casefold() for path in [*inputs, *decap_inputs]
    }
    known_linked_paths = {str(path.resolve()).casefold() for path in linked_scans}
    external_paths: set[str] = set()
    unresolved_nodes: list[str] = []
    unexpected_paths: list[str] = []
    for node in manifest["nodes"]:
        resolved = node["resolved_rcs_path"]
        if not resolved:
            unresolved_nodes.append(node["name"])
            continue
        key = str(Path(resolved).resolve()).casefold()
        if key in known_linked_paths:
            continue
        if key in known_source_paths:
            external_paths.add(str(Path(resolved).resolve()))
        else:
            unexpected_paths.append(resolved)
    if unresolved_nodes or unexpected_paths:
        diagnostics = (
            f"DeCap exit={result.returncode}; unresolved nodes={unresolved_nodes}; "
            f"unexpected paths={unexpected_paths}; stdout={result.stdout[-1200:]!r}; "
            f"stderr={result.stderr[-1200:]!r}"
        )
        _cleanup_failed_attempt(staging)
        raise RuntimeError(f"DeCap RCP has unresolved station sources ({diagnostics})")
    destination = output_root / project_name
    if destination.exists():
        _cleanup_failed_attempt(staging)
        raise FileExistsError("A ReCap project with this name already exists; choose another name")
    try:
        bundle_staging = _new_staging_dir(output_root, f".{project_name}_")
    except Exception:
        _cleanup_failed_attempt(staging)
        raise
    try:
        shutil.move(str(support), str(bundle_staging / support.name))
        final_rcp = bundle_staging / rcp.name
        shutil.move(str(rcp), str(final_rcp))
        bundle_staging.replace(destination)
        final_rcp = destination / rcp.name
        final_support = destination / support.name
    except OSError:
        shutil.rmtree(bundle_staging, ignore_errors=True)
        _cleanup_failed_attempt(staging)
        raise
    shutil.rmtree(staging, ignore_errors=True)
    try:
        final_manifest = read_rcp_manifest(final_rcp)
    except RcpManifestError as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise RuntimeError(f"Moved ReCap project failed manifest verification: {exc}") from exc
    if len(final_manifest["nodes"]) != len(manifest["nodes"]) or any(
        not node["resolved_rcs_path"] for node in final_manifest["nodes"]
    ):
        shutil.rmtree(destination, ignore_errors=True)
        raise RuntimeError("Moved ReCap project lost one or more linked station sources")
    final_linked_scans = list(final_support.rglob("*.rcs"))
    return {
        "status": "created_by_autodesk_decap",
        "project_verified": True,
        "package_verified": not external_paths,
        "rcp_path": str(final_rcp),
        "support_dir": str(final_support),
        "input_scan_count": len(inputs),
        "rcp_node_count": len(final_manifest["nodes"]),
        "linked_rcs_count": len(final_linked_scans),
        "external_rcs_count": len(external_paths),
        "external_rcs_paths": sorted(external_paths),
        "source_files_copied_for_decap": bool(decap_inputs),
        "source_cache_path": None,
        "rcp_size_bytes": final_rcp.stat().st_size,
        "linked_rcs_size_bytes": sum(path.stat().st_size for path in final_support.rglob("*.rcs")),
        "disk_preflight": {
            "status": "passed",
            "source_bytes": source_bytes,
            "required_free_bytes": required_bytes,
            "available_free_bytes": available_bytes,
            "reserve_bytes": RCP_OUTPUT_FREE_SPACE_RESERVE_BYTES,
            "estimate_is_conservative": True,
        },
        "decap_output": result.stdout[-4000:],
    }
