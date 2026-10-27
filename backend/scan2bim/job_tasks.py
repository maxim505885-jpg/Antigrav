"""Handlers for serializable tasks that may run in a separate worker process."""
from __future__ import annotations

from typing import Any, Callable

from .db import execute, one, utcnow
from .jobs import JobCancelled
from .processing.cleanup import apply_cleanup
from .processing.cloud_export import EXPORT_FORMATS, CloudExportError, export_cloud
from .storage import cloud_paths, project_dir, write_json_atomic


def execute_job_task(
    task_type: str,
    payload: dict[str, Any],
    progress: Callable[[float, str], None],
) -> dict[str, Any]:
    """Run one serializable heavy job using the same domain services as the API."""
    import importlib

    if task_type == "ingest":
        api_module = importlib.import_module("scan2bim.api.app")
        return api_module._ingest_work(payload["project_id"], payload["cloud_id"])(progress)
    if task_type == "rcp_batch_ingest":
        api_module = importlib.import_module("scan2bim.api.app")
        return _run_rcp_batch(api_module, payload, progress)
    if task_type == "recognition":
        api_module = importlib.import_module("scan2bim.api.app")
        return api_module._recognition_work(
            str(payload["project_id"]), str(payload["cloud_id"])
        )(progress)
    if task_type == "panorama_render":
        panorama_module = importlib.import_module("scan2bim.api.panoramas")
        return panorama_module.render_station_panorama_job(payload, progress)
    if task_type == "cleanup":
        return _run_cleanup(payload, progress)
    if task_type == "cloud_export":
        return _run_cloud_export(payload, progress)
    raise ValueError(f"unknown headless job task type: {task_type}")


def execute_ingest_task(
    task_type: str,
    payload: dict[str, Any],
    progress: Callable[[float, str], None],
) -> dict[str, Any]:
    """Backward-compatible dispatcher for callers that only support ingest jobs."""
    if task_type not in {"ingest", "rcp_batch_ingest"}:
        raise ValueError(f"unsupported headless ingest task type: {task_type}")
    return execute_job_task(task_type, payload, progress)


def _ready_cloud(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    cloud_id = str(payload.get("cloud_id") or "")
    project_id = str(payload.get("project_id") or "")
    cloud = one("SELECT id, project_id, status FROM clouds WHERE id = ?", (cloud_id,))
    if not cloud or cloud["project_id"] != project_id:
        raise ValueError("worker cloud does not belong to the requested project")
    if cloud["status"] != "ready":
        raise ValueError(f"cloud is not ready (status: {cloud['status']})")
    paths = cloud_paths(project_id, cloud_id)
    if not paths["positions"].is_file():
        raise ValueError("cloud positions are missing on disk")
    return cloud, paths


def _valid_id(value: Any) -> str:
    item = str(value or "")
    if not item or len(item) > 64 or not all(ch.isalnum() or ch in "-_" for ch in item):
        raise ValueError("invalid task artifact id")
    return item


def _run_cleanup(payload: dict[str, Any], progress) -> dict[str, Any]:
    cloud, paths = _ready_cloud(payload)
    derived_id = _valid_id(payload.get("derived_id"))
    method = str(payload.get("method") or "")
    if method not in {"statistical", "radius", "voxel"}:
        raise ValueError("unsupported cleanup method")
    params = payload.get("params")
    if not isinstance(params, dict):
        raise ValueError("cleanup parameters must be an object")
    derived_dir = paths["dir"] / "derived" / derived_id
    result = apply_cleanup(
        paths["positions"],
        derived_dir,
        method,
        params,
        colors_path=paths["colors"],
        progress=progress,
    )
    result.update({"derived_id": derived_id, "cloud_id": cloud["id"]})
    from .jobs import dispatch_event

    dispatch_event(
        "cleanup.completed",
        {"job_id": str(payload.get("job_id") or ""), "cloud_id": cloud["id"], "derived_id": derived_id},
    )
    return result


def _run_cloud_export(payload: dict[str, Any], progress) -> dict[str, Any]:
    cloud, paths = _ready_cloud(payload)
    export_id = _valid_id(payload.get("export_id"))
    export_format = str(payload.get("format") or "")
    if export_format not in EXPORT_FORMATS:
        raise ValueError("unsupported cloud export format")
    positions_path = paths["positions"]
    colors_path = paths["colors"] if paths["colors"].is_file() else None
    intensity_path = paths["intensity"] if paths["intensity"].is_file() else None
    derived_id = payload.get("derived_id")
    if derived_id:
        derived_dir = paths["dir"] / "derived" / _valid_id(derived_id)
        positions_path = derived_dir / "positions.npy"
        if not positions_path.is_file():
            raise ValueError("derived cloud is not available for export")
        colors_path = derived_dir / "colors.npy" if (derived_dir / "colors.npy").is_file() else None
        intensity_path = None

    folder = project_dir(str(cloud["project_id"])) / "exports" / (
        f"cloud_{export_format}_{cloud['id'][:8]}_{export_id}"
    )
    folder.mkdir(parents=True, exist_ok=True)
    out_path = folder / f"cloud.{export_format}"
    try:
        meta = export_cloud(
            positions_path,
            out_path,
            export_format,
            colors_path=colors_path,
            intensity_path=intensity_path,
            progress=progress,
            verify=bool(payload.get("verify", True)),
        )
    except CloudExportError as exc:
        raise ValueError(str(exc)) from exc
    meta.update({"export_id": export_id, "cloud_id": cloud["id"], "path": str(out_path)})
    write_json_atomic(folder / "meta.json", meta)
    from .jobs import dispatch_event

    dispatch_event(
        "cloud.exported",
        {"job_id": str(payload.get("job_id") or ""), "cloud_id": cloud["id"], "export_id": export_id},
    )
    return meta


def _run_rcp_batch(api_module, payload: dict[str, Any], progress) -> dict[str, Any]:
    project_id = str(payload["project_id"])
    stations = payload.get("stations")
    if not isinstance(stations, list) or not stations:
        raise ValueError("RCP batch task requires at least one station")
    failed: list[dict[str, str]] = []
    total = len(stations)
    for index, station in enumerate(stations):
        if not isinstance(station, dict) or not station.get("cloud_id"):
            raise ValueError(f"invalid station payload at index {index}")
        label = str(station.get("node_name") or station.get("node_id") or "станция")
        cloud_id = str(station["cloud_id"])
        current = one("SELECT status FROM clouds WHERE id = ?", (cloud_id,)) or {}
        if current.get("status") == "ready":
            progress(
                (index + 1) / total,
                f"Станция {index + 1}/{total}: {label} — уже готова, пропуск",
            )
            continue
        try:
            node_work = api_module._ingest_work(project_id, cloud_id)
            node_work(lambda fraction, message="": progress(
                (index + max(0.0, min(1.0, float(fraction)))) / total,
                f"Станция {index + 1}/{total}: {label}" + (f" — {message}" if message else ""),
            ))
        except JobCancelled:
            for pending in stations[index + 1:]:
                execute(
                    "UPDATE clouds SET status='cancelled', error=NULL, updated_at=? "
                    "WHERE id=? AND status='processing'",
                    (utcnow(), pending["cloud_id"]),
                )
            raise
        except Exception as exc:  # continue independent stations; retain per-station errors
            failed.append({
                "node_id": str(station.get("node_id") or ""),
                "node_name": label,
                "error": f"{type(exc).__name__}: {exc}",
            })
    return {
        "status": "completed_with_failures" if failed else "completed",
        "node_count": total,
        "ready_count": total - len(failed),
        "failed_count": len(failed),
        "failures": failed,
        "station_cloud_ids": [str(station["cloud_id"]) for station in stations],
    }
