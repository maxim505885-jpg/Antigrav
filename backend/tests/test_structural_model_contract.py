import copy
import math
import sqlite3

import pytest

from scan2bim.structure.models import validate_structural_model
from scan2bim import db as database


def _member(*, member_id="member-1", axis_end=(6.0, 0.0, 0.0), cross_section=None):
    identity = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
    return {
        "id": member_id,
        "element_id": f"element-{member_id}",
        "project_id": "project-1",
        "cloud_id": "cloud-1",
        "role": "column",
        "class_name": "column",
        "axis": {"start": [0.0, 0.0, 0.0], "end": list(axis_end)},
        "local_frame": identity,
        "cross_section": cross_section or {"kind": "unknown", "reason": "not measured"},
        "assemblies": [],
        "measured_dimensions": {},
        "evidence": {"source_point_ids": [2, 7, 9]},
        "method": {"name": "manual", "version": "1", "parameters": {}},
        "confidence": 0.5,
        "review_state": "unreviewed",
        "transforms": {"source_to_local": identity, "local_to_world": identity},
    }


def _model(*members):
    return {
        "schema": "scan2bim.structural/1.0",
        "units": "m",
        "coordinate_frame": {"id": "source_cloud_world", "units": "m", "vertical_axis": "Z"},
        "members": list(members),
    }


@pytest.mark.parametrize("axis_end", [(6.0, 0.0, 0.0), (0.0, 6.0, 0.0), (4.0, 3.0, 2.0), (0.0, 0.0, 6.0)])
def test_structural_contract_accepts_horizontal_rotated_sloped_and_vertical_members(axis_end):
    model = _model(_member(axis_end=axis_end))
    validate_structural_model(model)


@pytest.mark.parametrize("section", [
    {"kind": "unknown", "reason": "occluded"},
    {"kind": "built_up", "components": [{"profile": "C200", "count": 2}]},
])
def test_structural_contract_keeps_unknown_and_built_up_sections(section):
    validate_structural_model(_model(_member(cross_section=section)))


def test_structural_contract_rejects_zero_length_nonfinite_and_duplicate_ids():
    with pytest.raises(ValueError, match="non-zero"):
        validate_structural_model(_model(_member(axis_end=(0.0, 0.0, 0.0))))

    nonfinite = _member()
    nonfinite["axis"]["end"][0] = math.inf
    with pytest.raises(ValueError, match="finite"):
        validate_structural_model(_model(nonfinite))

    duplicate = _member()
    with pytest.raises(ValueError, match="unique"):
        validate_structural_model(_model(_member(), duplicate))


def test_structural_contract_checks_source_local_world_transform_round_trip():
    model = _model(_member())
    member = model["members"][0]
    member["transforms"]["source_to_local"] = [
        [0.0, -1.0, 0.0, -2.0], [1.0, 0.0, 0.0, 1.0],
        [0.0, 0.0, 1.0, -3.0], [0.0, 0.0, 0.0, 1.0],
    ]
    member["transforms"]["local_to_world"] = [
        [0.0, 1.0, 0.0, -1.0], [-1.0, 0.0, 0.0, -2.0],
        [0.0, 0.0, 1.0, 3.0], [0.0, 0.0, 0.0, 1.0],
    ]
    validated = validate_structural_model(model)

    point = [1.5, 2.5, 4.0, 1.0]
    local = [sum(row[i] * point[i] for i in range(4)) for row in member["transforms"]["source_to_local"]]
    world = [sum(row[i] * local[i] for i in range(4)) for row in member["transforms"]["local_to_world"]]
    assert world == pytest.approx(point)
    assert validated["members"][0]["id"] == "member-1"

    broken = copy.deepcopy(model)
    broken["members"][0]["transforms"]["local_to_world"][0][3] += 0.1
    with pytest.raises(ValueError, match="round-trip"):
        validate_structural_model(broken)


def test_additive_structural_member_migration_preserves_legacy_rows_and_backup(tmp_path, monkeypatch):
    path = tmp_path / "legacy.sqlite3"
    backup_path = tmp_path / "before-migration.sqlite3"
    rollback_path = tmp_path / "rollback.sqlite3"
    monkeypatch.setattr(database, "DB_PATH", path)
    database.init_db()
    now = database.utcnow()
    with database.db() as con:
        con.execute("INSERT INTO projects (id,name,created_at,updated_at) VALUES ('p','P',?,?)", (now, now))
        con.execute(
            "INSERT INTO clouds (id,project_id,name,source_path,source_format,created_at,updated_at) "
            "VALUES ('c','p','C','derived.e57','e57',?,?)", (now, now),
        )
        con.execute(
            "INSERT INTO elements (id,project_id,cloud_id,class_name,geometry_json,bbox_json,created_at,updated_at) "
            "VALUES ('e','p','c','column','{}','{}',?,?)", (now, now),
        )
        con.execute("DROP TABLE structural_members")
    with sqlite3.connect(path) as source, sqlite3.connect(backup_path) as backup:
        source.backup(backup)

    database.init_db()

    assert database.one("SELECT id FROM projects WHERE id='p'") == {"id": "p"}
    assert database.one("SELECT id FROM clouds WHERE id='c'") == {"id": "c"}
    assert database.one("SELECT id FROM elements WHERE id='e'") == {"id": "e"}
    assert database.one("SELECT name FROM sqlite_master WHERE type='table' AND name='structural_members'")

    with sqlite3.connect(backup_path) as backup, sqlite3.connect(rollback_path) as rollback:
        backup.backup(rollback)
    with sqlite3.connect(rollback_path) as rollback:
        names = {row[0] for row in rollback.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "structural_members" not in names
        assert rollback.execute("SELECT id FROM elements WHERE id='e'").fetchone() == ("e",)
