"""Headless worker for durable point-cloud processing tasks."""
from __future__ import annotations

import argparse
import json
import os
import socket
import threading
import time

from .db import init_db
from .jobs import _run, claim_next_ingest_job


def run_once(worker_id: str | None = None) -> bool:
    init_db()
    identity = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    row = claim_next_ingest_job(identity)
    if row is None:
        return False

    def run_task(progress):
        # Parse persisted input inside _run's exception boundary. Corrupt or
        # outdated payloads must fail the job and release its lease instead of
        # leaving it running until the lease expires on every worker restart.
        task = json.loads(row["task_payload_json"])
        if not isinstance(task, dict):
            raise ValueError("worker task payload must be an object")
        task_type = task.get("task_type")
        payload = task.get("payload")
        if not isinstance(task_type, str) or not isinstance(payload, dict):
            raise ValueError("worker task payload must include a task_type and object payload")
        from .job_tasks import execute_job_task

        return execute_job_task(task_type, payload, progress)

    _run(
        row["id"],
        run_task,
        threading.Event(),
        worker_id=identity,
    )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run SCAN headless point-cloud workers")
    parser.add_argument("--once", action="store_true", help="claim and run one available job")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    if args.once:
        return 0 if run_once() else 1
    try:
        while True:
            if not run_once():
                time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
