"""Native AutoCAD DWG Compiler (Автоматический фоновый транслятор в бинарный .DWG).

Использует официальную консольную утилиту Autodesk AutoCAD Core Console (accoreconsole.exe)
или сертифицированный COM/ActiveX интерфейс установленного AutoCAD.

Автоматически компилирует любые сформированные чертежи СПДС из .DXF в нативный бинарный формат .DWG (AutoCAD 2018-2026 format AC1032),
выполняет ZOOM EXTENTS и сохраняет готовый файл прямо рядом с исходным DXF.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ODA_CANDIDATE_PATHS = [
    Path(r"C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe"),
    Path(r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe"),
    Path(r"C:\Program Files (x86)\ODA\ODAFileConverter\ODAFileConverter.exe"),
]

ACCORE_CANDIDATE_PATHS = [
    Path(r"C:\Program Files\Autodesk\AutoCAD 2026\accoreconsole.exe"),
    Path(r"C:\Program Files\Autodesk\AutoCAD 2025\accoreconsole.exe"),
    Path(r"C:\Program Files\Autodesk\AutoCAD 2024\accoreconsole.exe"),
]

SEED_DWG_CANDIDATES = [
    Path(r"C:\Program Files\Autodesk\AutoCAD 2026\Express\brkline.dwg"),
    Path(r"C:\Program Files\Autodesk\AutoCAD 2026\UserDataCache\Template\acadiso.dwt"),
    Path(r"C:\Program Files\Autodesk\AutoCAD 2026\UserDataCache\Template\acad.dwt"),
]


def find_oda_converter() -> Path | None:
    """Find an installed ODAFileConverter binary.

    S2B_ODA_CONVERTER wins when the deployment keeps the converter somewhere
    unusual; otherwise known install roots are scanned so a minor version bump
    (27.1.0 -> 27.2.0) does not silently disable DWG export.
    """
    override = os.environ.get("S2B_ODA_CONVERTER")
    if override:
        candidate = Path(override)
        if candidate.is_file():
            return candidate
    for p in ODA_CANDIDATE_PATHS:
        if p.is_file():
            return p
    for root in (
        Path(r"C:\Program Files\ODA"),
        Path(r"C:\Program Files (x86)\ODA"),
        Path("/opt/ODA"),
        Path("/usr/local/ODA"),
    ):
        if not root.is_dir():
            continue
        for match in sorted(root.glob("ODAFileConverter*/ODAFileConverter*"), reverse=True):
            if match.is_file():
                return match
    return None


def find_accoreconsole() -> Path | None:
    """Find installed accoreconsole.exe binary."""
    for p in ACCORE_CANDIDATE_PATHS:
        if p.is_file():
            return p
    return None


def find_seed_dwg() -> Path | None:
    """Find a minimal seed drawing to bootstrap accoreconsole."""
    for p in SEED_DWG_CANDIDATES:
        if p.is_file():
            return p
    return None


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


def convert_dxf_to_dwg_oda(
    dxf_path: Path,
    dwg_path: Path,
    timeout_sec: int = 120,
) -> Path:
    """Headless compilation via ODAFileConverter (Open Design Alliance)."""
    oda = find_oda_converter()
    if not oda:
        raise FileNotFoundError("ODAFileConverter не найден в системных каталогах")

    tmp_dir = Path(tempfile.gettempdir()).resolve() / f"s2b_oda_{uuid.uuid4().hex[:8]}"
    in_dir = tmp_dir / "in"
    out_dir = tmp_dir / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        temp_dxf = in_dir / dxf_path.name
        shutil.copy2(dxf_path, temp_dxf)
        cmd = [
            str(oda),
            str(in_dir),
            str(out_dir),
            "ACAD2018",
            "DWG",
            "0",
            "1",
            "*.dxf",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
        out_dwg = out_dir / (temp_dxf.stem + ".dwg")
        if not out_dwg.is_file() or not is_valid_dwg(out_dwg):
            raise RuntimeError(f"ODAFileConverter не создал валидный DWG файл. Вывод: {proc.stderr}")

        dwg_path.parent.mkdir(parents=True, exist_ok=True)
        if dwg_path.exists():
            try:
                dwg_path.unlink()
            except Exception:
                pass
        shutil.move(str(out_dwg), str(dwg_path))
        return dwg_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def convert_dxf_to_dwg_accore(
    dxf_path: Path,
    dwg_path: Path,
    timeout_sec: int = 20,
) -> Path:
    """Headless compilation via AutoCAD Core Console (accoreconsole.exe)."""
    accore = find_accoreconsole()
    if not accore:
        raise FileNotFoundError("accoreconsole.exe не найден в системных каталогах AutoCAD")

    seed_dwg = find_seed_dwg()
    if not seed_dwg:
        raise FileNotFoundError("Шаблон seed DWG не найден для accoreconsole")

    tmp_dir = Path(tempfile.gettempdir()).resolve()
    session_id = uuid.uuid4().hex[:8]

    temp_input_dwg = tmp_dir / f"s2b_seed_{session_id}.dwg"
    shutil.copy2(seed_dwg, temp_input_dwg)

    temp_dxf = tmp_dir / f"s2b_in_{session_id}.dxf"
    shutil.copy2(dxf_path, temp_dxf)

    temp_out_dwg = tmp_dir / f"s2b_out_{session_id}.dwg"
    if temp_out_dwg.exists():
        temp_out_dwg.unlink()

    scr_file = tmp_dir / f"s2b_run_{session_id}.scr"
    scr_content = f"""(setvar "CMDECHO" 0)
(command "_.DXFIN" "{temp_dxf.name}")
(command "_.ZOOM" "_E")
(command "_.SAVEAS" "2018" "{temp_out_dwg.name}")
(command "_.QUIT" "_Y")
"""
    scr_file.write_text(scr_content, encoding="ascii")

    cmd = [
        str(accore),
        "/i", str(temp_input_dwg),
        "/s", str(scr_file),
        "/l", "en-US",
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(tmp_dir),
        )
        stdout, stderr = proc.communicate(input='(command "_.QUIT" "_Y")\n', timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        raise TimeoutError(f"Таймаут компиляции accoreconsole ({timeout_sec}с)")
    finally:
        # Cleanup temporary scratch files
        for p in (temp_input_dwg, temp_dxf, scr_file):
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass

    if not temp_out_dwg.is_file() or not is_valid_dwg(temp_out_dwg):
        raise RuntimeError(f"accoreconsole не создал валидный DWG файл. Вывод:\n{stdout[-400:]}")

    dwg_path.parent.mkdir(parents=True, exist_ok=True)
    if dwg_path.exists():
        try:
            dwg_path.unlink()
        except Exception:
            pass

    shutil.move(str(temp_out_dwg), str(dwg_path))
    return dwg_path


def convert_dxf_to_dwg_com(
    dxf_path: Path,
    dwg_path: Path,
    zoom_extents: bool = True,
) -> Path:
    """Fallback compilation via AutoCAD COM/ActiveX Automation."""
    import win32com.client

    acad = win32com.client.Dispatch("AutoCAD.Application")
    doc = acad.Documents.Open(str(dxf_path.resolve()))

    try:
        if zoom_extents:
            try:
                acad.ActiveDocument.SendCommand("._ZOOM _E\n")
            except Exception:
                pass
        doc.SaveAs(str(dwg_path.resolve()))
    finally:
        try:
            doc.Close(False)
        except Exception:
            pass

    if not is_valid_dwg(dwg_path):
        raise RuntimeError(f"COM Automation не создал валидный DWG: {dwg_path}")

    return dwg_path


def convert_dxf_to_dwg_native(
    dxf_path: str | Path,
    dwg_path: str | Path | None = None,
    zoom_extents: bool = True,
    force_recompile: bool = False,
) -> Path:
    """Конвертирует DXF файл в нативный бинарный DWG файл (AutoCAD 2018-2026 format AC1032)."""
    src_dxf = Path(dxf_path).resolve()
    if not src_dxf.is_file():
        raise FileNotFoundError(f"Исходный DXF чертеж не найден: {src_dxf}")

    dest_dwg = Path(dwg_path).resolve() if dwg_path is not None else src_dxf.with_suffix(".dwg")
    dest_dwg.parent.mkdir(parents=True, exist_ok=True)

    # Если уже есть скомпилированный валидный DWG файл и он новее или равен DXF, возвращаем его
    if not force_recompile and is_valid_dwg(dest_dwg) and dest_dwg.stat().st_mtime >= src_dxf.stat().st_mtime:
        return dest_dwg

    # 1. Попытка компиляции через быстрый headless ODAFileConverter
    if find_oda_converter():
        try:
            return convert_dxf_to_dwg_oda(src_dxf, dest_dwg)
        except Exception as exc:
            logger.warning(f"ODAFileConverter error: {exc}. Пробуем accoreconsole...")

    # 2. Попытка компиляции через accoreconsole.exe
    if find_accoreconsole() and find_seed_dwg():
        try:
            return convert_dxf_to_dwg_accore(src_dxf, dest_dwg)
        except Exception as exc:
            logger.warning(f"accoreconsole error: {exc}. Пробуем COM Automation...")

    # 3. Запасная попытка через COM Automation
    try:
        return convert_dxf_to_dwg_com(src_dxf, dest_dwg, zoom_extents=zoom_extents)
    except Exception as exc:
        logger.error(f"COM Automation error: {exc}")

    # Если DWG уже существовал, проверяем его
    if is_valid_dwg(dest_dwg):
        return dest_dwg

    raise RuntimeError(f"Не удалось скомпилировать бинарный DWG файл для {src_dxf.name}")


def batch_convert_album_to_dwg(album_dir: str | Path) -> list[Path]:
    """Пакетно компилирует все DXF чертежи альбома в бинарные DWG."""
    target_dir = Path(album_dir)
    dxf_files = sorted(target_dir.glob("*.dxf"))
    created_dwgs = []

    # Быстрый пакетный прогон через ODAFileConverter
    oda = find_oda_converter()
    if oda and dxf_files:
        try:
            cmd = [
                str(oda),
                str(target_dir),
                str(target_dir),
                "ACAD2018",
                "DWG",
                "0",
                "1",
                "*.dxf",
            ]
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            for dxf in dxf_files:
                dwg = dxf.with_suffix(".dwg")
                if is_valid_dwg(dwg):
                    created_dwgs.append(dwg)
            if len(created_dwgs) == len(dxf_files):
                return created_dwgs
        except Exception as exc:
            logger.warning(f"Пакетная ODA конвертация не завершилась: {exc}")

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
