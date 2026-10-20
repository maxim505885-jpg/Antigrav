"""Background jobs, progress and webhook delivery."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import traceback
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .db import dumps, execute, new_id, one, record_event, rows, utcnow

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="s2b-job")


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
    values.append(job_id)
    execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", tuple(values))


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
    _executor.submit(_run, job_id, fn)


def _run(job_id: str, fn) -> None:
    update_job(job_id, status="running", progress=0.01, message="запущено")

    def progress(value: float, message: str = "") -> None:
        update_job(job_id, progress=value, message=message or None)

    try:
        result = fn(progress) or {}
    except Exception as exc:  # noqa: BLE001 - job boundary must capture everything
        message = f"{type(exc).__name__}: {exc}"
        update_job(
            job_id,
            status="failed",
            message="ошибка",
            error=message + "\n" + traceback.format_exc(limit=8),
        )
        job = get_job(job_id) or {}
        dispatch_event("job.failed", {"job": job, "error": message})
        return
    update_job(job_id, status="succeeded", progress=1.0, message="готово", result=result)
    job = get_job(job_id) or {}
    dispatch_event("job.succeeded", {"job": job})
