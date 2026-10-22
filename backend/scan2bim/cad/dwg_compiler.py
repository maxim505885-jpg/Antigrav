"""Native AutoCAD DWG Compiler (Автоматический фоновый транслятор в бинарный .DWG).

Использует сертифицированный COM/ActiveX интерфейс установленного Autodesk AutoCAD 2026.
Автоматически конвертирует любые сформированные чертежи СПДС из .DXF в нативный бинарный формат .DWG (AutoCAD 2018-2026 format AC1032),
выполняет ZOOM EXTENTS и сохраняет файл без необходимости участия человека.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def convert_dxf_to_dwg_native(
    dxf_path: str | Path,
    dwg_path: str | Path | None = None,
    zoom_extents: bool = True,
) -> Path:
    """Конвертирует DXF файл в нативный бинарный DWG файл через AutoCAD Automation API."""
    import win32com.client

    src_dxf = Path(dxf_path).resolve()
    if not src_dxf.is_file():
        raise FileNotFoundError(f"Исходный DXF чертеж не найден: {src_dxf}")

    dest_dwg = Path(dwg_path).resolve() if dwg_path is not None else src_dxf.with_suffix(".dwg")
    dest_dwg.parent.mkdir(parents=True, exist_ok=True)

    if dest_dwg.exists():
        try:
            dest_dwg.unlink()
        except Exception:
            pass

    acad = win32com.client.Dispatch("AutoCAD.Application")
    # Открываем DXF в фоновом режиме через Document Management
    doc = acad.Documents.Open(str(src_dxf))

    try:
        if zoom_extents:
            try:
                acad.ActiveDocument.SendCommand("._ZOOM _E\n")
            except Exception:
                pass
        # Сохраняем как нативный бинарный DWG (формат AC1032)
        doc.SaveAs(str(dest_dwg))
    finally:
        # Закрываем рабочий документ без повторного сохранения
        try:
            doc.Close(False)
        except Exception:
            pass

    if not dest_dwg.is_file() or dest_dwg.stat().st_size == 0:
        raise RuntimeError(f"Не удалось скомпилировать бинарный DWG: {dest_dwg}")

    return dest_dwg


def batch_convert_album_to_dwg(album_dir: str | Path) -> list[Path]:
    """Пакетно компилирует все DXF чертежи альбома в бинарные DWG."""
    target_dir = Path(album_dir)
    dxf_files = sorted(target_dir.glob("*.dxf"))
    created_dwgs = []

    for dxf in dxf_files:
        try:
            dwg = convert_dxf_to_dwg_native(dxf)
            created_dwgs.append(dwg)
            print(f"Скомпилирован нативный DWG: {dwg.name} ({dwg.stat().st_size / 1024:.1f} KB)")
        except Exception as e:
            print(f"Ошибка при компиляции {dxf.name} в DWG: {e}")

    return created_dwgs
