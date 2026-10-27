"""Station panorama API: real images, cloud-derived views, depth measurement.

Contract rules that this module must never break:

* A photograph is reported as a photograph, with its checksum and size. A view
  rendered from the cloud is reported as ``source="point_cloud"``.
* Measurement returns a distance only when the depth panorama rendered from the
  stored points actually has a sample in that direction. Otherwise the request
  fails with 422 and the reason — no distance is interpolated or invented.
* Uploaded images are stored inside the cloud directory; the original point
  cloud and its source file are untouched.
"""
from __future__ import annotations

import hashlib
import io
import json
import time
from pathlib import Path
from typing import Any, Literal

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from ..db import loads, one, rows, utcnow
from ..jobs import create_job, dispatch_event, get_job, submit_job_task
from ..processing.panorama import (
    DEFAULT_PANO_HEIGHT,
    DEFAULT_PANO_WIDTH,
    MAX_PANO_WIDTH,
    MAX_RENDER_POINTS,
    MAX_RENDER_RANGE_M,
    MIN_PANO_WIDTH,
    MIN_RENDER_RANGE_M,
    PANORAMA_RENDER_VERSION,
    measure_between,
    panorama_pick,
    render_cloud_panorama,
    render_cloud_panorama_streaming,
    station_catalog,
    station_points,
)
from ..storage import cloud_paths

router = APIRouter(tags=["panoramas"])

PANORAMA_DIRNAME = "panoramas"
MAX_PHOTO_BYTES = 64 * 1024 * 1024
MAX_PHOTO_PIXELS = 120_000_000
MIN_PHOTO_WIDTH = 1024
PHOTO_FORMATS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "TIFF": ".tif"}
PHOTO_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".tif": "image/tiff"}


class UvPoint(BaseModel):
    u: float = Field(..., ge=0.0, le=1.0, description="доля ширины панорамы, 0 — левый край")
    v: float = Field(..., ge=0.0, le=1.0, description="доля высоты панорамы, 0 — верх")


class PickRequest(UvPoint):
    width: int = Field(default=DEFAULT_PANO_WIDTH, ge=MIN_PANO_WIDTH, le=MAX_PANO_WIDTH)
    height: int = Field(default=DEFAULT_PANO_HEIGHT, ge=MIN_PANO_WIDTH // 2, le=MAX_PANO_WIDTH // 2)
    max_range_m: float = Field(default=60.0, ge=MIN_RENDER_RANGE_M, le=MAX_RENDER_RANGE_M)


class MeasureRequest(BaseModel):
    a: UvPoint
    b: UvPoint
    width: int = Field(default=DEFAULT_PANO_WIDTH, ge=MIN_PANO_WIDTH, le=MAX_PANO_WIDTH)
    height: int = Field(default=DEFAULT_PANO_HEIGHT, ge=MIN_PANO_WIDTH // 2, le=MAX_PANO_WIDTH // 2)
    max_range_m: float = Field(default=60.0, ge=MIN_RENDER_RANGE_M, le=MAX_RENDER_RANGE_M)


def _cloud_row(cloud_id: str) -> dict[str, Any]:
    row = one("SELECT * FROM clouds WHERE id = ?", (cloud_id,))
    if not row:
        raise HTTPException(404, f"cloud {cloud_id} not found")
    return row


def _require_ready(row: dict[str, Any]) -> None:
    if row["status"] != "ready":
        raise HTTPException(
            409,
            detail={
                "summary": "Облако ещё не импортировано, панорамы недоступны.",
                "cloud_status": row["status"],
                "message": "Дождитесь окончания импорта точек и повторите запрос.",
            },
        )


def _station_dir(row: dict[str, Any], station_id: str) -> Path:
    paths = cloud_paths(row["project_id"], row["id"])
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in station_id).strip("._")
    if not safe:
        raise HTTPException(422, "station id contains no usable characters")
    return paths["dir"] / PANORAMA_DIRNAME / safe


def _stations(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Station catalogue, cached against the stored positions file signature.

    Anchoring reads real point rows, which is expensive on a 300M-point cloud,
    so the result is cached and the cache key is the file size/mtime signature.
    """
    paths = cloud_paths(row["project_id"], row["id"])
    positions = paths["positions"]
    if not positions.is_file():
        raise HTTPException(409, "positions.npy отсутствует: облако не импортировано")
    metadata = loads(row.get("metadata_json"), {}) or {}
    stat = positions.stat()
    key = f"{stat.st_size}:{stat.st_mtime_ns}"
    cache_path = paths["dir"] / "stations_catalog.json"
    if cache_path.is_file():
        cached = loads(cache_path.read_text(encoding="utf-8"), None)
        if isinstance(cached, dict) and cached.get("cache_key") == key and isinstance(cached.get("stations"), list):
            return cached["stations"]
    try:
        entries = station_catalog(positions, metadata)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(409, f"метаданные станций некорректны: {exc}") from exc
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"cache_key": key, "stations": entries}, ensure_ascii=False, indent=2), encoding="utf-8")
    return entries


def _station(row: dict[str, Any], station_id: str) -> dict[str, Any]:
    for entry in _stations(row):
        if entry["station_id"] == station_id:
            return entry
    raise HTTPException(404, f"станция {station_id} не найдена в облаке {row['id']}")


def _photo_meta(directory: Path) -> dict[str, Any] | None:
    meta_path = directory / "photo.json"
    if not meta_path.is_file():
        return None
    try:
        meta = loads(meta_path.read_text(encoding="utf-8"), None)
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict) or not meta.get("file"):
        return None
    if not (directory / meta["file"]).is_file():
        return None
    return meta


def _cache_key(positions: Path, width: int, height: int, max_range_m: float, renderer: str) -> str:
    stat = positions.stat()
    return (
        f"{PANORAMA_RENDER_VERSION}:{renderer}:{stat.st_size}:{stat.st_mtime_ns}:"
        f"{width}x{height}:{max_range_m:.2f}"
    )


def _cached_cloud_panorama(
    row: dict[str, Any],
    entry: dict[str, Any],
    width: int,
    height: int,
    max_range_m: float,
) -> dict[str, Any] | None:
    paths = cloud_paths(row["project_id"], row["id"])
    positions = paths["positions"]
    directory = _station_dir(row, entry["station_id"])
    meta_path = directory / "cloud_panorama.json"
    depth_path = directory / "depth.npy"
    png_path = directory / "cloud_panorama.png"
    if not (meta_path.is_file() and depth_path.is_file() and png_path.is_file()):
        return None
    streaming = int(entry["point_count"]) > MAX_RENDER_POINTS
    key = _cache_key(positions, width, height, max_range_m, "streaming" if streaming else "sampled")
    try:
        cached = loads(meta_path.read_text(encoding="utf-8"), None)
        depth = np.load(depth_path, mmap_mode="r")
    except (OSError, ValueError):
        return None
    if not isinstance(cached, dict) or cached.get("cache_key") != key or depth.shape != (height, width):
        return None
    return cached


def _render_depth(
    row: dict[str, Any],
    entry: dict[str, Any],
    width: int,
    height: int,
    max_range_m: float,
    progress=None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Render (or reuse) the cloud panorama and return its depth map."""
    paths = cloud_paths(row["project_id"], row["id"])
    positions = paths["positions"]
    directory = _station_dir(row, entry["station_id"])
    directory.mkdir(parents=True, exist_ok=True)
    # A station larger than the projection budget is rendered in full resolution
    # by streaming blocks instead of subsampling it, which used to leave at most
    # a quarter of the sheet covered on a 300M-point cloud.
    streaming = int(entry["point_count"]) > MAX_RENDER_POINTS
    renderer = "streaming" if streaming else "sampled"
    key = _cache_key(positions, width, height, max_range_m, renderer)
    meta_path = directory / "cloud_panorama.json"
    depth_path = directory / "depth.npy"
    png_path = directory / "cloud_panorama.png"

    cached = _cached_cloud_panorama(row, entry, width, height, max_range_m)
    if cached is not None:
        return np.load(depth_path), cached

    origin = np.asarray((loads(row.get("metadata_json"), {}) or {}).get("origin") or [0.0, 0.0, 0.0], dtype=np.float64)
    anchor_local = np.asarray(entry["anchor_local"], dtype=np.float64)
    if anchor_local.shape != (3,):
        raise HTTPException(409, "точка обзора станции некорректна")
    if not np.isfinite(anchor_local).all():
        raise HTTPException(409, "точка обзора станции содержит нечисловые координаты")

    colors_path = paths["colors"].is_file()
    render_started = time.perf_counter()
    try:
        if streaming:
            rendered = render_cloud_panorama_streaming(
                positions,
                entry,
                width=width,
                height=height,
                max_range_m=max_range_m,
                colors_path=paths["colors"] if colors_path else None,
                progress=(lambda fraction, message: progress(0.08 + 0.84 * fraction, message))
                if progress is not None else None,
            )
        else:
            points, step = station_points(positions, entry)
            colors = None
            if colors_path:
                colors_array = np.load(paths["colors"], mmap_mode="r")
                start, end = int(entry["row_start"]), int(entry["row_end"])
                sliced = np.asarray(colors_array[start:end:step])
                if len(sliced) == len(points):
                    colors = sliced
                del colors_array
            rendered = render_cloud_panorama(
                points,
                anchor_local,
                width=width,
                height=height,
                max_range_m=max_range_m,
                colors=colors,
            )
    except ValueError as exc:
        raise HTTPException(422, f"не удалось построить панораму: {exc}") from exc
    render_seconds = time.perf_counter() - render_started

    Image.fromarray(rendered["rgb"], mode="RGB").save(png_path, format="PNG", optimize=False)
    np.save(depth_path, rendered["depth"].astype(np.float32))

    meta = {
        "cache_key": key,
        "station_id": entry["station_id"],
        "source": "point_cloud",
        "is_photograph": False,
        "width": width,
        "height": height,
        "max_range_m": max_range_m,
        "anchor": entry["anchor"],
        "anchor_local": [float(v) for v in anchor_local],
        "anchor_kind": entry["anchor_kind"],
        "anchor_note": (
            "Точка обзора — измеренный центр точек станции, а не оптический центр сканера: "
            "читатели форматов его не сохраняют."
        ),
        "coverage": rendered["coverage"],
        "rendered_points": rendered["rendered_points"],
        "source_points": rendered["source_points"],
        "stride": rendered["stride"],
        "renderer": renderer,
        "renderer_version": PANORAMA_RENDER_VERSION,
        "full_resolution": bool(rendered.get("full_resolution", False)),
        "points_examined": int(rendered.get("points_examined", 0)),
        "station_points": int(rendered.get("station_points", entry["point_count"])),
        "beyond_range_points": int(rendered.get("beyond_range_points", 0)),
        "render_seconds": round(render_seconds, 2),
        "color_source": rendered["color_source"],
        "coverage_note": (
            "Доля пикселей, по которым измерены точки. Пустое направление не заполняется "
            "выдуманной геометрией: там нет данных."
        ),
        "rendered_at": utcnow(),
        "origin": [float(v) for v in origin],
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return rendered["depth"], meta


def render_station_panorama_job(payload: dict[str, Any], progress) -> dict[str, Any]:
    """Serializable worker entry point for expensive point-cloud panorama renders."""
    cloud_id = str(payload.get("cloud_id") or "")
    station_id = str(payload.get("station_id") or "")
    row = _cloud_row(cloud_id)
    _require_ready(row)
    entry = _station(row, station_id)
    width = int(payload.get("width", DEFAULT_PANO_WIDTH))
    height = int(payload.get("height", DEFAULT_PANO_HEIGHT))
    max_range_m = float(payload.get("max_range_m", 60.0))
    progress(0.03, "Подготовка панорамы")
    _, meta = _render_depth(row, entry, width, height, max_range_m, progress=progress)
    progress(0.97, "Сохраняю глубину и метаданные панорамы")
    dispatch_event(
        "panorama.rendered",
        {"cloud_id": cloud_id, "station_id": station_id, "rendered_at": meta.get("rendered_at")},
    )
    return {"cloud_id": cloud_id, "station_id": station_id, "panorama": meta}


@router.get("/clouds/{cloud_id}/stations")
def list_stations(cloud_id: str) -> dict[str, Any]:
    """List the stations of a cloud with their anchors and available imagery."""
    row = _cloud_row(cloud_id)
    _require_ready(row)
    entries = _stations(row)
    result = []
    for entry in entries:
        directory = _station_dir(row, entry["station_id"])
        photo = _photo_meta(directory) if directory.is_dir() else None
        cloud_meta_path = directory / "cloud_panorama.json"
        cloud_meta = None
        if cloud_meta_path.is_file():
            cloud_meta = loads(cloud_meta_path.read_text(encoding="utf-8"), None)
        result.append(
            {
                "station_id": entry["station_id"],
                "name": entry["name"],
                "point_count": entry["point_count"],
                "station_source": entry["station_source"],
                "anchor": entry["anchor"],
                "anchor_kind": entry["anchor_kind"],
                "bbox_min": entry["bbox_min"],
                "bbox_max": entry["bbox_max"],
                "photo": photo,
                "has_photo": photo is not None,
                "cloud_panorama": cloud_meta,
                "has_cloud_panorama": cloud_meta is not None,
                "panorama_url": f"/api/v1/clouds/{cloud_id}/stations/{entry['station_id']}/panorama",
                "measure_supported": True,
            }
        )
    return {"cloud_id": cloud_id, "count": len(result), "stations": result}


@router.post("/clouds/{cloud_id}/stations/{station_id}/panorama/render")
def request_cloud_panorama_render(
    cloud_id: str,
    station_id: str,
    width: int = Query(default=DEFAULT_PANO_WIDTH, ge=MIN_PANO_WIDTH, le=MAX_PANO_WIDTH),
    height: int = Query(default=DEFAULT_PANO_HEIGHT, ge=MIN_PANO_WIDTH // 2, le=MAX_PANO_WIDTH // 2),
    max_range_m: float = Query(default=60.0, ge=MIN_RENDER_RANGE_M, le=MAX_RENDER_RANGE_M),
) -> dict[str, Any]:
    """Queue an expensive cloud panorama render; photographs remain immediately served."""
    row = _cloud_row(cloud_id)
    _require_ready(row)
    entry = _station(row, station_id)
    cached = _cached_cloud_panorama(row, entry, width, height, max_range_m)
    if cached is not None:
        return {"status": "ready", "panorama": cached}

    payload = {
        "cloud_id": cloud_id,
        "station_id": station_id,
        "width": width,
        "height": height,
        "max_range_m": max_range_m,
    }
    # Reuse an active job for the same render request instead of rendering the
    # same 300M-point station twice when two viewers open it together.
    for job in rows(
        "SELECT id, task_payload_json FROM jobs WHERE type = 'panorama_render' "
        "AND status IN ('queued', 'running')"
    ):
        try:
            task = loads(job.get("task_payload_json") or "{}", {})
            if task.get("task_type") == "panorama_render" and task.get("payload") == payload:
                existing = get_job(job["id"])
                if existing is not None:
                    return {"status": "queued", "job": existing}
        except (AttributeError, TypeError, ValueError):
            continue

    job_id = create_job(
        "panorama_render", row["project_id"], cloud_id,
        f"панорама {station_id}",
    )
    submit_job_task(job_id, "panorama_render", payload)
    job = get_job(job_id)
    return {"status": "queued", "job": job}


@router.get("/clouds/{cloud_id}/stations/{station_id}/panorama")
def get_panorama(
    cloud_id: str,
    station_id: str,
    source: Literal["auto", "photo", "cloud"] = Query(default="auto"),
    width: int = Query(default=DEFAULT_PANO_WIDTH, ge=MIN_PANO_WIDTH, le=MAX_PANO_WIDTH),
    height: int = Query(default=DEFAULT_PANO_HEIGHT, ge=MIN_PANO_WIDTH // 2, le=MAX_PANO_WIDTH // 2),
    max_range_m: float = Query(default=60.0, ge=MIN_RENDER_RANGE_M, le=MAX_RENDER_RANGE_M),
) -> FileResponse:
    """Serve the station panorama: the uploaded photograph when present, else the cloud view."""
    row = _cloud_row(cloud_id)
    _require_ready(row)
    entry = _station(row, station_id)
    directory = _station_dir(row, station_id)
    photo = _photo_meta(directory) if directory.is_dir() else None

    if source in {"auto", "photo"} and photo is not None:
        path = directory / photo["file"]
        return FileResponse(
            path,
            media_type=PHOTO_MEDIA.get(Path(photo["file"]).suffix.lower(), "application/octet-stream"),
            filename=path.name,
            headers={
                "X-Panorama-Source": "photo",
                "X-Panorama-Checksum": photo.get("sha256", ""),
            },
        )
    if source == "photo":
        raise HTTPException(404, "для этой станции фотопанорама не загружена")

    _, meta = _render_depth(row, entry, width, height, max_range_m)
    path = directory / "cloud_panorama.png"
    return FileResponse(
        path,
        media_type="image/png",
        filename=f"{station_id}_cloud_panorama.png",
        headers={
            "X-Panorama-Source": "point_cloud",
            "X-Panorama-Coverage": f"{meta.get('coverage', 0.0):.4f}",
        },
    )


@router.post("/clouds/{cloud_id}/stations/{station_id}/photo")
def upload_photo(
    cloud_id: str,
    station_id: str,
    file: UploadFile = File(...),
    yaw_offset_deg: float = Form(default=0.0),
) -> dict[str, Any]:
    """Attach a real equirectangular photograph to a station (2:1, >=1024 px wide)."""
    row = _cloud_row(cloud_id)
    _require_ready(row)
    entry = _station(row, station_id)
    if not (-360.0 <= yaw_offset_deg <= 360.0):
        raise HTTPException(422, "yaw_offset_deg должен быть в пределах ±360")

    payload = file.file.read(MAX_PHOTO_BYTES + 1)
    if not payload:
        raise HTTPException(422, "пустой файл")
    if len(payload) > MAX_PHOTO_BYTES:
        raise HTTPException(413, f"файл больше {MAX_PHOTO_BYTES // (1024 * 1024)} МБ")

    try:
        with Image.open(io.BytesIO(payload)) as image:
            image_format = (image.format or "").upper()
            width, height = image.size
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(422, f"файл не является изображением: {exc}") from exc

    if image_format not in PHOTO_FORMATS:
        raise HTTPException(422, f"формат {image_format or 'неизвестен'} не поддерживается: нужен PNG, JPEG, WEBP или TIFF")
    if width * height > MAX_PHOTO_PIXELS:
        raise HTTPException(413, "изображение слишком большое по числу пикселей")
    if width < MIN_PHOTO_WIDTH:
        raise HTTPException(422, f"ширина панорамы меньше {MIN_PHOTO_WIDTH} px")
    aspect = width / float(height)
    if not 1.85 <= aspect <= 2.15:
        raise HTTPException(
            422,
            f"соотношение сторон {aspect:.2f}:1 не панорамное; нужна эквидистантная (equirectangular) панорама 2:1",
        )

    directory = _station_dir(row, station_id)
    directory.mkdir(parents=True, exist_ok=True)
    suffix = PHOTO_FORMATS[image_format]
    for stale in directory.glob("photo.*"):
        stale.unlink(missing_ok=True)
    target = directory / f"photo{suffix}"
    target.write_bytes(payload)
    meta = {
        "file": target.name,
        "source": "photo",
        "is_photograph": True,
        "original_filename": file.filename,
        "format": image_format,
        "width": width,
        "height": height,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "projection": "equirectangular",
        "yaw_offset_deg": yaw_offset_deg,
        "station_id": station_id,
        "uploaded_at": utcnow(),
    }
    (directory / "photo.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "stored", "station_id": station_id, "photo": meta}


@router.delete("/clouds/{cloud_id}/stations/{station_id}/photo")
def delete_photo(cloud_id: str, station_id: str) -> dict[str, Any]:
    """Remove the uploaded photograph; the cloud-derived panorama stays available."""
    row = _cloud_row(cloud_id)
    _require_ready(row)
    _station(row, station_id)
    directory = _station_dir(row, station_id)
    removed = False
    if directory.is_dir():
        for path in list(directory.glob("photo.*")) + [directory / "photo.json"]:
            if path.is_file():
                path.unlink()
                removed = True
    if not removed:
        raise HTTPException(404, "фотопанорама не найдена")
    return {"status": "deleted", "station_id": station_id}


@router.post("/clouds/{cloud_id}/stations/{station_id}/pick")
def pick(cloud_id: str, station_id: str, request: PickRequest) -> dict[str, Any]:
    """Resolve one panorama pixel to a measured 3D point through the cloud depth."""
    row = _cloud_row(cloud_id)
    _require_ready(row)
    entry = _station(row, station_id)
    depth, meta = _render_depth(row, entry, request.width, request.height, request.max_range_m)
    try:
        result = panorama_pick(depth, np.asarray(entry["anchor_local"], dtype=np.float64), request.u, request.v)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    result["station_id"] = station_id
    if result["resolved"]:
        # The depth pick is in the cloud's local frame; the API reports world
        # coordinates and keeps the local one alongside for verification.
        origin = np.asarray(meta.get("origin") or [0.0, 0.0, 0.0], dtype=np.float64)
        local = np.asarray(result["point"], dtype=np.float64)
        result["point_local"] = [float(v) for v in local]
        result["point"] = [float(v) for v in local + origin]
    return result


@router.post("/clouds/{cloud_id}/stations/{station_id}/measure")
def measure(cloud_id: str, station_id: str, request: MeasureRequest) -> dict[str, Any]:
    """Measure the distance between two panorama pixels using cloud depth."""
    row = _cloud_row(cloud_id)
    _require_ready(row)
    entry = _station(row, station_id)
    depth, meta = _render_depth(row, entry, request.width, request.height, request.max_range_m)
    anchor = np.asarray(entry["anchor_local"], dtype=np.float64)
    result = measure_between(depth, anchor, (request.a.u, request.a.v), (request.b.u, request.b.v))
    if not result["resolved"]:
        raise HTTPException(
            422,
            detail={
                "summary": "Замер невозможен: в этих направлениях нет точек облака.",
                "reason": result.get("reason"),
                "a": result["a"],
                "b": result["b"],
                "message": "Поверните панораму к участку с точками или выберите другую станцию.",
            },
        )
    origin = np.asarray(meta.get("origin") or [0.0, 0.0, 0.0], dtype=np.float64)
    for key in ("a", "b"):
        # Keep the cloud-frame point alongside the world one, exactly as /pick
        # does, so a caller can verify a measurement without inverting a shift.
        local = np.asarray(result[key]["point"], dtype=np.float64)
        result[key]["point_local"] = [float(v) for v in local]
        result[key]["point"] = [float(v) for v in local + origin]
    result["station_id"] = station_id
    return result
