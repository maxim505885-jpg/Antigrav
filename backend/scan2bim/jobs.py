"""Background jobs, progress and webhook delivery."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import traceback
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .db import db, dumps, execute, new_id, one, record_event, rows, utcnow

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="s2b-job")
_cancel_lock = threading.Lock()
_cancel_events: dict[str, threading.Event] = {}


class JobCancelled(Exception):
    """Raised at a cooperative cancellation point in a background job."""


class JobLeaseLost(Exception):
    """Raised when another worker has reclaimed a task after its lease expired."""


def create_job(
    job_type: str,
    project_id: str | None = None,
    cloud_id: str | None = None,
    message: str = "queued",
) -> str:
    job_id = new_id()
    now = utcnow()
    execute(
        """
        INSERT INTO jobs (id, project_id, cloud_id, type, status, progress, message, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (job_id, project_id, cloud_id, job_type, "queued", 0.0, message, now, now),
    )
    return job_id


def update_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: float | None = None,
    message: str | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    worker_id: str | None = None,
) -> None:
    fields = ["updated_at = ?"]
    values: list[Any] = [utcnow()]
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if progress is not None:
        fields.append("progress = ?")
        values.append(max(0.0, min(1.0, float(progress))))
    if message is not None:
        fields.append("message = ?")
        values.append(message)
    if result is not None:
        fields.append("result_json = ?")
        values.append(dumps(result))
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    if worker_id and status in {"succeeded", "failed", "cancelled"}:
        fields.extend(["worker_id = NULL", "lease_expires_at = NULL"])
    values.append(job_id)
    where = "id = ?"
    if worker_id:
        where += " AND worker_id = ?"
        values.append(worker_id)
    execute(f"UPDATE jobs SET {', '.join(fields)} WHERE {where}", tuple(values))


def get_job(job_id: str) -> dict[str, Any] | None:
    row = one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if not row:
        return None
    try:
        result = json.loads(row.get("result_json") or "{}")
    except Exception:
        result = {}
    row["result"] = result
    row.pop("result_json", None)
    return row


def _worker_mode() -> bool:
    return os.environ.get("S2B_INGEST_MODE", "local").strip().lower() == "worker"


_HEADLESS_TASK_TYPES = {
    "ingest", "rcp_batch_ingest", "recognition", "cleanup", "cloud_export", "panorama_render",
}


def submit_job_task(job_id: str, task_type: str, payload: dict[str, Any]) -> None:
    """Submit a serializable heavy job locally or persist it for a headless worker."""
    if task_type not in _HEADLESS_TASK_TYPES:
        raise ValueError(f"unsupported headless job task type: {task_type}")
    task = {"task_type": task_type, "payload": payload}
    encoded = dumps(task)
    if _worker_mode():
        execute(
            "UPDATE jobs SET task_payload_json = ?, cancel_requested = 0, updated_at = ? WHERE id = ?",
            (encoded, utcnow(), job_id),
        )
        return
    cancel_event = threading.Event()
    with _cancel_lock:
        _cancel_events[job_id] = cancel_event
    _executor.submit(_run, job_id, _task_callable(task), cancel_event)


def submit_ingest_task(job_id: str, task_type: str, payload: dict[str, Any]) -> None:
    """Backward-compatible submitter for point-cloud ingestion tasks."""
    if task_type not in {"ingest", "rcp_batch_ingest"}:
        raise ValueError(f"unsupported headless ingest task type: {task_type}")
    submit_job_task(job_id, task_type, payload)


def _task_callable(task: dict[str, Any]):
    def work(progress):
        from .job_tasks import execute_job_task

        return execute_job_task(task["task_type"], task["payload"], progress)

    return work


def claim_next_ingest_job(worker_id: str, lease_seconds: int = 120) -> dict[str, Any] | None:
    """Atomically claim one queued ingest job or one whose worker lease expired."""
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat(timespec="seconds")
    lease_until = (now_dt + timedelta(seconds=max(30, int(lease_seconds)))).isoformat(timespec="seconds")
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            """SELECT id FROM jobs
               WHERE task_payload_json IS NOT NULL AND cancel_requested = 0
                 AND (status = 'queued'
                      OR (status = 'running' AND (lease_expires_at IS NULL OR lease_expires_at <= ?)))
               ORDER BY created_at, id LIMIT 1""",
            (now,),
        ).fetchone()
        if row is None:
            return None
        job_id = row["id"]
        con.execute(
            """UPDATE jobs SET status = 'running', worker_id = ?, lease_expires_at = ?,
                      attempts = attempts + 1, updated_at = ?
               WHERE id = ? AND task_payload_json IS NOT NULL AND cancel_requested = 0
                 AND (status = 'queued'
                      OR (status = 'running' AND (lease_expires_at IS NULL OR lease_expires_at <= ?)))""",
            (worker_id, lease_until, now, job_id, now),
        )
        claimed = con.execute("SELECT * FROM jobs WHERE id = ? AND worker_id = ?", (job_id, worker_id)).fetchone()
        return dict(claimed) if claimed else None


def renew_job_lease(job_id: str, worker_id: str, lease_seconds: int = 120) -> bool:
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat(timespec="seconds")
    lease_until = (now_dt + timedelta(seconds=max(30, int(lease_seconds)))).isoformat(timespec="seconds")
    with db() as con:
        cursor = con.execute(
            """UPDATE jobs SET lease_expires_at = ?, updated_at = ?
               WHERE id = ? AND worker_id = ? AND status = 'running'""",
            (lease_until, now, job_id, worker_id),
        )
        return cursor.rowcount == 1


def _post_webhook(url: str, secret: str, payload: bytes) -> None:
    headers = {"Content-Type": "application/json", "User-Agent": "Intelligent-Scan-to-BIM/0.1"}
    if secret:
        headers["X-S2B-Signature"] = "sha256=" + hmac.new(
            secret.encode("utf-8"), payload, hashlib.sha256
        ).hexdigest()
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read(1)
    except Exception:
        pass


def dispatch_event(event_type: str, payload: dict[str, Any]) -> str:
    event_id = record_event(event_type, payload)
    try:
        endpoints = rows("SELECT * FROM webhooks WHERE active = 1")
    except Exception:
        endpoints = []
    body = json.dumps(
        {"event": event_type, "event_id": event_id, "payload": payload}, ensure_ascii=False
    ).encode("utf-8")
    for endpoint in endpoints:
        events = (endpoint.get("events") or "*").split(",")
        if "*" not in events and event_type not in [e.strip() for e in events]:
            continue
        threading.Thread(
            target=_post_webhook,
            args=(endpoint["url"], endpoint.get("secret", ""), body),
            daemon=True,
        ).start()
    return event_id


def submit(job_id: str, fn: Callable[[Callable[[float, str], None]], dict[str, Any]]) -> None:
    cancel_event = threading.Event()
    with _cancel_lock:
        _cancel_events[job_id] = cancel_event
    _executor.submit(_run, job_id, fn, cancel_event)


def request_cancel(job_id: str) -> bool:
    """Request cancellation for a queued/running job; work stops at its next progress checkpoint."""
    job = get_job(job_id)
    if not job or job["status"] not in {"queued", "running"}:
        return False
    with _cancel_lock:
        cancel_event = _cancel_events.get(job_id)
        if cancel_event is None:
            persisted = one("SELECT task_payload_json FROM jobs WHERE id = ?", (job_id,)) or {}
            if persisted.get("task_payload_json") is None:
                return False
            if job["status"] == "queued":
                update_job(job_id, status="cancelled", message="отменено")
                execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ?", (job_id,))
                dispatch_event("job.cancelled", {"job": get_job(job_id) or {}})
                return True
            execute("UPDATE jobs SET cancel_requested = 1, updated_at = ? WHERE id = ?", (utcnow(), job_id))
            return True
        cancel_event.set()
    return True


def _run(job_id: str, fn, cancel_event: threading.Event, worker_id: str | None = None) -> None:
    if worker_id:
        owner = one("SELECT worker_id FROM jobs WHERE id = ?", (job_id,)) or {}
        if owner.get("worker_id") != worker_id:
            return
    update_job(job_id, status="running", progress=0.01, message="запущено", worker_id=worker_id)
    heartbeat_stop = threading.Event()
    heartbeat = None
    if worker_id:
        def renew() -> None:
            while not heartbeat_stop.wait(30):
                if not renew_job_lease(job_id, worker_id):
                    return

        heartbeat = threading.Thread(target=renew, name=f"s2b-heartbeat-{job_id[:8]}", daemon=True)
        heartbeat.start()

    def progress(value: float, message: str = "") -> None:
        current = one("SELECT cancel_requested, worker_id FROM jobs WHERE id = ?", (job_id,)) or {}
        if worker_id and current.get("worker_id") != worker_id:
            raise JobLeaseLost("worker lease was reclaimed")
        if cancel_event.is_set() or current.get("cancel_requested"):
            raise JobCancelled("job cancellation requested")
        update_job(job_id, progress=value, message=message or None, worker_id=worker_id)
        if worker_id:
            renew_job_lease(job_id, worker_id)

    try:
        if cancel_event.is_set():
            raise JobCancelled("job cancellation requested")
        result = fn(progress) or {}
        if cancel_event.is_set():
            raise JobCancelled("job cancellation requested")
    except JobCancelled:
        update_job(job_id, status="cancelled", message="отменено", error=None, worker_id=worker_id)
        job = get_job(job_id) or {}
        dispatch_event("job.cancelled", {"job": job})
    except JobLeaseLost:
        return
    except Exception as exc:  # noqa: BLE001 - job boundary must capture everything
        message = f"{type(exc).__name__}: {exc}"
        update_job(
            job_id,
            status="failed",
            message="ошибка",
            error=message + "\n" + traceback.format_exc(limit=8),
            worker_id=worker_id,
        )
        job = get_job(job_id) or {}
        dispatch_event("job.failed", {"job": job, "error": message})
    else:
        if result.get("status") == "completed_with_failures":
            failed_count = int(result.get("failed_count") or 0)
            node_count = int(result.get("node_count") or 0)
            message = f"завершено с ошибками станций: {failed_count}/{node_count}"
            details = result.get("failures") or []
            error = "; ".join(
                f"{item.get('node_name') or item.get('node_id') or 'станция'}: {item.get('error') or 'ошибка'}"
                for item in details
            ) or message
            update_job(
                job_id,
                status="failed",
                progress=1.0,
                message=message,
                result=result,
                error=error,
                worker_id=worker_id,
            )
            job = get_job(job_id) or {}
            dispatch_event("job.failed", {"job": job, "error": error})
        else:
            update_job(
                job_id,
                status="succeeded",
                progress=1.0,
                message="готово",
                result=result,
                worker_id=worker_id,
            )
            job = get_job(job_id) or {}
            dispatch_event("job.succeeded", {"job": job})
    finally:
        heartbeat_stop.set()
        if heartbeat:
            heartbeat.join(timeout=1)
        if worker_id:
            execute(
                "UPDATE jobs SET worker_id = NULL, lease_expires_at = NULL WHERE id = ? AND worker_id = ?",
                (job_id, worker_id),
            )
        with _cancel_lock:
            if _cancel_events.get(job_id) is cancel_event:
                _cancel_events.pop(job_id, None)
