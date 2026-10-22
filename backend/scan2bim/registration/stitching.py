"""Point cloud stitching (registration) module for multi-station scans.

Provides:
- Robust Iterative Closest Point (ICP) using SVD / Kabsch algorithm and cKDTree.
- SE(3) Transformation matrix calculation.
- ReCap-compatible registration manifest and unified point cloud export.
- Batch merging of multiple RCS/PLY scans into unified positions.npy with meta.json.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any
import numpy as np
from scipy.spatial import cKDTree

logger = logging.getLogger(__name__)


def kabsch_fit(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Compute optimal rotation matrix R and translation t using Kabsch algorithm (SVD).

    Minimizes || R * source + t - target ||^2.
    """
    centroid_src = np.mean(source, axis=0)
    centroid_dst = np.mean(target, axis=0)

    p = source - centroid_src
    q = target - centroid_dst

    h = p.T @ q
    u, s, vt = np.linalg.svd(h)
    r = vt.T @ u.T

    # Reflection correction
    if np.linalg.det(r) < 0:
        vt[-1, :] *= -1
        r = vt.T @ u.T

    t = centroid_dst - r @ centroid_src
    return r, t


def rigid_icp(
    source_points: np.ndarray,
    target_points: np.ndarray,
    max_iterations: int = 50,
    tolerance_m: float = 1e-4,
    max_correspondence_distance_m: float = 0.5,
    sample_size: int = 10000,
) -> dict[str, Any]:
    """Align source point cloud to target point cloud.

    Returns:
    - R: 3x3 rotation matrix
    - t: 3-vector translation
    - transformation_4x4: SE(3) matrix
    - rmse_mm: root mean square error in millimeters
    - converged: bool
    """
    # Safe O(k) memory sampling to prevent OpenBLAS / RAM exhaustion on large scans
    if len(source_points) > sample_size:
        indices = np.random.randint(0, len(source_points), size=sample_size)
        src = np.asarray(source_points[indices], dtype=np.float64).copy()
    else:
        src = np.asarray(source_points, dtype=np.float64).copy()

    if len(target_points) > sample_size * 2:
        tgt_indices = np.random.randint(0, len(target_points), size=sample_size * 2)
        tgt = np.asarray(target_points[tgt_indices], dtype=np.float64)
    else:
        tgt = np.asarray(target_points, dtype=np.float64)

    tree = cKDTree(tgt)
    current_r = np.eye(3, dtype=np.float64)
    # Remove bulk translation before nearest-neighbour matching
    current_t = np.mean(tgt, axis=0) - np.mean(src, axis=0)
    prev_rmse = float("inf")

    converged = False
    iteration = 0
    for iteration in range(max_iterations):
        transformed_src = (current_r @ src.T).T + current_t
        distances, indices = tree.query(transformed_src, k=1)

        # Filter out points beyond max correspondence distance (outliers)
        valid = distances < max_correspondence_distance_m
        if np.sum(valid) < 10:
            break

        step_r, step_t = kabsch_fit(transformed_src[valid], tgt[indices[valid]])

        current_r = step_r @ current_r
        current_t = step_r @ current_t + step_t

        transformed_src = (current_r @ src.T).T + current_t
        updated_distances, _ = tree.query(transformed_src, k=1)
        updated_valid = updated_distances < max_correspondence_distance_m
        if np.sum(updated_valid) < 10:
            break

        rmse = float(np.sqrt(np.mean(updated_distances[updated_valid] ** 2)))
        rotation_step = float(
            np.arccos(np.clip((np.trace(step_r) - 1.0) / 2.0, -1.0, 1.0))
        )
        translation_step = float(np.linalg.norm(step_t))
        if abs(prev_rmse - rmse) < tolerance_m or (
            rotation_step < tolerance_m and translation_step < tolerance_m
        ):
            converged = True
            break
        prev_rmse = rmse

    t4x4 = np.eye(4, dtype=np.float64)
    t4x4[:3, :3] = current_r
    t4x4[:3, 3] = current_t

    final_points = (current_r @ src.T).T + current_t
    final_distances, _ = tree.query(final_points, k=1)
    final_valid = final_distances < max_correspondence_distance_m
    final_rmse = (
        None
        if not np.any(final_valid)
        else round(float(np.sqrt(np.mean(final_distances[final_valid] ** 2)) * 1000.0), 3)
    )

    return {
        "rotation": current_r.tolist(),
        "translation": current_t.tolist(),
        "matrix_4x4": t4x4.tolist(),
        "rmse_mm": final_rmse,
        "iterations": iteration + 1,
        "converged": converged,
    }


def create_recap_registration_project(
    stations: list[dict[str, Any]],
    project_name: str,
    output_path: Path,
) -> Path:
    """Write SCAN registration metadata; this does not create or verify an RCP project."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "version": "1.0",
        "format": "SCAN station-registration manifest",
        "status": "metadata_only",
        "recap_project_generated": False,
        "registration_verified": False,
        "notice": "This JSON records station poses only; it is not an Autodesk ReCap RCP/RCS project.",
        "project_name": project_name,
        "station_count": len(stations),
        "stations": [
            {
                "station_id": s.get("id") or s.get("station_id") or f"station_{idx+1}",
                "file_path": str(s.get("path", "")),
                "point_count": int(s.get("point_count", 0)),
                "matrix_4x4": s.get("matrix_4x4", np.eye(4).tolist()),
                "rmse_mm": (
                    float(s["rmse_mm"]) if s.get("rmse_mm") is not None else None
                ),
            }
            for idx, s in enumerate(stations)
        ],
    }
    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def export_stitched_cloud(
    stations_data: list[dict[str, Any]],
    output_path: Path,
) -> Path:
    """Apply SE(3) transformation to all stations and save unified point cloud (PLY format)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    all_points = []
    all_colors = []

    for st in stations_data:
        pts = np.asarray(st["points"], dtype=np.float32)
        mat = np.asarray(st.get("matrix_4x4", np.eye(4)), dtype=np.float32)

        r = mat[:3, :3]
        t = mat[:3, 3]
        transformed_pts = (r @ pts.T).T + t
        all_points.append(transformed_pts)

        if "colors" in st and st["colors"] is not None and len(st["colors"]) == len(pts):
            all_colors.append(np.asarray(st["colors"], dtype=np.uint8))
        else:
            all_colors.append(np.full((len(pts), 3), 200, dtype=np.uint8))

    merged_pts = np.vstack(all_points)
    merged_cols = np.vstack(all_colors)

    header = f"""ply
format binary_little_endian 1.0
element vertex {len(merged_pts)}
property float x
property float y
property float z
property uchar red
property uchar green
property uchar blue
end_header
"""
    with open(output_path, "wb") as f:
        f.write(header.encode("ascii"))
        vertex_dtype = np.dtype([
            ("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
            ("red", "u1"), ("green", "u1"), ("blue", "u1"),
        ])
        vertex_data = np.empty(len(merged_pts), dtype=vertex_dtype)
        vertex_data["x"] = merged_pts[:, 0]
        vertex_data["y"] = merged_pts[:, 1]
        vertex_data["z"] = merged_pts[:, 2]
        vertex_data["red"] = merged_cols[:, 0]
        vertex_data["green"] = merged_cols[:, 1]
        vertex_data["blue"] = merged_cols[:, 2]
        f.write(vertex_data.tobytes())

    return output_path


def merge_and_save_unified_cloud(
    stations: list[dict[str, Any]],
    output_dir: str | Path,
    project_title: str = "Сводное облако цеха (1.rcs + 2.rcs)",
    export_ply: bool = False,
) -> dict[str, Any]:
    """Merge multiple scan stations into a unified dataset with positions.npy and meta.json.

    Each station in `stations` contains:
    - 'id' or 'name': str
    - 'points': np.ndarray (Nx3)
    - 'matrix_4x4': optional 4x4 SE(3) transformation matrix (defaults to identity)
    - 'path': optional str / Path

    Returns dict with paths to positions.npy, meta.json, registration_manifest.json, and point count.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    transformed_clouds = []
    total_count = 0
    station_meta = []

    for idx, st in enumerate(stations):
        pts = np.asarray(st["points"], dtype=np.float32)
        mat = np.asarray(st.get("matrix_4x4", np.eye(4)), dtype=np.float32)

        r = mat[:3, :3]
        t = mat[:3, 3]
        transformed_pts = (r @ pts.T).T + t
        transformed_clouds.append(transformed_pts)
        total_count += len(transformed_pts)

        station_meta.append({
            "station_id": st.get("id") or st.get("name") or f"station_{idx+1}",
            "path": str(st.get("path", "")),
            "point_count": len(pts),
            "matrix_4x4": mat.tolist(),
            "rmse_mm": st.get("rmse_mm"),
        })

    merged_world = np.vstack(transformed_clouds)

    # Compute global world bounding box
    world_min = merged_world.min(axis=0).astype(np.float64)
    world_max = merged_world.max(axis=0).astype(np.float64)
    origin = ((world_min + world_max) / 2.0).astype(np.float64)

    # Local coordinates centered around origin
    local_positions = (merged_world - origin).astype(np.float32)
    local_min = local_positions.min(axis=0).astype(np.float64)
    local_max = local_positions.max(axis=0).astype(np.float64)

    # Save positions.npy
    positions_file = out_path / "positions.npy"
    np.save(positions_file, local_positions)

    # Compute SHA-256
    hasher = hashlib.sha256()
    with open(positions_file, "rb") as f:
        while chunk := f.read(4 * 1024 * 1024):
            hasher.update(chunk)
    sha256_hash = hasher.hexdigest()

    meta = {
        "reader": "multi_scan_unified_stitcher",
        "name": project_title,
        "source_point_count": total_count,
        "stored_point_count": total_count,
        "origin": origin.tolist(),
        "bbox_min": (local_min + origin).tolist(),
        "bbox_max": (local_max + origin).tolist(),
        "checksum_sha256": sha256_hash,
        "station_count": len(stations),
        "unified_merge": True,
    }
    meta_file = out_path / "meta.json"
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # Registration manifest
    manifest_file = out_path / "registration_manifest.json"
    create_recap_registration_project(station_meta, project_title, manifest_file)

    ply_path = None
    if export_ply:
        ply_file = out_path / "unified_cloud.ply"
        export_stitched_cloud([{"points": merged_world}], ply_file)
        ply_path = str(ply_file)

    return {
        "status": "success",
        "positions_file": str(positions_file),
        "meta_file": str(meta_file),
        "manifest_file": str(manifest_file),
        "ply_file": ply_path,
        "total_points": total_count,
        "origin": origin.tolist(),
        "world_bounds": {"min": world_min.tolist(), "max": world_max.tolist()},
    }
