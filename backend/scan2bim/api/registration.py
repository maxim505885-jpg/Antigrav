"""REST API endpoints for point cloud stitching, ICP registration, and ReCap project export."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import one, rows
from ..registration.stitching import (
    rigid_icp,
    export_stitched_cloud,
    create_recap_registration_project,
    compute_pairwise_svd_alignment,
)
from ..registration.targets import detect_spherical_targets
from ..registration.bundle_adjustment import optimize_pose_graph
from ..formats.recap_project import export_recap_project_bundle
from ..reports.executive_reports import (
    generate_deformation_bulletin_pdf,
    generate_registration_passport,
)
from ..storage import cloud_paths

router = APIRouter(tags=["registration"])


class PointPair(BaseModel):
    source_point: list[float] = Field(..., description="[x, y, z] in source cloud coordinates")
    target_point: list[float] = Field(..., description="[x, y, z] in target cloud coordinates")
    label: str | None = Field(default=None, description="Optional label for pair (e.g. Marker 1)")


class PairwiseAlignRequest(BaseModel):
    source_cloud_id: str
    target_cloud_id: str
    pairs: list[PointPair] = Field(..., min_length=3, description="At least 3 corresponding point pairs")
    apply_icp_refinement: bool = Field(default=False, description="Whether to refine with Point-to-Plane/Kabsch ICP after SVD initial guess")


class StitchingRequest(BaseModel):
    source_cloud_id: str
    target_cloud_id: str
    sample_points: int = Field(default=20000, ge=10, le=100000)
    max_iterations: int = Field(default=30, ge=5, le=100)
    tolerance_m: float = Field(default=0.001, ge=0.0001, le=0.05)
    random_seed: int = Field(default=0, ge=0)


class TargetDetectRequest(BaseModel):
    cloud_id: str
    expected_radius_m: float = Field(default=0.0725, ge=0.02, le=0.5, description="Expected radius in meters (e.g. 0.0725 for 145mm)")
    sample_points: int = Field(default=200000, ge=10, le=2000000)


class PoseGraphConstraint(BaseModel):
    from_id: str
    to_id: str
    matrix_4x4: list[list[float]]
    weight: float = Field(default=1.0, ge=0.01, le=100.0)
    rmse_mm: float | None = None


class BundleAdjustmentRequest(BaseModel):
    station_ids: list[str] = Field(..., min_length=2)
    constraints: list[PoseGraphConstraint] = Field(..., min_length=1)
    fixed_station_id: str | None = None


class RecapExportRequest(BaseModel):
    project_name: str = "Scan2BIM_ReCap_Project"
    stations: list[dict[str, Any]]


def _load_cloud_points(cloud_id: str, sample_size: int) -> tuple[np.ndarray, np.ndarray]:
    cloud = one("SELECT project_id, name, status FROM clouds WHERE id = ?", (cloud_id,))
    if not cloud:
        raise HTTPException(status_code=404, detail=f"Облако {cloud_id} не найдено")
    
    paths = cloud_paths(cloud["project_id"], cloud_id)
    pos_path = paths["positions"]
    if not pos_path.exists():
        raise HTTPException(status_code=400, detail=f"Файл точек positions.npy отсутствует для облака {cloud_id}")
    
    data = np.load(pos_path, mmap_mode="r")
    count = min(len(data), sample_size)
    if count == 0:
        raise HTTPException(status_code=400, detail="Облако не содержит точек")
    if count < 10:
        raise HTTPException(status_code=400, detail="Для регистрации ICP нужно не менее 10 точек в каждом облаке")
    
    # Evenly span the stored rows and retain their exact source-row identity.
    # This is a registration sample only; the persisted cloud is never changed.
    source_row_ids = np.linspace(0, len(data) - 1, count, dtype=np.int64)
    pts = np.asarray(data[source_row_ids], dtype=np.float64)
    return pts, source_row_ids


@router.post("/registration/pair-align")
def pair_align_clouds(req: PairwiseAlignRequest):
    """Calculate rigid transformation from user-selected corresponding point pairs via Kabsch/SVD.

    Optionally refines with ICP if requested.
    """
    if len(req.pairs) < 3:
        raise HTTPException(status_code=400, detail="Необходимо как минимум 3 пары реперных точек")

    # Verify clouds exist
    c_src = one("SELECT id, project_id FROM clouds WHERE id = ?", (req.source_cloud_id,))
    c_dst = one("SELECT id, project_id FROM clouds WHERE id = ?", (req.target_cloud_id,))
    if not c_src:
        raise HTTPException(status_code=404, detail=f"Исходное облако {req.source_cloud_id} не найдено")
    if not c_dst:
        raise HTTPException(status_code=404, detail=f"Целевое облако {req.target_cloud_id} не найдено")

    src_pts = np.array([p.source_point for p in req.pairs], dtype=np.float64)
    dst_pts = np.array([p.target_point for p in req.pairs], dtype=np.float64)

    if src_pts.shape[1] != 3 or dst_pts.shape[1] != 3:
        raise HTTPException(status_code=400, detail="Точки должны быть 3-мерными координатами [x, y, z]")

    try:
        svd_res = compute_pairwise_svd_alignment(src_pts, dst_pts)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    result: dict[str, Any] = {
        "status": "ok",
        "method": "svd_kabsch_manual_pairs",
        "source_cloud_id": req.source_cloud_id,
        "target_cloud_id": req.target_cloud_id,
        "pairs_count": svd_res["pairs_count"],
        "matrix_4x4": svd_res["matrix_4x4"],
        "rotation_3x3": svd_res["rotation_3x3"],
        "translation": svd_res["translation"],
        "rmse_mm": svd_res["rmse_mm"],
        "max_error_mm": svd_res["max_error_mm"],
        "residuals_mm": svd_res["residuals_mm"],
        "pair_details": [
            {
                "label": req.pairs[i].label or f"Репер {i + 1}",
                "source": req.pairs[i].source_point,
                "target": req.pairs[i].target_point,
                "residual_mm": round(svd_res["residuals_mm"][i], 4),
            }
            for i in range(len(req.pairs))
        ],
    }

    if req.apply_icp_refinement:
        try:
            source_cloud_pts, _ = _load_cloud_points(req.source_cloud_id, 20000)
            target_cloud_pts, _ = _load_cloud_points(req.target_cloud_id, 20000)

            # Apply SVD initial transform to source cloud points before ICP
            init_r = np.array(svd_res["rotation_3x3"], dtype=np.float64)
            init_t = np.array(svd_res["translation"], dtype=np.float64)
            pre_aligned_src = (init_r @ source_cloud_pts.T).T + init_t

            icp_res = rigid_icp(
                pre_aligned_src,
                target_cloud_pts,
                max_iterations=30,
                tolerance_m=0.0005,
                max_correspondence_distance_m=0.3,
            )

            # Combine transformations: T_final = T_icp @ T_svd
            icp_mat = np.array(icp_res["matrix_4x4"], dtype=np.float64)
            svd_mat = np.array(svd_res["matrix_4x4"], dtype=np.float64)
            final_mat = icp_mat @ svd_mat

            result["refined_with_icp"] = True
            result["icp_rmse_mm"] = icp_res["rmse_mm"]
            result["matrix_4x4"] = final_mat.tolist()
            result["rotation_3x3"] = final_mat[:3, :3].tolist()
            result["translation"] = final_mat[:3, 3].tolist()
        except Exception as e:
            result["refined_with_icp"] = False
            result["icp_warning"] = f"ICP refinement skipped or failed: {str(e)}"

    return result


@router.post("/registration/match")
def match_clouds_icp(req: StitchingRequest):
    """Run rigid ICP registration between two clouds."""
    source_pts, source_row_ids = _load_cloud_points(req.source_cloud_id, req.sample_points)
    target_pts, target_row_ids = _load_cloud_points(req.target_cloud_id, req.sample_points)

    result = rigid_icp(
        source_pts,
        target_pts,
        max_iterations=req.max_iterations,
        tolerance_m=req.tolerance_m,
        random_seed=req.random_seed,
    )
    result["source_sample_row_ids"] = source_row_ids[
        np.asarray(result["source_sample_indices"], dtype=np.int64)
    ].tolist()
    result["target_sample_row_ids"] = target_row_ids[
        np.asarray(result["target_sample_indices"], dtype=np.int64)
    ].tolist()
    return result


@router.post("/registration/detect-targets")
def detect_targets_endpoint(req: TargetDetectRequest):
    """Detect geodetic spheres (145mm/100mm/200mm) with sub-millimeter precision."""
    pts, _ = _load_cloud_points(req.cloud_id, req.sample_points)
    targets = detect_spherical_targets(pts, expected_radius_m=req.expected_radius_m)
    return {
        "status": "ok",
        "cloud_id": req.cloud_id,
        "targets_found": len(targets),
        "targets": targets,
    }


@router.post("/registration/bundle-adjustment")
def bundle_adjustment_endpoint(req: BundleAdjustmentRequest):
    """Run global multi-station pose graph optimization to eliminate drift."""
    try:
        raw_constraints = [c.model_dump() for c in req.constraints]
        result = optimize_pose_graph(
            station_ids=req.station_ids,
            relative_constraints=raw_constraints,
            fixed_station_id=req.fixed_station_id,
        )
        return {"status": "ok", **result}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/registration/export-ply")
def export_unified_ply(req: RecapExportRequest):
    """Export unified PLY stitched cloud."""
    from ..config import DATA_DIR
    out_dir = DATA_DIR / "output" / "registration"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_ply = out_dir / f"{req.project_name}.ply"

    export_stitched_cloud(req.stations, out_ply)
    return {
        "status": "ok",
        "output_path": str(out_ply.resolve()),
        "size_bytes": out_ply.stat().st_size,
    }


@router.post("/registration/export-recap")
def export_recap_project(req: RecapExportRequest):
    """Export ReCap registration manifest project and authentic .RCP XML project file."""
    from ..config import DATA_DIR
    out_dir = DATA_DIR / "output" / "registration"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"{req.project_name}_recap.json"

    create_recap_registration_project(req.stations, req.project_name, out_json)



    return {
        "status": "ok",
        "output_path": str(out_json.resolve()),
        "stations_count": len(req.stations),
    }


@router.post("/registration/export-rcp-project")
def export_rcp_project_endpoint(req: RecapExportRequest):
    """Create a native Autodesk project through the installed DeCap tool."""
    from ..config import DATA_DIR
    from ..formats.recap_decap import create_recap_project
    out_dir = DATA_DIR / "output" / "recap_projects"
    try:
        return create_recap_project(out_dir, req.project_name, req.stations)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
