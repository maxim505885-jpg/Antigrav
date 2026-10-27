"""Read the point count from a sibling 10.rcs without changing either source."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    project_root = repo.parent
    alternate = project_root / "10.rcs"
    linked = project_root / "10 Support" / "10.rcs"
    rcp = project_root / "10.rcp"
    run_dir = repo / "data" / ".t" / f"alternate-10-rcs-count-{uuid.uuid4().hex[:12]}"
    app_data = run_dir / "app-data"
    app_data.mkdir(parents=True)
    os.environ["S2B_DATA_DIR"] = str(app_data)
    sys.path.insert(0, str(repo / "backend"))

    from scan2bim.formats.rcs_native import native_available, read_rcs_native

    if not alternate.is_file() or not linked.is_file() or not rcp.is_file():
        raise FileNotFoundError("expected RCP and both sibling RCS files")
    before = {"path": str(alternate.resolve()), "size_bytes": alternate.stat().st_size,
              "sha256": digest(alternate)}
    evidence = {
        "date": datetime.now().date().isoformat(),
        "stage": 2,
        "purpose": "Determine whether the sibling 10.rcs is the source counted by the 10.rcp manifest, without modifying either RCS",
        "rcp": {"path": str(rcp.resolve()), "size_bytes": rcp.stat().st_size},
        "manifest_linked_rcs": {"path": str(linked.resolve()), "size_bytes": linked.stat().st_size,
                                "sha256": digest(linked)},
        "alternate_rcs_before": before,
        "reader": native_available(),
        "method": "Autodesk ReCap native reader reservoir sample max_points=1; full sequential pass reports source count",
        "start_utc": datetime.now(timezone.utc).isoformat(),
    }
    target = repo / "docs" / "validation" / "STAGE2_ALTERNATE_10_RCS_COUNT_2026-10-25.json"
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    started = time.monotonic()
    last_print = 0.0
    try:
        def progress(_fraction: float, message: str = "") -> None:
            nonlocal last_print
            now = time.monotonic()
            if now - last_print >= 30:
                print("PROGRESS " + json.dumps({"elapsed_seconds": round(now - started, 1),
                                                 "message": message}, ensure_ascii=False), flush=True)
                last_print = now

        raw = read_rcs_native(alternate, max_points=1, progress=progress)
        evidence["reader_result"] = {
            "sample_points_returned": len(raw.xyz),
            "source_point_count": raw.metadata.get("source_point_count"),
            "sample_has_rgb": raw.rgb is not None,
        }
        evidence["count_comparison"] = {
            "rcp_declared_point_count": 295_836_062,
            "manifest_linked_rcs_reader_count": 295_591_803,
            "sibling_rcs_reader_count": raw.metadata.get("source_point_count"),
            "sibling_matches_rcp_declaration": raw.metadata.get("source_point_count") == 295_836_062,
        }
        evidence["acceptance"] = {
            "diagnostic_only": True,
            "rcp_count_discrepancy_resolved": False,
            "original_files_modified": False,
        }
    except Exception as exc:
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        evidence["acceptance"] = {"diagnostic_only": True, "rcp_count_discrepancy_resolved": False}
        raise
    finally:
        evidence["duration_seconds"] = round(time.monotonic() - started, 2)
        evidence["alternate_rcs_after"] = {"size_bytes": alternate.stat().st_size,
                                            "sha256": digest(alternate)}
        evidence["acceptance"]["original_files_modified"] = (
            evidence["alternate_rcs_after"] != {"size_bytes": before["size_bytes"], "sha256": before["sha256"]}
        )
        evidence["cleanup"] = {"isolated_reader_scratch": "removed"}
        shutil.rmtree(run_dir, ignore_errors=True)
        target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("EVIDENCE " + str(target), flush=True)
    print("SUMMARY " + json.dumps(evidence.get("count_comparison", {}), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
