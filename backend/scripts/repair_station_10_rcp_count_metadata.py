"""Repair count-comparison metadata on the live sampled Station 10 cloud.

The full RCS reader count is already stored in ``clouds.point_count``. The bug
compared the RCP declaration to the limited sample in ``ingested_count``.
This guarded migration updates only the derived ReCap metadata in SQLite and
the cloud sidecar; it never touches the RCP/RCS sources or sampled arrays.

Dry-run by default; use --apply after reviewing the printed preconditions:
    python backend/scripts/repair_station_10_rcp_count_metadata.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "scan2bim.sqlite3"
CLOUD_ID = "52370d1f13a147518dd2458886dafee5"
PROJECT_ID = "workshop_project"
DECLARED_COUNT = 295_836_062
SOURCE_COUNT = 295_591_803
SAMPLE_COUNT = 5_000_000
SOURCE_SHA256 = "a11497ab0e4649e18480a31eceb00e8552051ff2209f1ca031c2be5b1f693a4a"


def _object(value: str | None) -> dict:
    parsed = json.loads(value or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("cloud metadata must be a JSON object")
    return parsed


def _read(db_path: Path) -> tuple[dict, dict, Path]:
    connection = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT id,project_id,status,point_count,ingested_count,decimated,metadata_json "
            "FROM clouds WHERE id=?", (CLOUD_ID,),
        ).fetchone()
        if row is None:
            raise ValueError(f"cloud {CLOUD_ID} does not exist")
        cloud = dict(row)
        cloud["metadata"] = _object(cloud.pop("metadata_json"))
        active = connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE cloud_id=? AND status IN ('queued','running','cancelling')",
            (CLOUD_ID,),
        ).fetchone()[0]
        if active:
            raise ValueError(f"refusing metadata change while {active} cloud job(s) are active")
    finally:
        connection.close()
    meta_path = REPO_ROOT / "data" / "projects" / PROJECT_ID / "clouds" / CLOUD_ID / "meta.json"
    if not meta_path.is_file():
        raise ValueError(f"cloud sidecar is missing: {meta_path}")
    return cloud, _object(meta_path.read_text(encoding="utf-8")), meta_path


def _validate(cloud: dict, sidecar: dict) -> None:
    if cloud["project_id"] != PROJECT_ID or cloud["status"] != "ready":
        raise ValueError("cloud project or state changed; refusing update")
    if (cloud["point_count"], cloud["ingested_count"], bool(cloud["decimated"])) != (
        SOURCE_COUNT, SAMPLE_COUNT, True
    ):
        raise ValueError("cloud source/sample counts or decimation flag changed; re-audit")
    for metadata in (cloud["metadata"], sidecar):
        source = metadata.get("source_identity") or {}
        recap = metadata.get("recap_project") or {}
        node = recap.get("selected_node") or {}
        if metadata.get("source_point_count") != SOURCE_COUNT:
            raise ValueError("stored source count differs from audited RCS reader count")
        if metadata.get("stored_point_count") != SAMPLE_COUNT:
            raise ValueError("stored sample count differs from audited cloud")
        if source.get("sha256") != SOURCE_SHA256:
            raise ValueError("RCS source fingerprint differs from the audit")
        if node.get("declared_point_count") != DECLARED_COUNT:
            raise ValueError("RCP declared count differs from the audit")
        if recap.get("actual_ingested_point_count") != SAMPLE_COUNT:
            raise ValueError("unexpected previous ingested-count metadata; inspect manually")
        if recap.get("declared_point_count_difference") != DECLARED_COUNT - SAMPLE_COUNT:
            raise ValueError("existing erroneous difference changed; inspect before migration")


def _reconcile(metadata: dict) -> dict:
    result = dict(metadata)
    recap = dict(result["recap_project"])
    recap["actual_source_point_count"] = SOURCE_COUNT
    recap["actual_ingested_point_count"] = SAMPLE_COUNT
    recap["declared_point_count_difference"] = DECLARED_COUNT - SOURCE_COUNT
    recap["point_count_comparison"] = {
        "status": "reader_count_differs_from_rcp_declaration",
        "declared_rcp_point_count": DECLARED_COUNT,
        "actual_source_point_count": SOURCE_COUNT,
        "actual_ingested_sample_count": SAMPLE_COUNT,
        "declared_minus_source_points": DECLARED_COUNT - SOURCE_COUNT,
        "comparison_basis": "full source count read from linked RCS; excludes limited stored sample count",
    }
    result["recap_project"] = recap
    return result


def apply(db_path: Path, meta_path: Path, cloud: dict, sidecar: dict) -> dict:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    new_metadata = _reconcile(cloud["metadata"])
    new_sidecar = _reconcile(sidecar)
    db_backup = db_path.with_name(f"{db_path.name}.before-rcp-count-{timestamp}.bak")
    meta_backup = meta_path.with_name(f"{meta_path.name}.before-rcp-count-{timestamp}.bak")
    with sqlite3.connect(db_path) as source, sqlite3.connect(db_backup) as destination:
        source.backup(destination)
    shutil.copy2(meta_path, meta_backup)
    temp_meta = meta_path.with_name(meta_path.name + ".count-repair.tmp")
    temp_meta.write_text(json.dumps(new_sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        changed = connection.execute(
            "UPDATE clouds SET metadata_json=?,updated_at=? WHERE id=? AND point_count=? AND ingested_count=?",
            (json.dumps(new_metadata, ensure_ascii=False, separators=(",", ":")),
             datetime.now(timezone.utc).isoformat(timespec="seconds"), CLOUD_ID,
             SOURCE_COUNT, SAMPLE_COUNT),
        ).rowcount
        if changed != 1:
            raise ValueError("cloud changed during migration; no update committed")
        os.replace(temp_meta, meta_path)
        connection.commit()
    except BaseException:
        connection.rollback()
        shutil.copy2(meta_backup, meta_path)
        temp_meta.unlink(missing_ok=True)
        raise
    finally:
        connection.close()
    with sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True) as check:
        row = check.execute("SELECT metadata_json FROM clouds WHERE id=?", (CLOUD_ID,)).fetchone()
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
    verified = _object(row[0])["recap_project"]
    return {
        "status": "applied",
        "cloud_id": CLOUD_ID,
        "source_count": SOURCE_COUNT,
        "stored_sample_count": SAMPLE_COUNT,
        "declared_rcp_count": DECLARED_COUNT,
        "declared_minus_source": verified["declared_point_count_difference"],
        "source_sha256": SOURCE_SHA256,
        "source_modified": False,
        "database_integrity": integrity,
        "database_backup": str(db_backup),
        "metadata_backup": str(meta_backup),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--apply", action="store_true", help="write corrected derived metadata")
    args = parser.parse_args()
    cloud, sidecar, meta_path = _read(args.db)
    _validate(cloud, sidecar)
    if not args.apply:
        print(json.dumps({
            "status": "dry_run_ok",
            "cloud_id": CLOUD_ID,
            "source_count": SOURCE_COUNT,
            "stored_sample_count": SAMPLE_COUNT,
            "declared_rcp_count": DECLARED_COUNT,
            "old_sample_based_difference": DECLARED_COUNT - SAMPLE_COUNT,
            "correct_source_based_difference": DECLARED_COUNT - SOURCE_COUNT,
            "metadata_path": str(meta_path),
            "source_modified": False,
        }, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(apply(args.db, meta_path, cloud, sidecar), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
