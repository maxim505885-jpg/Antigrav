"""Local REST API (v1) for Intelligent Scan-to-BIM."""
from __future__ import annotations

import hmac
import json
import shutil
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
from ..cad.dxf import export_elements_dxf
from ..config import ALLOWED_ORIGINS, API_KEY, API_VERSION, MAX_INGEST_POINTS
from ..db import dumps, execute, init_db, loads, new_id, one, rows, utcnow
from ..demo import write_room_ply
from ..formats import RcsConversionRequired, detect_format, read_cloud, supported_formats
from ..formats.readers import rcs_guidance
from ..geometry import extract_section
from ..geometry.section import CloudGeometry
from ..ingest import ingest_cloud
from ..jobs import create_job, dispatch_event, get_job, submit
from ..learning.features import features_from_element
from ..learning.knn import KNNModel
from ..learning.registry import activate, list_models, rollback
from ..learning.store import create_sample, list_samples, similar_samples
from ..learning.training import active_artifact, apply_learned_prior, train_candidate
from ..recognition import detect_structures, ml_status
from ..recognition.geometric import DetectedElement
from ..schemas import (
    CloudImportPath,
    CloudOut,
    ElementOut,
    ElementPatch,
    FeedbackCreate,
    JobOut,
    ModelOut,
    ProjectCreate,
    ProjectOut,
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
)
from ..storage import (
    cloud_paths,
    ensure_cloud_dir,
    new_export_dir,
    project_dir,
    safe_filename,
    write_json_atomic,
)

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


def _cloud_out(row: dict[str, Any]) -> dict[str, Any]:
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
) -> str:
    cloud_id = new_id()
    now = utcnow()
    execute(
        """
        INSERT INTO clouds
        (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            cloud_id,
            project_id,
            name,
            str(source),
            fmt,
            int(source.stat().st_size) if source.exists() else 0,
            status,
            now,
            now,
        ),
    )
    return cloud_id


def _ingest_work(project_id: str, cloud_id: str):
    def work(progress):
        try:
            return ingest_cloud(project_id, cloud_id, Path(_cloud(cloud_id)["source_path"]), progress)
        except Exception as exc:  # keep the cloud row truthful on failure
            execute(
                "UPDATE clouds SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                (f"{type(exc).__name__}: {exc}", utcnow(), cloud_id),
            )
            raise

    return work


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


# ---------------------------------------------------------------- app


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
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
                "SELECT * FROM clouds WHERE project_id = ? ORDER BY created_at DESC",
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
                "RCS/RCP are not read in-process; an approved Autodesk conversion step is required.",
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
        if fmt in {"rcs", "rcp"}:
            # Native local reader (ReCap DLL, subprocess-isolated) is verified on
            # this machine; fall back to the documented guidance when it is absent.
            from scan2bim.formats.rcs_native import native_available

            if not native_available()["dll_exists"]:
                raise HTTPException(409, detail=rcs_guidance(source))
        name = payload.name or source.name
        cloud_id = _cloud_row_from_import(project_id, name, source.resolve(), fmt)
        job_id = create_job("ingest", project_id, cloud_id, f"reading {name}")
        submit(job_id, _ingest_work(project_id, cloud_id))
        return _cloud_out(_cloud(cloud_id))

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
        job_id = create_job("ingest", project_id, cloud_id, f"reading {filename}")
        submit(job_id, _ingest_work(project_id, cloud_id))
        return _cloud_out(_cloud(cloud_id))

    @api.get("/clouds/{cloud_id}", response_model=CloudOut)
    def get_cloud(cloud_id: str):
        return _cloud_out(_cloud(cloud_id))

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
            raise HTTPException(
                409,
                {
                    "summary": "DWG export requires an Autodesk-licensed converter.",
                    "steps": [
                        "Export DXF from this endpoint.",
                        "Open the DXF in AutoCAD and use SAVEAS → DWG (native).",
                        "Or run ODA File Converter on the DXF if it is licensed in your organisation.",
                    ],
                    "note": "DWG is not generated by an unlicensed third-party writer.",
                },
            )
        return FileResponse(path, media_type=media, filename=path.name)

    # ------------------------------------------------------------ recognition
    @api.post("/clouds/{cloud_id}/recognize", response_model=JobOut)
    def recognize(cloud_id: str):
        cloud = _cloud(cloud_id)
        geom = _cloud_geometry(cloud)
        project_id = cloud["project_id"]
        job_id = create_job("recognition", project_id, cloud_id, "recognising structures")
        project = _project(project_id)

        def work(progress):
            result = detect_structures(geom, progress)
            execute(
                "DELETE FROM elements WHERE cloud_id = ? AND source = 'geometric' AND review_status = 'unreviewed'",
                (cloud_id,),
            )
            created = []
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
                    "metadata": el.metadata,
                }
                element["features"] = features_from_element(element)
                created.append(element)
            apply_learned_prior(created)
            now = utcnow()
            for element in created:
                execute(
                    """
                    INSERT INTO elements
                    (id, project_id, cloud_id, parent_id, class_name, geometry_json, bbox_json,
                     confidence, confidence_kind, measured, inferred, source, review_status,
                     dimensions_json, metadata_json, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            }

        submit(job_id, work)
        dispatch_event("recognition.started", {"job_id": job_id, "cloud_id": cloud_id})
        return get_job(job_id)

    @api.get("/clouds/{cloud_id}/elements", response_model=list[ElementOut])
    def get_elements(cloud_id: str):
        _cloud(cloud_id)
        return list_elements(cloud_id)

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
                create_sample(updated["project_id"], updated["cloud_id"], updated, source="engineer")
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
                )
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        dispatch_event("element.feedback", {"element_id": element_id, "action": payload.action})
        return result

    @api.get("/elements/{element_id}/similar")
    def element_similar(element_id: str, k: int = Query(default=5, ge=1, le=20)):
        element = get_element(element_id)
        return similar_samples(element["project_id"], element["features"], k=k)

    @api.get("/elements/{element_id}/points")
    def element_points(element_id: str, limit: int = Query(default=8000, ge=100, le=50000)):
        from ..learning.store import extract_element_points

        element = get_element(element_id)
        points = extract_element_points(element["cloud_id"], element["bbox"], limit=limit)
        return {"count": int(len(points)), "points": points.round(3).tolist()}

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

    # ------------------------------------------------------------ learning
    @api.get("/projects/{project_id}/samples", response_model=list[SampleOut])
    def get_samples(project_id: str):
        _project(project_id)
        return list_samples(project_id)

    class SampleCreate(BaseModel):
        element_id: str
        class_name: str | None = None

    @api.post("/projects/{project_id}/samples", response_model=SampleOut)
    def add_sample(project_id: str, payload: SampleCreate):
        _project(project_id)
        element = get_element(payload.element_id)
        if element["project_id"] != project_id:
            raise HTTPException(400, "element belongs to another project")
        sample = create_sample(
            project_id,
            element["cloud_id"],
            element,
            class_name=payload.class_name or element["class_name"],
            source="engineer",
        )
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
        samples = list_samples(project_id)
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
        job_id = create_job("ingest", project_id, cloud_id, "creating demo cloud")
        submit(job_id, _ingest_work(project_id, cloud_id))
        return {"project": get_project(project_id), "cloud": _cloud_out(_cloud(cloud_id)), "truth": truth}

    app.include_router(api, prefix=f"/api/{API_VERSION}")

    # Serve a production frontend build when present (python backend/run.py).
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="ui")
    return app


app = create_app()
