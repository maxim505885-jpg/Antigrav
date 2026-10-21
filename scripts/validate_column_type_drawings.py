"""Reproducible synthetic CAD/PDF layout check; no source scan or work DB."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import ezdxf
from ezdxf import bbox
from scan2bim.cad.dxf import export_structural_plan_dxf
from scan2bim.cad.pdf import export_structural_plan_pdf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "data/validation/column-types-qa")
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--scale", type=int, default=100, choices=[50, 100, 200, 500])
    args = parser.parse_args()
    if not 1 <= args.count <= 5000:
        parser.error("--count must be between 1 and 5000")
    args.out.mkdir(parents=True, exist_ok=True)
    elements = []
    grid_columns = 3 if args.count <= 6 else 10
    for index in range(args.count):
        elements.append({
            "id": f"synthetic-column-{index + 1:02d}", "class_name": "column", "measured": True,
            "inferred": False, "review_status": "unreviewed",
            "geometry": {"kind": "oriented_box", "center": [index % grid_columns * 6, index // grid_columns * 12, 4],
                "rotation_z": math.pi / 2 if index % 2 else 0,
                "sizes": {"length": 0.5 + index * 0.001, "thickness": 0.4, "height": 8}},
        })
    prototype = {"representative_sides_m": {"long": 0.5, "short": 0.4}}
    confirmed_count = max(1, args.count * 2 // 3)
    catalog = [
        {"id": "synthetic-type", "mark": "К1", "status": "confirmed", "prototype": prototype,
            "member_element_ids": [item["id"] for item in elements[:confirmed_count]]},
        {"proposal_key": "synthetic-proposal", "status": "proposed", **prototype,
            "member_element_ids": [item["id"] for item in elements[confirmed_count:]]},
    ]
    dxf = export_structural_plan_dxf(elements, args.out / "synthetic-column-types.dxf", "columns",
        "СИНТЕТИЧЕСКИЙ ТЕСТ — не обмер цеха", column_types=catalog, annotation_scale=args.scale)
    pdf = export_structural_plan_pdf(elements, args.out / "synthetic-column-types.pdf", "columns",
        "СИНТЕТИЧЕСКИЙ ТЕСТ — не обмер цеха", column_types=catalog, scale=args.scale)
    document = ezdxf.readfile(dxf)
    audit = document.audit()
    bounds = bbox.extents(document.modelspace())
    fit_mm_per_model_m = min(16.54 * 25.4 * 0.93 / max(bounds.size.x, 1e-9),
        11.69 * 25.4 * 0.88 / max(bounds.size.y, 1e-9))
    report = {"synthetic": True, "elements": len(elements), "dxf": str(dxf), "pdf": str(pdf),
        "audit_errors": len(audit.errors), "audit_fixes": len(audit.fixes),
        "hypothetical_single_sheet_text_height_mm": round(0.2 * fit_mm_per_model_m, 3),
        "schedule_font_pt": 9, "plan_scale": f"1:{args.scale}", "plan_annotation_height_mm": 2.5}
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
