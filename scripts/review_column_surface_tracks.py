"""Read-only voxel connectivity screen for vertical candidate point surfaces."""

from __future__ import annotations

import argparse
from hashlib import file_digest, sha256
import json
from pathlib import Path
import sys

import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from scan2bim.pointdata import NpyPointProvider, PointQuery
from scan2bim.structure.column_surface_assignment import (
    associate_surfaces_to_column,
    cluster_column_surface_tracks,
)
from scan2bim.structure.vertical_surfaces import extract_vertical_surfaces


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def screen_resolution(xyz: np.ndarray, source_rows: np.ndarray, center: np.ndarray,
                      rotation: np.ndarray, half_xy: np.ndarray, z_bounds: tuple[float, float],
                      candidate_height_m: float, voxel_m: float) -> dict:
    local_xy = (xyz[:, :2] - center[:2]) @ rotation
    lower = np.array([-half_xy[0], -half_xy[1], z_bounds[0]])
    upper = np.array([half_xy[0], half_xy[1], z_bounds[1]])
    local = np.column_stack((local_xy, xyz[:, 2]))
    dims = np.ceil((upper - lower) / voxel_m).astype(int) + 1
    ijk = np.floor((local - lower) / voxel_m).astype(int)
    ijk = np.minimum(np.maximum(ijk, 0), dims - 1)
    occupancy = np.zeros(tuple(dims), dtype=bool)
    occupancy[ijk[:, 0], ijk[:, 1], ijk[:, 2]] = True
    labels, label_count = ndimage.label(occupancy, structure=np.ones((3, 3, 3), dtype=np.uint8))
    point_labels = labels[ijk[:, 0], ijk[:, 1], ijk[:, 2]]
    point_counts = np.bincount(point_labels, minlength=label_count + 1)
    voxel_counts = np.bincount(labels.ravel(), minlength=label_count + 1)
    significant = [label for label in range(1, label_count + 1)
                   if voxel_counts[label] >= 3 and point_counts[label] >= 20]
    significant.sort(key=lambda label: (-int(point_counts[label]), -int(voxel_counts[label]), label))
    components = []
    for label in significant[:12]:
        component_points = np.flatnonzero(point_labels == label)
        coords = local[component_points]
        z_bin = np.floor((coords[:, 2] - z_bounds[0]) / .25).astype(int)
        occupied_bins = np.unique(z_bin)
        longest_run = run = 0
        previous = None
        for value in occupied_bins:
            run = run + 1 if previous is not None and value == previous + 1 else 1
            longest_run = max(longest_run, run)
            previous = int(value)
        rows = np.asarray(source_rows[component_points], dtype=np.int64)
        row_digest = sha256(np.sort(rows).tobytes()).hexdigest()
        components.append({
            "component_id": int(label), "point_count": int(point_counts[label]),
            "occupied_voxel_count": int(voxel_counts[label]),
            "local_bounds_m": [coords.min(axis=0).tolist(), coords.max(axis=0).tolist()],
            "vertical_span_m": float(coords[:, 2].max() - coords[:, 2].min()),
            "candidate_height_coverage_fraction": float((coords[:, 2].max() - coords[:, 2].min()) / candidate_height_m),
            "occupied_z_bins_0_25m": int(len(occupied_bins)),
            "longest_consecutive_z_bins": int(longest_run),
            "source_crop_row_ids_sha256": row_digest,
            "source_crop_row_ids_sample": np.sort(rows)[:20].tolist(),
        })
    return {
        "voxel_size_m": voxel_m,
        "roi_point_count": int(len(xyz)),
        "occupied_voxel_count": int(np.count_nonzero(occupancy)),
        "connected_component_count": int(label_count),
        "significant_component_count": int(len(significant)),
        "unassigned_point_count": int(point_counts[0]),
        "largest_component_point_fraction": float(point_counts[significant[0]] / len(xyz)) if significant and len(xyz) else 0.0,
        "components": components,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/validation/pilot-A/revit/scan2bim-pilot-A.json")
    parser.add_argument("--crop", type=Path, default=ROOT / "data/validation/pilot-A")
    parser.add_argument("--review", type=Path, default=ROOT / "data/validation/pilot-A/column-section-review-v3")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--voxel-m", type=float, nargs="+", default=[.02, .05])
    parser.add_argument("--candidate-margin-m", type=float, default=.2)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output already exists; choose a new path")
    if any(not np.isfinite(v) or v <= 0 for v in args.voxel_m) or args.candidate_margin_m < 0:
        parser.error("voxel sizes must be positive and candidate margin non-negative")
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
    before = {str(path): file_hash(path) for path in tracked}
    provider = NpyPointProvider(positions_path, origin=origin)
    source_rows = np.load(source_rows_path, mmap_mode="r", allow_pickle=False)
    if source_rows.shape != (provider.count,):
        parser.error("source_indices.npy does not match positions.npy")
    elements = {item["id"]: item for item in snapshot["elements"]}
    results = []
    surface_summary = {"candidates_with_vertical_faces": 0, "candidates_with_orthogonal_surface_intersection": 0,
                       "candidates_with_endpoint_supported_corner": 0,
                       "candidates_with_pair_over_half_candidate_height": 0,
                       "candidates_with_candidate_face": 0, "candidates_with_four_candidate_faces": 0,
                       "candidate_face_observation_count": 0,
                       "surface_track_count": 0, "candidate_surface_track_count": 0,
                       "full_height_surface_track_count": 0,
                       "vertical_surface_count": 0, "orthogonal_surface_intersection_count": 0,
                       "endpoint_supported_corner_count": 0, "pair_over_half_candidate_height_count": 0}
    summary = {str(v): {"candidate_count": 0, "roi_point_count": 0,
                        "significant_component_count": 0, "candidates_with_component_over_half_height": 0}
               for v in args.voxel_m}
    for index, record in enumerate(review["columns"], 1):
        element = elements[record["element_id"]]
        geometry = element["geometry"]
        center = np.asarray(geometry["center"], dtype=float)
        angle = float(geometry.get("rotation_z", 0.0))
        rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        half = np.array([geometry["sizes"]["length"], geometry["sizes"]["thickness"]], dtype=float) / 2
        padded_half = half + args.candidate_margin_m
        world_extent = np.abs(rotation) @ padded_half
        z_min, z_max = record["query_bounds_world_m"][2], record["query_bounds_world_m"][5]
        lower = np.array([*(center[:2] - world_extent), z_min])
        upper = np.array([*(center[:2] + world_extent), z_max])
        batches = list(provider.iter_points(PointQuery(tuple(np.r_[lower, upper]))))
        xyz = np.concatenate([batch.xyz for batch in batches]) if batches else np.empty((0, 3))
        row_ids = np.concatenate([batch.source_indices for batch in batches]) if batches else np.empty(0, dtype=np.int64)
        local_xy = (xyz[:, :2] - center[:2]) @ rotation
        keep = (np.abs(local_xy) <= padded_half).all(axis=1)
        xyz, row_ids = xyz[keep], row_ids[keep]
        row_ids = np.asarray(source_rows[row_ids], dtype=np.int64)
        surface_result = extract_vertical_surfaces(xyz, voxel_m=.02) if len(xyz) >= 30 else {
            "status": "insufficient_points", "input_point_count": len(xyz), "surfaces": [],
            "adjacent_face_pairs": [], "review_required": True,
            "engineering_status": "not_assessed", "structural_role": "unknown"}
        for surface in surface_result["surfaces"]:
            source_ids = np.asarray(row_ids[surface["input_point_indices"]], dtype=np.int64)
            surface["source_crop_row_ids"] = np.sort(source_ids).tolist()
            surface.pop("input_point_indices", None)
        for pair in surface_result["adjacent_face_pairs"]:
            pair["candidate_height_coverage_fraction"] = pair["shared_consecutive_vertical_span_m"] / float(geometry["sizes"]["height"])
            pair["covers_half_candidate_height"] = pair["candidate_height_coverage_fraction"] >= .5
        association = associate_surfaces_to_column(geometry, surface_result)
        surface_tracks = cluster_column_surface_tracks(geometry, surface_result, association)
        surface_summary["surface_track_count"] += len(surface_tracks)
        surface_summary["candidate_surface_track_count"] += sum(
            track["candidate_edge_id"] is not None for track in surface_tracks)
        surface_summary["full_height_surface_track_count"] += sum(
            track["candidate_edge_id"] is not None and track["vertical_support_fraction"] >= .95
            for track in surface_tracks)
        surface_summary["candidates_with_candidate_face"] += int(association["candidate_edge_count"] > 0)
        surface_summary["candidates_with_four_candidate_faces"] += int(association["candidate_edge_count"] == 4)
        surface_summary["candidate_face_observation_count"] += association["candidate_edge_count"]
        surface_summary["candidates_with_vertical_faces"] += int(bool(surface_result["surfaces"]))
        supported_pairs = [pair for pair in surface_result["adjacent_face_pairs"]
                           if pair["corner_supported_by_both_observed_endpoints"]]
        surface_summary["candidates_with_orthogonal_surface_intersection"] += int(bool(surface_result["adjacent_face_pairs"]))
        surface_summary["candidates_with_endpoint_supported_corner"] += int(bool(supported_pairs))
        surface_summary["vertical_surface_count"] += len(surface_result["surfaces"])
        surface_summary["orthogonal_surface_intersection_count"] += len(surface_result["adjacent_face_pairs"])
        surface_summary["endpoint_supported_corner_count"] += len(supported_pairs)
        persistent_pairs = [pair for pair in surface_result["adjacent_face_pairs"] if pair["covers_half_candidate_height"]]
        surface_summary["candidates_with_pair_over_half_candidate_height"] += int(bool(persistent_pairs))
        surface_summary["pair_over_half_candidate_height_count"] += len(persistent_pairs)
        screens = []
        for voxel in args.voxel_m:
            result = screen_resolution(xyz, row_ids, center, rotation, padded_half,
                                       (z_min, z_max), float(geometry["sizes"]["height"]), voxel)
            screens.append(result)
            current = summary[str(voxel)]
            current["candidate_count"] += 1
            current["roi_point_count"] += result["roi_point_count"]
            current["significant_component_count"] += result["significant_component_count"]
            current["candidates_with_component_over_half_height"] += int(any(
                c["candidate_height_coverage_fraction"] >= .5 for c in result["components"]))
        results.append({"candidate_id": record["element_id"], "candidate_role_status": element["review_status"],
            "candidate_geometry": geometry, "candidate_margin_m": args.candidate_margin_m,
            "roi_point_count": int(len(xyz)), "vertical_surface_screen": surface_result,
            "column_surface_association": association, "column_surface_tracks": surface_tracks,
            "screening_resolutions": screens})
        print(json.dumps({"candidate": index, "total": len(review["columns"]),
            "id": record["element_id"], "points": len(xyz)}, ensure_ascii=False), flush=True)
    after = {str(path): file_hash(path) for path in tracked}
    if before != after:
        raise RuntimeError("source data changed during the read-only connectivity screen")
    output = {"schema": "scan.column-surface-connectivity-review/1", "source_sha256": before,
        "input_files_unchanged": True, "candidate_margin_m": args.candidate_margin_m,
        "connectivity": "26-neighbour occupied voxels", "z_coverage_bin_m": .25,
        "summary_by_voxel_m": summary,
        "vertical_surface_summary": surface_summary,
        "notes": "This is a connectivity, plane-intersection, OBB-face-association and conservative face-track clustering screen, not proof of column ownership. Resolution-dependent merging/splitting and occlusion remain possible. Candidate tracks are geometric evidence only; roles remain unknown and settings are not engineering tolerances.",
        "engineering_status": "not_assessed", "catalog_assignment": "none", "candidates": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"output": str(args.out), "summary_by_voxel_m": summary,
        "input_files_unchanged": True, "engineering_status": "not_assessed"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
