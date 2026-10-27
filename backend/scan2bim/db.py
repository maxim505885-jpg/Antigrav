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

-- A station pair stores a proposed rigid transform between two individually
-- imported stations (one cloud row per RCP node or standalone station file).
-- Saving a proposal never applies it or changes the source points/RCP project.
CREATE TABLE IF NOT EXISTS station_registrations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_station_id TEXT NOT NULL REFERENCES clouds(id) ON DELETE CASCADE,
    target_station_id TEXT NOT NULL REFERENCES clouds(id) ON DELETE CASCADE,
    method TEXT NOT NULL CHECK (method IN ('rigid_icp', 'manual_kabsch', 'manual_kabsch_icp')),
    matrix_json TEXT NOT NULL,
    world_matrix_json TEXT,
    fit_rmse_mm REAL,
    independent_control_count INTEGER NOT NULL DEFAULT 0 CHECK (independent_control_count >= 0),
    control_rmse_mm REAL,
    acceptance_rmse_mm REAL,
    status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'verified')),
    matrix_applied INTEGER NOT NULL DEFAULT 0 CHECK (matrix_applied = 0),
    rcp_updated INTEGER NOT NULL DEFAULT 0 CHECK (rcp_updated = 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, source_station_id, target_station_id),
    CHECK (source_station_id <> target_station_id)
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

-- Additive structural contract storage. Existing element IDs and geometry stay
-- authoritative; this row stores the richer versioned interpretation beside it.
CREATE TABLE IF NOT EXISTS structural_members (
    id TEXT PRIMARY KEY,
    element_id TEXT NOT NULL UNIQUE REFERENCES elements(id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL DEFAULT 'scan2bim.structural/1.0',
    member_json TEXT NOT NULL,
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
    physical_instance_id TEXT,
    source_snapshot_id TEXT,
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

-- Independent semantic truth for all recognized element candidates. Separate
-- from reviewer feedback and column dimensions; revisions bind to one exact
-- cloud/candidate snapshot and survive recognition reruns.
CREATE TABLE IF NOT EXISTS element_annotations (
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
    task_payload_json TEXT,
    worker_id TEXT,
    lease_expires_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
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
CREATE INDEX IF NOT EXISTS idx_element_annotations_snapshot ON element_annotations(cloud_id, source_snapshot_sha256, element_id, revision);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id);
CREATE INDEX IF NOT EXISTS idx_station_registrations_project ON station_registrations(project_id);

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
        _ensure_job_worker_columns(con)
        _ensure_training_sample_identity(con)
        _downgrade_legacy_structural_grid_columns(con)


def _ensure_job_worker_columns(con: sqlite3.Connection) -> None:
    """Add durable task ownership and cancellation fields to existing databases."""
    columns = {row["name"] for row in con.execute("PRAGMA table_info(jobs)")}
    additions = {
        "task_payload_json": "TEXT",
        "worker_id": "TEXT",
        "lease_expires_at": "TEXT",
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, sql_type in additions.items():
        if name not in columns:
            con.execute(f"ALTER TABLE jobs ADD COLUMN {name} {sql_type}")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_worker_claim "
        "ON jobs(status, lease_expires_at, created_at)"
    )


def _ensure_training_sample_identity(con: sqlite3.Connection) -> None:
    """Add training identity and point-cloud provenance to older databases."""
    columns = {row["name"] for row in con.execute("PRAGMA table_info(training_samples)")}
    if "physical_instance_id" not in columns:
        con.execute("ALTER TABLE training_samples ADD COLUMN physical_instance_id TEXT")
    if "source_snapshot_id" not in columns:
        con.execute("ALTER TABLE training_samples ADD COLUMN source_snapshot_id TEXT")


def _downgrade_legacy_structural_grid_columns(con: sqlite3.Connection) -> int:
    """Remove unsupported measurements from legacy grid-generated column rows.

    The old grid script assigned section sizes, axes, marks and a calibrated-looking
    confidence to points found in a search window. Keep the row and its observed
    vertical extent for review, but represent it only as an unmeasured axis hypothesis.
    """
    candidates = con.execute(
        """SELECT id, geometry_json, bbox_json, dimensions_json
           FROM elements
           WHERE source = 'structural_grid'
             AND review_status NOT IN ('confirmed', 'corrected')
             AND (measured != 0 OR inferred != 1 OR confidence_kind != 'not_calibrated'
                  OR review_status != 'unreviewed')"""
    ).fetchall()
    changed = 0
    for row in candidates:
        try:
            geometry = json.loads(row["geometry_json"] or "{}")
            bbox = json.loads(row["bbox_json"] or "{}")
            center = geometry.get("center")
            lower = bbox.get("min")
            upper = bbox.get("max")
            if not isinstance(center, list) or len(center) < 2:
                continue
            if not isinstance(lower, list) or len(lower) < 3 or not isinstance(upper, list) or len(upper) < 3:
                continue
            x, y, z_min, z_max = (float(center[0]), float(center[1]), float(lower[2]), float(upper[2]))
            if not all(map(lambda value: value == value and abs(value) != float("inf"), (x, y, z_min, z_max))):
                continue
            if z_max <= z_min:
                continue
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        axis_geometry = {
            "kind": "member",
            "p0": [x, y, z_min],
            "p1": [x, y, z_max],
            "axis_status": "window_derived_candidate",
        }
        axis_bbox = {"min": [x, y, z_min], "max": [x, y, z_max]}
        dimensions = {
            "nominal_grid_hypothesis": {
                "grid_hypothesis": {
                    "status": "grid_control_not_provided",
                    "nominal_step_m": 6.0,
                }
            },
            "section_status": "not_measured",
            "extent_status": "point_extent_in_search_window_not_member_height",
            "candidate_method": "legacy_search_window",
            "search_window_half_width_m": 0.9,
        }
        metadata = {
            "method": "legacy_grid_search_window",
            "structural_status": "candidate_requires_review",
            "legacy_claims_redacted": True,
        }
        con.execute(
            """UPDATE elements
               SET geometry_json = ?, bbox_json = ?, confidence = 0,
                   confidence_kind = 'not_calibrated', measured = 0, inferred = 1,
                   review_status = 'unreviewed', dimensions_json = ?, metadata_json = ?,
                   updated_at = ?
               WHERE id = ?""",
            (json.dumps(axis_geometry, ensure_ascii=False), json.dumps(axis_bbox, ensure_ascii=False),
             json.dumps(dimensions, ensure_ascii=False), json.dumps(metadata, ensure_ascii=False), utcnow(), row["id"]),
        )
        changed += 1
    return changed


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
