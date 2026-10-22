"""Desktop helper endpoints: native Windows integration with AutoCAD 2026, ReCap, and Explorer."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/desktop", tags=["desktop"])

AUTOCAD_PATH = Path(r"C:\Program Files\Autodesk\AutoCAD 2026\acad.exe")
RECAP_PATH = Path(r"C:\Program Files\Autodesk\Autodesk ReCap\ReCap.exe")


class OpenPathRequest(BaseModel):
    path: str


class FileDialogRequest(BaseModel):
    title: str = "Выберите файл облака точек"
    file_type: str = "cloud"  # 'cloud' | 'dxf' | 'folder'


@router.get("/status")
def desktop_status() -> dict[str, Any]:
    """Check installed desktop CAD & BIM software availability."""
    return {
        "platform": sys.platform,
        "autocad_available": AUTOCAD_PATH.is_file(),
        "autocad_path": str(AUTOCAD_PATH) if AUTOCAD_PATH.is_file() else None,
        "recap_available": RECAP_PATH.is_file(),
        "recap_path": str(RECAP_PATH) if RECAP_PATH.is_file() else None,
    }


@router.post("/open-autocad")
def open_autocad(payload: OpenPathRequest) -> dict[str, Any]:
    """Open specified DXF/DWG file directly in installed Autodesk AutoCAD 2026."""
    target_path = Path(payload.path).resolve()
    if not target_path.is_file():
        raise HTTPException(status_code=404, detail=f"Чертеж не найден: {payload.path}")

    if not AUTOCAD_PATH.is_file():
        # Fallback to system default associate
        subprocess.Popen(["cmd.exe", "/c", "start", "", str(target_path)])
        return {"status": "started", "app": "system_default", "path": str(target_path)}

    subprocess.Popen([str(AUTOCAD_PATH), str(target_path)])
    return {"status": "started", "app": "AutoCAD 2026", "path": str(target_path)}


@router.post("/open-recap")
def open_recap(payload: OpenPathRequest | None = None) -> dict[str, Any]:
    """Open Autodesk ReCap, optionally loading a specified project or scan file."""
    if not RECAP_PATH.is_file():
        raise HTTPException(status_code=404, detail="Autodesk ReCap не найден на компьютере.")

    cmd = [str(RECAP_PATH)]
    if payload and payload.path:
        target = Path(payload.path).resolve()
        if target.exists():
            cmd.append(str(target))

    subprocess.Popen(cmd)
    return {"status": "started", "app": "Autodesk ReCap"}


@router.post("/open-explorer")
def open_explorer(payload: OpenPathRequest) -> dict[str, Any]:
    """Open Windows File Explorer focused on the specified folder or file."""
    target_path = Path(payload.path).resolve()
    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"Путь не найден: {payload.path}")

    if target_path.is_file():
        subprocess.Popen(["explorer.exe", f"/select,{str(target_path)}"])
    else:
        subprocess.Popen(["explorer.exe", str(target_path)])

    return {"status": "opened", "path": str(target_path)}


@router.post("/pick-file")
def pick_file(payload: FileDialogRequest | None = None) -> dict[str, Any]:
    """Open native Windows OpenFileDialog to choose point clouds without browser upload limits."""
    title = payload.title if payload else "Выберите файл облака точек"
    filter_str = "Облака точек (*.rcs;*.rcp;*.e57;*.las;*.laz;*.ply)|*.rcs;*.rcp;*.e57;*.las;*.laz;*.ply|Все файлы (*.*)|*.*"

    ps_script = f"""
    Add-Type -AssemblyName System.Windows.Forms
    $f = New-Object System.Windows.Forms.OpenFileDialog
    $f.Title = '{title}'
    $f.Filter = '{filter_str}'
    if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
        Write-Output $f.FileName
    }}
    """
    try:
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True, timeout=120)
        chosen_path = res.stdout.strip()
        if chosen_path and Path(chosen_path).is_file():
            p = Path(chosen_path)
            return {
                "cancelled": False,
                "path": str(p),
                "filename": p.name,
                "size_bytes": p.stat().st_size,
                "extension": p.suffix.lower().lstrip("."),
            }
        return {"cancelled": True, "path": None}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
