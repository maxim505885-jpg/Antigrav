"""Autodesk RCS/RCP conversion hook.

The application never decodes the proprietary container. If the user (or an
administrator) supplies an approved converter command, it is executed as a
separate process and only the converted open format is read. Without such a
command, the import fails with actionable guidance instead of pretending to
support RCS.
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from ..config import DATA_DIR, RCS_CONVERTER_CMD
from ..storage import safe_filename


def recap_available() -> bool:
    from ..config import RECAP_EXE

    return RECAP_EXE.exists()


def converter_output(path: Path) -> Path:
    folder = DATA_DIR / "converted"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (safe_filename(path.stem) + ".e57")


def convert_rcs(path: Path, progress=None, output: Path | None = None) -> Path | None:
    """Run the configured converter. Return None when none is configured.

    The command template supports {input} and {output} placeholders, e.g.
    S2B_RCS_CONVERTER="C:\\Tools\\recap-export.exe --in {input} --out {output}"
    It is executed without a shell. The converter must be licensed for RCS.
    """
    if not RCS_CONVERTER_CMD:
        return None
    target = output or converter_output(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        parts = shlex.split(RCS_CONVERTER_CMD, posix=False)
    except ValueError as exc:
        raise RuntimeError(f"invalid S2B_RCS_CONVERTER command: {exc}") from exc
    command = [part.replace("{input}", str(path)).replace("{output}", str(target)) for part in parts]
    if progress:
        progress(0.02, "running approved RCS conversion")
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60 * 60 * 6,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"could not start RCS converter: {exc}") from exc
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "")[-2000:]
        raise RuntimeError(
            f"RCS converter failed with exit code {completed.returncode}: {tail}"
        )
    if not target.exists() or target.stat().st_size == 0:
        raise RuntimeError(
            "RCS converter reported success but produced no output. "
            "Check the {output} placeholder in S2B_RCS_CONVERTER."
        )
    return target


def converter_status() -> dict[str, Any]:
    from ..config import RECAP_EXE

    return {
        "configured": bool(RCS_CONVERTER_CMD),
        "recap_installed": RECAP_EXE.exists(),
        "recap_path": str(RECAP_EXE),
        "command_template": "S2B_RCS_CONVERTER='tool --in {input} --out {output}'",
        "native_reading": False,
    }
