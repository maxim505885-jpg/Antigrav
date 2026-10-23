"""Adapter for Autodesk's installed DeCap import tool.

DeCap creates the proprietary RCP and indexed support folder. SCAN does not
write or emulate Autodesk's project format itself.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import locale
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
    staging = Path(tempfile.mkdtemp(prefix="s2b_decap_"))
    command = [str(decap), "--importWithLicense", str(staging), project_name, "--controlFile"]
    control = staging / "scan-list.txt"
    try:
        control.write_text("\n".join(str(p) for p in inputs), encoding=locale.getpreferredencoding(False))
        result = subprocess.run(command + [str(control)], capture_output=True,
                                text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError(f"DeCap exceeded the {timeout} second time limit") from exc
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
    destination = Path(output_root).resolve() / project_name
    destination.mkdir(parents=True, exist_ok=True)
    final_rcp = destination / rcp.name
    final_support = destination / support.name
    if final_rcp.exists() or final_support.exists():
        shutil.rmtree(staging, ignore_errors=True)
        raise FileExistsError("A ReCap project with this name already exists; choose another name")
    shutil.move(str(support), str(final_support))
    shutil.move(str(rcp), str(final_rcp))
    shutil.rmtree(staging, ignore_errors=True)
    return {"status": "created_by_autodesk_decap", "rcp_path": str(final_rcp),
            "support_dir": str(final_support), "input_scan_count": len(inputs),
            "linked_rcs_count": len(linked_scans), "decap_output": result.stdout[-4000:]}
