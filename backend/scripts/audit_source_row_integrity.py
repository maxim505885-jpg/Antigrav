"""Read-only audit of persisted point-row provenance for recognition candidates.

Example (from the repository root)::

    python backend/scripts/audit_source_row_integrity.py \
      --db data/scan2bim.sqlite3 \
      --cloud-id 2621e5a320df49949d04aa1b7399539e workshop_cloud \
      --output docs/validation/SOURCE_ROW_AUDIT_2026-10-24.json

The database is opened with SQLite ``mode=ro``. The production alignment
inspector is reused; its cloud and path lookups are injected from the read-only
connection so this utility never opens the application's writable DB handle.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from scan2bim.learning import store  # noqa: E402
from scan2bim.learning.store import element_bbox_coordinate_frame  # noqa: E402
from scan2bim.storage import cloud_paths  # noqa: E402

INVALIDATED_SOURCE = "invalidated_synthetic_ground_truth"
JSON_FIELDS = {
    "metadata": "metadata_json",
    "geometry": "geometry_json",
    "bbox": "bbox_json",
}


def _decode_element(row: sqlite3.Row) -> dict[str, Any]:
    element = dict(row)
    for field, column in JSON_FIELDS.items():
        try:
            element[field] = json.loads(element.pop(column) or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"candidate {element.get('id')} has invalid {column}") from exc
    return element


def audit_cloud(connection: sqlite3.Connection, cloud_id: str) -> dict[str, Any]:
    cloud_row = connection.execute("SELECT * FROM clouds WHERE id = ?", (cloud_id,)).fetchone()
    if cloud_row is None:
        raise ValueError(f"cloud not found: {cloud_id}")
    cloud = dict(cloud_row)
    if cloud.get("status") != "ready":
        raise ValueError(f"cloud is not ready: {cloud_id} ({cloud.get('status')})")

    paths = cloud_paths(cloud["project_id"], cloud_id)
    positions_path = paths["positions"].resolve()
    if not positions_path.is_file():
        raise ValueError(f"positions array not found for cloud: {cloud_id}")

    candidate_rows = connection.execute(
        "SELECT id, cloud_id, class_name, geometry_json, bbox_json, source, "
        "review_status, metadata_json FROM elements "
        "WHERE cloud_id = ? AND source != ? ORDER BY class_name, id",
        (cloud_id, INVALIDATED_SOURCE),
    ).fetchall()

    previous_cloud_lookup = store._cloud
    previous_paths_lookup = store.cloud_paths

    def read_only_cloud_lookup(requested_id: str) -> dict[str, Any]:
        if requested_id != cloud_id:
            raise KeyError(f"unexpected cloud lookup: {requested_id}")
        return cloud

    def read_only_paths_lookup(project_id: str, requested_id: str) -> dict[str, Path]:
        if project_id != cloud["project_id"] or requested_id != cloud_id:
            raise KeyError(f"unexpected path lookup: {project_id}/{requested_id}")
        return paths

    store._cloud = read_only_cloud_lookup
    store.cloud_paths = read_only_paths_lookup
    try:
        positions = np.load(positions_path, mmap_mode="r", allow_pickle=False)
        try:
            stored_rows = int(positions.shape[0])
        finally:
            mmap = getattr(positions, "_mmap", None)
            if mmap is not None:
                mmap.close()
        origin = [cloud.get(f"origin_{axis}") or 0.0 for axis in ("x", "y", "z")]
        snapshot_id = store.point_cloud_snapshot(
            cloud_id, positions_path, stored_rows, origin,
        )["snapshot_id"]
        elements = [_decode_element(row) for row in candidate_rows]
        counts: Counter[str] = Counter()
        counts_by_class: dict[str, Counter[str]] = defaultdict(Counter)
        review_counts: Counter[str] = Counter()
        reasons_by_status: dict[str, Counter[str]] = defaultdict(Counter)
        snapshot_counts: Counter[str] = Counter()

        for element in elements:
            evidence = store.inspect_source_point_alignment(
                cloud_id, element, element_bbox_coordinate_frame(element),
            )
            status = evidence.get("status", "unverifiable")
            if status not in {"consistent", "mismatch", "unverifiable"}:
                status = "unverifiable"
            class_name = str(element.get("class_name") or "unknown")
            counts[status] += 1
            counts_by_class[class_name][status] += 1
            review_counts[str(element.get("review_status") or "unknown")] += 1
            reasons_by_status[status][str(evidence.get("reason") or "none")] += 1
            if evidence.get("snapshot_matches") is True:
                snapshot_counts["current"] += 1
            elif evidence.get("snapshot_matches") is False:
                snapshot_counts["stale"] += 1
            elif not (element.get("metadata") or {}).get("source_cloud_snapshot"):
                snapshot_counts["missing"] += 1
            else:
                snapshot_counts["unchecked"] += 1

        annotation_counts = {}
        table_names = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for table in ("column_annotations", "element_annotations"):
            annotation_counts[table] = (
                int(connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE cloud_id = ?", (cloud_id,),
                ).fetchone()[0]) if table in table_names else None
            )

        return {
            "cloud_id": cloud_id,
            "source_file_name": Path(str(cloud.get("source_path") or "")).name or None,
            "source_format": cloud.get("source_format"),
            "stored_rows": stored_rows,
            "source_rows_declared": int(cloud.get("point_count") or 0),
            "source_snapshot_id": snapshot_id,
            "candidate_count": len(elements),
            "candidate_status_counts": {
                name: int(counts.get(name, 0))
                for name in ("consistent", "mismatch", "unverifiable")
            },
            "status_counts_by_class": {
                class_name: {
                    name: int(class_counts.get(name, 0))
                    for name in ("consistent", "mismatch", "unverifiable")
                }
                for class_name, class_counts in sorted(counts_by_class.items())
            },
            "review_status_counts": dict(sorted(review_counts.items())),
            "reason_counts_by_status": {
                status: dict(sorted(reasons.items()))
                for status, reasons in sorted(reasons_by_status.items())
            },
            "source_snapshot_counts": {
                key: int(snapshot_counts.get(key, 0))
                for key in ("current", "missing", "stale", "unchecked")
            },
            "independent_annotation_counts": annotation_counts,
        }
    finally:
        store._cloud = previous_cloud_lookup
        store.cloud_paths = previous_paths_lookup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "data" / "scan2bim.sqlite3")
    parser.add_argument("--cloud-id", action="append", required=True, dest="cloud_ids")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    db_path = args.db.expanduser().resolve()
    if not db_path.is_file():
        parser.error(f"database does not exist: {db_path}")

    uri = f"{db_path.as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        report = {
            "audit_type": "read_only_candidate_source_row_alignment",
            "implementation": "backend/scan2bim/learning/store.py:inspect_source_point_alignment",
            "database": db_path.name,
            "database_mode": "read_only",
            "source_files_modified": False,
            "audit_date": datetime.now(timezone.utc).date().isoformat(),
            "clouds": [audit_cloud(connection, cloud_id) for cloud_id in args.cloud_ids],
            "interpretation": (
                "Source-row alignment verifies point provenance only. It does not measure "
                "physical detection accuracy, independent labels, or engineering tolerance."
            ),
            "acceptance": {
                "stage_6_closed": False,
                "reason": "Independent physical-reference annotations and holdout evaluation are still required.",
            },
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
