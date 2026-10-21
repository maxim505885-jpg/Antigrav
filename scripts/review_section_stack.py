"""Compare column section evidence at several heights and slice thicknesses."""

from __future__ import annotations

import argparse
from hashlib import file_digest
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from scan2bim.pointdata import NpyPointProvider, PointQuery
from scan2bim.structure.section_fitting import fit_rectangular_section


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/validation/pilot-A/revit/scan2bim-pilot-A.json")
    parser.add_argument("--crop", type=Path, default=ROOT / "data/validation/pilot-A")
    parser.add_argument("--review", type=Path, default=ROOT / "data/validation/pilot-A/column-section-review-v3")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tolerance-m", type=float, default=.004)
    parser.add_argument("--candidate-margin-m", type=float, default=.2)
    parser.add_argument("--slice-thickness-m", type=float, nargs="+", default=[.2, .5, 1.0])
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output already exists; choose a new path")
    if args.source.suffix.lower() != ".json" or any(not np.isfinite(x) or x <= 0 for x in args.slice_thickness_m):
        parser.error("source must be JSON and slice thicknesses must be positive")
    snapshot = json.loads(args.source.read_text(encoding="utf-8"))
    review_path = args.review / "report.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    metadata_path = args.crop / "recognition.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    origin = np.asarray(snapshot["source"]["origin"], dtype=float)
    if not np.array_equal(origin, np.asarray(metadata["origin"], dtype=float)):
        parser.error("snapshot and derived crop origins differ")
    positions_path = args.crop / "positions.npy"
    source_rows_path = args.crop / "source_indices.npy"
    tracked = [args.source, review_path, metadata_path, positions_path, source_rows_path]
    before = {str(path): checksum(path) for path in tracked}
    provider = NpyPointProvider(positions_path, origin=origin)
    source_rows = np.load(source_rows_path, mmap_mode="r", allow_pickle=False)
    if source_rows.shape != (provider.count,):
        parser.error("derived point-source map does not match positions.npy")
    source_elements = {item["id"]: item for item in snapshot["elements"]}
    totals: dict[str, dict[str, int]] = {str(x): {} for x in args.slice_thickness_m}
    columns = []
    for column_number, record in enumerate(review["columns"], 1):
        element = source_elements[record["element_id"]]
        geometry = element["geometry"]
        center = np.asarray(geometry["center"], dtype=float)
        angle = float(geometry.get("rotation_z", 0.0))
        rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        half = np.array([geometry["sizes"]["length"], geometry["sizes"]["thickness"]], dtype=float) / 2
        padded_half = half + args.candidate_margin_m
        world_extent = np.abs(rotation) @ padded_half
        lower = np.array([*(center[:2] - world_extent), record["query_bounds_world_m"][2]])
        upper = np.array([*(center[:2] + world_extent), record["query_bounds_world_m"][5]])
        xyz_batches, row_batches = [], []
        for batch in provider.iter_points(PointQuery(tuple(np.r_[lower, upper]))):
            xyz_batches.append(batch.xyz)
            row_batches.append(batch.source_indices)
        roi_xyz = np.concatenate(xyz_batches) if xyz_batches else np.empty((0, 3))
        roi_rows = np.concatenate(row_batches) if row_batches else np.empty(0, dtype=np.int64)
        local_xy = (roi_xyz[:, :2] - center[:2]) @ rotation
        in_candidate = (np.abs(local_xy) <= padded_half).all(axis=1)
        roi_xyz, roi_rows = roi_xyz[in_candidate], roi_rows[in_candidate]

        # Reuse the diagnostic's observed-density peaks only as sampling locations.
        levels: list[float] = []
        for item in sorted(record["raw_height_profile"], key=lambda value: value["points_inside_candidate"], reverse=True):
            z = float(item["world_z_m"])
            if item["points_inside_candidate"] >= 100 and all(abs(z - used) >= .4 for used in levels):
                levels.append(z)
            if len(levels) == 5:
                break
        level_results = []
        for z in sorted(levels):
            for thickness in args.slice_thickness_m:
                selected = np.abs(roi_xyz[:, 2] - z) <= thickness / 2
                points, point_rows = roi_xyz[selected], roi_rows[selected]
                if len(points) >= 100:
                    fit = fit_rectangular_section(points[:, :2], distance_tolerance_m=args.tolerance_m)
                    status = fit["status"]
                    faces = []
                    for face in fit["observed_faces"]:
                        indices = np.asarray(face["input_point_indices"], dtype=int)
                        faces.append({
                            "face_id": face["face_id"],
                            "observed_span_m": face["observed_span_m"],
                            "rmse_m": face["rmse_m"],
                            "support_count": face["support_count"],
                            "source_crop_row_ids": np.asarray(source_rows[point_rows[indices]], dtype=np.int64).tolist(),
                        })
                    hypotheses = fit["hypotheses"]
                else:
                    status, faces, hypotheses = "insufficient_points", [], []
                key = str(thickness)
                totals[key][status] = totals[key].get(status, 0) + 1
                level_results.append({"world_z_m": z, "slice_thickness_m": thickness,
                    "point_count_within_candidate_footprint": int(len(points)), "status": status,
                    "observed_faces": faces, "hypotheses": hypotheses, "review_required": True})
        columns.append({"candidate_id": record["element_id"], "candidate_geometry": geometry,
            "sampling_levels_world_z_m": sorted(levels), "slice_results": level_results})
        print(json.dumps({"column": column_number, "total": len(review["columns"]),
            "id": record["element_id"], "sampled_levels": len(levels)}, ensure_ascii=False), flush=True)
    after = {str(path): checksum(path) for path in tracked}
    if before != after:
        raise RuntimeError("input files changed during read-only section-stack review")
    result = {"schema": "scan.column-section-stack-review/1",
        "source_sha256": before, "input_files_unchanged": True,
        "candidate_footprint_margin_m": args.candidate_margin_m,
        "slice_thicknesses_m": args.slice_thickness_m, "line_distance_tolerance_m": args.tolerance_m,
        "sampling_note": "Heuristic candidates and density peaks define query windows only; neither confirms point ownership or structural role.",
        "engineering_status": "not_assessed", "catalog_assignment": "none",
        "summary_by_slice_thickness": totals, "columns": columns}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(args.out), "summary_by_slice_thickness": totals,
        "input_files_unchanged": True, "engineering_status": "not_assessed"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
