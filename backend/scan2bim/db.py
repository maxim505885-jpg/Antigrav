"""SQLite persistence layer.

SQLite is used for the standalone product. The schema deliberately avoids
SQLite-only constructs in the domain model so it can be migrated to PostgreSQL
for the corporate stage.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    units TEXT NOT NULL DEFAULT 'm',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clouds (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_format TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT,
    point_count INTEGER NOT NULL DEFAULT 0,
    ingested_count INTEGER NOT NULL DEFAULT 0,
    decimated INTEGER NOT NULL DEFAULT 0,
    origin_x REAL, origin_y REAL, origin_z REAL,
    bbox_min_x REAL, bbox_min_y REAL, bbox_min_z REAL,
    bbox_max_x REAL, bbox_max_y REAL, bbox_max_z REAL,
    has_color INTEGER NOT NULL DEFAULT 0,
    has_intensity INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'processing',
    error TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sections (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    cloud_id TEXT NOT NULL REFERENCES clouds(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    axis TEXT,
    position REAL NOT NULL,
    thickness REAL NOT NULL,
    grid_res REAL NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL,
    point_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS elements (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    cloud_id TEXT NOT NULL REFERENCES clouds(id) ON DELETE CASCADE,
    parent_id TEXT,
    class_name TEXT NOT NULL,
    geometry_json TEXT NOT NULL,
    bbox_json TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    confidence_kind TEXT NOT NULL DEFAULT 'heuristic',
    measured INTEGER NOT NULL DEFAULT 1,
    inferred INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'geometric',
    review_status TEXT NOT NULL DEFAULT 'unreviewed',
    dimensions_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    element_id TEXT,
    cloud_id TEXT NOT NULL,
    action TEXT NOT NULL,
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}',
    engineer TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS training_samples (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    cloud_id TEXT NOT NULL,
    element_id TEXT,
    class_name TEXT NOT NULL,
    features_json TEXT NOT NULL,
    points_path TEXT,
    split TEXT NOT NULL DEFAULT 'train',
    source TEXT NOT NULL DEFAULT 'engineer',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS column_types (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    proposal_key TEXT NOT NULL,
    mark TEXT NOT NULL,
    prototype_json TEXT NOT NULL,
    engineer TEXT NOT NULL DEFAULT 'engineer',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, proposal_key),
    UNIQUE(project_id, mark)
);

CREATE TABLE IF NOT EXISTS column_type_assignments (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    element_id TEXT PRIMARY KEY REFERENCES elements(id) ON DELETE CASCADE,
    type_id TEXT NOT NULL REFERENCES column_types(id) ON DELETE NO ACTION,
    assigned_at TEXT NOT NULL,
    engineer TEXT NOT NULL DEFAULT 'engineer',
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS column_type_actions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    target_action_id TEXT UNIQUE REFERENCES column_type_actions(id) ON DELETE NO ACTION,
    created_type_id TEXT,
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}',
    engineer TEXT NOT NULL DEFAULT 'engineer',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS column_type_rejections (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    proposal_key TEXT NOT NULL,
    proposal_json TEXT NOT NULL,
    action_id TEXT NOT NULL REFERENCES column_type_actions(id) ON DELETE NO ACTION,
    PRIMARY KEY(project_id, proposal_key)
);

-- Independent ground-truth annotations are append-only and tied to an exact
-- candidate snapshot. They deliberately do not reference element rows, so a
-- recognition rerun cannot overwrite or delete reviewed measurements.
CREATE TABLE IF NOT EXISTS column_annotations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    cloud_id TEXT NOT NULL REFERENCES clouds(id) ON DELETE CASCADE,
    source_snapshot_sha256 TEXT NOT NULL,
    element_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(cloud_id, source_snapshot_sha256, element_id, revision)
);

CREATE TABLE IF NOT EXISTS model_versions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'candidate',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    activated_at TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    cloud_id TEXT,
    type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS webhooks (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    secret TEXT NOT NULL DEFAULT '',
    events TEXT NOT NULL DEFAULT '*',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL DEFAULT 'engineer',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clouds_project ON clouds(project_id);
CREATE INDEX IF NOT EXISTS idx_sections_cloud ON sections(cloud_id);
CREATE INDEX IF NOT EXISTS idx_elements_cloud ON elements(cloud_id);
CREATE INDEX IF NOT EXISTS idx_samples_project ON training_samples(project_id);
CREATE INDEX IF NOT EXISTS idx_column_types_project ON column_types(project_id);
CREATE INDEX IF NOT EXISTS idx_column_type_assignments_type ON column_type_assignments(type_id);
CREATE INDEX IF NOT EXISTS idx_column_type_actions_project ON column_type_actions(project_id);
CREATE INDEX IF NOT EXISTS idx_column_annotations_snapshot ON column_annotations(cloud_id, source_snapshot_sha256, element_id, revision);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id);

-- Also supports the initial local catalog schema whose foreign keys used
-- immediate RESTRICT checks. Cleanup order is explicit, without rebuilding
-- any existing table or changing individual-type deletion protection.
CREATE TRIGGER IF NOT EXISTS column_types_project_cleanup
BEFORE DELETE ON projects
BEGIN
    DELETE FROM column_type_rejections WHERE project_id=OLD.id;
    DELETE FROM column_type_assignments WHERE project_id=OLD.id;
    DELETE FROM column_type_actions WHERE project_id=OLD.id AND target_action_id IS NOT NULL;
    DELETE FROM column_type_actions WHERE project_id=OLD.id;
    DELETE FROM column_types WHERE project_id=OLD.id;
END;
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    con = connect()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    with db() as con:
        con.executescript(SCHEMA)


def rows(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    with db() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def one(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    with db() as con:
        row = con.execute(sql, params).fetchone()
        return dict(row) if row else None


def execute(sql: str, params: tuple | list = ()) -> None:
    with db() as con:
        con.execute(sql, params)


def execute_returning(sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
    with db() as con:
        return con.execute(sql, params)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def record_event(event_type: str, payload: dict[str, Any]) -> str:
    event_id = new_id()
    execute(
        "INSERT INTO events (id, type, payload_json, created_at) VALUES (?,?,?,?)",
        (event_id, event_type, dumps(payload), utcnow()),
    )
    return event_id
