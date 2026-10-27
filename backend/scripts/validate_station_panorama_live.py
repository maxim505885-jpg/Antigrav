"""Live check of station panoramas and cloud export against a real API process.

A synthetic room is uploaded through the HTTP API, then the panorama catalogue,
render, pixel pick, depth measurement, E57/LAS export and download are exercised
as a client would use them. The API runs on an isolated ``S2B_DATA_DIR`` so the
production project database and the FARO sources are untouched.

    python backend/scripts/validate_station_panorama_live.py [--port 8011] [--out docs/validation]

Exit codes: 0 passed, 1 failed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PORT = 8011
BASE = f"http://127.0.0.1:{PORT}/api/v1"


def call(method: str, path: str, body: bytes | None = None, headers: dict | None = None):
    request = urllib.request.Request(BASE + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def json_call(method: str, path: str, payload: dict | None = None):
    body = json.dumps(payload).encode() if payload is not None else None
    status, _, raw = call(method, path, body, {"Content-Type": "application/json"})
    return status, json.loads(raw) if raw else None


def build_room_ply(path: Path) -> int:
    xs = np.arange(0.0, 8.0, 0.05)
    zs = np.arange(0.0, 3.0, 0.05)
    points = []
    for x in xs:
        for z in zs:
            points.append((x, 0.0, z))
            points.append((x, 6.0, z))
    ys = np.arange(0.0, 6.0, 0.05)
    for y in ys:
        for z in zs:
            points.append((0.0, y, z))
            points.append((8.0, y, z))
    ys2 = np.arange(0.0, 6.0, 0.1)
    for x in np.arange(0.0, 8.0, 0.1):
        for y in ys2:
            points.append((x, y, 0.0))
            points.append((x, y, 3.0))
    data = np.asarray(points, dtype=np.float64)
    colors = np.clip(
        np.stack([data[:, 0] / 8.0 * 255, data[:, 1] / 6.0 * 255, data[:, 2] / 3.0 * 255], axis=1),
        0,
        255,
    ).astype(np.uint8)
    with path.open("w", encoding="ascii") as handle:
        handle.write("ply\nformat ascii 1.0\n")
        handle.write(f"element vertex {len(data)}\n")
        handle.write("property float x\nproperty float y\nproperty float z\n")
        handle.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
        handle.write("end_header\n")
        for (x, y, z), (r, g, b) in zip(data, colors):
            handle.write(f"{x:.3f} {y:.3f} {z:.3f} {r} {g} {b}\n")
    return len(data)


def upload_cloud(project_id: str, ply: Path, name: str):
    boundary = "----scan" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{ply.name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    body = head + ply.read_bytes() + tail
    return call(
        "POST",
        f"/projects/{project_id}/clouds/upload?name={name}",
        body,
        {"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )


def main() -> int:
    global BASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--out", type=Path, default=None, help="куда записать JSON-протокол")
    args = parser.parse_args()
    PORT = args.port
    BASE = f"http://127.0.0.1:{PORT}/api/v1"

    work = Path(tempfile.mkdtemp(prefix="s2b_live_smoke_"))
    data_root = work / "data"
    data_root.mkdir()
    ply = work / "room.ply"
    count = build_room_ply(ply)
    env = dict(os.environ, S2B_DATA_DIR=str(data_root))
    log = (work / "server.log").open("w", encoding="utf-8")
    server = subprocess.Popen(
        [sys.executable, str(ROOT / "backend" / "run.py"), "--port", str(PORT)],
        cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    report: dict = {
        "check": "station_panorama_and_export_live",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "points_uploaded": count,
        "data_root": str(data_root),
    }
    try:
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                status, _, raw = call("GET", "/health")
                if status == 200:
                    report["health"] = json.loads(raw)
                    break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("API did not start: " + (work / "server.log").read_text()[-2000:])

        status, project = json_call("POST", "/projects", {"name": "live smoke"})
        assert status == 200, project
        project_id = project["id"]
        status, _, raw = upload_cloud(project_id, ply, "room")
        assert status == 200, raw[:500]
        cloud = json.loads(raw)
        cloud_id = cloud["id"]
        deadline = time.time() + 240
        while time.time() < deadline:
            status, current = json_call("GET", f"/clouds/{cloud_id}")
            if current["status"] in {"ready", "failed"}:
                break
            time.sleep(0.5)
        report["cloud"] = {k: current.get(k) for k in ("status", "point_count", "source_format", "error")}
        assert current["status"] == "ready", report["cloud"]

        status, stations = json_call("GET", f"/clouds/{cloud_id}/stations")
        assert status == 200, stations
        report["stations"] = {
            "count": stations["count"],
            "first": {
                k: stations["stations"][0][k]
                for k in ("station_id", "station_source", "anchor_kind", "point_count")
            },
        }
        station_id = stations["stations"][0]["station_id"]

        status, headers, png = call("GET", f"/clouds/{cloud_id}/stations/{station_id}/panorama?source=cloud")
        report["panorama"] = {
            "status": status,
            "bytes": len(png),
            "png_magic": png[:8].hex(),
            "source_header": headers.get("X-Panorama-Source"),
            "coverage_header": headers.get("X-Panorama-Coverage"),
        }
        assert status == 200 and png.startswith(b"\x89PNG"), report["panorama"]

        resolved = []
        for u in (0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9):
            for v in (0.3, 0.45, 0.55, 0.7):
                status, pick = json_call(
                    "POST", f"/clouds/{cloud_id}/stations/{station_id}/pick", {"u": u, "v": v}
                )
                if status == 200 and pick.get("resolved"):
                    resolved.append({"u": u, "v": v, "distance_m": pick.get("distance_m")})
                    if len(resolved) >= 4:
                        break
            if len(resolved) >= 4:
                break
        report["resolved_picks"] = resolved
        assert len(resolved) >= 2, "no resolved panorama picks"

        a, b = resolved[0], resolved[1]
        status, measure = json_call(
            "POST",
            f"/clouds/{cloud_id}/stations/{station_id}/measure",
            {"a": {"u": a["u"], "v": a["v"]}, "b": {"u": b["u"], "v": b["v"]}},
        )
        report["measure"] = (
            {k: measure.get(k) for k in ("distance_m", "distance_mm", "precision_mm", "depth_source")}
            if status == 200
            else {"status": status, "detail": measure}
        )
        assert status == 200, report["measure"]

        status, job = json_call("POST", f"/clouds/{cloud_id}/export", {"format": "las", "verify": True})
        assert status == 200, job
        deadline = time.time() + 300
        while time.time() < deadline:
            status, current_job = json_call("GET", f"/jobs/{job['id']}")
            if current_job["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.5)
        report["export_job"] = {
            "status": current_job["status"],
            "error": current_job.get("error"),
            "result": current_job.get("result"),
        }
        assert current_job["status"] == "succeeded", report["export_job"]

        status, exports = json_call("GET", f"/clouds/{cloud_id}/exports")
        assert status == 200 and exports, exports
        export_id = exports[-1]["export_id"]
        status, _, las = call("GET", f"/clouds/{cloud_id}/exports/{export_id}/download")
        report["export"] = {
            "count": len(exports),
            "meta": {k: exports[-1].get(k) for k in ("format", "point_count", "size_bytes", "verified", "max_deviation_m", "tolerance_m")},
            "download_status": status,
            "download_bytes": len(las),
            "las_magic": las[:4].decode("ascii", "replace"),
        }
        assert status == 200 and las[:4] == b"LASF", report["export"]
        report["result"] = "passed"
    except Exception as exc:  # noqa: BLE001 - the traceback is the report
        import traceback

        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out is not None:
        args.out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (args.out / f"STATION_PANORAMA_LIVE_{stamp}.json").write_text(text, encoding="utf-8")
    return 0 if report.get("result") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
