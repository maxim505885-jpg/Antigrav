"""Read-only local inventory and consistent SQLite backup; never uploads data.

Run with the project's Python. JSON and backups stay under ignored data/.
No application imports: importing config would create directories as a side effect.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def command(argv: list[str]) -> dict:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        return {"exit_code": result.returncode, "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}


def inventory(data_dir: Path, source: Path, output: Path) -> dict:
    import numpy as np

    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    source_stat = source.stat()
    disk = shutil.disk_usage(data_dir)
    report = {
        "schema": "scan.baseline/1", "created_at": stamp,
        "source": {"name": source.name, "size_bytes": source_stat.st_size,
                   "mtime_ns": source_stat.st_mtime_ns, "content_read": False},
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "cpu_threads": os.cpu_count(), "disk_free_bytes": disk.free,
                        "s2b_overrides": sorted(k for k in os.environ if k.startswith("S2B_"))},
        "git": command(["git", "-C", str(ROOT), "rev-parse", "HEAD"]),
        "packages": {}, "clouds": [],
    }
    for name in ("numpy", "scipy", "open3d", "ifcopenshell", "ezdxf", "fastapi", "pytest"):
        try:
            report["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            report["packages"][name] = None

    db_path = data_dir / "scan2bim.sqlite3"
    backup_path = output / f"database-{stamp}.sqlite3"
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        # Backup API includes committed WAL data and does not modify the live database.
        with sqlite3.connect(backup_path) as backup:
            connection.backup(backup)
        report["database_backup"] = backup_path.name
        report["database_integrity"] = connection.execute("PRAGMA quick_check").fetchone()[0]
        for row in connection.execute("SELECT * FROM clouds ORDER BY updated_at DESC"):
            cloud = dict(row)
            stored_source = Path(cloud["source_path"])
            cloud["source_path"] = stored_source.name
            cloud["is_requested_source"] = stored_source.resolve() == source.resolve()
            cloud["metadata"] = json.loads(cloud.pop("metadata_json") or "{}")
            # DLL paths and other local machine details remain only in ignored JSON.
            cloud_dir = data_dir / "projects" / cloud["project_id"] / "clouds" / cloud["id"]
            cloud["arrays"] = {}
            for name in ("positions", "colors", "intensity"):
                path = cloud_dir / f"{name}.npy"
                if path.exists():
                    array = np.load(path, mmap_mode="r", allow_pickle=False)
                    cloud["arrays"][name] = {"shape": list(array.shape), "dtype": str(array.dtype),
                                              "file_bytes": path.stat().st_size}
                    del array
            cloud["element_counts"] = [dict(r) for r in connection.execute(
                "SELECT class_name,review_status,COUNT(*) AS count FROM elements "
                "WHERE cloud_id=? GROUP BY class_name,review_status", (cloud["id"],))]
            report["clouds"].append(cloud)

    unchanged = source.stat()
    report["source"]["stat_unchanged"] = (
        source_stat.st_size == unchanged.st_size and source_stat.st_mtime_ns == unchanged.st_mtime_ns)
    destination = output / f"baseline-{stamp}.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_file"] = str(destination)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--source", type=Path, default=ROOT.parent / "1.rcs")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "validation")
    args = parser.parse_args()
    report = inventory(args.data_dir.resolve(), args.source.resolve(), args.output.resolve())
    real = [c for c in report["clouds"] if c["is_requested_source"]]
    print(json.dumps({"report_file": report["report_file"], "database_integrity": report["database_integrity"],
                      "source": report["source"], "disk_free_gib": round(report["environment"]["disk_free_bytes"] / 2**30, 2),
                      "clouds": [{"id": c["id"], "stored": c["ingested_count"], "original": c["point_count"],
                                  "arrays": c["arrays"], "elements": c["element_counts"]} for c in real]},
                     ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
