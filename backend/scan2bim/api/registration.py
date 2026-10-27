"""REST API endpoints for point cloud stitching, ICP registration, and ReCap project export."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from ..db import execute, new_id, one, rows, utcnow
from ..registration.stitching import (
    rigid_icp,
    export_stitched_cloud,
    create_recap_registration_project,
    compute_pairwise_svd_alignment,
    convert_local_transform_to_world,
)
from ..registration.targets import detect_spherical_targets
from ..registration.bundle_adjustment import optimize_pose_graph
from ..registration.control_validation import evaluate_control_points
from ..formats.recap_project import export_recap_project_bundle
from ..reports.executive_reports import (
    generate_deformation_bulletin_pdf,
    generate_registration_passport,
)
from ..storage import cloud_paths

router = APIRouter(tags=["registration"])


def _cloud_origin_world(cloud_id: str) -> list[float] | None:
    cloud = one(
        "SELECT origin_x, origin_y, origin_z, metadata_json FROM clouds WHERE id = ?",
        (cloud_id,),
    )
    if not cloud:
        return None
    try:
        metadata = json.loads(cloud.get("metadata_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        metadata = {}
    recap_metadata = metadata.get("recap_project") if isinstance(metadata, dict) else None
    if isinstance(recap_metadata, dict) and recap_metadata.get("transform_applied") is False:
        # RCP station transforms are preserved as provenance but not applied to
        # stored points until their coordinate convention is verified.
        return None
    origin = [cloud.get("origin_x"), cloud.get("origin_y"), cloud.get("origin_z")]
    if all(value is not None for value in origin):
        values = np.asarray(origin, dtype=np.float64)
        return values.tolist() if np.isfinite(values).all() else None
    fallback = metadata.get("origin") if isinstance(metadata, dict) else None
    if not isinstance(fallback, (list, tuple)) or len(fallback) != 3:
        return None
    values = np.asarray(fallback, dtype=np.float64)
    return values.tolist() if np.isfinite(values).all() else None


def _add_registration_coordinate_frames(
    result: dict[str, Any], source_cloud_id: str, target_cloud_id: str,
) -> None:
    source_origin = _cloud_origin_world(source_cloud_id)
    target_origin = _cloud_origin_world(target_cloud_id)
    world_matrix = None
    if source_origin is not None and target_origin is not None:
        world_matrix = convert_local_transform_to_world(
            result["matrix_4x4"], source_origin, target_origin
        ).tolist()
    result["world_matrix_4x4"] = world_matrix
    result["coordinate_frame"] = {
        "matrix_4x4": "stored_local_source_to_stored_local_target",
        "world_matrix_4x4": "source_world_to_target_world" if world_matrix is not None else None,
        "source_origin_world_m": source_origin,
        "target_origin_world_m": target_origin,
    }


class PointPair(BaseModel):
    source_point: list[float] = Field(
        ..., min_length=3, max_length=3,
        description="[x, y, z] in source cloud coordinates",
    )
    target_point: list[float] = Field(
        ..., min_length=3, max_length=3,
        description="[x, y, z] in target cloud coordinates",
    )
    label: str | None = Field(default=None, description="Optional label for pair (e.g. Marker 1)")


class PairwiseAlignRequest(BaseModel):
    source_cloud_id: str
    target_cloud_id: str
    pairs: list[PointPair] = Field(..., min_length=3, description="At least 3 corresponding point pairs")
    apply_icp_refinement: bool = Field(default=False, description="Whether to refine with Point-to-Plane/Kabsch ICP after SVD initial guess")


class ControlPointEvaluationRequest(BaseModel):
    source_cloud_id: str
    target_cloud_id: str
    matrix_4x4: list[list[float]] = Field(..., min_length=4, max_length=4)
    controls: list[PointPair] = Field(..., min_length=3)
    independent_of_fit: bool = Field(
        ...,
        description="Explicitly attest that these surveyed controls were not used to fit or refine the matrix",
    )
    acceptance_rmse_mm: float = Field(default=10.0, gt=0, le=1000)


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


class SaveStationRegistrationRequest(BaseModel):
    source_station_id: str
    target_station_id: str
    method: Literal["rigid_icp", "manual_kabsch", "manual_kabsch_icp"]
    matrix_4x4: list[list[float]] = Field(..., min_length=4, max_length=4)
    world_matrix_4x4: list[list[float]] | None = Field(default=None, min_length=4, max_length=4)
    fit_rmse_mm: float | None = Field(default=None, ge=0, le=1_000_000)

    @staticmethod
    def _validate_rigid_matrix(value: list[list[float]], label: str) -> np.ndarray:
        matrix = np.asarray(value, dtype=np.float64)
        if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
            raise ValueError(f"{label} must be a finite 4x4 matrix")
        if not np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0], atol=1e-8):
            raise ValueError(f"{label} last row must be [0, 0, 0, 1]")
        rotation = matrix[:3, :3]
        if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-3):
            raise ValueError(f"{label} rotation must be orthonormal")
        if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-3):
            raise ValueError(f"{label} rotation determinant must be +1")
        return matrix

    @model_validator(mode="after")
    def validate_rigid_matrices(self) -> "SaveStationRegistrationRequest":
        self._validate_rigid_matrix(self.matrix_4x4, "matrix_4x4")
        if self.world_matrix_4x4 is not None:
            self._validate_rigid_matrix(self.world_matrix_4x4, "world_matrix_4x4")
        return self


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
    if c_src["project_id"] != c_dst["project_id"]:
        raise HTTPException(status_code=422, detail="Сшивайте станции внутри одного проекта")
    _station_for_registration(c_src["project_id"], req.source_cloud_id, "source")
    _station_for_registration(c_src["project_id"], req.target_cloud_id, "target")

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
        "accuracy_status": "not_measured",
        "independent_control_count": 0,
        "fit_residuals_are_independent": False,
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

            # Keep the measured tie-point transform as ICP's true initial pose.
            # Rigid ICP must not replace it with a centroid-only translation.
            svd_mat = np.array(svd_res["matrix_4x4"], dtype=np.float64)

            icp_res = rigid_icp(
                source_cloud_pts,
                target_cloud_pts,
                max_iterations=30,
                tolerance_m=0.0005,
                max_correspondence_distance_m=0.3,
                initial_t4x4=svd_mat,
            )

            # Combine transformations: T_final = T_icp @ T_svd
            icp_mat = np.array(icp_res["matrix_4x4"], dtype=np.float64)
            final_mat = icp_mat @ svd_mat

            result["refined_with_icp"] = True
            result["icp_rmse_mm"] = icp_res["rmse_mm"]
            result["icp_inlier_count"] = icp_res["inlier_count"]
            result["icp_inlier_fraction"] = icp_res["inlier_fraction"]
            result["icp_iterations"] = icp_res["iterations"]
            result["icp_converged"] = icp_res["converged"]
            result["matrix_4x4"] = final_mat.tolist()
            result["rotation_3x3"] = final_mat[:3, :3].tolist()
            result["translation"] = final_mat[:3, 3].tolist()
        except Exception as e:
            result["refined_with_icp"] = False
            result["icp_warning"] = f"ICP refinement skipped or failed: {str(e)}"

    _add_registration_coordinate_frames(result, req.source_cloud_id, req.target_cloud_id)

    return result


@router.post("/registration/evaluate-controls")
def evaluate_registration_controls(req: ControlPointEvaluationRequest):
    """Evaluate a proposed transform against independently surveyed controls."""
    for cloud_id, label in ((req.source_cloud_id, "Исходное"), (req.target_cloud_id, "Целевое")):
        if not one("SELECT id FROM clouds WHERE id = ?", (cloud_id,)):
            raise HTTPException(status_code=404, detail=f"{label} облако {cloud_id} не найдено")
    if not req.independent_of_fit:
        raise HTTPException(
            status_code=400,
            detail="Контрольные точки должны быть независимы от пар, по которым рассчитана матрица",
        )
    try:
        result = evaluate_control_points(
            req.matrix_4x4,
            [control.source_point for control in req.controls],
            [control.target_point for control in req.controls],
            acceptance_rmse_mm=req.acceptance_rmse_mm,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result.update({
        "source_cloud_id": req.source_cloud_id,
        "target_cloud_id": req.target_cloud_id,
        "matrix_4x4": req.matrix_4x4,
        "control_details": [
            {
                "label": control.label or f"Контроль {index + 1}",
                "source": control.source_point,
                "target": control.target_point,
                "residual_mm": round(result["residuals_mm"][index], 4),
            }
            for index, control in enumerate(req.controls)
        ],
    })
    _add_registration_coordinate_frames(result, req.source_cloud_id, req.target_cloud_id)
    return result


@router.post("/registration/match")
def match_clouds_icp(req: StitchingRequest):
    """Calculate a read-only rigid ICP proposal between two station records."""
    source = one("SELECT project_id FROM clouds WHERE id = ?", (req.source_cloud_id,))
    target = one("SELECT project_id FROM clouds WHERE id = ?", (req.target_cloud_id,))
    if not source or not target:
        missing_id = req.source_cloud_id if not source else req.target_cloud_id
        raise HTTPException(status_code=404, detail=f"Станция {missing_id} не найдена")
    if source["project_id"] != target["project_id"]:
        raise HTTPException(status_code=422, detail="Сшивайте станции внутри одного проекта")
    _station_for_registration(source["project_id"], req.source_cloud_id, "source")
    _station_for_registration(source["project_id"], req.target_cloud_id, "target")
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
    _add_registration_coordinate_frames(result, req.source_cloud_id, req.target_cloud_id)
    return result


def _station_registration_out(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["matrix_4x4"] = json.loads(result.pop("matrix_json"))
    world_matrix = result.pop("world_matrix_json")
    result["world_matrix_4x4"] = json.loads(world_matrix) if world_matrix else None
    result["matrix_applied"] = bool(result["matrix_applied"])
    result["rcp_updated"] = bool(result["rcp_updated"])
    return result


def _station_for_registration(project_id: str, station_id: str, side: str) -> dict[str, Any]:
    station = one(
        """SELECT id, project_id, name, status, metadata_json, source_format
           FROM clouds WHERE id = ? AND project_id = ?""",
        (station_id, project_id),
    )
    if not station:
        raise HTTPException(404, f"{side} station does not belong to project {project_id}")
    if station["status"] != "ready":
        raise HTTPException(409, f"{side} station must finish importing before registration")
    metadata = json.loads(station.get("metadata_json") or "{}")
    ranges = metadata.get("station_row_ranges") if isinstance(metadata, dict) else None
    if isinstance(ranges, list) and len(ranges) > 1:
        raise HTTPException(
            409,
            detail={
                "summary": f"{side} cloud contains several stations; it cannot be registered as one station.",
                "station_count": len(ranges),
                "message": "Split the multi-station cloud into individual station records before saving this pair.",
            },
        )
    selected_node = (metadata.get("recap_project") or {}).get("selected_node") if isinstance(metadata, dict) else None
    return {
        **station,
        "station_identity": "rcp_node" if isinstance(selected_node, dict) else "single_cloud_station",
    }


@router.get("/projects/{project_id}/station-registrations")
def list_station_registrations(project_id: str) -> dict[str, Any]:
    if not one("SELECT id FROM projects WHERE id = ?", (project_id,)):
        raise HTTPException(404, f"project {project_id} not found")
    items = rows(
        """SELECT r.*, s.name AS source_station_name, t.name AS target_station_name
           FROM station_registrations r
           JOIN clouds s ON s.id = r.source_station_id
           JOIN clouds t ON t.id = r.target_station_id
           WHERE r.project_id = ?
           ORDER BY r.updated_at DESC, r.id""",
        (project_id,),
    )
    return {"project_id": project_id, "items": [_station_registration_out(row) for row in items]}


@router.post("/projects/{project_id}/station-registrations")
def save_station_registration(
    project_id: str,
    req: SaveStationRegistrationRequest,
) -> dict[str, Any]:
    if not one("SELECT id FROM projects WHERE id = ?", (project_id,)):
        raise HTTPException(404, f"project {project_id} not found")
    if req.source_station_id == req.target_station_id:
        raise HTTPException(422, "Подвижная и опорная станции должны отличаться")
    source = _station_for_registration(project_id, req.source_station_id, "source")
    target = _station_for_registration(project_id, req.target_station_id, "target")
    now = utcnow()
    registration_id = new_id()
    execute(
        """INSERT INTO station_registrations (
             id, project_id, source_station_id, target_station_id, method,
             matrix_json, world_matrix_json, fit_rmse_mm,
             independent_control_count, control_rmse_mm, acceptance_rmse_mm,
             status, matrix_applied, rcp_updated, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, 'proposed', 0, 0, ?, ?)
           ON CONFLICT(project_id, source_station_id, target_station_id) DO UPDATE SET
             method=excluded.method,
             matrix_json=excluded.matrix_json,
             world_matrix_json=excluded.world_matrix_json,
             fit_rmse_mm=excluded.fit_rmse_mm,
             independent_control_count=0,
             control_rmse_mm=NULL,
             acceptance_rmse_mm=NULL,
             status='proposed',
             matrix_applied=0,
             rcp_updated=0,
             updated_at=excluded.updated_at""",
        (
            registration_id,
            project_id,
            req.source_station_id,
            req.target_station_id,
            req.method,
            json.dumps(req.matrix_4x4, allow_nan=False),
            json.dumps(req.world_matrix_4x4, allow_nan=False) if req.world_matrix_4x4 is not None else None,
            req.fit_rmse_mm,
            now,
            now,
        ),
    )
    row = one(
        """SELECT r.*, s.name AS source_station_name, t.name AS target_station_name
           FROM station_registrations r
           JOIN clouds s ON s.id = r.source_station_id
           JOIN clouds t ON t.id = r.target_station_id
           WHERE r.project_id = ? AND r.source_station_id = ? AND r.target_station_id = ?""",
        (project_id, req.source_station_id, req.target_station_id),
    )
    if not row:
        raise HTTPException(500, "station registration was not persisted")
    return {
        "status": "proposed",
        "accuracy_status": "not_measured",
        "message": "Pair saved as an unverified proposal. The transform was not applied and the RCP project was not changed.",
        "source_station_identity": source["station_identity"],
        "target_station_identity": target["station_identity"],
        "item": _station_registration_out(row),
    }


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
    """Export a SCAN station-pose JSON manifest; this endpoint does not create an Autodesk RCP."""
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
    from ..formats.recap_decap import InsufficientStorageError, create_recap_project
    out_dir = DATA_DIR / "output" / "recap_projects"
    try:
        return create_recap_project(out_dir, req.project_name, req.stations)
    except InsufficientStorageError as exc:
        raise HTTPException(
            status_code=507,
            detail={
                "summary": "Недостаточно свободного места для безопасного создания RCP.",
                "available_bytes": exc.available_bytes,
                "required_bytes": exc.required_bytes,
                "source_bytes": exc.source_bytes,
                "message": "DeCap не запускался; исходные станции не изменены.",
            },
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
