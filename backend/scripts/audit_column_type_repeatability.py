"""Read-only sensitivity audit of repeated measured-column type proposals.

The default tolerance is the production API default (5 mm / 1%). Wider values
are exploratory only and must not be used to confirm catalog types without
physical labels and an agreed engineering tolerance.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from statistics import median
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from scan2bim.structure.column_types import column_descriptor, propose_column_types  # noqa: E402

TOLERANCES_M = (0.005, 0.01, 0.02, 0.05, 0.10)
RELATIVE_TOLERANCE = 0.01


def _json(value: str | None, field: str, element_id: str) -> dict[str, Any]:
    try:
        decoded = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"element {element_id} has invalid {field}") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"element {element_id} has non-object {field}")
    return decoded


def audit_cloud(connection: sqlite3.Connection, cloud_id: str) -> dict[str, Any]:
    cloud = connection.execute(
        "SELECT id,name,status,source_format,ingested_count FROM clouds WHERE id=?", (cloud_id,),
    ).fetchone()
    if cloud is None:
        raise ValueError(f"cloud not found: {cloud_id}")
    if cloud["status"] != "ready":
        raise ValueError(f"cloud is not ready: {cloud_id}")
    records = connection.execute(
        "SELECT id,class_name,geometry_json,dimensions_json,measured,inferred,source,review_status "
        "FROM elements WHERE cloud_id=? AND class_name='column' "
        "AND source!='invalidated_synthetic_ground_truth' ORDER BY id", (cloud_id,),
    ).fetchall()
    elements: list[dict[str, Any]] = []
    descriptors: list[dict[str, Any]] = []
    statuses: Counter[str] = Counter()
    ineligible_reasons: Counter[str] = Counter()
    morphology: Counter[str] = Counter()
    coverages: list[float] = []
    for row in records:
        element = {
            "id": row["id"],
            "class_name": row["class_name"],
            "geometry": _json(row["geometry_json"], "geometry_json", row["id"]),
            "dimensions": _json(row["dimensions_json"], "dimensions_json", row["id"]),
            "measured": bool(row["measured"]),
            "inferred": bool(row["inferred"]),
            "source": row["source"],
            "review_status": row["review_status"],
        }
        descriptor = column_descriptor(element)
        elements.append(element)
        statuses[str(element["dimensions"].get("section_status") or "missing")] += 1
        if descriptor["eligible"]:
            descriptors.append(descriptor)
            morphology[descriptor["morphology"]] += 1
            if descriptor["evidence_coverage"] is not None:
                coverages.append(float(descriptor["evidence_coverage"]))
        else:
            ineligible_reasons.update(descriptor["reasons"])

    sensitivity = []
    for tolerance_m in TOLERANCES_M:
        proposals = propose_column_types(
            elements,
            linear_tolerance_m=tolerance_m,
            relative_tolerance=RELATIVE_TOLERANCE,
        )
        group_sizes = [int(item["evidence_summary"]["member_count"]) for item in proposals]
        sensitivity.append({
            "linear_tolerance_m": tolerance_m,
            "relative_tolerance": RELATIVE_TOLERANCE,
            "groups": len(group_sizes),
            "repeated_groups": sum(size > 1 for size in group_sizes),
            "columns_in_repeated_groups": sum(size for size in group_sizes if size > 1),
            "largest_group": max(group_sizes, default=0),
            "group_size_histogram": {
                str(size): count for size, count in sorted(Counter(group_sizes).items())
            },
            "exploratory_only": tolerance_m != 0.005,
        })

    annotation_table = connection.execute(
        "SELECT COUNT(*) FROM column_annotations WHERE cloud_id=?", (cloud_id,),
    ).fetchone()[0]
    return {
        "cloud_id": cloud["id"],
        "cloud_name": cloud["name"],
        "source_format": cloud["source_format"],
        "stored_point_count": int(cloud["ingested_count"] or 0),
        "candidate_columns": len(records),
        "section_status_counts": dict(sorted(statuses.items())),
        "eligible_measured_sections": len(descriptors),
        "ineligible_reason_counts": dict(sorted(ineligible_reasons.items())),
        "eligible_morphology_counts": dict(sorted(morphology.items())),
        "eligible_section_coverage": {
            "count": len(coverages),
            "minimum": min(coverages) if coverages else None,
            "median": median(coverages) if coverages else None,
            "maximum": max(coverages) if coverages else None,
        },
        "independent_column_annotation_count": int(annotation_table),
        "type_grouping_sensitivity": sensitivity,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "data" / "scan2bim.sqlite3")
    parser.add_argument("--cloud-id", action="append", required=True, dest="cloud_ids")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    db_path = args.db.expanduser().resolve()
    if not db_path.is_file():
        parser.error(f"database does not exist: {db_path}")
    with sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "column_annotations" not in tables:
            parser.error("database has no independent column_annotations table")
        report = {
            "audit_type": "read_only_column_type_repeatability_sensitivity",
            "implementation": "production column_descriptor/propose_column_types",
            "database": db_path.name,
            "database_mode": "read_only",
            "audit_date": datetime.now(timezone.utc).date().isoformat(),
            "production_default_tolerance_m": 0.005,
            "production_relative_tolerance": RELATIVE_TOLERANCE,
            "wider_tolerances_are_exploratory_only": True,
            "clouds": [audit_cloud(connection, cloud_id) for cloud_id in args.cloud_ids],
            "interpretation": (
                "Type proposals compare only eligible stored measured dimensions. They do not prove that "
                "two candidates are the same physical column. No tolerance is calibrated here; wider "
                "thresholds are sensitivity analysis only. Independent field labels remain required."
            ),
            "acceptance": {"stage_6_closed": False, "stage_8_closed": False},
        }
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output_path = args.output.resolve()
        if not output_path.is_relative_to(REPO_ROOT):
            parser.error("--output must stay inside the repository")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
        print(output_path)
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
