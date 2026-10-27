"""Run a protected, isolated full-resolution import from a real single-node RCP.

The RCP and linked RCS are opened read-only. Imported arrays, database rows,
and checkpoints are written under a unique data/.t directory and removed after
the API has been restarted and the imported cloud has been verified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def verify_after_restart(repo: Path, data_dir: Path, project_id: str) -> dict[str, Any]:
    code = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'backend'))
from fastapi.testclient import TestClient
from scan2bim.api.app import app
with TestClient(app, client=('127.0.0.1', 8000)) as client:
    health = client.get('/api/v1/health')
    projects = client.get('/api/v1/projects')
    project = next(item for item in projects.json() if item['id'] == sys.argv[1])
    clouds = client.get('/api/v1/projects/' + project['id'] + '/clouds')
    print(json.dumps({
        'health_http': health.status_code,
        'health': health.json(),
        'projects_http': projects.status_code,
        'clouds_http': clouds.status_code,
        'project_id': project['id'],
        'clouds': [{key: cloud.get(key) for key in (
            'id', 'status', 'point_count', 'ingested_count', 'decimated',
            'source_format', 'name'
        )} for cloud in clouds.json()],
    }))
"""
    environment = os.environ.copy()
    environment["S2B_DATA_DIR"] = str(data_dir)
    environment["PYTHONPATH"] = str(repo / "backend")
    process = subprocess.run(
        [sys.executable, "-c", code, project_id],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(f"restart verification failed: {process.stderr[-2000:]}")
    return json.loads(process.stdout.strip().splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rcp", type=Path)
    parser.add_argument("--expected-rcs-sha256", required=True)
    parser.add_argument("--expected-rcp-sha256", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    rcp_path = args.rcp.expanduser().resolve()
    evidence_path = args.evidence.expanduser().resolve()
    test_root = (repo / "data" / ".t").resolve()
    test_root.mkdir(parents=True, exist_ok=True)
    run_dir = test_root / f"fullrcp_{uuid.uuid4().hex[:12]}"
    data_dir = run_dir / "app-data"
    data_dir.mkdir(parents=True)
    if data_dir.resolve().parent != run_dir.resolve() or run_dir.resolve().parent != test_root:
        raise SystemExit("Unsafe isolated-data path")

    # Set the data root before importing any scan2bim package: importing the
    # RCP resolver also loads format readers and freezes config.DB_PATH.
    os.environ["S2B_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    sys.path.insert(0, str(repo / "backend"))
    from scan2bim.formats.rcp_manifest import read_rcp_manifest

    rcp_hash_before = sha256(rcp_path)
    if rcp_hash_before.lower() != args.expected_rcp_sha256.lower():
        raise SystemExit("RCP hash does not match the expected source identity")
    manifest = read_rcp_manifest(rcp_path)
    if len(manifest["nodes"]) != 1:
        raise SystemExit("This acceptance runner requires exactly one RCP station")
    node = manifest["nodes"][0]
    rcs_path = Path(node["resolved_rcs_path"]).resolve()
    rcs_hash_before = sha256(rcs_path)
    if rcs_hash_before.lower() != args.expected_rcs_sha256.lower():
        raise SystemExit("Resolved RCS hash does not match the expected station identity")

    from fastapi.testclient import TestClient
    from scan2bim.api.app import app

    process = psutil.Process()
    start = time.monotonic()
    max_tree_rss = 0
    min_free_bytes: int | None = None
    min_available_memory: int | None = None
    result: dict[str, Any] = {
        "date": datetime.now().date().isoformat(),
        "stage": 2,
        "purpose": "Isolated full-resolution import through the real single-node RCP API route",
        "source": {
            "rcp_path": str(rcp_path),
            "rcp_sha256_before": rcp_hash_before,
            "rcs_path": str(rcs_path),
            "rcs_size_bytes": rcs_path.stat().st_size,
            "rcs_sha256_before": rcs_hash_before,
            "declared_point_count": node["declared_point_count"],
        },
        "derived_test_data_root": str(data_dir),
        "api": {},
        "resource_trace": {"sample_interval_seconds": 5, "started_utc": utc_now()},
        "acceptance": {"stage_2": "in_progress"},
        "cleanup": {"completed": False},
    }
    write_json(evidence_path, result)
    import_job_finished = False
    full_resolution_verified = False
    restart_verified = False
    job_id: str | None = None
    try:
        with TestClient(app, client=("127.0.0.1", 8000)) as client:
            health = client.get("/api/v1/health")
            if health.status_code != 200:
                raise RuntimeError(f"health check returned {health.status_code}")
            project_response = client.post(
                "/api/v1/projects",
                json={
                    "name": "Isolated full RCP acceptance 10",
                    "description": "Temporary isolated Stage 2 validation",
                    "units": "m",
                },
            )
            if project_response.status_code != 200:
                raise RuntimeError(f"project create failed: {project_response.text}")
            project_id = project_response.json()["id"]
            import_response = client.post(
                f"/api/v1/projects/{project_id}/clouds/import-path",
                json={"path": str(rcp_path), "max_points": 0, "name": "10 — full-resolution validation"},
            )
            result["api"].update(
                {
                    "health_http": health.status_code,
                    "project_id": project_id,
                    "import_http": import_response.status_code,
                }
            )
            if import_response.status_code != 200:
                result["api"]["import_error"] = import_response.json()
                raise RuntimeError(f"import request failed: {import_response.text}")
            cloud_initial = import_response.json()
            job_id = cloud_initial["import_job_id"]
            cloud_id = cloud_initial["id"]
            result["api"].update({"cloud_id": cloud_id, "job_id": job_id})
            write_json(evidence_path, result)

            deadline = time.monotonic() + args.timeout_seconds
            last_status: str | None = None
            last_print = 0.0
            final_job: dict[str, Any] | None = None
            while time.monotonic() < deadline:
                job_response = client.get(f"/api/v1/jobs/{job_id}")
                if job_response.status_code != 200:
                    raise RuntimeError(f"job polling failed: {job_response.text}")
                final_job = job_response.json()
                try:
                    tree = [process, *process.children(recursive=True)]
                    rss = sum(child.memory_info().rss for child in tree if child.is_running())
                    max_tree_rss = max(max_tree_rss, rss)
                except (psutil.Error, PermissionError):
                    rss = 0
                free_bytes = shutil.disk_usage(data_dir).free
                min_free_bytes = free_bytes if min_free_bytes is None else min(min_free_bytes, free_bytes)
                available = psutil.virtual_memory().available
                min_available_memory = available if min_available_memory is None else min(min_available_memory, available)
                now = time.monotonic()
                if now - last_print >= 30 or final_job.get("status") != last_status:
                    print(
                        "PROGRESS "
                        + json.dumps(
                            {
                                "elapsed_seconds": round(now - start, 1),
                                "status": final_job.get("status"),
                                "progress": final_job.get("progress"),
                                "message": final_job.get("message"),
                                "free_bytes": free_bytes,
                                "aggregate_process_tree_rss_bytes": rss,
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    last_print = now
                    last_status = final_job.get("status")
                if final_job.get("status") in {"succeeded", "failed", "cancelled"}:
                    import_job_finished = True
                    break
                time.sleep(5)
            if not import_job_finished:
                client.post(f"/api/v1/jobs/{job_id}/cancel")
                cancel_deadline = time.monotonic() + 180
                while time.monotonic() < cancel_deadline:
                    final_job = client.get(f"/api/v1/jobs/{job_id}").json()
                    if final_job.get("status") in {"succeeded", "failed", "cancelled"}:
                        import_job_finished = True
                        break
                    time.sleep(2)
                raise TimeoutError(f"import exceeded {args.timeout_seconds} seconds")

            cloud_response = client.get(f"/api/v1/clouds/{cloud_id}")
            if cloud_response.status_code != 200:
                raise RuntimeError(f"cloud verification failed: {cloud_response.text}")
            cloud = cloud_response.json()
            result["api"]["job"] = final_job
            result["api"]["cloud_after_import"] = {
                key: cloud.get(key)
                for key in (
                    "id", "project_id", "name", "source_path", "source_format",
                    "size_bytes", "point_count", "ingested_count", "preview_count",
                    "decimated", "has_color", "has_intensity", "status", "error", "metadata",
                )
            }
            result["resource_trace"].update(
                {
                    "ended_utc": utc_now(),
                    "duration_seconds": round(time.monotonic() - start, 2),
                    "peak_aggregate_process_tree_rss_bytes": max_tree_rss,
                    "minimum_free_bytes_in_isolated_data_volume": min_free_bytes,
                    "minimum_system_available_memory_bytes": min_available_memory,
                }
            )
            if final_job["status"] != "succeeded" or cloud["status"] != "ready":
                raise RuntimeError(
                    f"import failed: job={final_job['status']}, cloud={cloud['status']}, "
                    f"error={cloud.get('error')}"
                )
            if cloud["point_count"] != cloud["ingested_count"] or cloud.get("decimated"):
                raise RuntimeError("cloud is not full-resolution")
            full_resolution_verified = True

        result["restart_verification"] = verify_after_restart(repo, data_dir, project_id)
        restart = result["restart_verification"]
        if (
            restart["health_http"] != 200
            or restart["clouds_http"] != 200
            or len(restart["clouds"]) != 1
            or restart["clouds"][0]["status"] != "ready"
            or restart["clouds"][0]["point_count"] != restart["clouds"][0]["ingested_count"]
        ):
            raise RuntimeError("cloud was not restored full-resolution after process restart")
        restart_verified = True
        result["acceptance"].update(
            {
                "full_resolution_import": "passed",
                "project_reopen_after_process_restart": "passed",
                "faro_sources_unchanged": None,
                "closed_stages": "3/12",
                "stage_6": "parked_until_final_pass",
            }
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["acceptance"]["stage_2"] = "not_accepted"
        raise
    finally:
        result["source"]["rcp_sha256_after"] = sha256(rcp_path)
        result["source"]["rcs_sha256_after"] = sha256(rcs_path)
        unchanged = (
            result["source"]["rcp_sha256_after"] == rcp_hash_before
            and result["source"]["rcs_sha256_after"] == rcs_hash_before
        )
        result["source"]["unchanged"] = unchanged
        result["acceptance"]["faro_sources_unchanged"] = unchanged
        resolved_run = run_dir.resolve()
        safe_to_remove = (
            job_id is None
            or (import_job_finished and (not full_resolution_verified or restart_verified))
        )
        if (
            safe_to_remove
            and resolved_run.parent == test_root
            and run_dir.name.startswith("fullrcp_")
            and not run_dir.is_symlink()
        ):
            try:
                shutil.rmtree(run_dir)
                result["cleanup"] = {"completed": True, "path": str(run_dir)}
            except OSError as exc:
                result["cleanup"] = {"completed": False, "path": str(run_dir), "error": str(exc)}
        else:
            result["cleanup"] = {
                "completed": False,
                "path": str(run_dir),
                "note": "preserved for inspection because import/restart verification did not reach a safe terminal state",
            }
        result["resource_trace"].setdefault("ended_utc", utc_now())
        result["resource_trace"].setdefault("duration_seconds", round(time.monotonic() - start, 2))
        result["resource_trace"].update(
            {
                "peak_aggregate_process_tree_rss_bytes": max_tree_rss,
                "minimum_free_bytes_in_isolated_data_volume": min_free_bytes,
                "minimum_system_available_memory_bytes": min_available_memory,
            }
        )
        if result["cleanup"]["completed"] and unchanged and not result.get("error"):
            result["cleanup"]["note"] = "derived test data removed after restart verification; original scans retained"
        write_json(evidence_path, result)

    print("EVIDENCE", evidence_path)
    print(
        "SUMMARY "
        + json.dumps(
            {
                "duration_seconds": result["resource_trace"]["duration_seconds"],
                "cloud": result["api"]["cloud_after_import"],
                "restart_verified": restart_verified,
                "source_unchanged": result["source"]["unchanged"],
                "cleanup": result["cleanup"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
