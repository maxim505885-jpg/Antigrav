"""Create immutable synthetic BIM JSON fixtures for the Revit 2027 pilot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from scan2bim.bim.model import build_model


PROJECT = {"id": "revit-import-pilot", "name": "SCAN Revit importer verification"}
CLOUD = {
    "id": "synthetic-revit-import-fixture", "name": "Synthetic fixture", "source_format": "synthetic",
    "point_count": 0, "origin_x": 0.0, "origin_y": 0.0, "origin_z": 0.0,
}


def _column(element_id: str, x: float, *, length: float = 0.5) -> dict:
    y, z, thickness, height = 20.0, 3.0, 0.4, 6.0
    return {
        "id": element_id,
        "class_name": "column",
        "geometry": {
            "kind": "oriented_box", "center": [x, y, z],
            "sizes": {"length": length, "thickness": thickness, "height": height}, "rotation_z": 0.0,
        },
        "bbox": {"min": [x - length / 2, y - thickness / 2, 0.0],
                 "max": [x + length / 2, y + thickness / 2, height]},
        "confidence": 1.0, "confidence_kind": "synthetic_fixture", "measured": True, "inferred": False,
        "source": "synthetic_fixture", "review_status": "confirmed", "dimensions": {},
    }


def _beam() -> dict:
    return {
        "id": "SCAN-BEAM-KEEP", "class_name": "beam",
        "geometry": {"kind": "member", "p0": [10.0, 20.0, 6.0], "p1": [16.0, 20.0, 6.0], "section_m": 0.25},
        "bbox": {"min": [10.0, 19.875, 5.875], "max": [16.0, 20.125, 6.125]},
        "confidence": 1.0, "confidence_kind": "synthetic_fixture", "measured": True, "inferred": False,
        "source": "synthetic_fixture", "review_status": "confirmed", "dimensions": {},
    }


def _truss_envelope() -> dict:
    return {
        "id": "SCAN-TRUSS-UNSUPPORTED", "class_name": "truss",
        "geometry": {"kind": "member", "p0": [0.0, 0.0, 8.0], "p1": [6.0, 0.0, 9.0], "section_m": 0.2},
        "bbox": {"min": [0.0, -0.1, 8.0], "max": [6.0, 0.1, 9.0]},
        "confidence": 1.0, "confidence_kind": "synthetic_fixture", "measured": False, "inferred": True,
        "source": "synthetic_fixture", "review_status": "unreviewed", "dimensions": {},
    }


def _serialize(elements: list[dict], levels: list[dict] | None = None) -> dict:
    return build_model(PROJECT, CLOUD, elements, levels)


def _write(path: Path, model: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(model, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "integrations/revit/pilot")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    names = ("import-run-1.json", "import-run-2.json", "rollback-invalid-geometry.json")
    existing = [name for name in names if (args.out_dir / name).exists()]
    if existing:
        parser.error(f"refusing to overwrite existing fixture(s): {', '.join(existing)}")

    run1 = _serialize([
        _column("SCAN-COL-KEEP", 10.0),
        _column("SCAN-COL-CHANGE", 12.0),
        _column("SCAN-COL-OMIT", 14.0),
        _beam(),
    ], [{"z": 0.0, "method": "synthetic fixture"}, {"z": 6.0, "method": "synthetic fixture"}])
    run2 = _serialize([
        _column("SCAN-COL-KEEP", 10.0),
        _column("SCAN-COL-CHANGE", 12.1, length=0.6),
        _beam(),
        _truss_envelope(),
    ], [{"z": 0.0, "method": "synthetic fixture"}, {"z": 6.0, "method": "synthetic fixture"}])

    rollback = _serialize([
        _column("SCAN-ROLLBACK-COLUMN", 30.0),
        _beam(),
    ], [{"z": 99.0, "method": "rollback fixture only"}])
    rollback["elements"][1]["geometry"] = {"kind": "member", "p0": [0.0, 0.0, 0.0]}

    for name, model in zip(names, (run1, run2, rollback)):
        _write(args.out_dir / name, model)
    print(json.dumps({"output_dir": str(args.out_dir), "fixtures": list(names)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
