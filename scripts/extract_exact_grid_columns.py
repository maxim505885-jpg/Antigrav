"""Legacy filename: export measured column candidates without inventing a grid."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from scan2bim.pipeline_single_pass import _candidate_record, _load_geometry
from scan2bim.recognition.geometric import detect_structures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("positions", type=Path, help="path to a derived positions.npy file")
    parser.add_argument("--output", type=Path, default=Path("data/output/column_candidates.json"))
    args = parser.parse_args()

    geometry, provenance = _load_geometry(args.positions)
    result = detect_structures(geometry)
    columns = [
        _candidate_record(element)
        for element in result.elements
        if element.class_name == "column"
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "source": provenance,
        "issue": "review_only",
        "review_state": "unreviewed",
        "grid_step_m": 6.0,
        "grid_step_note": "nominal step only; axis origin, rows and physical IDs are not established",
        "columns": columns,
        "candidate_count": len(columns),
        "warnings": result.warnings,
    }, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Сохранено {len(columns)} измеренных кандидатов колонн; типы и оси требуют проверки: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
