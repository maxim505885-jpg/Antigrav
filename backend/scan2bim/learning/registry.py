"""Model version registry: explicit activation, gated by held-out metrics."""
from __future__ import annotations

from typing import Any

from ..db import dumps, execute, loads, one, rows, utcnow


def _model(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "version": row["version"],
        "kind": row["kind"],
        "path": row["path"],
        "metrics": loads(row.get("metrics_json"), {}),
        "status": row["status"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "activated_at": row.get("activated_at"),
    }


def list_models(name: str | None = None) -> list[dict[str, Any]]:
    if name:
        records = rows("SELECT * FROM model_versions WHERE name = ? ORDER BY version DESC", (name,))
    else:
        records = rows("SELECT * FROM model_versions ORDER BY created_at DESC")
    return [_model(r) for r in records]


def activate(model_id: str, force: bool = False) -> dict[str, Any]:
    record = one("SELECT * FROM model_versions WHERE id = ?", (model_id,))
    if not record:
        raise KeyError(f"model {model_id} not found")
    metrics = loads(record.get("metrics_json"), {})
    if not metrics.get("eligible_for_activation") and not force:
        raise ValueError(
            "model did not pass held-out quality gates: "
            + str(metrics.get("blocking_reason") or "metrics unavailable")
        )
    execute(
        "UPDATE model_versions SET status = 'archived' WHERE name = ? AND kind = ? AND status = 'active'",
        (record["name"], record["kind"]),
    )
    execute(
        "UPDATE model_versions SET status = 'active', activated_at = ? WHERE id = ?",
        (utcnow(), model_id),
    )
    return _model(one("SELECT * FROM model_versions WHERE id = ?", (model_id,)))


def rollback(name: str, kind: str = "knn-prior") -> dict[str, Any]:
    active = one(
        "SELECT * FROM model_versions WHERE name = ? AND kind = ? AND status = 'active' "
        "ORDER BY version DESC LIMIT 1",
        (name, kind),
    )
    candidates = rows(
        "SELECT * FROM model_versions WHERE name = ? AND kind = ? AND status = 'archived' "
        "ORDER BY version DESC",
        (name, kind),
    )
    eligible = []
    for candidate in candidates:
        metrics = loads(candidate.get("metrics_json"), {})
        if metrics.get("eligible_for_activation") or metrics.get("rollback_allowed"):
            eligible.append(candidate)
    if not eligible:
        raise ValueError("no previous eligible model version is available for rollback")
    target = eligible[0]
    execute(
        "UPDATE model_versions SET status = 'archived' WHERE id = ?",
        (active["id"],) if active else ("",),
    )
    execute(
        "UPDATE model_versions SET status = 'active', activated_at = ? WHERE id = ?",
        (utcnow(), target["id"]),
    )
    return _model(one("SELECT * FROM model_versions WHERE id = ?", (target["id"],)))
