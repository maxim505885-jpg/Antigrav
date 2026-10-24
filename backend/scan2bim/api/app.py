"""Local REST API (v1) for Intelligent Scan-to-BIM."""
from __future__ import annotations

import hmac
import json
import shutil
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__
from ..bim import build_model, export_ifc
from ..cad import export_section_dxf, export_section_pdf
from ..cad.dxf import export_elements_dxf, export_structural_plan_dxf
from ..cad.pdf import export_structural_plan_pdf
from ..config import ALLOWED_ORIGINS, API_KEY, API_VERSION, MAX_INGEST_POINTS
from ..db import db as db_session, dumps, execute, init_db, loads, new_id, one, rows, utcnow
from ..demo import write_room_ply
from ..formats import RcsConversionRequired, detect_format, read_cloud, supported_formats
from ..formats.readers import rcs_guidance
from ..formats.rcp_manifest import (
    RcpManifestError,
    compare_axis_aligned_asset_bounds,
    read_rcp_manifest,
)
from ..geometry import extract_section
from ..geometry.section import CloudGeometry
from ..ingest import ingest_cloud
from ..jobs import JobCancelled, create_job, dispatch_event, get_job, request_cancel, submit, update_job
from ..learning.features import features_from_element
from ..learning.knn import KNNModel
from ..learning.registry import activate, list_models, rollback
from ..learning.store import (
    create_sample,
    element_bbox_coordinate_frame,
    inspect_source_point_alignment,
    list_samples,
    point_cloud_snapshot,
    samples_for_training,
    similar_samples,
    validate_training_sample_source,
)
from ..learning.training import active_artifact, apply_learned_prior, train_candidate
from ..recognition import detect_structures, ml_status
from ..recognition.evaluation import evaluate_recognition
from ..recognition.geometric import DetectedElement
from ..recognition.reconcile import protect_reviewed_candidates
from ..structure.column_surface_assignment import (
    associate_surfaces_to_column,
    cluster_column_surface_tracks,
)
from ..structure.column_section_series import fit_column_track_sections
from ..structure.vertical_surfaces import extract_vertical_surfaces
from ..processing.cleanup import apply_cleanup, write_ply, write_xyz
from ..processing.cloud_export import EXPORT_FORMATS, CloudExportError, export_cloud
from ..schemas import (
    CleanupRequest,
    CloudExportRequest,
    CloudImportPath,
    CloudOut,
    ColumnTypeAssign,
    ColumnAnnotationSave,
    ColumnTypeConfirm,
    ColumnTypeReject,
    ColumnTypeUndo,
    ColumnSectionFitRequest,
    ColumnSectionBatchFitRequest,
    ElementOut,
    ElementAnnotationSave,
    ElementPatch,
    FeedbackCreate,
    JobOut,
    ModelOut,
    ProjectCreate,
    ProjectOut,
    RecognitionEvaluationRequest,
    SampleCreate,
    SampleOut,
    SectionOut,
    SectionRequest,
    TrainRequest,
    WebhookCreate,
)
from ..services import (
    derive_bbox,
    element_from_row,
    get_element,
    list_elements,
    merge_elements,
    review_element,
    split_element,
    undo_feedback,
)
from ..storage import (
    cloud_paths,
    ensure_cloud_dir,
    new_export_dir,
    project_dir,
    safe_filename,
    sha256_file,
    write_json_atomic,
)
from ..structure.column_type_store import (
    assign_column_type,
    confirm_column_type,
    list_column_types,
    list_rejected_column_types,
    reject_column_type,
    undo_column_type_action,
)
from ..structure.column_types import propose_column_types
from ..structure.column_type_matching import match_project_column_types
from ..structure.column_annotations import (
    annotation_reference_document,
    column_cloud_manifest,
    column_snapshot_sha256,
    empty_annotation,
    validate_column_annotation,
)
from ..structure.element_annotations import (
    INVALIDATED_SOURCE,
    element_reference_document,
    element_snapshot_sha256,
    validate_element_annotation,
)
from ..structure.section_fitting import fit_rectangular_section
from ..pointdata import NpyPointProvider, PointQuery, select_query_provider

# ---------------------------------------------------------------- helpers


def require_auth(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    if API_KEY and not hmac.compare_digest(x_api_key or "", API_KEY):
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


def _project(project_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not row:
        raise HTTPException(404, f"project {project_id} not found")
    return row


def _cloud(cloud_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM clouds WHERE id = ?", (cloud_id,))
    if not row:
        raise HTTPException(404, f"cloud {cloud_id} not found")
    return row


def _cloud_out(row: dict[str, Any], import_job_id: str | None = None) -> dict[str, Any]:
    meta = loads(row.get("metadata_json"), {})
    origin = None
    if row.get("origin_x") is not None:
        origin = [row["origin_x"], row["origin_y"], row["origin_z"]]
    bbox_min = None
    bbox_max = None
    if row.get("bbox_min_x") is not None:
        bbox_min = [row["bbox_min_x"], row["bbox_min_y"], row["bbox_min_z"]]
        bbox_max = [row["bbox_max_x"], row["bbox_max_y"], row["bbox_max_z"]]
    return {
        "id": row["id"],
        "import_job_id": import_job_id,
        "project_id": row["project_id"],
        "name": row["name"],
        "source_path": row["source_path"],
        "source_format": row["source_format"],
        "size_bytes": row["size_bytes"],
        "point_count": row["point_count"],
        "ingested_count": row["ingested_count"],
        "decimated": bool(row["decimated"]),
        "origin": origin,
        "bbox_min": bbox_min,
        "bbox_max": bbox_max,
        "has_color": bool(row["has_color"]),
        "has_intensity": bool(row["has_intensity"]),
        "status": row["status"],
        "error": row.get("error"),
        "preview_count": int(meta.get("preview_count") or 0),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": meta,
        "warning": meta.get("warning"),
    }


def _dxf_to_dwg_or_409(dxf_path: Path, dwg_path: Path) -> Path:
    """Convert a DXF we generated into DWG, or explain honestly why not.

    Only licensed headless converters are used (ODA File Converter, AutoCAD
    Core Console). COM automation is deliberately skipped: opening the AutoCAD
    GUI on a server is not an export path.
    """
    from ..cad.dwg_compiler import (
        convert_dxf_to_dwg_accore,
        convert_dxf_to_dwg_oda,
        find_accoreconsole,
        find_oda_converter,
    )

    errors: list[str] = []
    if find_oda_converter():
        try:
            return convert_dxf_to_dwg_oda(dxf_path, dwg_path)
        except Exception as exc:
            errors.append(f"ODA File Converter: {type(exc).__name__}: {exc}")
    if find_accoreconsole():
        try:
            return convert_dxf_to_dwg_accore(dxf_path, dwg_path)
        except Exception as exc:
            errors.append(f"AutoCAD Core Console: {type(exc).__name__}: {exc}")
    raise HTTPException(
        409,
        {
            "summary": "DWG не создан: на сервере не найден лицензированный конвертер.",
            "steps": [
                "Установите ODA File Converter (бесплатен для членов ODA) и перезапустите сервер.",
                "Либо укажите путь к ODAFileConverter в переменной окружения S2B_ODA_CONVERTER.",
                "Либо запросите format=dxf и сохраните DWG в AutoCAD.",
            ],
            "errors": errors,
            "note": "DWG не подделывается файлом с другим расширением.",
        },
    )


def _cloud_geometry(row: dict[str, Any]) -> CloudGeometry:
    if row["status"] != "ready":
        raise HTTPException(409, f"cloud is not ready (status: {row['status']})")
    paths = cloud_paths(row["project_id"], row["id"])
    if not paths["positions"].exists():
        raise HTTPException(409, "cloud positions are missing on disk")
    return CloudGeometry(
        positions_path=paths["positions"],
        origin=np.array([row["origin_x"], row["origin_y"], row["origin_z"]], dtype=np.float64),
        bbox_min=np.array([row["bbox_min_x"], row["bbox_min_y"], row["bbox_min_z"]], dtype=np.float64),
        bbox_max=np.array([row["bbox_max_x"], row["bbox_max_y"], row["bbox_max_z"]], dtype=np.float64),
        count=int(row["ingested_count"] or 0),
    )


def _cloud_row_from_import(
    project_id: str,
    name: str,
    source: Path,
    fmt: str,
    status: str = "processing",
    metadata: dict[str, Any] | None = None,
) -> str:
    cloud_id = new_id()
    now = utcnow()
    execute(
        """
        INSERT INTO clouds
        (id, project_id, name, source_path, source_format, size_bytes, status, metadata_json, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            cloud_id,
            project_id,
            name,
            str(source),
            fmt,
            int(source.stat().st_size) if source.exists() else 0,
            status,
            dumps(metadata or {}),
            now,
            now,
        ),
    )
    return cloud_id


def _ingest_work(project_id: str, cloud_id: str):
    def work(progress):
        try:
            row = _cloud(cloud_id)
            import_metadata = loads(row.get("metadata_json"), {})
            result = ingest_cloud(project_id, cloud_id, Path(row["source_path"]), progress)
            recap_project = import_metadata.get("recap_project")
            if recap_project:
                current = _cloud(cloud_id)
                selected_node = recap_project.get("selected_node", {})
                declared = int(selected_node.get("declared_point_count") or 0)
                actual = int(current.get("ingested_count") or 0)
                recap_project["actual_ingested_point_count"] = actual
                recap_project["declared_point_count_difference"] = (
                    declared - actual if declared else None
                )
                asset_bounds = selected_node.get("asset_bounds") or {}
                if asset_bounds.get("axis_aligned_interpretation_supported"):
                    actual_min = [current[f"bbox_min_{axis}"] for axis in "xyz"]
                    actual_max = [current[f"bbox_max_{axis}"] for axis in "xyz"]
                    coordinate_check = compare_axis_aligned_asset_bounds(
                        actual_min,
                        actual_max,
                        asset_bounds,
                        recap_project.get("unit_type_raw"),
                    )
                    recap_project["coordinate_frame_check"] = coordinate_check
                    if coordinate_check["translation_reapplication"] == "do_not_apply_for_this_node":
                        recap_project["transform_note"] = (
                            "SCAN did not reapply the RCP node translation: the full linked RCS extents "
                            "match the axis-aligned RCP asset bounds within the metadata-consistency epsilon. "
                            "This verifies extents for this node only, not every point or other RCP projects."
                        )
                metadata = loads(current.get("metadata_json"), {})
                metadata["recap_project"] = recap_project
                execute(
                    "UPDATE clouds SET metadata_json = ?, updated_at = ? WHERE id = ?",
                    (dumps(metadata), utcnow(), cloud_id),
                )
                meta_path = cloud_paths(project_id, cloud_id)["meta"]
                if meta_path.is_file():
                    try:
                        stored = json.loads(meta_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        stored = {}
                    stored["recap_project"] = recap_project
                    write_json_atomic(meta_path, stored)
            return result
        except JobCancelled:
            execute(
                "UPDATE clouds SET status = 'cancelled', error = NULL, updated_at = ? WHERE id = ?",
                (utcnow(), cloud_id),
            )
            raise
        except Exception as exc:  # keep the cloud row truthful on failure
            execute(
                "UPDATE clouds SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                (f"{type(exc).__name__}: {exc}", utcnow(), cloud_id),
            )
            raise

    return work


def _mark_interrupted_imports() -> None:
    """Mark imports left processing by a prior API process as resumable failures.

    Recovery is deliberately metadata-only: it must never open the user's source
    file during startup. A complete staged checkpoint is picked up only after
    the user explicitly resumes the cloud from the UI/API.
    """
    interrupted = rows("SELECT id, name FROM clouds WHERE status = 'processing'")
    for cloud in interrupted:
        message = "Импорт прерван перезапуском сервера. Нажмите «Возобновить импорт»."
        execute(
            "UPDATE clouds SET status = 'failed', error = ?, updated_at = ? WHERE id = ? AND status = 'processing'",
            (message, utcnow(), cloud["id"]),
        )
        jobs = rows(
            "SELECT id FROM jobs WHERE cloud_id = ? AND type = 'ingest' AND status IN ('queued', 'running')",
            (cloud["id"],),
        )
        for job in jobs:
            update_job(
                job["id"],
                status="failed",
                message="прервано перезапуском сервера; можно возобновить импорт",
                error=message,
            )


def _section_row(section: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": section["id"],
        "cloud_id": section["cloud_id"],
        "kind": section["kind"],
        "axis": section.get("axis"),
        "position": section["position"],
        "thickness": section["thickness"],
        "grid_res": section["grid_res"],
        "point_count": section["point_count"],
        "created_at": section["created_at"],
        "result": loads(section.get("result_json"), {}),
    }


def _section(section_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM sections WHERE id = ?", (section_id,))
    if not row:
        raise HTTPException(404, f"section {section_id} not found")
    return row


def _column_type_http_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if any(fragment in message for fragment in ("does not exist", "unknown element", "unknown column type")):
        return HTTPException(404, message)
    if any(fragment in message for fragment in ("same project", "changed after", "undo later actions", "already confirms", "already rejects", "was rejected")):
        return HTTPException(409, message)
    return HTTPException(400, message)


def _unassigned_type_elements(elements: list[dict[str, Any]], confirmed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assigned_ids = {element_id for item in confirmed for element_id in item["member_element_ids"]}
    return [item for item in elements if item["id"] not in assigned_ids and item["review_status"] != "rejected"]


def _column_reference_candidates(cloud_id: str) -> list[dict[str, Any]]:
    """Return columns eligible for independent reference annotation.

    Invalidated synthetic rows are retained in the database for audit, but must
    never enter a reference dataset or be reintroduced through annotation APIs.
    """
    return [
        item for item in list_elements(cloud_id)
        if item["class_name"] == "column" and item.get("source") != "invalidated_synthetic_ground_truth"
    ]


def _element_reference_candidates(cloud_id: str) -> list[dict[str, Any]]:
    """Return all eligible candidates for independent semantic role labels."""
    candidates = [element_from_row(row) for row in rows(
        "SELECT * FROM elements WHERE cloud_id=? ORDER BY class_name,id", (cloud_id,),
    )]
    return [item for item in candidates if item.get("source") != INVALIDATED_SOURCE]


def _current_physical_instance_id(cloud_id: str, element_id: str) -> str | None:
    """Return only a labeled physical ID tied to the current candidate snapshot."""
    cloud = _cloud(cloud_id)
    elements = _element_reference_candidates(cloud_id)
    if not any(item["id"] == element_id for item in elements):
        return None
    try:
        snapshot = element_snapshot_sha256(elements, cloud)
    except ValueError:
        return None
    record = one(
        "SELECT payload_json FROM element_annotations WHERE cloud_id=? AND source_snapshot_sha256=? "
        "AND element_id=? ORDER BY revision DESC LIMIT 1",
        (cloud_id, snapshot, element_id),
    )
    annotation = loads(record["payload_json"], {}) if record else {}
    physical_id = annotation.get("physical_instance_id")
    if annotation.get("state") != "labeled" or not isinstance(physical_id, str) or not physical_id.strip():
        return None
    return physical_id.strip()


def _column_type_export_catalog(project_id: str, elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    confirmed = list_column_types(project_id)
    excluded = {item["proposal_key"] for item in list_rejected_column_types(project_id)}
    proposals = propose_column_types(
        _unassigned_type_elements(elements, confirmed),
        linear_tolerance_m=0.005, relative_tolerance=0.01,
    )
    return confirmed + [item for item in proposals if item["proposal_key"] not in excluded]


# ---------------------------------------------------------------- app


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _mark_interrupted_imports()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Intelligent Scan-to-BIM API",
        version=__version__,
        description=(
            "Local API for point-cloud ingestion, sectioning, editable DXF/IFC export, "
            "geometric recognition and engineer-in-the-loop learning."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "api": API_VERSION,
            "auth_required": bool(API_KEY),
            "max_ingest_points": MAX_INGEST_POINTS,
        }

    api = APIRouter(dependencies=[Depends(require_auth)])

    # ------------------------------------------------------------ projects
    @api.post("/projects", response_model=ProjectOut)
    def create_project(payload: ProjectCreate):
        project_id = new_id()
        now = utcnow()
        execute(
            "INSERT INTO projects (id,name,description,units,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (project_id, payload.name.strip(), payload.description, payload.units, now, now),
        )
        (project_dir(project_id)).mkdir(parents=True, exist_ok=True)
        dispatch_event("project.created", {"project_id": project_id, "name": payload.name})
        return get_project(project_id)

    @api.get("/projects", response_model=list[ProjectOut])
    def list_projects():
        records = rows(
            """
            SELECT p.*,
              (SELECT COUNT(*) FROM clouds c WHERE c.project_id = p.id) AS cloud_count,
              (SELECT COUNT(*) FROM elements e WHERE e.project_id = p.id) AS element_count
            FROM projects p ORDER BY p.updated_at DESC
            """
        )
        return records

    @api.get("/projects/{project_id}", response_model=ProjectOut)
    def get_project(project_id: str):
        row = _project(project_id)
        row["cloud_count"] = (one("SELECT COUNT(*) AS n FROM clouds WHERE project_id = ?", (project_id,)) or {}).get("n", 0)
        row["element_count"] = (one("SELECT COUNT(*) AS n FROM elements WHERE project_id = ?", (project_id,)) or {}).get("n", 0)
        return row

    @api.delete("/projects/{project_id}")
    def delete_project(project_id: str):
        _project(project_id)
        execute("DELETE FROM projects WHERE id = ?", (project_id,))
        path = project_dir(project_id)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        dispatch_event("project.deleted", {"project_id": project_id})
        return {"deleted": project_id}

    @api.get("/projects/{project_id}/clouds", response_model=list[CloudOut])
    def project_clouds(project_id: str):
        _project(project_id)
        return [
            _cloud_out(row)
            for row in rows(
                "SELECT * FROM clouds WHERE project_id = ? ORDER BY CASE WHEN id = 'workshop_cloud' THEN 0 ELSE 1 END, created_at DESC",
                (project_id,),
            )
        ]

    @api.get("/projects/{project_id}/jobs", response_model=list[JobOut])
    def project_jobs(project_id: str):
        _project(project_id)
        jobs = rows("SELECT * FROM jobs WHERE project_id = ? ORDER BY created_at DESC LIMIT 50", (project_id,))
        for job in jobs:
            job["result"] = loads(job.pop("result_json"), {})
        return jobs

    # ------------------------------------------------------------ formats
    @api.get("/formats")
    def formats():
        return {
            "supported": supported_formats(),
            "ml": ml_status().__dict__,
            "notes": [
                "RCS point data is read through the installed Autodesk ReCap DLL; RCP manifests link scans to RCS files.",
                "All source files are treated as read-only.",
            ],
        }

    @api.get("/formats/rcs")
    def rcs_format(path: str | None = None):
        return rcs_guidance(path or "")

    # ------------------------------------------------------------ clouds
    @api.post("/projects/{project_id}/clouds/import-path", response_model=CloudOut)
    def import_path(project_id: str, payload: CloudImportPath):
        _project(project_id)
        source = Path(payload.path).expanduser()
        if not source.exists():
            raise HTTPException(404, f"file does not exist: {source}")
        try:
            fmt = detect_format(source)
        except RcsConversionRequired as exc:
            raise HTTPException(409, detail=exc.guidance) from exc
        except Exception as exc:
            raise HTTPException(415, str(exc)) from exc
        import_metadata: dict[str, Any] = {}
        if fmt == "rcp":
            try:
                manifest = read_rcp_manifest(source)
            except RcpManifestError as exc:
                raise HTTPException(415, str(exc)) from exc
            if len(manifest["nodes"]) != 1:
                raise HTTPException(
                    409,
                    {
                        "summary": "Этот RCP содержит несколько станций.",
                        "node_count": len(manifest["nodes"]),
                        "message": "Пакетный импорт станций из многосканового RCP ещё не поддержан; выберите отдельные RCS-файлы.",
                    },
                )
            node = manifest["nodes"][0]
            linked_source = Path(node["resolved_rcs_path"]) if node["resolved_rcs_path"] else None
            if linked_source is None or not linked_source.is_file():
                raise HTTPException(
                    409,
                    {
                        "summary": "Связанный RCS-файл не найден.",
                        "project_file": str(source),
                        "node": node,
                    },
                )
            source = linked_source
            fmt = "rcs"
            name = payload.name or f"{Path(payload.path).stem} — {node['name']}"
            import_metadata = {
                "recap_project": {
                    **manifest,
                    "project_sha256": sha256_file(Path(payload.path).expanduser()),
                    "selected_node": node,
                    "declared_point_count_difference": None,
                    "transform_applied": False,
                    "transform_note": "RCP translation/rotation/scale are preserved; no transform is auto-applied before comparing the full linked RCS extents with the RCP asset bounds.",
                }
            }
        if fmt == "rcs":
            # Native local reader (ReCap DLL, subprocess-isolated) is verified on
            # this machine; fall back to the documented guidance when it is absent.
            from scan2bim.formats.rcs_native import native_available

            if not native_available()["dll_exists"]:
                raise HTTPException(409, detail=rcs_guidance(source))
        if not import_metadata:
            name = payload.name or source.name
        cloud_id = _cloud_row_from_import(project_id, name, source.resolve(), fmt, metadata=import_metadata)
        job_id = create_job("ingest", project_id, cloud_id, f"чтение {name}")
        submit(job_id, _ingest_work(project_id, cloud_id))
        return _cloud_out(_cloud(cloud_id), job_id)

    @api.post("/projects/{project_id}/clouds/upload", response_model=CloudOut)
    def upload_cloud(project_id: str, file: UploadFile = File(...), name: str | None = None):
        _project(project_id)
        filename = safe_filename(file.filename or "cloud.ply")
        ext = Path(filename).suffix.lower().lstrip(".")
        if ext in {"rcs", "rcp"}:
            raise HTTPException(409, detail=rcs_guidance(filename))
        cloud_id = new_id()
        dest_dir = ensure_cloud_dir(project_id, cloud_id) / "source"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename
        total = 0
        with dest.open("wb") as out:
            while True:
                block = file.file.read(8 * 1024 * 1024)
                if not block:
                    break
                out.write(block)
                total += len(block)
        try:
            fmt = detect_format(dest)
        except Exception as exc:
            shutil.rmtree(dest_dir.parent, ignore_errors=True)
            raise HTTPException(415, str(exc)) from exc
        now = utcnow()
        execute(
            """
            INSERT INTO clouds (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                cloud_id,
                project_id,
                name or filename,
                str(dest),
                fmt,
                total,
                "processing",
                now,
                now,
            ),
        )
        job_id = create_job("ingest", project_id, cloud_id, f"чтение {filename}")
        submit(job_id, _ingest_work(project_id, cloud_id))
        return _cloud_out(_cloud(cloud_id), job_id)

    @api.get("/clouds/{cloud_id}", response_model=CloudOut)
    def get_cloud(cloud_id: str):
        return _cloud_out(_cloud(cloud_id))

    @api.post("/clouds/{cloud_id}/resume", response_model=CloudOut)
    def resume_cloud_import(cloud_id: str):
        cloud = _cloud(cloud_id)
        if cloud["status"] not in {"failed", "cancelled"}:
            raise HTTPException(409, f"cloud import cannot be resumed from status {cloud['status']}")
        project_id = cloud["project_id"]
        execute(
            "UPDATE clouds SET status = 'processing', error = NULL, updated_at = ? WHERE id = ?",
            (utcnow(), cloud_id),
        )
        job_id = create_job("ingest", project_id, cloud_id, f"возобновление {cloud['name']}")
        submit(job_id, _ingest_work(project_id, cloud_id))
        return _cloud_out(_cloud(cloud_id), job_id)

    @api.delete("/clouds/{cloud_id}")
    def delete_cloud(cloud_id: str):
        row = _cloud(cloud_id)
        execute("DELETE FROM clouds WHERE id = ?", (cloud_id,))
        shutil.rmtree(cloud_paths(row["project_id"], cloud_id)["dir"], ignore_errors=True)
        dispatch_event("cloud.deleted", {"cloud_id": cloud_id})
        return {"deleted": cloud_id}

    @api.get("/clouds/{cloud_id}/preview")
    def preview_binary(cloud_id: str):
        row = _cloud(cloud_id)
        if row["status"] != "ready":
            raise HTTPException(409, f"cloud is not ready (status: {row['status']})")
        path = cloud_paths(row["project_id"], cloud_id)["preview"]
        if not path.exists():
            raise HTTPException(404, "preview is missing")
        return FileResponse(
            path,
            media_type="application/octet-stream",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @api.get("/clouds/{cloud_id}/stats")
    def cloud_stats(cloud_id: str):
        row = _cloud(cloud_id)
        return {
            "cloud": _cloud_out(row),
            "elements": len(list_elements(cloud_id)),
            "sections": len(rows("SELECT id FROM sections WHERE cloud_id = ?", (cloud_id,))),
        }

    # ------------------------------------------------------------ sections
    @api.post("/clouds/{cloud_id}/sections", response_model=SectionOut)
    def create_section(cloud_id: str, payload: SectionRequest):
        row = _cloud(cloud_id)
        geom = _cloud_geometry(row)
        try:
            result = extract_section(
                geom,
                kind=payload.kind,
                axis=payload.axis,
                position=payload.position,
                thickness=payload.thickness,
                grid_res=payload.grid_res,
                region=(
                    (payload.region.min_u, payload.region.max_u, payload.region.min_v, payload.region.max_v)
                    if payload.region
                    else None
                ),
                regularize=payload.regularize,
                min_component_area=payload.min_component_area,
                close_radius_m=payload.close_radius_m,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        section_id = new_id()
        now = utcnow()
        frame = result["frame"]
        execute(
            """
            INSERT INTO sections
            (id, project_id, cloud_id, kind, axis, position, thickness, grid_res, params_json, result_json, point_count, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                section_id,
                row["project_id"],
                cloud_id,
                payload.kind,
                payload.axis,
                frame["position_world"],
                payload.thickness,
                payload.grid_res,
                dumps(payload.model_dump()),
                dumps(result),
                int(result.get("point_count", 0)),
                now,
            ),
        )
        dispatch_event(
            "section.created",
            {"section_id": section_id, "cloud_id": cloud_id, "kind": payload.kind},
        )
        return _section_row(_section(section_id))

    @api.get("/clouds/{cloud_id}/sections")
    def cloud_sections(cloud_id: str):
        _cloud(cloud_id)
        return [_section_row(r) for r in rows("SELECT * FROM sections WHERE cloud_id = ? ORDER BY created_at DESC", (cloud_id,))]

    @api.get("/sections/{section_id}", response_model=SectionOut)
    def get_section(section_id: str):
        return _section_row(_section(section_id))

    @api.delete("/sections/{section_id}")
    def delete_section(section_id: str):
        _section(section_id)
        execute("DELETE FROM sections WHERE id = ?", (section_id,))
        return {"deleted": section_id}

    @api.post("/sections/{section_id}/export")
    def export_section(
        section_id: str,
        format: str = Query(default="dxf", pattern="^(dxf|pdf|json|dwg)$"),
        scale: int = Query(default=50, ge=1, le=500),
        draw_scan_points: bool = False,
    ):
        section = _section(section_id)
        result = loads(section["result_json"], {})
        cloud = _cloud(section["cloud_id"])
        project = _project(section["project_id"])
        export_id, folder = new_export_dir(section["project_id"], f"section_{section_id[:8]}")
        base = f"{project['name']}_{section['kind']}_{section['position']:.3f}".replace(" ", "_").replace(",", "_")
        if format == "json":
            path = folder / f"{base}.json"
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            media = "application/json"
        elif format == "dxf":
            path = folder / f"{base}.dxf"
            export_section_dxf(
                result,
                path,
                cloud_name=cloud["name"],
                project_name=project["name"],
                scale=scale,
                draw_scan_points=draw_scan_points,
            )
            media = "application/dxf"
        elif format == "pdf":
            path = folder / f"{base}.pdf"
            export_section_pdf(
                result,
                path,
                cloud_name=cloud["name"],
                project_name=project["name"],
                scale=scale,
            )
            media = "application/pdf"
        else:
            # DWG is a translation of the DXF we just produced, done by a
            # licensed converter (ODA File Converter / accoreconsole).
            dxf_path = folder / f"{base}.dxf"
            export_section_dxf(
                result,
                dxf_path,
                cloud_name=cloud["name"],
                project_name=project["name"],
                scale=scale,
                draw_scan_points=draw_scan_points,
            )
            path = folder / f"{base}.dwg"
            _dxf_to_dwg_or_409(dxf_path, path)
            media = "application/acad"
        return FileResponse(path, media_type=media, filename=path.name)

    # ------------------------------------------------------------ recognition
    @api.post("/clouds/{cloud_id}/recognize", response_model=JobOut)
    def recognize(cloud_id: str):
        cloud = _cloud(cloud_id)
        geom = _cloud_geometry(cloud)
        project_id = cloud["project_id"]
        job_id = create_job("recognition", project_id, cloud_id, "распознавание конструкций")
        project = _project(project_id)

        def work(progress):
            source_snapshot = point_cloud_snapshot(
                cloud_id, geom.positions_path, geom.count, geom.origin,
            )
            result = detect_structures(geom, progress)
            current_snapshot = point_cloud_snapshot(
                cloud_id, geom.positions_path, geom.count, geom.origin,
            )
            if current_snapshot["snapshot_id"] != source_snapshot["snapshot_id"]:
                raise RuntimeError("cloud positions changed during recognition; no candidates were saved")
            candidates = []
            for el in result.elements:
                element = {
                    "id": new_id(),
                    "project_id": project_id,
                    "cloud_id": cloud_id,
                    "class_name": el.class_name,
                    "geometry": el.geometry,
                    "bbox": el.bbox,
                    "confidence": el.confidence,
                    "confidence_kind": "heuristic",
                    "measured": 1 if el.measured else 0,
                    "inferred": 1 if el.inferred else 0,
                    "source": el.source,
                    "dimensions": el.dimensions,
                    "metadata": {
                        **el.metadata,
                        "bbox_coordinate_frame": "source_cloud_world",
                        "source_cloud_snapshot": source_snapshot,
                    },
                }
                element["features"] = features_from_element(element)
                candidates.append(element)
            apply_learned_prior(candidates)
            existing_geometric = rows(
                """SELECT id, class_name, geometry_json, bbox_json, review_status FROM elements
                   WHERE cloud_id = ? AND source = 'geometric'""",
                (cloud_id,),
            )
            reviewed = [
                item for item in existing_geometric
                if item["review_status"] in {"confirmed", "corrected", "rejected"}
            ]
            reusable = [item for item in existing_geometric if item["review_status"] == "unreviewed"]
            reconciliation = protect_reviewed_candidates(candidates, reviewed, reusable)
            reused_ids = reconciliation.reused_candidate_ids
            if reused_ids:
                placeholders = ",".join("?" for _ in reused_ids)
                execute(
                    f"DELETE FROM elements WHERE cloud_id = ? AND source = 'geometric' "
                    f"AND review_status = 'unreviewed' AND id NOT IN ({placeholders})",
                    (cloud_id, *reused_ids),
                )
            else:
                execute(
                    "DELETE FROM elements WHERE cloud_id = ? AND source = 'geometric' AND review_status = 'unreviewed'",
                    (cloud_id,),
                )
            created = []
            conflicts = []
            for element in reconciliation.candidates:
                if element.get("dimensions", {}).get("review_conflict_with"):
                    conflicts.append({
                        "candidate_id": element["id"],
                        "protected_ids": element["dimensions"]["review_conflict_with"],
                    })
                created.append(element)
            now = utcnow()
            for element in created:
                execute(
                    """
                    INSERT INTO elements
                    (id, project_id, cloud_id, parent_id, class_name, geometry_json, bbox_json,
                     confidence, confidence_kind, measured, inferred, source, review_status,
                     dimensions_json, metadata_json, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        class_name=excluded.class_name,
                        geometry_json=excluded.geometry_json,
                        bbox_json=excluded.bbox_json,
                        confidence=excluded.confidence,
                        confidence_kind=excluded.confidence_kind,
                        measured=excluded.measured,
                        inferred=excluded.inferred,
                        dimensions_json=excluded.dimensions_json,
                        metadata_json=excluded.metadata_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        element["id"],
                        project_id,
                        cloud_id,
                        None,
                        element["class_name"],
                        dumps(element["geometry"]),
                        dumps(element["bbox"]),
                        element["confidence"],
                        element["confidence_kind"],
                        element["measured"],
                        element["inferred"],
                        element["source"],
                        "unreviewed",
                        dumps(element["dimensions"]),
                        dumps({**element["metadata"], "features": element["features"]}),
                        now,
                        now,
                    ),
                )
            meta = loads(cloud.get("metadata_json"), {})
            meta["recognition"] = {
                "levels": result.levels,
                "stats": result.stats,
                "warnings": result.warnings,
                "recognised_at": now,
            }
            execute(
                "UPDATE clouds SET metadata_json = ?, updated_at = ? WHERE id = ?",
                (dumps(meta), utcnow(), cloud_id),
            )
            return {
                "cloud_id": cloud_id,
                "element_count": len(created),
                "levels": result.levels,
                "stats": result.stats,
                "warnings": result.warnings,
                "review_reconciliation": {
                    "preserved_manual_element_ids": reconciliation.preserved_ids,
                    "reused_candidate_ids": reconciliation.reused_candidate_ids,
                    "conflicts": conflicts,
                },
            }

        submit(job_id, work)
        dispatch_event("recognition.started", {"job_id": job_id, "cloud_id": cloud_id})
        return get_job(job_id)

    @api.get("/clouds/{cloud_id}/elements", response_model=list[ElementOut])
    def get_elements(cloud_id: str):
        _cloud(cloud_id)
        return list_elements(cloud_id)

    @api.get("/clouds/{cloud_id}/element-annotations")
    def get_element_annotations(cloud_id: str):
        cloud = _cloud(cloud_id)
        elements = _element_reference_candidates(cloud_id)
        if not elements:
            raise HTTPException(404, "cloud has no eligible element candidates")
        try:
            source_hash = element_snapshot_sha256(elements, cloud)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        history = rows(
            "SELECT element_id,revision,payload_json,created_at FROM element_annotations "
            "WHERE cloud_id=? AND source_snapshot_sha256=? ORDER BY element_id,revision",
            (cloud_id, source_hash),
        )
        latest: dict[str, dict[str, Any]] = {}
        history_out = []
        for record in history:
            item = {**loads(record["payload_json"], {}), "element_id": record["element_id"],
                    "revision": record["revision"], "created_at": record["created_at"]}
            latest[record["element_id"]] = item
            history_out.append(item)
        dataset_id = f"{cloud_id}:{source_hash[:12]}"
        document = element_reference_document(dataset_id, source_hash, elements, latest, cloud)
        return {**document, "project_id": cloud["project_id"], "cloud_id": cloud_id,
                "history": history_out}

    @api.post("/clouds/{cloud_id}/recognition-evaluation")
    def evaluate_cloud_recognition(cloud_id: str, payload: RecognitionEvaluationRequest):
        cloud = _cloud(cloud_id)
        elements = _element_reference_candidates(cloud_id)
        if not elements:
            raise HTTPException(404, "cloud has no eligible recognition candidates")
        try:
            source_hash = element_snapshot_sha256(elements, cloud)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if payload.source_snapshot_sha256 != source_hash:
            raise HTTPException(409, "candidate snapshot changed; reload the cloud before evaluation")

        references = []
        physical_ids: set[str] = set()
        for reference in payload.reference_elements:
            physical_id = reference.physical_instance_id.strip()
            if not physical_id:
                raise HTTPException(422, "physical_instance_id must be non-empty")
            if physical_id in physical_ids:
                raise HTTPException(422, "reference physical_instance_id values must be unique")
            physical_ids.add(physical_id)
            references.append({
                "id": physical_id,
                "class_name": reference.class_name,
                "role_name": reference.role_label,
                "bbox": reference.bbox.model_dump(),
            })

        detections = [{
            "id": item["id"],
            "class_name": item["class_name"],
            "role_name": (item.get("dimensions") or {}).get("role"),
            "bbox": item.get("bbox"),
            "geometry": item.get("geometry"),
        } for item in elements]
        try:
            report = evaluate_recognition(
                detections,
                references,
                iou_threshold=payload.iou_threshold,
                reference_set_id=payload.reference_set_id.strip(),
                reference_kind=payload.reference_kind,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            **report,
            "cloud_id": cloud_id,
            "source_snapshot_sha256": source_hash,
            "reference_origin": payload.reference_origin,
            "annotator": payload.annotator.strip(),
            "reference_set_id": payload.reference_set_id.strip(),
            "holdout_status": "not_verified",
            "training_usage": "not_used",
            "missed_reference_elements_counted_as_false_negatives": True,
        }

    @api.post("/clouds/{cloud_id}/element-annotations/{element_id}")
    def save_element_annotation(cloud_id: str, element_id: str, payload: ElementAnnotationSave):
        cloud = _cloud(cloud_id)
        elements = _element_reference_candidates(cloud_id)
        if not any(item["id"] == element_id for item in elements):
            raise HTTPException(404, "element candidate not found in this cloud")
        try:
            source_hash = element_snapshot_sha256(elements, cloud)
            annotation = validate_element_annotation(payload.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if payload.source_snapshot_sha256 != source_hash:
            raise HTTPException(409, "element snapshot changed; reload the annotation dataset before saving")

        with db_session() as con:
            con.execute("BEGIN IMMEDIATE")
            current_cloud = _cloud(cloud_id)
            current_elements = _element_reference_candidates(cloud_id)
            try:
                current_hash = element_snapshot_sha256(current_elements, current_cloud)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            if current_hash != source_hash:
                raise HTTPException(409, "element snapshot changed while saving; reload the annotation dataset")
            current = con.execute(
                "SELECT element_id,payload_json,MAX(revision) AS revision FROM element_annotations "
                "WHERE cloud_id=? AND source_snapshot_sha256=? GROUP BY element_id",
                (cloud_id, source_hash),
            ).fetchall()
            if annotation["state"] == "labeled":
                duplicate = next((row["element_id"] for row in current
                    if row["element_id"] != element_id
                    and (stored := loads(row["payload_json"], {})).get("state") == "labeled"
                    and stored.get("physical_instance_id") == annotation["physical_instance_id"]), None)
                if duplicate:
                    raise HTTPException(409, f"physical instance ID is already used by {duplicate}")
            revision_row = con.execute(
                "SELECT COALESCE(MAX(revision),0) AS revision FROM element_annotations "
                "WHERE cloud_id=? AND source_snapshot_sha256=? AND element_id=?",
                (cloud_id, source_hash, element_id),
            ).fetchone()
            revision = int(revision_row["revision"]) + 1
            created_at = utcnow()
            con.execute(
                "INSERT INTO element_annotations "
                "(id,project_id,cloud_id,source_snapshot_sha256,element_id,revision,payload_json,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (new_id(), cloud["project_id"], cloud_id, source_hash, element_id,
                 revision, dumps(annotation), created_at),
            )
            candidate = next(item for item in current_elements if item["id"] == element_id)
            if annotation["state"] == "labeled" and annotation["class_label"] == candidate["class_name"]:
                con.execute(
                    "UPDATE training_samples SET physical_instance_id=? "
                    "WHERE cloud_id=? AND element_id=? AND class_name=? AND source='engineer' "
                    "AND physical_instance_id IS NULL",
                    (annotation["physical_instance_id"], cloud_id, element_id, annotation["class_label"]),
                )
        result = {**annotation, "element_id": element_id, "revision": revision,
                  "created_at": created_at, "source_snapshot_sha256": source_hash}
        dispatch_event("element_annotation.saved", {
            "project_id": cloud["project_id"], "cloud_id": cloud_id, "element_id": element_id,
            "revision": revision, "source_snapshot_sha256": source_hash,
        })
        return result

    @api.get("/clouds/{cloud_id}/element-annotations/export")
    def export_element_annotations(cloud_id: str):
        cloud = _cloud(cloud_id)
        elements = _element_reference_candidates(cloud_id)
        if not elements:
            raise HTTPException(404, "cloud has no eligible element candidates")
        try:
            source_hash = element_snapshot_sha256(elements, cloud)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        history = rows(
            "SELECT element_id,payload_json,MAX(revision) AS revision FROM element_annotations "
            "WHERE cloud_id=? AND source_snapshot_sha256=? GROUP BY element_id",
            (cloud_id, source_hash),
        )
        latest = {record["element_id"]: loads(record["payload_json"], {}) for record in history}
        document = element_reference_document(
            f"{cloud_id}:{source_hash[:12]}", source_hash, elements, latest, cloud,
        )
        return {**document, "project_id": cloud["project_id"], "cloud_id": cloud_id}

    @api.get("/clouds/{cloud_id}/element-annotations/history")
    def get_element_annotation_history(cloud_id: str):
        cloud = _cloud(cloud_id)
        history = rows(
            "SELECT a.source_snapshot_sha256,a.element_id,a.revision,a.payload_json,a.created_at "
            "FROM element_annotations a LEFT JOIN elements e ON e.id=a.element_id "
            "WHERE a.cloud_id=? AND (e.id IS NULL OR COALESCE(e.source,'') != ?) "
            "ORDER BY a.created_at,a.element_id,a.revision",
            (cloud_id, INVALIDATED_SOURCE),
        )
        return {"project_id": cloud["project_id"], "cloud_id": cloud_id, "history": [
            {**loads(record["payload_json"], {}), "dataset_id": f"{cloud_id}:{record['source_snapshot_sha256'][:12]}",
             "source_snapshot_sha256": record["source_snapshot_sha256"], "element_id": record["element_id"],
             "revision": record["revision"], "created_at": record["created_at"]}
            for record in history
        ]}

    @api.get("/clouds/{cloud_id}/column-annotations")
    def get_column_annotations(cloud_id: str):
        cloud = _cloud(cloud_id)
        elements = _column_reference_candidates(cloud_id)
        if not elements:
            raise HTTPException(404, "cloud has no column candidates")
        try:
            source_hash = column_snapshot_sha256(elements, cloud)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        history = rows(
            "SELECT element_id,revision,payload_json,created_at FROM column_annotations "
            "WHERE cloud_id=? AND source_snapshot_sha256=? ORDER BY element_id,revision",
            (cloud_id, source_hash),
        )
        latest: dict[str, dict[str, Any]] = {}
        history_out = []
        for record in history:
            payload = loads(record["payload_json"], {})
            latest[record["element_id"]] = {
                **payload, "element_id": record["element_id"],
                "revision": record["revision"], "created_at": record["created_at"],
            }
            history_out.append(latest[record["element_id"]])
        annotations = []
        for element in sorted(elements, key=lambda item: item["id"]):
            annotations.append(latest.get(element["id"]) or empty_annotation(element["id"]))
        dataset_id = f"{cloud_id}:{source_hash[:12]}"
        return {
            "schema": "scan.column-type-reference/1",
            "dataset_id": dataset_id,
            "project_id": cloud["project_id"],
            "cloud_id": cloud_id,
            "source_snapshot_sha256": source_hash,
            "source_cloud_manifest": column_cloud_manifest(cloud),
            "annotation_origin": "independent_manual",
            "engineering_tolerance_m": None,
            "annotations": annotations,
            "history": history_out,
        }

    @api.post("/clouds/{cloud_id}/column-annotations/{element_id}")
    def save_column_annotation(cloud_id: str, element_id: str, payload: ColumnAnnotationSave):
        cloud = _cloud(cloud_id)
        elements = _column_reference_candidates(cloud_id)
        element = next((item for item in elements if item["id"] == element_id), None)
        if element is None:
            raise HTTPException(404, "column candidate not found in this cloud")
        try:
            source_hash = column_snapshot_sha256(elements, cloud)
            annotation = validate_column_annotation(payload.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if payload.source_snapshot_sha256 != source_hash:
            raise HTTPException(409, "column snapshot changed; reload the annotation dataset before saving")

        with db_session() as con:
            con.execute("BEGIN IMMEDIATE")
            # The initial snapshot is read before the write lock. Recognition or
            # re-ingest may commit in that gap, so validate the snapshot again
            # while BEGIN IMMEDIATE prevents another writer from changing it.
            current_cloud = _cloud(cloud_id)
            current_elements = _column_reference_candidates(cloud_id)
            try:
                current_source_hash = column_snapshot_sha256(current_elements, current_cloud)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            if current_source_hash != source_hash:
                raise HTTPException(409, "column snapshot changed while saving; reload the annotation dataset")
            cloud = current_cloud
            current = con.execute(
                "SELECT element_id,payload_json,MAX(revision) AS revision FROM column_annotations "
                "WHERE cloud_id=? AND source_snapshot_sha256=? GROUP BY element_id",
                (cloud_id, source_hash),
            ).fetchall()
            if annotation["state"] == "labeled":
                duplicate = next((row["element_id"] for row in current
                    if row["element_id"] != element_id
                    and (stored := loads(row["payload_json"], {})).get("state") == "labeled"
                    and stored.get("physical_instance_id") == annotation["physical_instance_id"]), None)
                if duplicate:
                    raise HTTPException(409, f"physical instance ID is already used by {duplicate}")
            revision_row = con.execute(
                "SELECT COALESCE(MAX(revision),0) AS revision FROM column_annotations "
                "WHERE cloud_id=? AND source_snapshot_sha256=? AND element_id=?",
                (cloud_id, source_hash, element_id),
            ).fetchone()
            revision = int(revision_row["revision"]) + 1
            created_at = utcnow()
            con.execute(
                "INSERT INTO column_annotations "
                "(id,project_id,cloud_id,source_snapshot_sha256,element_id,revision,payload_json,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (new_id(), cloud["project_id"], cloud_id, source_hash, element_id,
                 revision, dumps(annotation), created_at),
            )
        result = {**annotation, "element_id": element_id, "revision": revision,
                  "created_at": created_at, "source_snapshot_sha256": source_hash}
        dispatch_event("column_annotation.saved", {
            "project_id": cloud["project_id"], "cloud_id": cloud_id,
            "element_id": element_id, "revision": revision,
            "source_snapshot_sha256": source_hash,
        })
        return result

    @api.get("/clouds/{cloud_id}/column-annotations/export")
    def export_column_annotations(cloud_id: str):
        cloud = _cloud(cloud_id)
        elements = _column_reference_candidates(cloud_id)
        if not elements:
            raise HTTPException(404, "cloud has no column candidates")
        try:
            source_hash = column_snapshot_sha256(elements, cloud)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        history = rows(
            "SELECT element_id,revision,payload_json,created_at FROM column_annotations "
            "WHERE cloud_id=? AND source_snapshot_sha256=? ORDER BY element_id,revision",
            (cloud_id, source_hash),
        )
        latest = {}
        for record in history:
            latest[record["element_id"]] = loads(record["payload_json"], {})
        dataset_id = f"{cloud_id}:{source_hash[:12]}"
        document = annotation_reference_document(dataset_id, source_hash, elements, latest, cloud)
        return {**document, "project_id": cloud["project_id"], "cloud_id": cloud_id}

    @api.get("/clouds/{cloud_id}/column-annotations/history")
    def get_column_annotation_history(cloud_id: str):
        cloud = _cloud(cloud_id)
        history = rows(
            "SELECT a.source_snapshot_sha256,a.element_id,a.revision,a.payload_json,a.created_at "
            "FROM column_annotations a LEFT JOIN elements e ON e.id=a.element_id "
            "WHERE a.cloud_id=? AND (e.id IS NULL OR COALESCE(e.source,'') != ?) "
            "ORDER BY a.created_at,a.element_id,a.revision",
            (cloud_id, "invalidated_synthetic_ground_truth"),
        )
        records = []
        for record in history:
            records.append({
                **loads(record["payload_json"], {}),
                "dataset_id": f"{cloud_id}:{record['source_snapshot_sha256'][:12]}",
                "source_snapshot_sha256": record["source_snapshot_sha256"],
                "element_id": record["element_id"],
                "revision": record["revision"],
                "created_at": record["created_at"],
            })
        return {"project_id": cloud["project_id"], "cloud_id": cloud_id, "history": records}

    @api.get("/clouds/{cloud_id}/column-types")
    def cloud_column_types(
        cloud_id: str,
        linear_tolerance_m: float = Query(default=0.005, ge=0, le=0.5, allow_inf_nan=False),
        relative_tolerance: float = Query(default=0.01, ge=0, le=0.25, allow_inf_nan=False),
    ):
        cloud = _cloud(cloud_id)
        elements = [item for item in list_elements(cloud_id) if item["review_status"] != "rejected"]
        confirmed_types = list_column_types(cloud["project_id"])
        try:
            proposals = propose_column_types(
                _unassigned_type_elements(elements, confirmed_types),
                linear_tolerance_m=linear_tolerance_m,
                relative_tolerance=relative_tolerance,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        rejected = list_rejected_column_types(cloud["project_id"])
        rejected_keys = {item["proposal_key"] for item in rejected}
        sources = [element_from_row(item) for item in rows(
            "SELECT e.*,c.sha256 AS source_cloud_sha256 FROM elements e "
            "JOIN clouds c ON c.id=e.cloud_id "
            "JOIN column_type_assignments a ON a.element_id=e.id "
            "WHERE e.project_id=? AND a.project_id=?", (cloud["project_id"], cloud["project_id"]))]
        reuse = match_project_column_types(cloud["project_id"], elements, confirmed_types, sources,
            linear_tolerance_m=linear_tolerance_m, relative_tolerance=relative_tolerance)
        return {
            "cloud_id": cloud_id,
            "project_id": cloud["project_id"],
            "tolerance_status": "provisional",
            "linear_tolerance_m": linear_tolerance_m,
            "relative_tolerance": relative_tolerance,
            "proposals": [
                proposal for proposal in proposals
                if proposal["proposal_key"] not in rejected_keys
            ],
            "confirmed_types": confirmed_types,
            "rejected_proposals": rejected,
            "catalog_reuse": reuse,
        }

    @api.post("/column-types/{proposal_key}/confirm")
    def column_type_confirm(proposal_key: str, payload: ColumnTypeConfirm):
        cloud = _cloud(payload.cloud_id)
        elements = [item for item in list_elements(payload.cloud_id) if item["review_status"] != "rejected"]
        confirmed = list_column_types(cloud["project_id"])
        existing = next((item for item in confirmed if item["proposal_key"] == proposal_key), None)
        if existing:
            original_ids = set(existing["prototype"]["member_element_ids"])
            review_elements = [item for item in elements if item["id"] in original_ids]
        else:
            review_elements = _unassigned_type_elements(elements, confirmed)
        try:
            proposals = propose_column_types(
                review_elements,
                linear_tolerance_m=payload.linear_tolerance_m,
                relative_tolerance=payload.relative_tolerance,
            )
            proposal = next(
                (item for item in proposals if item["proposal_key"] == proposal_key), None
            )
            if proposal is None:
                raise HTTPException(404, "column type proposal not found for this cloud")
            result = confirm_column_type(
                cloud["project_id"], proposal, mark=payload.mark,
                engineer=payload.engineer, note=payload.note,
            )
        except ValueError as exc:
            raise _column_type_http_error(exc) from exc
        dispatch_event("column_type.confirmed", {
            "project_id": cloud["project_id"], "type_id": result["id"],
            "mark": result["mark"], "proposal_key": proposal_key,
        })
        return result

    @api.post("/column-types/{proposal_key}/reject")
    def column_type_reject(proposal_key: str, payload: ColumnTypeReject):
        cloud = _cloud(payload.cloud_id)
        elements = [item for item in list_elements(payload.cloud_id) if item["review_status"] != "rejected"]
        confirmed = list_column_types(cloud["project_id"])
        try:
            proposals = propose_column_types(
                _unassigned_type_elements(elements, confirmed), linear_tolerance_m=payload.linear_tolerance_m,
                relative_tolerance=payload.relative_tolerance,
            )
            proposal = next((item for item in proposals if item["proposal_key"] == proposal_key), None)
            if proposal is None:
                raise HTTPException(404, "column type proposal not found for this cloud")
            result = reject_column_type(cloud["project_id"], proposal, payload.engineer, payload.note)
        except ValueError as exc:
            raise _column_type_http_error(exc) from exc
        dispatch_event("column_type.rejected", {"project_id": cloud["project_id"], "proposal_key": proposal_key})
        return result

    @api.post("/elements/{element_id}/column-type")
    def element_column_type(element_id: str, payload: ColumnTypeAssign):
        try:
            result = assign_column_type(
                element_id, payload.type_id, engineer=payload.engineer, note=payload.note
            )
        except ValueError as exc:
            raise _column_type_http_error(exc) from exc
        dispatch_event("column_type.assigned", {
            "element_id": element_id, "type_id": payload.type_id,
        })
        return result

    @api.post("/column-types/actions/{action_id}/undo")
    def column_type_undo(action_id: str, payload: ColumnTypeUndo):
        try:
            result = undo_column_type_action(
                action_id, engineer=payload.engineer, note=payload.note
            )
        except ValueError as exc:
            raise _column_type_http_error(exc) from exc
        dispatch_event("column_type.undo", {
            "target_action_id": action_id, "action_id": result["action_id"],
        })
        return result

    @api.get("/clouds/{cloud_id}/levels")
    def get_levels(cloud_id: str):
        row = _cloud(cloud_id)
        meta = loads(row.get("metadata_json"), {})
        return (meta.get("recognition") or {}).get("levels", [])

    @api.get("/elements/{element_id}", response_model=ElementOut)
    def get_single_element(element_id: str):
        try:
            return get_element(element_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @api.post("/elements/{element_id}/section-fit")
    def propose_element_section(element_id: str, payload: ColumnSectionFitRequest):
        """Fit one horizontal slice for review; never changes element geometry or type."""
        try:
            element = get_element(element_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        geometry = element.get("geometry") or {}
        if element.get("class_name") != "column" or geometry.get("kind") != "oriented_box":
            raise HTTPException(409, "section fitting requires a column with oriented_box geometry")
        cloud = _cloud(element["cloud_id"])
        if cloud["status"] != "ready":
            raise HTTPException(409, f"cloud is not ready (status: {cloud['status']})")
        paths = cloud_paths(cloud["project_id"], cloud["id"])
        if not paths["positions"].exists():
            raise HTTPException(409, "derived cloud positions are missing")
        center = np.asarray(geometry["center"], dtype=np.float64)
        angle = float(geometry.get("rotation_z", 0.0))
        rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        half = np.array([geometry["sizes"]["length"], geometry["sizes"]["thickness"]], dtype=np.float64) / 2
        padded = half + payload.candidate_margin_m
        extent = np.abs(rotation) @ padded
        z_center = float(payload.slice_z_m if payload.slice_z_m is not None else center[2])
        lower = np.array([center[0] - extent[0], center[1] - extent[1], z_center - payload.thickness_m / 2])
        upper = np.array([center[0] + extent[0], center[1] + extent[1], z_center + payload.thickness_m / 2])
        point_source = NpyPointProvider(
            paths["positions"],
            origin=np.array([cloud["origin_x"], cloud["origin_y"], cloud["origin_z"]], dtype=np.float64),
            colors_path=paths["colors"] if paths["colors"].exists() else None,
        )
        point_query = PointQuery(tuple(np.r_[lower, upper]))
        point_source, query_strategy = select_query_provider(
            point_source, paths["dir"] / "spatial-index-v1", point_query,
        )
        xyz_parts, row_parts = [], []
        selected_count = 0
        hard_limit = 250_000
        for batch in point_source.iter_points(point_query):
            local_xy = (batch.xyz[:, :2] - center[:2]) @ rotation
            inside = (np.abs(local_xy) <= padded).all(axis=1)
            if not inside.any():
                continue
            xyz_parts.append(batch.xyz[inside])
            row_parts.append(batch.source_indices[inside])
            selected_count += int(inside.sum())
            if selected_count > hard_limit:
                raise HTTPException(413, "slice has more than 250000 points; reduce slice thickness or candidate margin")
        points = np.concatenate(xyz_parts) if xyz_parts else np.empty((0, 3), dtype=np.float64)
        source_rows = np.concatenate(row_parts) if row_parts else np.empty(0, dtype=np.int64)
        if len(points) < 2:
            fit = {"status": "insufficient_points", "hypotheses": [], "observed_faces": [],
                   "open_corners": [], "dimension_conflicts": [], "review_required": True,
                   "engineering_status": "not_assessed"}
        else:
            fit = fit_rectangular_section(
                points[:, :2],
                known_sides_m=tuple(payload.known_sides_m) if payload.known_sides_m is not None else None,
                distance_tolerance_m=payload.distance_tolerance_m,
            )
        faces = []
        for face in fit.get("observed_faces", []):
            row_ids = np.asarray(face.get("input_point_indices", []), dtype=np.int64)
            source_ids = np.sort(source_rows[row_ids]) if len(row_ids) else np.empty(0, dtype=np.int64)
            faces.append({**face, "ingested_point_row_id_sample": source_ids[:100].tolist(),
                          "ingested_point_row_id_count": len(source_ids)})
        observed_point_indices = {
            int(index)
            for face in fit.get("observed_faces", [])
            for index in face.get("input_point_indices", [])
            if 0 <= int(index) < len(points)
        }
        observed_point_count = len(observed_point_indices)
        preview_step = max(1, int(np.ceil(len(points) / 4000)))
        preview = (points[::preview_step, :2] - center[:2]).tolist()
        return {
            "element_id": element_id,
            "algorithm": {"name": "fit_rectangular_section", "version": "1"},
            "parameters": {
                "slice_z_m": z_center,
                "thickness_m": payload.thickness_m,
                "known_sides_m": payload.known_sides_m,
                "distance_tolerance_m": payload.distance_tolerance_m,
                "candidate_margin_m": payload.candidate_margin_m,
            },
            "source_rows": {
                "kind": "derived_cloud_zero_based_row_index",
                "count": int(len(points)),
                "sample_limit_per_face": 100,
                "description": "Строки в производном массиве координат облака; это не номера точек FARO.",
            },
            "point_query": query_strategy,
            "point_support": {
                "selected_point_count": int(len(points)),
                "unique_observed_face_point_count": observed_point_count,
                "unassigned_point_count": int(len(points) - observed_point_count),
                "observed_face_point_fraction": (
                    float(observed_point_count / len(points)) if len(points) else None
                ),
                "scope": (
                    "Уникальные точки среза, использованные хотя бы одной найденной гранью; "
                    "это не покрытие площади поверхности и не оценка точности."
                ),
            },
            "slice_z_m": z_center,
            "slice_thickness_m": payload.thickness_m,
            "candidate_margin_m": payload.candidate_margin_m,
            "point_count": int(len(points)),
            "preview_points_xy_local_m": preview,
            "status": fit["status"],
            "hypotheses": fit.get("hypotheses", []),
            "observed_faces": faces,
            "open_corners": fit.get("open_corners", []),
            "dimension_conflicts": fit.get("dimension_conflicts", []),
            "review_required": True,
            "engineering_status": "not_assessed",
            "persisted": False,
            "source_geometry_modified": False,
        }

    @api.post("/elements/{element_id}/section-fit-batch")
    def propose_element_section_batch(element_id: str, payload: ColumnSectionBatchFitRequest):
        """Fit several independent horizontal slices in one review request."""
        results = [
            propose_element_section(
                element_id,
                ColumnSectionFitRequest(
                    slice_z_m=z_m,
                    thickness_m=payload.thickness_m,
                    known_sides_m=payload.known_sides_m,
                    distance_tolerance_m=payload.distance_tolerance_m,
                    candidate_margin_m=payload.candidate_margin_m,
                ),
            )
            for z_m in payload.slice_z_values_m
        ]
        return {
            "element_id": element_id,
            "algorithm": {"name": "fit_rectangular_section", "version": "1"},
            "slice_count": len(results),
            "review_required": True,
            "persisted": False,
            "source_geometry_modified": False,
            "slices": results,
        }

    @api.post("/elements/{element_id}/surface-track-analysis")
    def analyze_column_surface_tracks(element_id: str):
        """Build a source-linked, review-only vertical-face/section report."""
        try:
            element = get_element(element_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        geometry = element.get("geometry") or {}
        if element.get("class_name") != "column" or geometry.get("kind") != "oriented_box":
            raise HTTPException(409, "surface tracking requires a column with oriented_box geometry")
        cloud = _cloud(element["cloud_id"])
        if cloud["status"] != "ready":
            raise HTTPException(409, f"cloud is not ready (status: {cloud['status']})")
        paths = cloud_paths(cloud["project_id"], cloud["id"])
        if not paths["positions"].exists():
            raise HTTPException(409, "derived cloud positions are missing")

        center = np.asarray(geometry["center"], dtype=np.float64)
        sizes = geometry["sizes"]
        rotation_z = float(geometry.get("rotation_z", 0.0))
        rotation = np.array([
            [np.cos(rotation_z), -np.sin(rotation_z)],
            [np.sin(rotation_z), np.cos(rotation_z)],
        ])
        margin_m = 0.15
        half = np.array([sizes["length"], sizes["thickness"]], dtype=np.float64) / 2
        padded = half + margin_m
        extent = np.abs(rotation) @ padded
        z_margin_m = 0.1
        lower = np.array([
            center[0] - extent[0], center[1] - extent[1], center[2] - sizes["height"] / 2 - z_margin_m,
        ])
        upper = np.array([
            center[0] + extent[0], center[1] + extent[1], center[2] + sizes["height"] / 2 + z_margin_m,
        ])
        point_source = NpyPointProvider(
            paths["positions"],
            origin=np.array([cloud["origin_x"], cloud["origin_y"], cloud["origin_z"]], dtype=np.float64),
            colors_path=paths["colors"] if paths["colors"].exists() else None,
        )
        point_query = PointQuery(tuple(np.r_[lower, upper]))
        point_source, query_strategy = select_query_provider(
            point_source, paths["dir"] / "spatial-index-v1", point_query,
        )
        xyz_parts: list[np.ndarray] = []
        row_parts: list[np.ndarray] = []
        selected_count = 0
        hard_limit = 250_000
        for batch in point_source.iter_points(point_query):
            local_xy = (batch.xyz[:, :2] - center[:2]) @ rotation
            in_crop = (
                (np.abs(local_xy) <= padded).all(axis=1)
                & (batch.xyz[:, 2] >= lower[2])
                & (batch.xyz[:, 2] <= upper[2])
            )
            if not in_crop.any():
                continue
            selected_count += int(in_crop.sum())
            if selected_count > hard_limit:
                raise HTTPException(
                    413,
                    "column candidate crop exceeds 250000 points; refine the candidate box before surface analysis",
                )
            xyz_parts.append(batch.xyz[in_crop])
            row_parts.append(batch.source_indices[in_crop])
        points = np.concatenate(xyz_parts) if xyz_parts else np.empty((0, 3), dtype=np.float64)
        source_rows = np.concatenate(row_parts) if row_parts else np.empty(0, dtype=np.int64)

        if len(points) >= 3:
            surface_result = extract_vertical_surfaces(
                points,
                distance_tolerance_m=0.015,
                voxel_m=0.02,
                min_support=30,
                min_vertical_span_m=0.5,
                max_planes=8,
                max_trials=192,
            )
        else:
            surface_result = {"surfaces": [], "adjacent_face_pairs": []}
        for surface in surface_result.get("surfaces", []):
            local_indices = np.asarray(surface.get("input_point_indices", []), dtype=np.int64)
            linked_rows = np.sort(source_rows[local_indices]) if len(local_indices) else np.empty(0, dtype=np.int64)
            surface["source_crop_row_ids"] = linked_rows.tolist()
            surface["source_point_row_id_count"] = int(len(linked_rows))
            surface["source_point_row_id_sample"] = linked_rows[:100].tolist()

        candidate_geometry = {**geometry, "id": element_id}
        association = associate_surfaces_to_column(candidate_geometry, surface_result)
        tracks = cluster_column_surface_tracks(candidate_geometry, surface_result, association)
        series = fit_column_track_sections(
            candidate_geometry,
            tracks,
            points,
            source_rows,
        )

        public_surfaces = []
        for surface in surface_result.get("surfaces", []):
            item = dict(surface)
            item.pop("input_point_indices", None)
            item.pop("source_crop_row_ids", None)
            public_surfaces.append(item)
        for track in tracks:
            source_ids = track.pop("source_point_indices", [])
            track["source_point_row_id_count"] = len(source_ids)
            track["source_point_row_id_sample"] = source_ids[:100]
            track["source_id_scope"] = "derived_cloud_zero_based_row_index"
        for section in series["section_series"]["section_slices"]:
            source_ids = section.pop("source_point_ids", [])
            section["source_point_row_id_count"] = len(source_ids)
            section["source_point_row_id_sample"] = source_ids[:100]
            for face in section.get("observed_faces", []):
                face_ids = face.pop("source_point_ids", [])
                face["source_point_row_id_count"] = len(face_ids)
                face["source_point_row_id_sample"] = face_ids[:100]
            for hypothesis in section.get("hypotheses", []):
                hypothesis_ids = hypothesis.pop("source_point_ids", [])
                hypothesis["source_point_row_id_count"] = len(hypothesis_ids)
                hypothesis["source_point_row_id_sample"] = hypothesis_ids[:100]
                hypothesis.pop("input_point_indices", None)
            for hypothesis in section.get("built_up_hypotheses", []):
                hypothesis_ids = hypothesis.pop("source_point_ids", [])
                hypothesis["source_point_row_id_count"] = len(hypothesis_ids)
                hypothesis["source_point_row_id_sample"] = hypothesis_ids[:100]
                hypothesis.pop("input_point_indices", None)
            for hypothesis in section.get("shape_hypotheses", []):
                hypothesis_ids = hypothesis.pop("source_point_ids", [])
                hypothesis["source_point_row_id_count"] = len(hypothesis_ids)
                hypothesis["source_point_row_id_sample"] = hypothesis_ids[:100]
                hypothesis.pop("input_point_indices", None)

        return {
            "schema": "scan.column-surface-track-analysis/1",
            "candidate_id": element_id,
            "cloud_id": cloud["id"],
            "algorithm": {"surface_extraction": "extract_vertical_surfaces/1", "section_series": "fit_column_track_sections/2"},
            "parameters": {
                "candidate_margin_m": margin_m,
                "vertical_context_margin_m": z_margin_m,
                "distance_tolerance_m": 0.015,
                "voxel_m": 0.02,
                "vertical_bin_m": 0.25,
                "maximum_crop_points": hard_limit,
            },
            "point_query": query_strategy,
            "input_points": {
                "count": int(len(points)),
                "source_row_kind": "derived_cloud_zero_based_row_index",
                "description": "Строки производного массива координат, не ID точек FARO.",
            },
            "surface_result": {**surface_result, "surfaces": public_surfaces},
            "surface_association": association,
            "tracks": tracks,
            "section_series": series["section_series"],
            "excluded_tracks": series["excluded_tracks"],
            "confirmed": False,
            "review_required": True,
            "engineering_status": "not_assessed",
            "persisted": False,
            "source_geometry_modified": False,
        }

    @api.patch("/elements/{element_id}", response_model=ElementOut)
    def patch_element(element_id: str, payload: ElementPatch):
        try:
            current = get_element(element_id)
            updates: dict[str, Any] = {}
            if payload.class_name:
                updates["class_name"] = payload.class_name
            if payload.geometry:
                updates["geometry"] = payload.geometry
                updates["bbox"] = derive_bbox(payload.geometry, current["bbox"])
            if payload.review_status:
                updates["review_status"] = payload.review_status
            if not updates:
                return current
            if payload.review_status == "confirmed":
                proposed = {**current, **updates}
                try:
                    validate_training_sample_source(proposed["cloud_id"], proposed)
                except ValueError as exc:
                    raise HTTPException(409, str(exc)) from exc
            execute_fields = []
            values: list[Any] = []
            for key, value in updates.items():
                if key in {"geometry", "bbox"}:
                    execute_fields.append(f"{key}_json = ?")
                    values.append(dumps(value))
                else:
                    execute_fields.append(f"{key} = ?")
                    values.append(value)
            execute_fields.append("updated_at = ?")
            values.append(utcnow())
            values.append(element_id)
            execute(f"UPDATE elements SET {', '.join(execute_fields)} WHERE id = ?", tuple(values))
            updated = get_element(element_id)
            if payload.review_status == "confirmed":
                create_sample(
                    updated["project_id"], updated["cloud_id"], updated, source="engineer",
                    physical_instance_id=_current_physical_instance_id(updated["cloud_id"], element_id),
                )
            return updated
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @api.post("/elements/{element_id}/feedback")
    def element_feedback(element_id: str, payload: FeedbackCreate):
        try:
            if payload.action == "merge":
                if not payload.other_element_id:
                    raise HTTPException(400, "merge requires other_element_id")
                result = merge_elements(
                    element_id,
                    payload.other_element_id,
                    class_name=payload.class_name,
                    engineer=payload.engineer,
                    note=payload.note,
                )
            elif payload.action == "split":
                if payload.axis is None or payload.value is None:
                    raise HTTPException(400, "split requires axis and value")
                result = split_element(
                    element_id, payload.axis, float(payload.value), payload.engineer, payload.note
                )
            else:
                result = review_element(
                    element_id,
                    payload.action,
                    class_name=payload.class_name,
                    geometry=payload.geometry,
                    engineer=payload.engineer,
                    note=payload.note,
                    physical_instance_id=(
                        _current_physical_instance_id(get_element(element_id)["cloud_id"], element_id)
                        if payload.action in {"confirm", "reclassify"} else None
                    ),
                )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        dispatch_event("element.feedback", {"element_id": element_id, "action": payload.action})
        return result

    @api.get("/elements/{element_id}/history")
    def element_history(element_id: str):
        try:
            get_element(element_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        history = rows("SELECT rowid AS sequence, * FROM feedback WHERE element_id = ? ORDER BY rowid", (element_id,))
        undone_ids = {
            loads(item.get("after_json"), {}).get("undo_of")
            for item in history
            if item["action"] == "undo"
        }
        latest_undoable = next(
            (item["id"] for item in reversed(history) if item["action"] != "undo" and item["id"] not in undone_ids),
            None,
        )
        return [
            {
                "id": item["id"],
                "action": item["action"],
                "before": loads(item.get("before_json"), {}),
                "after": loads(item.get("after_json"), {}),
                "can_undo": item["id"] == latest_undoable,
                "engineer": item.get("engineer", ""),
                "note": item.get("note", ""),
                "created_at": item["created_at"],
            }
            for item in history
        ]

    @api.post("/elements/{element_id}/history/{feedback_id}/undo")
    def element_history_undo(element_id: str, feedback_id: str):
        try:
            result = undo_feedback(element_id, feedback_id, engineer="engineer")
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        dispatch_event("element.feedback", {"element_id": element_id, "action": "undo"})
        return result

    @api.get("/elements/{element_id}/similar")
    def element_similar(element_id: str, k: int = Query(default=5, ge=1, le=20)):
        element = get_element(element_id)
        return similar_samples(element["project_id"], element["features"], k=k)

    @api.get("/elements/{element_id}/points")
    def element_points(element_id: str, limit: int = Query(default=8000, ge=100, le=50000)):
        from ..learning.store import extract_element_points

        element = get_element(element_id)
        geometry = element.get("geometry") or {}
        points = extract_element_points(
            element["cloud_id"],
            element["bbox"],
            limit=limit,
            coordinate_frame=element_bbox_coordinate_frame(element),
            degenerate_context_half_extent_m=0.6 if geometry.get("kind") == "member" else None,
        )
        frame = element_bbox_coordinate_frame(element)
        point_evidence = inspect_source_point_alignment(element["cloud_id"], element, frame)
        return {
            "count": int(len(points)),
            "points": points.round(3).tolist(),
            "bbox_coordinate_frame": frame,
            "source_point_evidence": point_evidence,
        }

    @api.get("/clouds/{cloud_id}/source-evidence-audit")
    def cloud_source_evidence_audit(cloud_id: str):
        """Summarize persisted point-row provenance without changing cloud or candidates."""
        cloud = _cloud(cloud_id)
        if cloud["status"] != "ready":
            raise HTTPException(409, f"cloud is not ready (status: {cloud['status']})")

        elements = list_elements(cloud_id)
        counts = {"consistent": 0, "mismatch": 0, "unverifiable": 0}
        counts_by_class: dict[str, dict[str, int]] = {}
        snapshot_counts = {"current": 0, "missing": 0, "stale": 0, "unchecked": 0}
        attention = []
        for element in elements:
            evidence = inspect_source_point_alignment(
                cloud_id,
                element,
                element_bbox_coordinate_frame(element),
            )
            status = evidence.get("status")
            if status not in counts:
                status = "unverifiable"
                evidence = {**evidence, "status": status}
            counts[status] += 1
            metadata = element.get("metadata")
            snapshot = metadata.get("source_cloud_snapshot") if isinstance(metadata, dict) else None
            if evidence.get("snapshot_matches") is True:
                snapshot_counts["current"] += 1
            elif evidence.get("snapshot_matches") is False:
                snapshot_counts["stale"] += 1
            elif not isinstance(snapshot, dict):
                snapshot_counts["missing"] += 1
            else:
                snapshot_counts["unchecked"] += 1
            class_name = str(element.get("class_name") or "unknown")
            class_counts = counts_by_class.setdefault(
                class_name,
                {"consistent": 0, "mismatch": 0, "unverifiable": 0},
            )
            class_counts[status] += 1
            if status != "consistent":
                attention.append({
                    "id": element["id"],
                    "class_name": class_name,
                    "review_status": element["review_status"],
                    "evidence": evidence,
                })

        return {
            "cloud_id": cloud_id,
            "candidate_count": len(elements),
            "status_counts": counts,
            "status_counts_by_class": dict(sorted(counts_by_class.items())),
            "source_snapshot_counts": snapshot_counts,
            "attention_count": len(attention),
            "accuracy_status": "not_measured",
            "candidates": attention,
        }

    # ------------------------------------------------------------ BIM / drawings
    @api.get("/clouds/{cloud_id}/bim")
    def bim_export(cloud_id: str, format: str = Query(default="json", pattern="^(json|ifc)$")):
        cloud = _cloud(cloud_id)
        project = _project(cloud["project_id"])
        elements = [el for el in list_elements(cloud_id) if el["review_status"] != "rejected"]
        meta = loads(cloud.get("metadata_json"), {})
        levels = (meta.get("recognition") or {}).get("levels", [])
        model = build_model(project, cloud, elements, levels)
        if format == "json":
            export_id, folder = new_export_dir(project["id"], f"bim_{cloud_id[:8]}")
            path = folder / "bim_model.json"
            path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
            return FileResponse(path, media_type="application/json", filename=path.name)
        export_id, folder = new_export_dir(project["id"], f"ifc_{cloud_id[:8]}")
        path = folder / "scan2bim_model.ifc"
        try:
            export_ifc(model, path, project_name=project["name"])
        except Exception as exc:  # IFC writer must not hide its error
            raise HTTPException(500, f"IFC export failed: {type(exc).__name__}: {exc}") from exc
        return FileResponse(path, media_type="application/octet-stream", filename=path.name)

    @api.get("/clouds/{cloud_id}/elements.dxf")
    def elements_dxf(cloud_id: str):
        cloud = _cloud(cloud_id)
        project = _project(cloud["project_id"])
        elements = list_elements(cloud_id)
        export_id, folder = new_export_dir(cloud["project_id"], f"elements_{cloud_id[:8]}")
        path = folder / "elements.dxf"
        export_elements_dxf(elements, path, project_name=project["name"])
        return FileResponse(path, media_type="application/dxf", filename=path.name)

    @api.get("/clouds/{cloud_id}/elements.dwg")
    def elements_dwg(cloud_id: str):
        cloud = _cloud(cloud_id)
        project = _project(cloud["project_id"])
        elements = list_elements(cloud_id)
        export_id, folder = new_export_dir(cloud["project_id"], f"elements_dwg_{cloud_id[:8]}")
        dxf_path = folder / "elements.dxf"
        export_elements_dxf(elements, dxf_path, project_name=project["name"])
        path = _dxf_to_dwg_or_409(dxf_path, folder / "elements.dwg")
        return FileResponse(path, media_type="application/acad", filename=path.name)

    # ------------------------------------------------------------ cleanup
    @api.post("/clouds/{cloud_id}/cleanup", response_model=JobOut)
    def cleanup_cloud(cloud_id: str, request: CleanupRequest):
        """Filter a cloud into a derived copy; the source stays untouched."""
        cloud = _cloud(cloud_id)
        if cloud["status"] != "ready":
            raise HTTPException(409, f"cloud is not ready (status: {cloud['status']})")
        paths = cloud_paths(cloud["project_id"], cloud["id"])
        if not paths["positions"].exists():
            raise HTTPException(409, "cloud positions are missing on disk")
        project_id = cloud["project_id"]
        derived_id = new_id()[:12]
        job_id = create_job("cleanup", project_id, cloud_id, "очистка облака")
        params = request.model_dump()
        method = params.pop("method")
        derived_dir = paths["dir"] / "derived" / derived_id

        def work(progress):
            result = apply_cleanup(
                paths["positions"],
                derived_dir,
                method,
                params,
                colors_path=paths["colors"],
                progress=progress,
            )
            result["derived_id"] = derived_id
            result["cloud_id"] = cloud_id
            dispatch_event(
                "cleanup.completed",
                {"job_id": job_id, "cloud_id": cloud_id, "derived_id": derived_id},
            )
            return result

        submit(job_id, work)
        dispatch_event("cleanup.started", {"job_id": job_id, "cloud_id": cloud_id})
        return get_job(job_id)

    @api.get("/clouds/{cloud_id}/derived")
    def list_derived(cloud_id: str):
        cloud = _cloud(cloud_id)
        base = cloud_paths(cloud["project_id"], cloud["id"])["dir"] / "derived"
        items = []
        if base.is_dir():
            for meta_path in sorted(base.glob("*/meta.json")):
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                meta["derived_id"] = meta_path.parent.name
                items.append(meta)
        return items

    @api.get("/clouds/{cloud_id}/derived/{derived_id}/download")
    def download_derived(
        cloud_id: str,
        derived_id: str,
        format: str = Query(default="ply", pattern="^(ply|xyz|npy)$"),
    ):
        cloud = _cloud(cloud_id)
        if len(derived_id) > 64 or not all(ch.isalnum() or ch in "-_" for ch in derived_id):
            raise HTTPException(404, "derived cloud not found")
        derived_dir = cloud_paths(cloud["project_id"], cloud["id"])["dir"] / "derived" / derived_id
        positions_path = derived_dir / "positions.npy"
        meta_path = derived_dir / "meta.json"
        if not positions_path.is_file() or not meta_path.is_file():
            raise HTTPException(404, "derived cloud not found")
        if format == "npy":
            return FileResponse(
                positions_path,
                media_type="application/octet-stream",
                filename=f"{cloud['name']}_{derived_id}.npy",
            )
        positions = np.load(positions_path, mmap_mode="r")
        colors_path = derived_dir / "colors.npy"
        colors = np.load(colors_path, mmap_mode="r") if colors_path.is_file() else None
        out_path = derived_dir / f"cloud.{format}"
        if not out_path.is_file():
            if format == "ply":
                write_ply(positions, colors, out_path)
            else:
                write_xyz(positions, out_path)
        media = "application/ply" if format == "ply" else "text/plain"
        return FileResponse(
            out_path,
            media_type=media,
            filename=f"{cloud['name']}_{derived_id}.{format}",
        )

    @api.post("/clouds/{cloud_id}/export")
    def export_cloud_endpoint(cloud_id: str, payload: CloudExportRequest):
        """Export the registered (or a derived) cloud to E57/LAS/LAZ/PLY/XYZ."""
        cloud = _cloud(cloud_id)
        if cloud["status"] != "ready":
            raise HTTPException(409, f"cloud is not ready (status: {cloud['status']})")
        paths = cloud_paths(cloud["project_id"], cloud["id"])
        if not paths["positions"].exists():
            raise HTTPException(409, "cloud positions are missing on disk")
        positions_path = paths["positions"]
        colors_path = paths["colors"] if paths["colors"].is_file() else None
        intensity_path = paths["intensity"] if paths["intensity"].is_file() else None
        if payload.derived_id:
            if len(payload.derived_id) > 64 or not all(
                ch.isalnum() or ch in "-_" for ch in payload.derived_id
            ):
                raise HTTPException(404, "derived cloud not found")
            derived_dir = paths["dir"] / "derived" / payload.derived_id
            if not (derived_dir / "positions.npy").is_file():
                raise HTTPException(404, "derived cloud not found")
            positions_path = derived_dir / "positions.npy"
            colors_path = derived_dir / "colors.npy" if (derived_dir / "colors.npy").is_file() else None
            intensity_path = None

        project_id = cloud["project_id"]
        export_id, folder = new_export_dir(project_id, f"cloud_{payload.format}_{cloud_id[:8]}")
        out_path = folder / f"cloud.{payload.format}"
        job_id = create_job("cloud_export", project_id, cloud_id, f"экспорт облака в {payload.format.upper()}")

        def work(progress):
            try:
                meta = export_cloud(
                    positions_path,
                    out_path,
                    payload.format,
                    colors_path=colors_path,
                    intensity_path=intensity_path,
                    progress=progress,
                    verify=payload.verify,
                )
            except CloudExportError as exc:
                raise ValueError(str(exc)) from exc
            meta.update({"export_id": export_id, "cloud_id": cloud_id, "path": str(out_path)})
            write_json_atomic(folder / "meta.json", meta)
            dispatch_event(
                "cloud.exported",
                {"job_id": job_id, "cloud_id": cloud_id, "export_id": export_id},
            )
            return meta

        submit(job_id, work)
        dispatch_event("cloud.export.started", {"job_id": job_id, "cloud_id": cloud_id})
        return get_job(job_id)

    @api.get("/clouds/{cloud_id}/exports")
    def list_cloud_exports(cloud_id: str):
        cloud = _cloud(cloud_id)
        base = project_dir(cloud["project_id"]) / "exports"
        items = []
        if base.is_dir():
            for meta_path in sorted(base.glob(f"cloud_*_{cloud_id[:8]}_*/meta.json")):
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                # Keep the public ID stable and usable by the download route;
                # the directory name also includes the descriptive prefix.
                meta.setdefault("export_id", meta_path.parent.name.rsplit("_", 1)[-1])
                items.append(meta)
        return items

    @api.get("/clouds/{cloud_id}/exports/{export_id}/download")
    def download_cloud_export(cloud_id: str, export_id: str):
        cloud = _cloud(cloud_id)
        if len(export_id) > 64 or not all(ch.isalnum() or ch in "-_" for ch in export_id):
            raise HTTPException(404, "export not found")
        base = project_dir(cloud["project_id"]) / "exports"
        folder = base / export_id
        if not (folder / "meta.json").is_file():
            # new_export_dir stores exports as ``<prefix>_<export_id>``; the job
            # result carries the bare id, so resolve by folder-name suffix.
            matches = [p.parent for p in base.glob(f"*_{export_id}/meta.json")]
            if len(matches) != 1:
                raise HTTPException(404, "export not found")
            folder = matches[0]
        meta_path = folder / "meta.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise HTTPException(404, "export not found") from exc
        out_path = folder / f"cloud.{meta.get('format', 'bin')}"
        if not out_path.is_file():
            raise HTTPException(404, "export file is missing on disk")
        fmt = meta.get("format", "bin")
        media = {
            "ply": "application/ply",
            "xyz": "text/plain",
            "las": "application/octet-stream",
            "laz": "application/octet-stream",
            "e57": "application/octet-stream",
        }.get(fmt, "application/octet-stream")
        return FileResponse(out_path, media_type=media, filename=out_path.name)


    @api.get("/clouds/{cloud_id}/structural-plan.dxf")
    def structural_plan_dxf(
        cloud_id: str,
        drawing_type: str = Query(default="columns", alias="type", pattern="^(columns|crane_girders)$"),
        issue_mode: str = Query(default="final", alias="issue", pattern="^(draft|final)$"),
    ):
        cloud = _cloud(cloud_id)
        project = _project(cloud["project_id"])
        elements = list_elements(cloud_id)
        export_id, folder = new_export_dir(cloud["project_id"], f"plan_{issue_mode}_{drawing_type}_{cloud_id[:8]}")
        path = folder / f"plan_{issue_mode}_{drawing_type}.dxf"
        export_structural_plan_dxf(
            elements,
            path,
            drawing_type=drawing_type,
            project_name=project["name"],
            column_types=_column_type_export_catalog(cloud["project_id"], elements) if drawing_type == "columns" else None,
            issue_mode=issue_mode,
        )
        return FileResponse(path, media_type="application/dxf", filename=path.name)

    @api.get("/clouds/{cloud_id}/structural-plan.pdf")
    def structural_plan_pdf(
        cloud_id: str,
        drawing_type: str = Query(default="columns", alias="type", pattern="^(columns|crane_girders)$"),
        scale: int = Query(default=100, ge=10, le=1000),
        issue_mode: str = Query(default="final", alias="issue", pattern="^(draft|final)$"),
    ):
        cloud = _cloud(cloud_id)
        project = _project(cloud["project_id"])
        elements = list_elements(cloud_id)
        export_id, folder = new_export_dir(cloud["project_id"], f"plan_{issue_mode}_{drawing_type}_{cloud_id[:8]}")
        path = folder / f"plan_{issue_mode}_{drawing_type}.pdf"
        try:
            export_structural_plan_pdf(
                elements,
                path,
                scale=scale,
                drawing_type=drawing_type,
                project_name=project["name"],
                column_types=_column_type_export_catalog(cloud["project_id"], elements) if drawing_type == "columns" else None,
                issue_mode=issue_mode,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return FileResponse(path, media_type="application/pdf", filename=path.name)

    @api.get("/clouds/{cloud_id}/spds-album.pdf")
    def spds_album_pdf(cloud_id: str):
        from ..cad.spds_full_set import generate_full_spds_album
        cloud = _cloud(cloud_id)
        project = _project(cloud["project_id"])
        elements = list_elements(cloud_id)
        export_id, folder = new_export_dir(cloud["project_id"], f"spds_album_{cloud_id[:8]}")
        manifest = generate_full_spds_album(
            elements=elements,
            output_dir=folder,
            project_title=project["name"],
        )
        album_path = Path(manifest["album_pdf_path"]) if Path(manifest["album_pdf_path"]).is_absolute() else folder / manifest["album_pdf_path"]
        return FileResponse(album_path, media_type="application/pdf", filename=album_path.name)

    @api.get("/clouds/{cloud_id}/spds-album.zip")
    def spds_album_zip(cloud_id: str):
        from ..cad.spds_full_set import generate_full_spds_album
        cloud = _cloud(cloud_id)
        project = _project(cloud["project_id"])
        elements = list_elements(cloud_id)
        export_id, folder = new_export_dir(cloud["project_id"], f"spds_album_{cloud_id[:8]}")
        manifest = generate_full_spds_album(
            elements=elements,
            output_dir=folder,
            project_title=project["name"],
        )
        zip_path = folder / "ALBUM_RD_KR_KM_SPDS.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for s in manifest["sheets"]:
                dxf_file = folder / s["dxf_path"] if not Path(s["dxf_path"]).is_absolute() else Path(s["dxf_path"])
                pdf_file = folder / s["pdf_path"] if not Path(s["pdf_path"]).is_absolute() else Path(s["pdf_path"])
                if dxf_file.exists():
                    zf.write(dxf_file, arcname=dxf_file.name)
                if pdf_file.exists():
                    zf.write(pdf_file, arcname=pdf_file.name)
                dwg_file = dxf_file.with_suffix(".dwg")
                if dwg_file.exists():
                    zf.write(dwg_file, arcname=dwg_file.name)
            alb_pdf = folder / manifest["album_pdf_path"] if not Path(manifest["album_pdf_path"]).is_absolute() else Path(manifest["album_pdf_path"])
            if alb_pdf.exists():
                zf.write(alb_pdf, arcname=alb_pdf.name)
            archive_manifest = dict(manifest)
            archive_manifest["album_pdf_path"] = Path(manifest["album_pdf_path"]).name
            archive_manifest["sheets"] = [
                {
                    **s,
                    "dxf_path": Path(s["dxf_path"]).name,
                    "pdf_path": Path(s["pdf_path"]).name,
                }
                for s in manifest["sheets"]
            ]
            zf.writestr("manifest.json", json.dumps(archive_manifest, ensure_ascii=False, indent=2))
        return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)

    # ------------------------------------------------------------ learning
    @api.get("/projects/{project_id}/samples", response_model=list[SampleOut])
    def get_samples(project_id: str):
        _project(project_id)
        # Keep invalidated synthetic rows in the database for audit, but don't
        # present them through the ordinary engineer-sample endpoint.
        return [sample for sample in list_samples(project_id)
                if sample.get("source") != INVALIDATED_SOURCE]

    @api.post("/projects/{project_id}/samples", response_model=SampleOut)
    def add_sample(project_id: str, payload: SampleCreate):
        _project(project_id)
        element = get_element(payload.element_id)
        if element["project_id"] != project_id:
            raise HTTPException(400, "element belongs to another project")
        if element["review_status"] not in {"confirmed", "corrected"}:
            raise HTTPException(409, "training samples require an explicitly reviewed element")
        if element.get("source") == "invalidated_synthetic_ground_truth":
            raise HTTPException(409, "invalidated synthetic ground truth cannot be used for training")
        if element["inferred"]:
            raise HTTPException(409, "training samples cannot use inferred geometry")
        label = payload.class_name or element["class_name"]
        if label != element["class_name"]:
            raise HTTPException(409, "training sample label must match the reviewed element class")
        physical_instance_id = _current_physical_instance_id(element["cloud_id"], element["id"])
        existing = next((sample for sample in list_samples(project_id)
            if sample.get("element_id") == element["id"]
            and sample.get("class_name") == label and sample.get("source") != "undone"), None)
        if existing:
            if physical_instance_id and not existing.get("physical_instance_id"):
                execute("UPDATE training_samples SET physical_instance_id=? WHERE id=?",
                        (physical_instance_id, existing["id"]))
                existing["physical_instance_id"] = physical_instance_id
            return existing
        try:
            sample = create_sample(
                project_id,
                element["cloud_id"],
                element,
                class_name=label,
                source="engineer",
                physical_instance_id=physical_instance_id,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return sample

    @api.post("/projects/{project_id}/train", response_model=ModelOut)
    def train(project_id: str, payload: TrainRequest):
        _project(project_id)
        try:
            model = train_candidate(
                project_id,
                name=payload.name,
                test_fraction=payload.test_fraction,
                min_test_samples=payload.min_test_samples,
                min_macro_f1=payload.min_macro_f1,
                notes=payload.notes,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        dispatch_event("model.trained", {"project_id": project_id, "model": model})
        return model

    @api.get("/models", response_model=list[ModelOut])
    def get_models():
        return list_models()

    @api.post("/models/{model_id}/activate", response_model=ModelOut)
    def activate_model(model_id: str, force: bool = False):
        try:
            model = activate(model_id, force=force)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        dispatch_event("model.activated", {"model": model})
        return model

    @api.post("/models/rollback", response_model=ModelOut)
    def rollback_model(name: str = Query(default="geometric-knn")):
        try:
            model = rollback(name)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        dispatch_event("model.rolled_back", {"model": model})
        return model

    @api.get("/projects/{project_id}/model-status")
    def model_status(project_id: str):
        _project(project_id)
        artifact = active_artifact()
        samples = samples_for_training(project_id)
        return {
            "samples": len(samples),
            "classes": sorted({s["class_name"] for s in samples}),
            "active_model": {
                "version": artifact.get("version"),
                "name": artifact.get("name"),
                "metrics": artifact.get("metrics"),
            }
            if artifact
            else None,
            "ml": ml_status().__dict__,
        }

    # ------------------------------------------------------------ webhooks / events / plugins
    @api.post("/webhooks")
    def add_webhook(payload: WebhookCreate):
        webhook_id = new_id()
        execute(
            "INSERT INTO webhooks (id,url,secret,events,active,created_at) VALUES (?,?,?,?,1,?)",
            (webhook_id, payload.url, payload.secret, payload.events, utcnow()),
        )
        return {"id": webhook_id, "url": payload.url, "events": payload.events}

    @api.get("/webhooks")
    def get_webhooks():
        return rows("SELECT id,url,events,active,created_at FROM webhooks ORDER BY created_at DESC")

    @api.get("/events")
    def get_events(limit: int = Query(default=50, ge=1, le=500)):
        records = rows("SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,))
        for record in records:
            record["payload"] = loads(record.pop("payload_json"), {})
        return records

    @api.get("/jobs/{job_id}", response_model=JobOut)
    def job_status(job_id: str):
        job = get_job(job_id)
        if not job:
            raise HTTPException(404, f"job {job_id} not found")
        return job

    @api.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        job = get_job(job_id)
        if not job:
            raise HTTPException(404, f"job {job_id} not found")
        requested = request_cancel(job_id)
        return {
            "job_id": job_id,
            "cancel_requested": requested,
            "status": "cancellation_requested" if requested else job["status"],
        }


    @api.get("/plugin/manifest")
    def plugin_manifest():
        return {
            "api_version": API_VERSION,
            "schema": "scan2bim.plugin/1.0",
            "capabilities": [
                "get-recognised-elements",
                "get-bim-model",
                "download-dxf",
                "send-feedback",
            ],
            "endpoints": {
                "elements": "/api/v1/clouds/{cloud_id}/elements",
                "bim_json": "/api/v1/clouds/{cloud_id}/bim?format=json",
                "ifc": "/api/v1/clouds/{cloud_id}/bim?format=ifc",
                "elements_dxf": "/api/v1/clouds/{cloud_id}/elements.dxf",
                "feedback": "/api/v1/elements/{element_id}/feedback",
                "sections": "/api/v1/clouds/{cloud_id}/sections",
            },
            "auth": "X-API-Key header when S2B_API_KEY is configured",
            "element_classes": [
                "wall",
                "column",
                "beam",
                "slab",
                "roof",
                "truss",
                "brace",
                "stair",
                "opening",
                "pipe",
                "duct",
                "equipment",
                "unknown",
            ],
        }

    @api.get("/plugin/cloud/{cloud_id}/model")
    def plugin_model(cloud_id: str):
        cloud = _cloud(cloud_id)
        project = _project(cloud["project_id"])
        meta = loads(cloud.get("metadata_json"), {})
        levels = (meta.get("recognition") or {}).get("levels", [])
        return build_model(project, cloud, list_elements(cloud_id), levels)

    @api.post("/demo")
    def create_demo():
        project_id = new_id()
        now = utcnow()
        execute(
            "INSERT INTO projects (id,name,description,units,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (
                project_id,
                "Demo room (synthetic)",
                "Synthetic 6 x 4 x 3 m room with 0.2 m walls and a 0.4 m column. Known ground truth.",
                "m",
                now,
                now,
            ),
        )
        demo_path = project_dir(project_id) / "demo_room.ply"
        truth = write_room_ply(demo_path, spacing=0.04)
        cloud_id = _cloud_row_from_import(project_id, "Demo room PLY", demo_path, "ply")
        job_id = create_job("ingest", project_id, cloud_id, "создание демонстрационного облака")
        submit(job_id, _ingest_work(project_id, cloud_id))
        return {"project": get_project(project_id), "cloud": _cloud_out(_cloud(cloud_id)), "truth": truth}

    app.include_router(api, prefix=f"/api/{API_VERSION}")
    from .desktop import router as desktop_router
    app.include_router(desktop_router, prefix=f"/api/{API_VERSION}")
    from .registration import router as registration_router
    app.include_router(registration_router, prefix=f"/api/{API_VERSION}")
    from .expert_agent import router as expert_agent_router
    app.include_router(expert_agent_router, prefix=f"/api/{API_VERSION}")
    from .lod import router as lod_router
    app.include_router(lod_router, prefix=f"/api/{API_VERSION}")

    # Serve a production frontend build when present (python backend/run.py).
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="ui")
    return app


app = create_app()
