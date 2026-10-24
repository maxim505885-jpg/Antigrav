from __future__ import annotations

import json
import sqlite3

from scan2bim.db import _downgrade_legacy_structural_grid_columns


def test_legacy_grid_columns_are_downgraded_to_unmeasured_axis_hypotheses():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE elements (
            id TEXT PRIMARY KEY, class_name TEXT NOT NULL, geometry_json TEXT NOT NULL,
            bbox_json TEXT NOT NULL, confidence REAL NOT NULL, confidence_kind TEXT NOT NULL,
            measured INTEGER NOT NULL, inferred INTEGER NOT NULL, source TEXT NOT NULL,
            review_status TEXT NOT NULL, dimensions_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT ''
        )"""
    )
    con.execute(
        """INSERT INTO elements (id, class_name, geometry_json, bbox_json, confidence,
            confidence_kind, measured, inferred, source, review_status, dimensions_json, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "grid-column-1", "column",
            json.dumps({"kind": "oriented_box", "center": [12.3, 4.5, -6.0], "sizes": {"length": 0.6, "thickness": 0.5, "height": 9.0}}),
            json.dumps({"min": [12.0, 4.25, -10.5], "max": [12.6, 4.75, -1.5]}),
            0.98, "measured_grid_consensus", 1, 0, "structural_grid", "approved",
            json.dumps({"length_m": 0.6, "thickness_m": 0.5, "height_m": 9.0, "mark": "К-A1", "row": "A", "axis": 1, "type": "К-1", "point_count": 1000, "structural_status": "confirmed_grid_column"}),
            json.dumps({"grid_step_m": 6.0, "row_axis": "A", "transverse_axis": "1", "confidence_kind": "measured_grid_consensus"}),
        ),
    )

    changed = _downgrade_legacy_structural_grid_columns(con)
    row = con.execute("SELECT * FROM elements WHERE id = 'grid-column-1'").fetchone()
    geometry = json.loads(row["geometry_json"])
    bbox = json.loads(row["bbox_json"])
    dimensions = json.loads(row["dimensions_json"])
    metadata = json.loads(row["metadata_json"])

    assert changed == 1
    assert row["id"] == "grid-column-1"
    assert row["class_name"] == "column"
    assert row["review_status"] == "unreviewed"
    assert row["measured"] == 0 and row["inferred"] == 1
    assert row["confidence"] == 0 and row["confidence_kind"] == "not_calibrated"
    assert geometry == {"kind": "member", "p0": [12.3, 4.5, -10.5], "p1": [12.3, 4.5, -1.5], "axis_status": "window_derived_candidate"}
    assert bbox == {"min": [12.3, 4.5, -10.5], "max": [12.3, 4.5, -1.5]}
    assert dimensions["nominal_grid_hypothesis"] == {"grid_hypothesis": {"status": "grid_control_not_provided", "nominal_step_m": 6.0}}
    assert dimensions["section_status"] == "not_measured"
    assert "mark" not in dimensions and "row" not in dimensions and "axis" not in dimensions
    assert "point_count" not in dimensions
    assert metadata["legacy_claims_redacted"] is True
    assert _downgrade_legacy_structural_grid_columns(con) == 0


def test_migration_leaves_non_grid_and_already_reviewed_elements_untouched():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE elements (
            id TEXT PRIMARY KEY, class_name TEXT NOT NULL, geometry_json TEXT NOT NULL,
            bbox_json TEXT NOT NULL, confidence REAL NOT NULL, confidence_kind TEXT NOT NULL,
            measured INTEGER NOT NULL, inferred INTEGER NOT NULL, source TEXT NOT NULL,
            review_status TEXT NOT NULL, dimensions_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT ''
        )"""
    )
    for row in (
        ("geometric", "geometric", "approved"),
        ("human-reviewed", "structural_grid", "confirmed"),
    ):
        con.execute(
            """INSERT INTO elements (id, class_name, geometry_json, bbox_json, confidence,
               confidence_kind, measured, inferred, source, review_status, dimensions_json, metadata_json)
               VALUES (?, 'column', '{}', '{}', 0.7, 'heuristic', 1, 0, ?, ?, '{}', '{}')""",
            row,
        )

    assert _downgrade_legacy_structural_grid_columns(con) == 0
    assert con.execute("SELECT COUNT(*) FROM elements WHERE measured=1 AND review_status IN ('approved', 'confirmed')").fetchone()[0] == 2
