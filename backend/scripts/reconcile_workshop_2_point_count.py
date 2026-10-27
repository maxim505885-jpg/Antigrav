"""Correct the legacy Workshop 2 cloud's unverified source point count.

The old project-assembly script hard-coded 576,820,490 as source_point_count.
Two full sequential passes through the installed ReCap DLL observed 574,367,742
for the same source SHA-256. This script preserves the old claim as unverified
metadata and updates only the derived SQLite/meta.json records. The RCS source
and the 3.5M stored sample are never opened for writing.

Run without --apply for a guarded dry-run. Apply only after inspecting output:
    python backend/scripts/reconcile_workshop_2_point_count.py --apply
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
CLOUD_ID = "workshop_cloud_02"
PROJECT_ID = "workshop_project"
LEGACY_COUNT = 576_820_490
VERIFIED_COUNT = 574_367_742
SAMPLE_COUNT = 3_500_000
SOURCE_SHA256 = "784c2235541c89fbf78e02e28af8756a1040d46ff18111df3581b9b6b75b3792"
SOURCE_SIZE_BYTES = 13_906_332_111
SOURCE_MTIME_UTC = "2026-10-16T09:14:28.2322579Z"
DLL_VERSION = "24.0.0.240"


def _json_object(value: str | None) -> dict:
    parsed = json.loads(value or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("cloud metadata must be a JSON object")
    return parsed


def _read_current(db_path: Path) -> tuple[dict, dict, Path]:
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT id,project_id,status,point_count,ingested_count,decimated,source_path,metadata_json "
            "FROM clouds WHERE id=?",
            (CLOUD_ID,),
        ).fetchone()
        if row is None:
            raise ValueError(f"cloud {CLOUD_ID} does not exist")
        cloud = dict(row)
        cloud["metadata"] = _json_object(cloud.pop("metadata_json"))
        active = connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE cloud_id=? AND status IN ('queued','running','cancelling')",
            (CLOUD_ID,),
        ).fetchone()[0]
        if active:
            raise ValueError(f"refusing metadata change while {active} job(s) are active")
    finally:
        connection.close()

    cloud_dir = REPO_ROOT / "data" / "projects" / PROJECT_ID / "clouds" / CLOUD_ID
    meta_path = cloud_dir / "meta.json"
    if not meta_path.is_file():
        raise ValueError(f"cloud sidecar metadata is missing: {meta_path}")
    sidecar = _json_object(meta_path.read_text(encoding="utf-8"))
    return cloud, sidecar, meta_path


def _validate(cloud: dict, sidecar: dict) -> None:
    if cloud["project_id"] != PROJECT_ID or cloud["status"] != "ready":
        raise ValueError("cloud project or state changed; refusing update")
    if cloud["point_count"] != LEGACY_COUNT or cloud["ingested_count"] != SAMPLE_COUNT:
        raise ValueError("database counts differ from the audited legacy cloud; refusing update")
    if not cloud["decimated"]:
        raise ValueError("cloud no longer carries the expected decimated flag")
    metadata = cloud["metadata"]
    if metadata.get("source_point_count") != LEGACY_COUNT or metadata.get("stored_point_count") != SAMPLE_COUNT:
        raise ValueError("database metadata counts differ from the audited legacy cloud")
    if metadata.get("reader") != "rcs_native_stream":
        raise ValueError("legacy reader label changed; re-audit before applying")
    source = metadata.get("source_identity") or {}
    if source.get("sha256") != SOURCE_SHA256 or source.get("size_bytes") != SOURCE_SIZE_BYTES:
        raise ValueError("source identity differs from the repeated DLL recount evidence")
    if metadata.get("source_sha256") != SOURCE_SHA256:
        raise ValueError("metadata source hash differs from the repeated DLL recount evidence")
    if sidecar.get("source_point_count") != LEGACY_COUNT or sidecar.get("stored_point_count") != SAMPLE_COUNT:
        raise ValueError("sidecar counts differ from the audited legacy cloud")
    if (sidecar.get("source_identity") or {}).get("sha256") != SOURCE_SHA256:
        raise ValueError("sidecar source identity differs from the repeated DLL recount evidence")
    if "count_reconciliation" in metadata or "count_reconciliation" in sidecar:
        raise ValueError("count reconciliation is already present; inspect before retrying")


def _updated_metadata(old: dict, *, timestamp: str) -> dict:
    metadata = dict(old)
    metadata["reader"] = "recap-adskrcexport-dll"
    metadata["reader_version"] = DLL_VERSION
    metadata["source_point_count"] = VERIFIED_COUNT
    metadata["legacy_unverified_source_point_count"] = {
        "count": LEGACY_COUNT,
        "label": "rcs_native_stream",
        "status": "unverified_hard_coded_value",
        "origin": "scripts/prepare_both_workshop_clouds.py set this constant; no independent reader log was recorded",
    }
    metadata["count_reconciliation"] = {
        "status": "reconciled_to_repeated_full_dll_pass",
        "verified_source_point_count": VERIFIED_COUNT,
        "legacy_unverified_source_point_count": LEGACY_COUNT,
        "difference_points": LEGACY_COUNT - VERIFIED_COUNT,
        "source_sha256": SOURCE_SHA256,
        "reader": "scan2bim.formats.rcs_native via installed Autodesk ReCap DLL",
        "reader_version": DLL_VERSION,
        "full_sequential_passes": 2,
        "recorded_at": timestamp,
    }
    metadata.pop("cross_reader_count_comparison", None)
    metadata["warning"] = (
        "Старое значение 576,820,490 было задано константой при сборке проекта и не имеет отдельного отчёта reader. "
        "Два полных последовательных прохода через установленную Autodesk ReCap DLL 24.0.0.240 для исходника "
        "с SHA-256 784c2235541c89fbf78e02e28af8756a1040d46ff18111df3581b9b6b75b3792 насчитали 574,367,742 точки. "
        "В проекте сохранена прореженная выборка 3,500,000 точек; она не подходит для полноразмерной регистрации "
        "или точных чертежей. Исходный RCS не изменён."
    )
    return metadata


def apply(db_path: Path) -> dict:
    cloud, sidecar, meta_path = _read_current(db_path)
    _validate(cloud, sidecar)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_metadata = _updated_metadata(cloud["metadata"], timestamp=timestamp)
    new_sidecar = _updated_metadata(sidecar, timestamp=timestamp)
    new_metadata_json = json.dumps(new_metadata, ensure_ascii=False, separators=(",", ":"))
    new_sidecar_json = json.dumps(new_sidecar, ensure_ascii=False, indent=2) + "\n"

    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    db_backup = db_path.with_name(f"{db_path.name}.before-workshop-2-count-{suffix}.bak")
    meta_backup = meta_path.with_name(f"{meta_path.name}.before-count-{suffix}.bak")
    connection = sqlite3.connect(db_path)
    try:
        with sqlite3.connect(db_backup) as destination:
            connection.backup(destination)
    finally:
        connection.close()
    shutil.copy2(meta_path, meta_backup)
    temp_meta = meta_path.with_name(meta_path.name + ".count-repair.tmp")
    temp_meta.write_text(new_sidecar_json, encoding="utf-8")

    connection = sqlite3.connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        changed = connection.execute(
            "UPDATE clouds SET point_count=?, metadata_json=? WHERE id=? AND point_count=? AND ingested_count=?",
            (VERIFIED_COUNT, new_metadata_json, CLOUD_ID, LEGACY_COUNT, SAMPLE_COUNT),
        ).rowcount
        if changed != 1:
            raise ValueError("database row changed during reconciliation; no metadata committed")
        os.replace(temp_meta, meta_path)
        connection.commit()
    except BaseException:
        connection.rollback()
        if meta_backup.exists():
            shutil.copy2(meta_backup, meta_path)
        temp_meta.unlink(missing_ok=True)
        raise
    finally:
        connection.close()

    check = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    check.row_factory = sqlite3.Row
    try:
        result = check.execute(
            "SELECT point_count,ingested_count,decimated,metadata_json FROM clouds WHERE id=?",
            (CLOUD_ID,),
        ).fetchone()
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    final_meta = _json_object(result["metadata_json"])
    return {
        "project_id": PROJECT_ID,
        "cloud_id": CLOUD_ID,
        "old_unverified_count": LEGACY_COUNT,
        "verified_count": result["point_count"],
        "stored_sample_count": result["ingested_count"],
        "decimated": bool(result["decimated"]),
        "legacy_count_preserved": final_meta["legacy_unverified_source_point_count"]["count"],
        "source_sha256": SOURCE_SHA256,
        "source_modified": False,
        "database_integrity": integrity,
        "database_backup": str(db_backup),
        "metadata_backup": str(meta_backup),
        "metadata_path": str(meta_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--apply", action="store_true", help="write corrected derived metadata; default is dry-run")
    args = parser.parse_args()
    cloud, sidecar, meta_path = _read_current(args.db)
    _validate(cloud, sidecar)
    if not args.apply:
        print(json.dumps({
            "status": "dry_run_ok",
            "cloud_id": CLOUD_ID,
            "before_source_point_count": cloud["point_count"],
            "new_source_point_count": VERIFIED_COUNT,
            "legacy_count_will_be_preserved": LEGACY_COUNT,
            "stored_sample_count": cloud["ingested_count"],
            "metadata_path": str(meta_path),
            "source_modified": False,
        }, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(apply(args.db), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
