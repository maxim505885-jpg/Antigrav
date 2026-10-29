"""Read-only smoke check for a database snapshot and existing cloud storage."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


def _sqlite_readonly_uri(path: Path) -> str:
    """Build a SQLite read-only URI that also works for Windows UNC paths."""
    raw = str(path)
    if raw.startswith("\\\\"):
        uri_path = raw[2:].replace("\\", "/")
        return f"file:////{uri_path}?mode=ro"
    return f"{path.resolve().as_uri()}?mode=ro"


def _snapshot_database(source: Path, destination: Path) -> None:
    """Copy a consistent SQLite snapshot without writing to the source DB."""
    with sqlite3.connect(_sqlite_readonly_uri(source), uri=True, timeout=15) as reader:
        with sqlite3.connect(destination) as snapshot:
            reader.backup(snapshot)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Exercise read-only API routes against a temporary SQLite snapshot "
            "and existing point-cloud storage. No write endpoints are called."
        )
    )
    parser.add_argument("--db", type=Path, required=True, help="SQLite database to snapshot")
    parser.add_argument("--data-dir", type=Path, required=True, help="Existing API data root")
    parser.add_argument("--project-id", required=True, help="Project ID to inspect")
    parser.add_argument(
        "--cloud-match",
        default="",
        help="Substring to select one cloud by ID or name; defaults to the first ready cloud",
    )
    parser.add_argument(
        "--expected-cloud-count",
        type=int,
        default=None,
        help="Optional expected number of clouds in the selected project",
    )
    return parser.parse_args()


def _require_status(response: Any, expected: int, route: str) -> Any:
    if response.status_code != expected:
        raise RuntimeError(
            f"{route}: expected HTTP {expected}, received {response.status_code}: "
            f"{response.text[:500]}"
        )
    return response


def main() -> int:
    args = _parse_args()
    if not args.db.is_file():
        raise FileNotFoundError(f"Database not found: {args.db}")
    if not args.data_dir.is_dir():
        raise NotADirectoryError(f"Data root not found: {args.data_dir}")

    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "backend"))

    with tempfile.TemporaryDirectory(prefix="scan-readonly-api-") as temporary_root:
        snapshot_path = Path(temporary_root) / "snapshot.sqlite3"
        _snapshot_database(args.db, snapshot_path)

        # The app's startup recovery and any incidental DB writes stay inside
        # this disposable snapshot. The shared point arrays are only read.
        os.environ["S2B_DATA_DIR"] = str(args.data_dir.resolve())
        os.environ["S2B_DB_PATH"] = str(snapshot_path)
        os.environ["S2B_INGEST_MODE"] = "worker"

        from fastapi.testclient import TestClient
        from scan2bim.api.app import app

        started = time.perf_counter()
        with TestClient(app, client=("127.0.0.1", 12345)) as client:
            health = _require_status(client.get("/api/v1/health"), 200, "health")
            projects_response = _require_status(
                client.get("/api/v1/projects"), 200, "projects"
            )
            projects = projects_response.json()
            project = next(
                (item for item in projects if item.get("id") == args.project_id), None
            )
            if project is None:
                raise RuntimeError(f"Project not found: {args.project_id}")

            clouds_response = _require_status(
                client.get(f"/api/v1/projects/{args.project_id}/clouds"),
                200,
                "project clouds",
            )
            clouds = clouds_response.json()
            if args.expected_cloud_count is not None:
                if len(clouds) != args.expected_cloud_count:
                    raise RuntimeError(
                        f"Expected {args.expected_cloud_count} clouds, received {len(clouds)}"
                    )

            ready_clouds = [cloud for cloud in clouds if cloud.get("status") == "ready"]
            if not ready_clouds:
                raise RuntimeError("Selected project has no ready clouds")

            selected = next(
                (
                    cloud
                    for cloud in ready_clouds
                    if args.cloud_match
                    and args.cloud_match.casefold()
                    in f"{cloud.get('id', '')} {cloud.get('name', '')}".casefold()
                ),
                None,
            )
            if args.cloud_match and selected is None:
                raise RuntimeError(f"No ready cloud matches: {args.cloud_match}")
            if selected is None:
                selected = ready_clouds[0]

            cloud_response = _require_status(
                client.get(f"/api/v1/clouds/{selected['id']}"), 200, "cloud"
            )
            cloud = cloud_response.json()
            preview_response = _require_status(
                client.get(f"/api/v1/clouds/{selected['id']}/preview"),
                200,
                "cloud preview",
            )
            stats_response = _require_status(
                client.get(f"/api/v1/clouds/{selected['id']}/stats"),
                200,
                "cloud stats",
            )
            stats = stats_response.json()

        report = {
            "result": "passed",
            "database": "temporary SQLite snapshot; removed after run",
            "source_database_modified": False,
            "point_cloud_storage_access": "read-only GET routes",
            "health": health.json().get("status"),
            "projects_http": projects_response.status_code,
            "project_id": project["id"],
            "project_name": project["name"],
            "project_clouds_http": clouds_response.status_code,
            "cloud_count": len(clouds),
            "ready_cloud_count": len(ready_clouds),
            "cloud_id": cloud["id"],
            "cloud_name": cloud["name"],
            "point_count": cloud.get("point_count"),
            "ingested_count": cloud.get("ingested_count"),
            "has_count_warning": bool(cloud.get("warning")),
            "preview_http": preview_response.status_code,
            "preview_bytes": len(preview_response.content),
            "stats_http": stats_response.status_code,
            "element_count": stats.get("elements"),
            "section_count": stats.get("sections"),
            "elapsed_seconds": round(time.perf_counter() - started, 2),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
