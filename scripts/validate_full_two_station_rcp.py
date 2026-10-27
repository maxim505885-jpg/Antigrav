"""Full-resolution acceptance run for two original FARO RCS stations via RCP.

All database rows and derived arrays live in a unique isolated data root.
The original RCS files are read-only inputs; successful test output is removed
only after both stations reopen as ready in a fresh API process.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def make_rcp(path: Path, sources: list[tuple[str, Path, int]]) -> None:
    nodes = []
    for name, source, point_count in sources:
        location = escape(str(source.resolve()), quote=True)
        node_name = escape(name, quote=True)
        nodes.append(
            f'<VoxelTreeRunTime Id="{{{uuid.uuid4()}}}">'
            '<Translation x="0" y="0" z="0"/><Rotation x="0" y="0" z="0"/>'
            '<Scale x="1" y="1" z="1"/><Registered Value="1"/>'
            f'<NodeName Value="{node_name}"/><Path Value="{location}"/>'
            f'<RelativePath Value="{location}"/><NumPoints Value="{point_count}"/>'
            '<HasRGB Value="1"/><HasIntensity Value="0"/><HasNormals Value="0"/>'
            '</VoxelTreeRunTime>'
        )
    xml = '<Autodesk><ProjectId UUID="scan-two-station-acceptance"/><Nodes>' + "".join(nodes) + '</Nodes></Autodesk>'
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.xml", xml)


def fresh_process_check(repo: Path, data_dir: Path, project_id: str) -> dict:
    code = r"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'backend'))
from fastapi.testclient import TestClient
from scan2bim.api.app import app
with TestClient(app, client=('127.0.0.1', 8000)) as client:
    health = client.get('/api/v1/health')
    response = client.get(f'/api/v1/projects/{sys.argv[1]}/clouds')
    print(json.dumps({'health_http': health.status_code, 'clouds_http': response.status_code,
      'clouds': [{k: c.get(k) for k in ('id','name','status','point_count','ingested_count','decimated','has_color')}
                 for c in response.json()]}))
"""
    environment = os.environ.copy()
    environment["S2B_DATA_DIR"] = str(data_dir)
    environment["PYTHONPATH"] = str(repo / "backend")
    result = subprocess.run(
        [sys.executable, "-c", code, project_id], cwd=repo, env=environment,
        capture_output=True, text=True, timeout=120, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"fresh-process check failed: {result.stderr[-2000:]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    source_dir = repo.parent
    stations = [
        ("FARO Station 1", source_dir / "1.rcs", 297_873_927),
        ("FARO Station 2", source_dir / "2.rcs", 574_367_742),
    ]
    evidence_path = repo / "docs" / "validation" / "STAGE2_FULL_TWO_STATION_RCP_2026-10-25.json"
    test_root = repo / "data" / ".t"
    test_root.mkdir(parents=True, exist_ok=True)
    run_dir = test_root / f"rcp-two-full-{uuid.uuid4().hex[:12]}"
    data_dir = run_dir / "app-data"
    data_dir.mkdir(parents=True)
    rcp_path = run_dir / "faro-two-station.rcp"
    os.environ["S2B_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    sys.path.insert(0, str(repo / "backend"))

    from scan2bim.formats.rcs_native import estimate_full_resolution_batch_disk_bytes, native_available

    missing = [str(path) for _, path, _ in stations if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"FARO sources missing: {missing}")
    availability = native_available()
    if not availability.get("dll_exists"):
        raise RuntimeError(f"ReCap reader DLL unavailable: {availability.get('dll_path')}")
    estimate = estimate_full_resolution_batch_disk_bytes(
        [count for _, _, count in stations], max_preview_points=2_500_000,
    )
    free = shutil.disk_usage(data_dir).free
    if estimate is None or free < estimate["required_bytes"]:
        raise RuntimeError(f"capacity preflight failed: need {estimate}, free={free}")

    sources_before = [
        {"name": name, "path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha256(path)}
        for name, path, _ in stations
    ]
    make_rcp(rcp_path, stations)
    result = {
        "date": datetime.now().date().isoformat(),
        "stage": 2,
        "purpose": "Full-resolution two-station RCP import from original FARO RCS sources in isolated data",
        "reader": availability,
        "sources_before": sources_before,
        "synthetic_rcp": str(rcp_path),
        "isolated_data_root": str(data_dir),
        "capacity": {"free_before_bytes": free, "estimate": estimate},
        "api": {},
        "resource_trace": {"started_utc": datetime.now(timezone.utc).isoformat(), "minimum_free_bytes": free},
        "acceptance": {"stage_2": "in_progress", "source_files_modified": False},
        "cleanup": {"completed": False},
    }
    write_json(evidence_path, result)
    terminal = False
    restarted = False
    job_id = None
    started = time.monotonic()
    try:
        from fastapi.testclient import TestClient
        from scan2bim.api.app import app

        with TestClient(app, client=("127.0.0.1", 8000)) as client:
            health = client.get("/api/v1/health")
            if health.status_code != 200:
                raise RuntimeError(f"isolated API health failed: {health.status_code}")
            project_response = client.post("/api/v1/projects", json={
                "name": "FARO full two-station acceptance", "units": "m",
            })
            if project_response.status_code != 200:
                raise RuntimeError(f"project creation failed: {project_response.text}")
            project_id = project_response.json()["id"]
            submitted = client.post(
                f"/api/v1/projects/{project_id}/rcp/import-path",
                json={"path": str(rcp_path), "max_points": 0, "name_prefix": "FARO acceptance"},
            )
            if submitted.status_code != 200:
                raise RuntimeError(f"RCP batch request rejected: {submitted.status_code} {submitted.text}")
            batch = submitted.json()
            job_id = batch["import_job_id"]
            expected_ids = {station["cloud"]["id"] for station in batch["stations"]}
            if len(expected_ids) != 2 or batch.get("node_count") != 2:
                raise RuntimeError(f"RCP did not create two separate station clouds: {batch}")
            result["api"] = {"health_http": 200, "project_id": project_id, "batch": batch}
            write_json(evidence_path, result)
            deadline = time.monotonic() + 7_200
            last_progress_at = 0.0
            while time.monotonic() < deadline:
                job = client.get(f"/api/v1/jobs/{job_id}").json()
                result["api"]["job"] = job
                free_now = shutil.disk_usage(data_dir).free
                result["resource_trace"]["minimum_free_bytes"] = min(
                    result["resource_trace"]["minimum_free_bytes"], free_now,
                )
                result["resource_trace"]["elapsed_seconds"] = round(time.monotonic() - started, 1)
                if time.monotonic() - last_progress_at >= 30 or job.get("status") in {"succeeded", "failed", "cancelled"}:
                    print("PROGRESS " + json.dumps({
                        "elapsed_seconds": result["resource_trace"]["elapsed_seconds"],
                        "status": job.get("status"), "progress": job.get("progress"),
                        "message": job.get("message"), "free_bytes": free_now,
                    }, ensure_ascii=False), flush=True)
                    write_json(evidence_path, result)
                    last_progress_at = time.monotonic()
                if job.get("status") in {"succeeded", "failed", "cancelled"}:
                    terminal = True
                    break
                time.sleep(5)
            if not terminal:
                client.post(f"/api/v1/jobs/{job_id}/cancel")
                raise TimeoutError("two-station RCP import exceeded two hours; job cancellation requested")
            clouds = client.get(f"/api/v1/projects/{project_id}/clouds").json()
            result["api"]["clouds"] = clouds
            if len(clouds) != 2 or {cloud["id"] for cloud in clouds} != expected_ids:
                raise RuntimeError("station cloud list does not match submitted RCP nodes")
            for cloud, (_, source, count) in zip(clouds, stations):
                if cloud["status"] != "ready" or cloud["point_count"] != count or cloud["ingested_count"] != count:
                    raise RuntimeError(f"station did not pass full-resolution acceptance: {cloud}")
                if cloud.get("decimated") or not cloud.get("has_color"):
                    raise RuntimeError(f"station lost full-resolution or RGB data: {cloud}")
                if Path(cloud["source_path"]).resolve() != source.resolve():
                    raise RuntimeError("a station resolved to the wrong source file")
            result["acceptance"]["both_stations_full_resolution_rgb"] = "passed"
            result["restart_check"] = fresh_process_check(repo, data_dir, project_id)
            restart_clouds = result["restart_check"].get("clouds", [])
            if result["restart_check"].get("health_http") != 200 or result["restart_check"].get("clouds_http") != 200:
                raise RuntimeError("fresh process could not reopen isolated project")
            if len(restart_clouds) != 2 or any(
                cloud["status"] != "ready" or cloud["point_count"] != cloud["ingested_count"]
                for cloud in restart_clouds
            ):
                raise RuntimeError("fresh process did not restore both complete station clouds")
            restarted = True
            result["acceptance"]["fresh_process_reopen"] = "passed"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["acceptance"]["stage_2"] = "not_accepted"
        raise
    finally:
        result["resource_trace"]["duration_seconds"] = round(time.monotonic() - started, 2)
        result["resource_trace"]["ended_utc"] = datetime.now(timezone.utc).isoformat()
        sources_after = []
        for source in sources_before:
            path = Path(source["path"])
            sources_after.append({"path": source["path"], "sha256": sha256(path)})
        result["sources_after"] = sources_after
        unchanged = all(before["sha256"] == after["sha256"] for before, after in zip(sources_before, sources_after))
        result["acceptance"]["source_files_unchanged"] = unchanged
        safe_to_cleanup = terminal and restarted and unchanged and not result.get("error")
        resolved_root = test_root.resolve()
        resolved_run = run_dir.resolve()
        if safe_to_cleanup and resolved_run.parent == resolved_root and run_dir.name.startswith("rcp-two-full-"):
            try:
                shutil.rmtree(run_dir)
                result["cleanup"] = {"completed": True, "removed_isolated_data": True}
                result["acceptance"]["stage_2"] = "passed_for_two_station_full_ingest"
            except OSError as exc:
                result["cleanup"] = {"completed": False, "error": str(exc), "path": str(run_dir)}
        else:
            result["cleanup"] = {
                "completed": False,
                "path": str(run_dir),
                "note": "preserved for checkpoint recovery or failure review",
            }
        write_json(evidence_path, result)
    print("EVIDENCE " + str(evidence_path), flush=True)
    print("SUMMARY " + json.dumps({
        "duration_seconds": result["resource_trace"]["duration_seconds"],
        "points": [cloud.get("point_count") for cloud in result.get("api", {}).get("clouds", [])],
        "source_unchanged": result["acceptance"].get("source_files_unchanged"),
        "cleanup": result["cleanup"],
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
