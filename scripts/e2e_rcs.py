"""Live end-to-end route on the user's real 7.2 GB scan, through the public HTTP API.

    import 1.rcs -> ingest -> horizontal section -> DXF -> recognition -> IFC

Run only while the server is up (``python backend/run.py --port 8000``).
The RCS step needs the installed Autodesk ReCap DLL.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
NAME = "Real scan 1.rcs"
RCS = Path("../1.rcs").resolve()
OUT = Path("data/live_check")
OUT.mkdir(parents=True, exist_ok=True)


def wait_job(http: httpx.Client, job_id: str, label: str, timeout: float = 1800) -> dict:
    start = time.time()
    last = None
    while time.time() - start < timeout:
        job = http.get(f"{BASE}/jobs/{job_id}").json()
        state = (job["status"], round(float(job.get("progress") or 0), 3), job.get("message"))
        if state != last:
            print(f"  [{label}] {state[0]} {state[1]:.2f} {state[2]}")
            last = state
        if job["status"] in {"succeeded", "failed"}:
            return job
        time.sleep(3)
    raise SystemExit(f"{label}: job {job_id} did not finish in {timeout}s")


def latest_job(http: httpx.Client, pid: str, cloud_id: str, kind: str) -> str:
    jobs = http.get(f"{BASE}/projects/{pid}/jobs").json()
    for job in jobs:
        if job.get("cloud_id") == cloud_id and job.get("type") == kind:
            return job["id"]
    raise SystemExit(f"no {kind} job for cloud {cloud_id}")


def main() -> int:
    if not RCS.exists():
        raise SystemExit(f"missing {RCS}")
    print(f"source: {RCS} ({RCS.stat().st_size / 2**30:.2f} GiB)")
    with httpx.Client(timeout=600) as http:
        # Re-runnable: reuse the existing project/cloud instead of importing
        # the 7.2 GB file a second time.
        existing = [p for p in http.get(f"{BASE}/projects").json() if p["name"] == NAME]
        if existing:
            pid = existing[0]["id"]
            clouds = http.get(f"{BASE}/projects/{pid}/clouds").json()
            cid = clouds[0]["id"] if clouds else None
            print(f"reusing project {pid} cloud {cid}")
            t0 = time.time()
        else:
            pid = http.post(f"{BASE}/projects", json={"name": NAME}).json()["id"]
            print(f"project {pid}")
            t0 = time.time()
            cid = None

        if cid is None:
            r = http.post(
                f"{BASE}/projects/{pid}/clouds/import-path",
                json={"path": str(RCS), "name": "1.rcs (real, 7.2 GB)"},
            )
            if r.status_code != 200:
                print("import rejected:", r.status_code, json.dumps(r.json(), ensure_ascii=False)[:900])
                return 1
            cid = r.json()["id"]
            print(f"cloud {cid}: import accepted, ingest running")

        job_id = latest_job(http, pid, cid, "ingest")
        job = wait_job(http, job_id, "ingest")
        print(f"ingest wall clock: {time.time() - t0:.0f}s")

        cloud = http.get(f"{BASE}/clouds/{cid}").json()
        print(
            "status:", cloud["status"],
            "| points:", cloud["point_count"],
            "| ingested:", cloud["ingested_count"],
            "| preview:", cloud["preview_count"],
            "| decimated:", cloud["decimated"],
        )
        print("metadata:", json.dumps(cloud.get("metadata"), ensure_ascii=False)[:1000])
        if cloud["status"] != "ready":
            print("FAILED:", cloud.get("error"))
            return 1

        zmin = cloud["bbox_min"][2]
        zmax = cloud["bbox_max"][2]
        print(f"extent Z {zmin:.2f}..{zmax:.2f}")

        # 1.5 m above the lowest floor is a normal plan cut.
        cut = round(zmin + 1.5, 3)
        section = http.post(
            f"{BASE}/clouds/{cid}/sections",
            json={"kind": "horizontal", "position": cut, "thickness": 0.06, "grid_res": 0.03},
        )
        if section.status_code != 200:
            print("section failed:", section.status_code, section.text[:600])
            return 1
        sec = section.json()
        segs = sec["result"].get("segments") or sec["result"].get("components") or []
        print(
            f"horizontal section @ z={cut}: points={sec['point_count']} "
            f"objects={len(segs)} keys={sorted(sec['result'].keys())}"
        )

        dxf = http.post(f"{BASE}/sections/{sec['id']}/export", params={"format": "dxf", "scale": 50})
        print("DXF:", dxf.status_code, len(dxf.content), "bytes")
        (OUT / "live_section.dxf").write_bytes(dxf.content)

        vertical = http.post(
            f"{BASE}/clouds/{cid}/sections",
            json={"kind": "vertical", "axis": "y", "thickness": 0.08, "grid_res": 0.03},
        )
        if vertical.status_code == 200:
            v = vertical.json()
            print(f"vertical section: points={v['point_count']} pos={v['position']:.2f}")
            vdxf = http.post(f"{BASE}/sections/{v['id']}/export", params={"format": "dxf"})
            (OUT / "live_vertical.dxf").write_bytes(vdxf.content)
            print("vertical DXF:", vdxf.status_code, len(vdxf.content), "bytes")
        else:
            print("vertical section failed:", vertical.status_code, vertical.text[:300])

        t1 = time.time()
        rec = http.post(f"{BASE}/clouds/{cid}/recognize")
        job = wait_job(http, rec.json()["id"], "recognize")
        print(f"recognition: {job['status']} in {time.time() - t1:.0f}s")
        if job["status"] != "succeeded":
            print("recognition error:", job.get("error"))
            return 1

        elems = http.get(f"{BASE}/clouds/{cid}/elements").json()
        counts: dict[str, int] = {}
        for el in elems:
            counts[el["class_name"]] = counts.get(el["class_name"], 0) + 1
        print("elements:", counts)
        levels = http.get(f"{BASE}/clouds/{cid}/levels").json()
        print("levels:", [(round(l["z"], 2), l.get("point_count")) for l in levels])

        edxf = http.get(f"{BASE}/clouds/{cid}/elements.dxf")
        print("elements DXF:", edxf.status_code, len(edxf.content), "bytes")
        (OUT / "live_elements.dxf").write_bytes(edxf.content)

        ifc = http.get(f"{BASE}/clouds/{cid}/bim", params={"format": "ifc"})
        print("IFC:", ifc.status_code, len(ifc.content), "bytes")
        if ifc.status_code == 200:
            (OUT / "live_model.ifc").write_bytes(ifc.content)

        (OUT / "summary.json").write_text(
            json.dumps(
                {
                    "project_id": pid,
                    "cloud_id": cid,
                    "point_count": cloud["point_count"],
                    "ingested_count": cloud["ingested_count"],
                    "bbox_min": cloud["bbox_min"],
                    "bbox_max": cloud["bbox_max"],
                    "section_z": cut,
                    "section_objects": len(segs),
                    "elements": counts,
                    "levels": levels,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
