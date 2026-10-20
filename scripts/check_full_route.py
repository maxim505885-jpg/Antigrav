"""End-to-end verification of the full route over real HTTP:
load -> viewer preview -> section -> DXF export -> DXF re-read.
Run while backend/run.py is listening (default http://127.0.0.1:8000).
"""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"


def req(method: str, path: str, body: dict | None = None, raw: bool = False):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=180) as resp:
        payload = resp.read()
        return payload if raw else json.loads(payload)


def main() -> int:
    projects = req("GET", "/projects")
    if not projects:
        print("no projects; POST /api/v1/demo first")
        return 1
    print("1. projects:", [(p["id"][:8], p["name"]) for p in projects])
    pid = projects[0]["id"]

    clouds = req("GET", f"/projects/{pid}/clouds")
    print(
        "2. clouds:",
        [(c["id"][:8], c["source_format"], c["point_count"], c["status"]) for c in clouds],
    )
    cid = clouds[0]["id"]

    prev = req("GET", f"/clouds/{cid}/preview", raw=True)
    print(
        "3. preview: binary payload=%d bytes, stored preview_count=%d, bbox=[%s .. %s]"
        % (len(prev), clouds[0].get("preview_count", 0), clouds[0]["bbox_min"], clouds[0]["bbox_max"])
    )
    assert len(prev) > 100, "preview payload too small"

    stats = req("GET", f"/clouds/{cid}/stats")
    print("4. stats: elements=%s sections=%s" % (stats.get("elements"), stats.get("sections")))

    section = req(
        "POST",
        f"/clouds/{cid}/sections",
        {"kind": "horizontal", "position": 1.0, "thickness": 0.1},
    )
    result = section.get("result", {})
    print(
        "5. section: id=%s kind=%s points=%d contours=%d"
        % (
            section["id"][:8],
            section["kind"],
            section["point_count"],
            len(result.get("polygons", [])),
        )
    )
    assert section["point_count"] > 0, "section is empty"

    dxf_bytes = req("POST", f"/sections/{section['id']}/export?format=dxf", raw=True)
    print("6. dxf download: %d bytes" % len(dxf_bytes))
    head = dxf_bytes[:200].replace(b"\r", b"")
    assert b"SECTION" in head and b"EOF" in dxf_bytes[-64:], "not a DXF payload"

    # 7. re-read the downloaded DXF and count entities
    import tempfile
    from pathlib import Path

    import ezdxf  # noqa: E402

    with tempfile.TemporaryDirectory() as tmp:
        dxf_path = Path(tmp) / "route_check.dxf"
        dxf_path.write_bytes(dxf_bytes)
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        kinds: dict[str, int] = {}
        for e in msp:
            kinds[e.dxftype()] = kinds.get(e.dxftype(), 0) + 1
        print("7. DXF re-read: %s" % kinds)
        assert kinds.get("LWPOLYLINE") or kinds.get("POLYLINE"), "no editable polylines"

    # 8. vertical section too, so both requested kinds are proven
    vsec = req(
        "POST",
        f"/clouds/{cid}/sections",
        {"kind": "vertical", "axis": "x", "position": 3.0, "thickness": 0.1},
    )
    print(
        "8. vertical section: points=%d contours=%d"
        % (vsec["point_count"], len(vsec.get("result", {}).get("polygons", [])))
    )
    assert vsec["point_count"] > 0, "vertical section is empty"

    print("FULL ROUTE OK: load -> preview -> section -> DXF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
