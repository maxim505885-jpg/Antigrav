"""Create a fresh, source-linked AutoCAD review package from frozen pilot A results."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import ezdxf

from scan2bim.cad.dxf import export_structural_plan_dxf
from scan2bim.cad.pdf import export_structural_plan_pdf, structural_schedule_from_dxf


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data/validation/pilot-A/recognition.json"
DEFAULT_OUTPUT = ROOT / "data/validation/pilot-A/autocad-review-v3"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare_package(source_path: Path, output_dir: Path) -> Path:
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite existing review package: {output_dir}")
    source_path = source_path.resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    elements: list[dict[str, Any]] = source.get("result", {}).get("elements", [])
    if not elements:
        raise ValueError("pilot recognition file has no result.elements")

    class_indices: dict[str, int] = defaultdict(int)
    girder_index = 0
    for element in elements:
        class_name = str(element.get("class_name") or "unknown")
        class_indices[class_name] += 1
        element["id"] = element.get("id") or f"candidate-{class_name}-{class_indices[class_name]:03d}"
        element["review_status"] = element.get("review_status") or "unreviewed"
        if class_name == "column":
            element["drawing_mark"] = f"C-{class_indices[class_name]:02d}"
        elif class_name == "beam" and (element.get("dimensions") or {}).get("role") == "crane_girder":
            girder_index += 1
            element["drawing_mark"] = f"G-{girder_index:02d}"

    output_dir.mkdir(parents=True)
    files: dict[str, dict[str, Any]] = {}
    expected_draft_counts = {"columns": 16, "crane_girders": 5}
    for drawing_type in ("columns", "crane_girders"):
        for issue_mode in ("draft", "final"):
            stem = f"{drawing_type}-{issue_mode}"
            dxf_path = output_dir / f"{stem}.dxf"
            pdf_path = output_dir / f"{stem}.pdf"
            export_structural_plan_dxf(elements, dxf_path, drawing_type,
                project_name="Пилот A · кандидаты без физической приёмки", issue_mode=issue_mode)
            export_structural_plan_pdf(elements, pdf_path, drawing_type,
                project_name="Пилот A · кандидаты без физической приёмки", issue_mode=issue_mode)

            document = ezdxf.readfile(dxf_path)
            audit = document.audit()
            schedule = structural_schedule_from_dxf(document)
            ids = [row[1] for row in schedule["rows"]]
            statuses = Counter(row[4] for row in schedule["rows"])
            expected_count = expected_draft_counts[drawing_type] if issue_mode == "draft" else 0
            if audit.has_errors or audit.fixes or len(ids) != expected_count or len(ids) != len(set(ids)):
                raise RuntimeError(
                    f"unexpected {stem} QA: errors={len(audit.errors)}, fixes={len(audit.fixes)}, "
                    f"rows={len(ids)}, expected={expected_count}, unique={len(set(ids))}"
                )
            if issue_mode == "draft" and any(status != "КАНДИДАТ" for status in statuses):
                raise RuntimeError(f"draft schedule includes a non-candidate status: {statuses}")
            if issue_mode == "final" and statuses:
                raise RuntimeError(f"unreviewed elements leaked into final schedule: {statuses}")

            for path in (dxf_path, pdf_path):
                files[path.name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
            files[dxf_path.name].update({
                "schedule_rows": len(ids),
                "schedule_ids": ids,
                "schedule_statuses": dict(statuses),
                "ezdxf_errors": len(audit.errors),
                "ezdxf_fixes": len(audit.fixes),
            })

    manifest = {
        "schema": "scan.autocad-review-package/1",
        "source": str(source_path.relative_to(ROOT)),
        "source_sha256": sha256(source_path),
        "issue_date": "2026-10-21",
        "project_acceptance": "pending",
        "engineering_tolerance_mm": None,
        "nominal_longitudinal_column_pitch_mm": 6000,
        "caution": "Candidate IDs are generated for this review package; they are not physical column IDs or accepted SCAN IDs.",
        "source_element_counts": dict(Counter(str(e.get("class_name", "unknown")) for e in elements)),
        "files": files,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_dir / "manifest.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = prepare_package(args.source, args.out)
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
