"""Full-resolution native RCS checkpoint cancellation/resume acceptance.

Uses one original FARO source read-only and an isolated database/data root.
The import is cancelled through the jobs API and resumed through the cloud
resume API, exercising the same path used by Studio.
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
from datetime import datetime, timezone
from pathlib import Path


CANCEL_AFTER_POINTS = 20_000_000
EXPECTED_POINTS = 297_873_927


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        capture_output=True, text=True, timeout=180, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"fresh-process verification failed: {result.stderr[-2000:]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    source = repo.parent / "1.rcs"
    evidence_path = repo / "docs" / "validation" / "STAGE2_FULL_RCS_CANCEL_RESUME_2026-10-25.json"
    test_root = repo / "data" / ".t"
    test_root.mkdir(parents=True, exist_ok=True)
    run_dir = test_root / f"rcs-cancel-resume-{uuid.uuid4().hex[:12]}"
    data_dir = run_dir / "app-data"
    data_dir.mkdir(parents=True)
    os.environ["S2B_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    sys.path.insert(0, str(repo / "backend"))

    from fastapi.testclient import TestClient
    from scan2bim.api.app import app
    from scan2bim.formats.rcs_native import estimate_full_resolution_batch_disk_bytes, native_available
    from scan2bim.storage import cloud_paths

    if not source.is_file():
        raise FileNotFoundError(source)
    if not native_available().get("dll_exists"):
        raise RuntimeError("Installed Autodesk ReCap RCS reader is unavailable")
    estimate = estimate_full_resolution_batch_disk_bytes([EXPECTED_POINTS], max_preview_points=2_500_000)
    free_before = shutil.disk_usage(data_dir).free
    if estimate is None or free_before < estimate["required_bytes"]:
        raise RuntimeError(f"capacity preflight failed: estimate={estimate}, free={free_before}")

    source_before = {"path": str(source.resolve()), "size_bytes": source.stat().st_size, "sha256": sha256(source)}
    evidence = {
        "date": datetime.now().date().isoformat(),
        "stage": 2,
        "purpose": "Exercise the Studio API import, cancel, and resume routes against a full-resolution native RCS stream in isolated data",
        "method": {"source": source_before["path"], "cancel_after_committed_points": CANCEL_AFTER_POINTS,
                   "import_route": "POST /api/v1/projects/{project_id}/clouds/import-path",
                   "cancel_route": "POST /api/v1/jobs/{job_id}/cancel",
                   "resume_route": "POST /api/v1/clouds/{cloud_id}/resume",
                   "reader": native_available(), "data_root": str(data_dir),
                   "production_data_used": False},
        "source_before": source_before,
        "capacity": {"free_before_bytes": free_before, "estimate": estimate},
        "resource_trace": {"minimum_free_bytes": free_before, "started_utc": datetime.now(timezone.utc).isoformat()},
        "cancel": {}, "resume": {}, "acceptance": {"stage_2": "in_progress"},
        "cleanup": {"isolated_derived_data": "pending", "original_source": "retained"},
    }
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    started = time.monotonic()
    safe_to_cleanup = False
    try:
        with TestClient(app, client=("127.0.0.1", 8000)) as client:
            health = client.get("/api/v1/health")
            if health.status_code != 200:
                raise RuntimeError(f"isolated API health failed: {health.status_code}")
            project_response = client.post("/api/v1/projects", json={"name": "FARO full RCS cancel-resume", "units": "m"})
            if project_response.status_code != 200:
                raise RuntimeError(f"project creation failed: {project_response.text}")
            project_id = project_response.json()["id"]
            submitted = client.post(f"/api/v1/projects/{project_id}/clouds/import-path",
                                    json={"path": str(source), "max_points": 0, "name": "FARO 1.rcs full-resolution resume"})
            if submitted.status_code != 200:
                raise RuntimeError(f"full-resolution cloud import rejected: {submitted.status_code} {submitted.text}")
            cloud_id = submitted.json()["id"]
            initial_job_id = submitted.json()["import_job_id"]
            stage_dir = cloud_paths(project_id, cloud_id)["dir"] / ".ingest-stage"
            checkpoint_path = stage_dir / "raw" / "stream.json"
            cancellation = {"requested": False, "committed_points": 0}
            last_report = {"at": time.monotonic()}

            def report_progress(phase: str, fraction: float, message: str, free_now: int) -> None:
                now = time.monotonic()
                if now - last_report["at"] < 30:
                    return
                last_report["at"] = now
                evidence["resource_trace"]["minimum_free_bytes"] = min(
                    evidence["resource_trace"]["minimum_free_bytes"], free_now,
                )
                evidence.setdefault("progress_trace", []).append({"phase": phase, "progress": fraction, "message": message,
                                   "elapsed_seconds": round(now - started, 1),
                                   "free_bytes": free_now})
                evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print("PROGRESS " + json.dumps({"phase": phase, "elapsed_seconds": round(now - started, 1),
                                                 "progress": fraction, "message": message,
                                                 "free_bytes": free_now}, ensure_ascii=False), flush=True)

            deadline = time.monotonic() + 7_200
            while time.monotonic() < deadline:
                free_now = shutil.disk_usage(data_dir).free
                evidence["resource_trace"]["minimum_free_bytes"] = min(
                    evidence["resource_trace"]["minimum_free_bytes"], free_now,
                )
                if checkpoint_path.is_file() and not cancellation["requested"]:
                    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                    committed = int(checkpoint.get("committed_count") or 0)
                    if committed >= CANCEL_AFTER_POINTS and not checkpoint.get("complete"):
                        response = client.post(f"/api/v1/jobs/{initial_job_id}/cancel")
                        if response.status_code != 200 or not response.json().get("cancel_requested"):
                            raise RuntimeError(f"job cancellation API failed: {response.status_code} {response.text}")
                        cancellation.update(requested=True, committed_points=committed,
                                            cancel_response=response.json())
                        print("CANCEL_REQUESTED " + json.dumps(cancellation, ensure_ascii=False), flush=True)
                if time.monotonic() - last_report["at"] >= 30:
                    report_progress("import", 0.0, "waiting for durable RCS checkpoint", free_now)
                job = client.get(f"/api/v1/jobs/{initial_job_id}").json()
                cloud_state = client.get(f"/api/v1/clouds/{cloud_id}").json()
                if job.get("status") in {"succeeded", "failed", "cancelled"}:
                    break
                time.sleep(0.5)
            else:
                raise TimeoutError("initial full-resolution RCS import exceeded two hours")
            if not cancellation["requested"] or job.get("status") != "cancelled" or cloud_state.get("status") != "cancelled":
                raise RuntimeError(f"full-resolution cancellation did not reach cancelled state: job={job}, cloud={cloud_state}")
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if checkpoint.get("complete") or checkpoint.get("committed_count", 0) < CANCEL_AFTER_POINTS:
                raise RuntimeError("cancellation did not preserve the expected incomplete durable checkpoint")
            evidence["cancel"] = {"status": job["status"], "cloud_status": cloud_state["status"],
                                  "job_id": initial_job_id, "cloud_id": cloud_id, "checkpoint_complete": False,
                                  "committed_points": checkpoint["committed_count"],
                                  "block_count": len(checkpoint.get("blocks", [])),
                                  "stream_bytes": (stage_dir / "raw" / "xyz.local.f32").stat().st_size
                                                   + (stage_dir / "raw" / "rgb.u8").stat().st_size,
                                  "checkpoint_retained": True,
                                  "cancel_response": cancellation["cancel_response"]}
            evidence["acceptance"]["cancel_preserves_checkpoint"] = "passed"
            evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print("CANCEL_CHECKPOINT " + json.dumps(evidence["cancel"], ensure_ascii=False), flush=True)

            resume_started = time.monotonic()
            resumed = client.post(f"/api/v1/clouds/{cloud_id}/resume")
            if resumed.status_code != 200:
                raise RuntimeError(f"resume API failed: {resumed.status_code} {resumed.text}")
            resume_job_id = resumed.json()["import_job_id"]
            if resumed.json().get("id") != cloud_id:
                raise RuntimeError("resume API returned a different cloud identity")
            if resume_job_id == initial_job_id:
                raise RuntimeError("resume did not create a new import job")
            evidence["resume"] = {"job_id": resume_job_id, "api_http": resumed.status_code}
            print("RESUME_STARTED " + json.dumps({"job_id": resume_job_id,
                                                  "committed_points": evidence["cancel"]["committed_points"]}), flush=True)

            while time.monotonic() < deadline:
                free_now = shutil.disk_usage(data_dir).free
                evidence["resource_trace"]["minimum_free_bytes"] = min(
                    evidence["resource_trace"]["minimum_free_bytes"], free_now,
                )
                if time.monotonic() - last_report["at"] >= 30:
                    progress_job = client.get(f"/api/v1/jobs/{resume_job_id}").json()
                    report_progress("resume", float(progress_job.get("progress") or 0.0),
                                    str(progress_job.get("message") or "resuming import"), free_now)
                job = client.get(f"/api/v1/jobs/{resume_job_id}").json()
                cloud_state = client.get(f"/api/v1/clouds/{cloud_id}").json()
                if job.get("status") in {"succeeded", "failed", "cancelled"}:
                    break
                time.sleep(0.5)
            else:
                raise TimeoutError("resumed full-resolution RCS import exceeded two hours")
            if job.get("status") != "succeeded" or cloud_state.get("status") != "ready":
                raise RuntimeError(f"resumed full-resolution import failed: job={job}, cloud={cloud_state}")
            evidence["resume"].update({"job_status": job["status"], "cloud_status": cloud_state["status"],
                                       "duration_seconds": round(time.monotonic() - resume_started, 2)})
            cloud_response = client.get(f"/api/v1/projects/{project_id}/clouds")
            if cloud_response.status_code != 200:
                raise RuntimeError("cloud listing failed after resumed import")
            clouds = cloud_response.json()
            if len(clouds) != 1:
                raise RuntimeError(f"expected one imported cloud, found {len(clouds)}")
            cloud = clouds[0]
            if cloud["status"] != "ready" or cloud["point_count"] != EXPECTED_POINTS \
                    or cloud["ingested_count"] != EXPECTED_POINTS or cloud.get("decimated") \
                    or not cloud.get("has_color"):
                raise RuntimeError(f"resumed full-resolution cloud failed acceptance: {cloud}")
            evidence["resume"]["cloud"] = {key: cloud.get(key) for key in
                                              ("id", "status", "point_count", "ingested_count", "decimated", "has_color")}
            evidence["acceptance"]["full_resolution_after_resume"] = "passed"

        reopened = fresh_process_check(repo, data_dir, project_id)
        if reopened["health_http"] != 200 or reopened["clouds_http"] != 200 or len(reopened["clouds"]) != 1:
            raise RuntimeError(f"fresh process reopen failed: {reopened}")
        reopened_cloud = reopened["clouds"][0]
        if reopened_cloud["status"] != "ready" or reopened_cloud["point_count"] != EXPECTED_POINTS \
                or reopened_cloud["ingested_count"] != EXPECTED_POINTS:
            raise RuntimeError(f"fresh process returned incomplete cloud: {reopened_cloud}")
        evidence["resume"]["fresh_process"] = reopened
        evidence["acceptance"]["fresh_process_reopen"] = "passed"
        safe_to_cleanup = True
    except Exception as exc:
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        evidence["acceptance"]["stage_2"] = "not_accepted"
        raise
    finally:
        source_after = {"sha256": sha256(source), "size_bytes": source.stat().st_size}
        evidence["source_after"] = source_after
        evidence["acceptance"]["source_unchanged"] = (
            source_before["sha256"] == source_after["sha256"]
            and source_before["size_bytes"] == source_after["size_bytes"]
        )
        evidence["resource_trace"]["duration_seconds"] = round(time.monotonic() - started, 2)
        evidence["resource_trace"]["ended_utc"] = datetime.now(timezone.utc).isoformat()
        resolved_root = test_root.resolve()
        resolved_run = run_dir.resolve()
        if safe_to_cleanup and evidence["acceptance"].get("source_unchanged") \
                and resolved_run.parent == resolved_root and run_dir.name.startswith("rcs-cancel-resume-"):
            shutil.rmtree(resolved_run)
            evidence["cleanup"] = {"isolated_derived_data": "removed after successful fresh-process verification",
                                   "original_source": "retained unchanged"}
            evidence["acceptance"]["stage_2"] = "passed_for_full_resolution_cancel_resume"
        else:
            evidence["cleanup"] = {"isolated_derived_data": "preserved for checkpoint/failure review",
                                   "path": str(run_dir), "original_source": "retained"}
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("EVIDENCE " + str(evidence_path), flush=True)
    print("SUMMARY " + json.dumps({"cancelled_points": evidence["cancel"]["committed_points"],
                                   "resumed_points": evidence["resume"]["cloud"]["point_count"],
                                   "duration_seconds": evidence["resource_trace"]["duration_seconds"],
                                   "cleanup": evidence["cleanup"]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
