"""Acceptance check: DXF -> native DWG through the production accoreconsole path.

The drawing is built here with ezdxf so the check is reproducible without a
project database. The conversion uses the same function the API uses
(``scan2bim.cad.dwg_compiler.convert_dxf_to_dwg_accore``), and the produced DWG
is then opened by AutoCAD itself, which reports the marker text, its insertion
point and the entity count. A DWG that AutoCAD cannot open, or that lost the
geometry, fails the check instead of being reported as converted.

Exit codes: 0 passed, 1 failed, 2 the host cannot run the check (no AutoCAD).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import ezdxf  # noqa: E402

from scan2bim.cad.dwg_compiler import (  # noqa: E402
    convert_dxf_to_dwg_accore,
    find_accoreconsole,
    find_seed_dwg,
    is_valid_dwg,
)

MARKER = "SCAN_ACCEPTANCE_MARKER"
MARKER_XY = (12.75, 4.25)
POSITION_TOLERANCE_M = 0.0005

READBACK_SCRIPT = f"""(setvar "CMDECHO" 0)
(princ "\\nSCAN_READBACK_BEGIN")
(setq s (ssget "_X"))
(princ (strcat "\\nSCAN_ENTITY_COUNT=" (if s (itoa (sslength s)) "0")))
(setq ms (ssget "_X" (list (cons 0 "TEXT") (cons 1 "{MARKER}"))))
(princ (strcat "\\nSCAN_MARKER_COUNT=" (if ms (itoa (sslength ms)) "0")))
(if ms
  (progn
    (setq d (entget (ssname ms 0)))
    (setq p (cdr (assoc 10 d)))
    (princ (strcat "\\nSCAN_MARKER_XYZ="
      (rtos (car p) 2 6) "," (rtos (cadr p) 2 6) "," (rtos (caddr p) 2 6)))
    (princ (strcat "\\nSCAN_MARKER_LAYER=" (cdr (assoc 8 d))))
  )
)
(princ (strcat "\\nSCAN_ACADVER=" (getvar "ACADVER")))
(princ "\\nSCAN_READBACK_END")
(command "_.QUIT" "_Y")
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dwg_header(path: Path) -> str | None:
    if not path.is_file() or path.stat().st_size < 1024:
        return None
    with open(path, "rb") as handle:
        head = handle.read(6)
    return head.decode("ascii", errors="replace") if head.startswith(b"AC10") else None


def build_source_dxf(dxf_path: Path) -> dict[str, Any]:
    """A small but representative sheet: lines, circle, closed polyline, text."""
    doc = ezdxf.new("R2018", setup=True)
    doc.layers.add("SCAN-ACCEPT", color=3)
    msp = doc.modelspace()
    attributes = {"layer": "SCAN-ACCEPT"}
    msp.add_line((0.0, 0.0), (14.0, 0.0), dxfattribs=attributes)
    msp.add_line((14.0, 0.0), (14.0, 9.0), dxfattribs=attributes)
    msp.add_circle((5.0, 4.0), 2.5, dxfattribs=attributes)
    msp.add_lwpolyline([(0, 0), (4, 0), (4, 3), (0, 3)], close=True, dxfattribs=attributes)
    msp.add_text(MARKER, height=0.5, dxfattribs=attributes).set_placement(MARKER_XY)
    doc.saveas(dxf_path)

    counts: dict[str, int] = {}
    for entity in msp:
        counts[entity.dxftype()] = counts.get(entity.dxftype(), 0) + 1
    return {
        "path": str(dxf_path),
        "size_bytes": dxf_path.stat().st_size,
        "sha256": sha256(dxf_path),
        "entity_counts": counts,
        "entity_total": sum(counts.values()),
        "marker_xy": list(MARKER_XY),
    }


def read_back(dwg_path: Path, accore: Path, work_dir: Path) -> dict[str, Any]:
    """Open the DWG with AutoCAD and read the marker geometry back."""
    script = work_dir / f"readback_{uuid.uuid4().hex[:8]}.scr"
    script.write_text(READBACK_SCRIPT, encoding="ascii", newline="\r\n")
    command = [str(accore), "/i", str(dwg_path), "/s", str(script), "/l", "en-US"]
    started = time.time()
    process = subprocess.run(
        command,
        capture_output=True,
        timeout=180,
        stdin=subprocess.DEVNULL,
    )
    elapsed = round(time.time() - started, 2)
    # accoreconsole writes UTF-16 to its console; fall back to UTF-8 for other builds.
    raw = (process.stdout or b"") + (process.stderr or b"")
    if raw.count(b"\x00") > len(raw) // 4:
        output = raw.decode("utf-16-le", errors="replace")
    else:
        output = raw.decode("utf-8", errors="replace")
    result: dict[str, Any] = {
        "exit_code": process.returncode,
        "elapsed_seconds": elapsed,
        "opened": "SCAN_READBACK_BEGIN" in output and "SCAN_READBACK_END" in output,
        "entity_count": None,
        "marker_count": None,
        "marker_xyz": None,
        "marker_layer": None,
        "acad_version": None,
        "output_tail": output[-2000:],
    }
    # accoreconsole echoes the script back, so only the trailing (real) answers count.
    def last_int(key: str) -> int | None:
        found = re.findall(rf"{key}=(\d+)", output)
        return int(found[-1]) if found else None

    result["entity_count"] = last_int("SCAN_ENTITY_COUNT")
    result["marker_count"] = last_int("SCAN_MARKER_COUNT")
    numbers = re.findall(
        r"SCAN_MARKER_XYZ=(-?\d+\.?\d*),(-?\d+\.?\d*),(-?\d+\.?\d*)", output
    )
    result["marker_xyz"] = [float(value) for value in numbers[-1]] if numbers else None
    layers = re.findall(r"SCAN_MARKER_LAYER=([A-Za-z0-9_\-]+)", output)
    if layers:
        result["marker_layer"] = layers[-1]
    versions = re.findall(r"SCAN_ACADVER=([0-9.]+)", output)
    if versions:
        result["acad_version"] = versions[-1]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "docs" / "validation",
        help="каталог для JSON-протокола",
    )
    parser.add_argument("--keep", action="store_true", help="оставить рабочие файлы проверки")
    parser.add_argument("--dxf", type=Path, default=None, help="проверить готовый DXF вместо синтетического")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    record: dict[str, Any] = {
        "check": "autocad_accoreconsole_acceptance",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "host": sys.platform,
        "python": sys.version.split()[0],
        "failures": [],
        "notes": [],
    }

    accore = find_accoreconsole()
    seed = find_seed_dwg()
    record["accoreconsole"] = str(accore) if accore else None
    record["seed_drawing"] = str(seed) if seed else None

    if accore is None or seed is None:
        record["result"] = "unavailable"
        record["reason"] = (
            "accoreconsole.exe или опорный DWG не найдены: на этом хосте AutoCAD не установлен."
        )
        args.out.mkdir(parents=True, exist_ok=True)
        target = args.out / f"AUTOCAD_ACCORECONSOLE_{stamp}.json"
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[unavailable] {record['reason']}")
        print(f"протокол: {target}")
        return 2

    if args.dxf and not args.dxf.resolve().is_file():
        record["result"] = "failed"
        record["failures"].append(f"исходный DXF не найден: {args.dxf}")
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        args.out.mkdir(parents=True, exist_ok=True)
        target = args.out / f"AUTOCAD_ACCORECONSOLE_{stamp}.json"
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[failed] исходный DXF не найден: {args.dxf}")
        print(f"протокол: {target}")
        return 1

    work_dir = Path(tempfile.mkdtemp(prefix="s2b_accore_"))
    try:
        if args.dxf:
            source_dxf = args.dxf.resolve()
            record["source"] = {
                "path": str(source_dxf),
                "size_bytes": source_dxf.stat().st_size,
                "sha256": sha256(source_dxf),
                "entity_counts": None,
                "marker_xy": None,
            }
        else:
            source_dxf = work_dir / "acceptance_sheet.dxf"
            record["source"] = build_source_dxf(source_dxf)

        dwg_path = work_dir / "acceptance_sheet.dwg"
        started = time.time()
        try:
            convert_dxf_to_dwg_accore(source_dxf, dwg_path)
        except Exception as exc:  # noqa: BLE001 - the reason is the result
            record["conversion_error"] = f"{type(exc).__name__}: {exc}"
            record["conversion_elapsed_seconds"] = round(time.time() - started, 2)
            record["dwg"] = {"path": str(dwg_path), "exists": dwg_path.is_file()}
            record["failures"].append("конвертация DXF → DWG не завершилась")
            record["result"] = "failed"
        else:
            record["conversion_elapsed_seconds"] = round(time.time() - started, 2)
            record["dwg"] = {
                "path": str(dwg_path),
                "exists": dwg_path.is_file(),
                "size_bytes": dwg_path.stat().st_size if dwg_path.is_file() else 0,
                "sha256": sha256(dwg_path) if dwg_path.is_file() else None,
                "header": dwg_header(dwg_path),
                "header_valid": is_valid_dwg(dwg_path),
            }
            if not is_valid_dwg(dwg_path):
                record["failures"].append("DWG отсутствует или его заголовок не AC10xx")

            readback = read_back(dwg_path, accore, work_dir)
            record["readback"] = readback
            if not readback["opened"]:
                record["failures"].append(
                    "AutoCAD не открыл полученный DWG (нет маркеров сеанса чтения)"
                )
            if readback["marker_count"] != 1:
                record["failures"].append(
                    f"маркер {MARKER} найден в DWG {readback['marker_count'] or 0} раз вместо 1"
                )
            elif readback["marker_xyz"] is not None:
                deviation = max(
                    abs(readback["marker_xyz"][axis] - MARKER_XY[axis]) for axis in range(2)
                )
                record["marker_deviation_m"] = round(deviation, 9)
                if deviation > POSITION_TOLERANCE_M:
                    record["failures"].append(
                        f"координаты маркера в DWG отличаются на {deviation * 1000:.3f} мм"
                    )
            if readback["marker_layer"] not in {None, "SCAN-ACCEPT"}:
                record["failures"].append(
                    f"слой маркера изменился: {readback['marker_layer']}"
                )
            if (
                record["source"].get("entity_total")
                and readback["entity_count"] is not None
                and readback["entity_count"] < record["source"]["entity_total"]
            ):
                record["failures"].append(
                    f"в DWG {readback['entity_count']} объектов, в исходном DXF {record['source']['entity_total']}"
                )

            if not record["failures"]:
                record["notes"].append(
                    "Опорный DWG мог содержать собственные объекты, поэтому проверяется "
                    "не равенство счётчиков, а наличие маркера и его координаты."
                )
            record["result"] = "passed" if not record["failures"] else "failed"

        if args.keep:
            kept = args.out / "artifacts" / f"autocad_acceptance_{stamp}"
            kept.mkdir(parents=True, exist_ok=True)
            for path in (source_dxf, dwg_path):
                if path.is_file():
                    shutil.copy2(path, kept / path.name)
            record["artifacts"] = str(kept)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"AUTOCAD_ACCORECONSOLE_{stamp}.json"
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    status = record.get("result", "failed")
    print(f"[{status}] accoreconsole: {record['accoreconsole']}")
    if record.get("dwg"):
        print(
            f"DWG: {record['dwg'].get('size_bytes', 0)} байт, заголовок "
            f"{record['dwg'].get('header') or 'нет'}, SHA-256 {str(record['dwg'].get('sha256'))[:16]}…"
        )
    readback = record.get("readback") or {}
    if readback:
        print(
            f"Чтение AutoCAD: объектов {readback.get('entity_count')}, маркеров "
            f"{readback.get('marker_count')}, ACADVER {readback.get('acad_version')}"
        )
    for failure in record["failures"]:
        print(f"  FAIL: {failure}")
    print(f"протокол: {target}")
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
