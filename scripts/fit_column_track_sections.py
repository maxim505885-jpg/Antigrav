"""Fit multi-height column sections from frozen candidate surface tracks.

All input clouds are local derived NPY data. The original FARO RCS is not read.
The report is append-only: choose a new --out path for every run.
"""

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
from scan2bim.structure.column_section_series import fit_column_track_sections


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def _candidate_result(candidate_id: str, report: dict) -> dict:
    """Keep the frozen audit ID authoritative over measurement payload fields."""
    return {**report, "candidate_id": candidate_id}


def _bounds(geometry: dict, margin_m: float) -> tuple[np.ndarray, np.ndarray]:
    center = np.asarray(geometry["center"], dtype=np.float64)
    angle = float(geometry.get("rotation_z", 0.0))
    rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    half = np.asarray([geometry["sizes"]["length"], geometry["sizes"]["thickness"]], dtype=np.float64) / 2
    padded_half = half + margin_m
    extent = np.abs(rotation) @ padded_half
    z_min, z_max = center[2] - geometry["sizes"]["height"] / 2, center[2] + geometry["sizes"]["height"] / 2
    return np.array([*(center[:2] - extent), z_min]), np.array([*(center[:2] + extent), z_max])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracks", type=Path, default=ROOT / "data/validation/pilot-A/column-surface-tracks-v15.json")
    parser.add_argument("--source", type=Path, default=ROOT / "data/validation/pilot-A/revit/scan2bim-pilot-A.json")
    parser.add_argument("--crop", type=Path, default=ROOT / "data/validation/pilot-A")
    parser.add_argument("--review", type=Path, default=ROOT / "data/validation/pilot-A/column-section-review-v3")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--vertical-bin-m", type=float, default=0.25)
    parser.add_argument("--known-sides-m", type=float, nargs=2, metavar=("A", "B"),
                        help="explicit measured side lengths, metres; applied to observed slices only")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output exists; choose a new immutable report path")
    if not np.isfinite(args.vertical_bin_m) or args.vertical_bin_m <= 0:
        parser.error("vertical-bin-m must be finite and positive")

    tracks_report = json.loads(args.tracks.read_text(encoding="utf-8"))
    snapshot = json.loads(args.source.read_text(encoding="utf-8"))
    review_path = args.review / "report.json"
    metadata_path = args.crop / "recognition.json"
    positions_path = args.crop / "positions.npy"
    source_rows_path = args.crop / "source_indices.npy"
    paths = [args.tracks, args.source, review_path, metadata_path, positions_path, source_rows_path]
    before = {str(path): sha256(path) for path in paths}

    # The v15 provenance dictionary is keyed by original absolute paths. Match
    # by unique basename while validating every expected source hash.
    audit_sources = tracks_report.get("source_sha256", {})
    for path in (args.source, review_path, metadata_path, positions_path, source_rows_path):
        expected = [digest for old_path, digest in audit_sources.items() if Path(old_path).name == path.name]
        if len(expected) != 1 or before[str(path)] != expected[0]:
            parser.error(f"frozen surface audit source hash mismatch for {path.name}")

    origin = np.asarray(snapshot["source"]["origin"], dtype=np.float64)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not np.array_equal(origin, np.asarray(metadata["origin"], dtype=np.float64)):
        parser.error("snapshot and derived crop coordinate origins differ")
    provider = NpyPointProvider(positions_path, origin=origin)
    source_rows = np.load(source_rows_path, mmap_mode="r", allow_pickle=False)
    if source_rows.shape != (provider.count,) or not np.issubdtype(source_rows.dtype, np.integer):
        parser.error("derived source row map does not match positions.npy")
    elements = {item["id"]: item for item in snapshot["elements"]}

    results = []
    totals = {"candidate_count": 0, "candidate_track_count": 0, "excluded_track_count": 0,
              "slice_count": 0, "proposed_slice_count": 0, "unknown_slice_count": 0}
    for record in tracks_report["candidates"]:
        candidate_id = record["candidate_id"]
        if candidate_id not in elements:
            parser.error(f"track audit references missing candidate {candidate_id}")
        element = elements[candidate_id]
        geometry = record["candidate_geometry"]
        if element.get("geometry") != geometry:
            parser.error(f"candidate geometry changed since the frozen audit for {candidate_id}")
        surface_tracks = record["column_surface_tracks"]
        supported = [track for track in surface_tracks
                     if track.get("candidate_edge_id") in {"u+", "u-", "v+", "v-"}
                     and track.get("track_status") in {"candidate_track", "weak_candidate_track"}]
        if supported:
            lower, upper = _bounds(geometry, float(tracks_report["candidate_margin_m"]))
            xyz_parts, row_parts = [], []
            for batch in provider.iter_points(PointQuery(tuple(np.r_[lower, upper]))):
                xyz_parts.append(batch.xyz)
                row_parts.append(np.asarray(source_rows[batch.source_indices], dtype=np.int64))
            xyz = np.concatenate(xyz_parts) if xyz_parts else np.empty((0, 3), dtype=np.float64)
            ids = np.concatenate(row_parts) if row_parts else np.empty(0, dtype=np.int64)
            angle = float(geometry.get("rotation_z", 0.0))
            rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
            half = np.asarray([geometry["sizes"]["length"], geometry["sizes"]["thickness"]]) / 2
            local_xy = (xyz[:, :2] - np.asarray(geometry["center"][:2])) @ rotation
            keep = (np.abs(local_xy) <= half + float(tracks_report["candidate_margin_m"])).all(axis=1)
            xyz, ids = xyz[keep], ids[keep]
        else:
            xyz, ids = np.empty((0, 3), dtype=np.float64), np.empty(0, dtype=np.int64)

        report = fit_column_track_sections(
            geometry, surface_tracks, xyz, ids,
            vertical_bin_m=args.vertical_bin_m,
            known_sides_m=tuple(args.known_sides_m) if args.known_sides_m else None,
        )
        series = report["section_series"]
        results.append(_candidate_result(candidate_id, report))
        totals["candidate_count"] += 1
        totals["candidate_track_count"] += report["candidate_track_count"]
        totals["excluded_track_count"] += len(report["excluded_tracks"])
        totals["slice_count"] += len(series["section_slices"])
        totals["proposed_slice_count"] += sum(item["status"] == "proposed" for item in series["section_slices"])
        totals["unknown_slice_count"] += sum(item["status"] == "unknown" for item in series["section_slices"])

    after = {str(path): sha256(path) for path in paths}
    if before != after:
        raise RuntimeError("an input changed during the read-only track-section run")
    output = {
        "schema": "scan.column-track-section-series-review/1",
        "inputs_sha256": before,
        "input_files_unchanged": True,
        "vertical_bin_m": args.vertical_bin_m,
        "known_sides_m": args.known_sides_m,
        "engineering_status": "not_assessed",
        "catalog_assignment": "none",
        "source_geometry_modified": False,
        "notes": "Only already-associated candidate surface tracks are fitted. Unassigned tracks are excluded; empty height bins stay unknown. This diagnostic does not confirm column ownership or type.",
        "summary": totals,
        "candidates": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(args.out), "summary": totals, "input_files_unchanged": True,
                      "engineering_status": "not_assessed"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
