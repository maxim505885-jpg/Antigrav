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


def is_valid_dwg(file_path: Path) -> bool:
    """Проверяет валидность заголовка бинарного DWG файла (AutoCAD AC10xx)."""
    if not file_path.is_file() or file_path.stat().st_size < 1024:
        return False
    try:
        with open(file_path, "rb") as f:
            header = f.read(6)
        return header.startswith(b"AC10")
    except Exception:
        return False


def convert_dxf_to_dwg_native(
    dxf_path: str | Path,
    dwg_path: str | Path | None = None,
    zoom_extents: bool = True,
    force_recompile: bool = False,
) -> Path:
    """Конвертирует DXF файл в нативный бинарный DWG файл через AutoCAD Automation API."""
    import win32com.client

    src_dxf = Path(dxf_path).resolve()
    if not src_dxf.is_file():
        raise FileNotFoundError(f"Исходный DXF чертеж не найден: {src_dxf}")

    dest_dwg = Path(dwg_path).resolve() if dwg_path is not None else src_dxf.with_suffix(".dwg")
    dest_dwg.parent.mkdir(parents=True, exist_ok=True)

    # Если уже есть скомпилированный валидный DWG файл и он новее или равен DXF, возвращаем его
    if not force_recompile and is_valid_dwg(dest_dwg) and dest_dwg.stat().st_mtime >= src_dxf.stat().st_mtime:
        return dest_dwg

    try:
        if dest_dwg.exists():
            dest_dwg.unlink()
    except Exception:
        pass

    acad = win32com.client.Dispatch("AutoCAD.Application")
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
        try:
            doc.Close(False)
        except Exception:
            pass

    if not is_valid_dwg(dest_dwg):
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
            dest_dwg = dxf.with_suffix(".dwg")
            if is_valid_dwg(dest_dwg):
                created_dwgs.append(dest_dwg)
                print(f"Использован существующий валидный DWG: {dest_dwg.name} ({dest_dwg.stat().st_size / 1024:.1f} KB)")
                continue
            print(f"Ошибка при компиляции {dxf.name} в DWG: {e}")

    return created_dwgs
