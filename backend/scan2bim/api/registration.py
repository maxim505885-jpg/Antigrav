"""REST API endpoints for point cloud stitching, ICP registration, and ReCap project export."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import one, rows
from ..registration.stitching import rigid_icp, export_stitched_cloud, create_recap_registration_project
from ..storage import cloud_paths

router = APIRouter(tags=["registration"])


class StitchingRequest(BaseModel):
    source_cloud_id: str
    target_cloud_id: str
    sample_points: int = Field(default=20000, ge=10, le=100000)
    max_iterations: int = Field(default=30, ge=5, le=100)
    tolerance_m: float = Field(default=0.001, ge=0.0001, le=0.05)


class RecapExportRequest(BaseModel):
    project_name: str = "Scan2BIM_ReCap_Project"
    stations: list[dict[str, Any]]


def _load_cloud_points(cloud_id: str, sample_size: int) -> np.ndarray:
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
    
    # Резервуарное или равномерное прореживание
    step = max(1, len(data) // count)
    pts = np.asarray(data[::step][:count], dtype=np.float64)
    return pts


@router.post("/registration/match")
def match_clouds_icp(req: StitchingRequest):
    """Run rigid ICP registration between two clouds."""
    source_pts = _load_cloud_points(req.source_cloud_id, req.sample_points)
    target_pts = _load_cloud_points(req.target_cloud_id, req.sample_points)

    result = rigid_icp(
        source_pts,
        target_pts,
        max_iterations=req.max_iterations,
        tolerance_m=req.tolerance_m,
    )
    return result


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
    """Export ReCap registration manifest project."""
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
