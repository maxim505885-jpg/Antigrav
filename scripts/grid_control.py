"""Create a read-only pitch check for column candidates in pilot-A."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from scan2bim.structure.grid import station_pitch_report


def group_rows(points: np.ndarray, angle_rad: float, tolerance_m: float) -> list[list[int]]:
    """Group candidates by across-axis coordinate; this is a review aid only."""
    direction = np.array([np.cos(angle_rad), np.sin(angle_rad)])
    normal = np.array([-direction[1], direction[0]])
    across = points @ normal
    order = np.argsort(across, kind="stable")
    groups: list[list[int]] = []
    for index in order:
        if not groups or across[index] - float(np.mean(across[groups[-1]])) > tolerance_m:
            groups.append([int(index)])
        else:
            groups[-1].append(int(index))
    return groups


def build_report(recognition_path: Path, nominal_pitch_m: float, row_tolerance_m: float) -> dict:
    payload = json.loads(recognition_path.read_text(encoding="utf-8"))
    result = payload["result"]
    angle_deg = float(result["stats"]["steel"]["hall_axis_deg"])
    angle_rad = float(np.deg2rad(angle_deg))
    candidates = [e for e in result["elements"] if e.get("class_name") == "column"]
    centers = np.asarray([e["geometry"]["center"][:2] for e in candidates], dtype=np.float64)
    if not len(centers):
        centers = np.empty((0, 2), dtype=np.float64)
    groups = group_rows(centers, angle_rad, row_tolerance_m) if len(centers) else []
    direction = np.array([np.cos(angle_rad), np.sin(angle_rad)])
    normal = np.array([-direction[1], direction[0]])
    rows = []
    for row_number, indices in enumerate(groups, start=1):
        row_points = centers[indices]
        along = row_points @ direction
        order = np.argsort(along, kind="stable")
        sorted_indices = [indices[int(i)] for i in order]
        sorted_points = centers[sorted_indices]
        pitch = station_pitch_report(sorted_points, angle_rad, nominal_pitch_m)
        rows.append({
            "row_candidate": row_number,
            "transverse_center_m": float(np.mean(row_points @ normal)),
            "candidate_count": len(indices),
            "candidate_indices": sorted_indices,
            "world_centers_m": [candidates[i]["geometry"]["center"] for i in sorted_indices],
            "intervals": pitch["intervals"],
            "status": "manual_row_assignment_required",
        })
    return {
        "schema": "scan.column-grid-review/1",
        "source_cloud_id": payload["source_cloud_id"],
        "source_crop": str(recognition_path.parent),
        "candidate_count": len(candidates),
        "hall_axis_deg": angle_deg,
        "nominal_pitch_m": nominal_pitch_m,
        "row_grouping_tolerance_m": row_tolerance_m,
        "rows": rows,
        "acceptance_status": "manual_ground_truth_and_tolerance_required",
        "geometry_modified": False,
        "method_note": (
            "Rows are provisional clusters of detected candidates by transverse coordinate. "
            "No candidate was snapped, moved, accepted, or rejected. Intervals require manual review."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recognition", type=Path, default=ROOT / "data/validation/pilot-A/recognition.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/validation/pilot-A/grid-report.json")
    parser.add_argument("--pitch", type=float, default=6.0, help="Nominal longitudinal column pitch in metres")
    parser.add_argument("--row-tolerance", type=float, default=1.0, help="Provisional row-clustering tolerance in metres")
    args = parser.parse_args()
    if args.pitch <= 0 or args.row_tolerance <= 0:
        parser.error("pitch and row tolerance must be positive")
    report = build_report(args.recognition, args.pitch, args.row_tolerance)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    interval_count = sum(len(row["intervals"]) for row in report["rows"])
    print(json.dumps({
        "output": str(args.output),
        "candidates": report["candidate_count"],
        "provisional_rows": len(report["rows"]),
        "intervals_for_review": interval_count,
        "acceptance_status": report["acceptance_status"],
        "geometry_modified": report["geometry_modified"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
