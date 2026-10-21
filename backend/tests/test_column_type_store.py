"""Persistence tests use a disposable SQLite database, never the work DB."""
from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from scan2bim import db as database
from scan2bim.structure import column_type_store as store


@pytest.fixture
def isolated_db(monkeypatch):
    path = Path.cwd() / f".column_type_store_{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setattr(database, "DB_PATH", path)
    database.init_db()
    with database.db() as con:
        now = database.utcnow()
        for project_id in ("project-a", "project-b"):
            con.execute(
                "INSERT INTO projects (id,name,created_at,updated_at) VALUES (?,?,?,?)",
                (project_id, project_id, now, now),
            )
            cloud_id = f"cloud-{project_id}"
            con.execute(
                "INSERT INTO clouds (id,project_id,name,source_path,source_format,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (cloud_id, project_id, cloud_id, "derived-test.e57", "e57", now, now),
            )
        for element_id, project_id in (
            ("column-a1", "project-a"),
            ("column-a2", "project-a"),
            ("column-b1", "project-b"),
        ):
            con.execute(
                "INSERT INTO elements (id,project_id,cloud_id,class_name,geometry_json,bbox_json,"
                "dimensions_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    element_id, project_id, f"cloud-{project_id}", "column",
                    '{"kind":"oriented_box","sizes":{"length":0.5,"thickness":0.4}}',
                    "{}", '{"length_m":0.5,"thickness_m":0.4}', now, now,
                ),
            )
    yield path
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


def _proposal(key="proposal-a", members=None):
    member_ids = members or ["column-a1"]
    return {
        "proposal_key": key,
        "member_element_ids": member_ids,
        "representative_sides_m": {"long": 0.5, "short": 0.4},
        "residuals_m": {member_id: {"long_side_m": 0.0, "short_side_m": 0.0} for member_id in member_ids},
        "morphology": "solid",
        "morphology_agreement": True,
        "evidence_summary": {"member_count": len(member_ids)},
        "confidence": 0.75,
        "confidence_kind": "heuristic",
        "status": "proposed",
    }


def test_empty_database_migration_adds_catalog_and_action_tables(isolated_db):
    with database.db() as con:
        tables = {
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

    assert {"column_types", "column_type_assignments", "column_type_actions"} <= tables


def test_confirmation_assigns_members_without_mutating_element_ids_or_geometry(isolated_db):
    before = database.one("SELECT id,geometry_json,dimensions_json FROM elements WHERE id=?", ("column-a1",))

    result = store.confirm_column_type("project-a", _proposal(members=["column-a1", "column-a2"]))

    after = database.one("SELECT id,geometry_json,dimensions_json FROM elements WHERE id=?", ("column-a1",))
    assert result["mark"] == "К1"
    assert result["member_element_ids"] == ["column-a1", "column-a2"]
    assert result["status"] == "confirmed"
    assert after == before
    assert len(store.list_column_types("project-a")) == 1


def test_assigning_type_from_another_project_is_rejected(isolated_db):
    type_a = store.confirm_column_type("project-a", _proposal())
    type_b = store.confirm_column_type("project-b", _proposal("proposal-b", ["column-b1"]))

    with pytest.raises(ValueError, match="same project"):
        store.assign_column_type("column-a2", type_b["id"])

    assert store.list_column_types("project-a")[0]["member_element_ids"] == ["column-a1"]
    assert store.list_column_types("project-b")[0]["member_element_ids"] == ["column-b1"]


def test_reconfirming_same_proposal_is_idempotent(isolated_db):
    first = store.confirm_column_type("project-a", _proposal())
    second = store.confirm_column_type("project-a", _proposal())

    assert second["id"] == first["id"]
    assert second["action_id"] == first["action_id"]
    assert len(store.list_column_types("project-a")) == 1
    assert database.one("SELECT COUNT(*) AS n FROM column_type_actions")["n"] == 1


def test_undo_assignment_restores_previous_type_membership(isolated_db):
    original = store.confirm_column_type("project-a", _proposal())
    other = store.confirm_column_type("project-a", _proposal("proposal-other", ["column-a2"]))
    reassignment = store.assign_column_type("column-a1", other["id"])

    undone = store.undo_column_type_action(reassignment["action_id"])

    assignments = {
        member_id: type_id
        for column_type in store.list_column_types("project-a")
        for member_id, type_id in (
            (member_id, column_type["id"])
            for member_id in column_type["member_element_ids"]
        )
    }
    assert undone["status"] == "undone"
    assert assignments == {"column-a1": original["id"], "column-a2": other["id"]}


def test_undo_confirmation_removes_new_type_and_its_assignments(isolated_db):
    confirmed = store.confirm_column_type("project-a", _proposal(members=["column-a1", "column-a2"]))

    undone = store.undo_column_type_action(confirmed["action_id"])

    assert undone["status"] == "undone"
    assert store.list_column_types("project-a") == []
    assert database.one("SELECT COUNT(*) AS n FROM column_type_actions")["n"] == 2


def test_type_prototype_is_stored_as_json_without_losing_evidence(isolated_db):
    proposal = _proposal()
    confirmed = store.confirm_column_type("project-a", proposal)
    row = database.one("SELECT prototype_json FROM column_types WHERE id=?", (confirmed["id"],))

    assert json.loads(row["prototype_json"]) == proposal


def test_reusing_proposal_key_with_different_members_is_rejected(isolated_db):
    store.confirm_column_type("project-a", _proposal())

    with pytest.raises(ValueError, match="proposal key"):
        store.confirm_column_type("project-a", _proposal(members=["column-a2"]))


def test_repeating_undo_is_idempotent(isolated_db):
    confirmed = store.confirm_column_type("project-a", _proposal())

    first = store.undo_column_type_action(confirmed["action_id"])
    second = store.undo_column_type_action(confirmed["action_id"])

    assert second["action_id"] == first["action_id"]
    assert second["changed"] is False
    assert database.one("SELECT COUNT(*) AS n FROM column_type_actions")["n"] == 2


def test_confirm_undo_refuses_to_delete_type_with_later_assignments(isolated_db):
    confirmed = store.confirm_column_type("project-a", _proposal())
    store.assign_column_type("column-a2", confirmed["id"])

    with pytest.raises(ValueError, match="undo later actions"):
        store.undo_column_type_action(confirmed["action_id"])


def test_rejection_persists_is_idempotent_and_undo_restores_proposal(isolated_db):
    proposal = _proposal()
    first = store.reject_column_type("project-a", proposal, note="different sections")
    second = store.reject_column_type("project-a", proposal)

    rejected = store.list_rejected_column_types("project-a")
    assert len(rejected) == 1
    assert rejected[0]["proposal"] == proposal
    assert rejected[0]["note"] == "different sections"
    assert rejected[0]["status"] == "rejected"
    assert second["action_id"] == first["action_id"]
    assert second["changed"] is False
    assert store.list_rejected_column_types("project-b") == []
    assert database.one("SELECT review_status FROM elements WHERE id='column-a1'")["review_status"] == "unreviewed"

    store.undo_column_type_action(first["action_id"])
    assert store.list_rejected_column_types("project-a") == []
    assert database.one("SELECT COUNT(*) AS n FROM column_type_actions")["n"] == 2


def test_rejection_cannot_include_other_project_elements(isolated_db):
    with pytest.raises(ValueError, match="same project"):
        store.reject_column_type("project-a", _proposal(members=["column-b1"]))


def test_rejected_proposal_requires_undo_before_confirmation(isolated_db):
    store.reject_column_type("project-a", _proposal())
    with pytest.raises(ValueError, match="rejected"):
        store.confirm_column_type("project-a", _proposal())


@pytest.mark.parametrize("legacy_constraints", [False, True])
def test_project_deletion_cleans_catalog_assignments_rejections_and_undo_history(isolated_db, legacy_constraints):
    if legacy_constraints:
        # Recreate the first local schema, then run the additive migration.
        order = ("column_types", "column_type_assignments", "column_type_actions", "column_type_rejections")
        with database.db() as con:
            definitions = {
                name: con.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()[0]
                for name in order
            }
            con.execute("DROP TRIGGER IF EXISTS column_types_project_cleanup")
            for name in reversed(order):
                con.execute(f"DROP TABLE {name}")
            for name in order:
                con.execute(definitions[name].replace("ON DELETE NO ACTION", "ON DELETE RESTRICT"))
        database.init_db()
    confirmed = store.confirm_column_type("project-a", _proposal())
    assigned = store.assign_column_type("column-a2", confirmed["id"])
    store.undo_column_type_action(assigned["action_id"])
    store.reject_column_type("project-a", _proposal("other-proposal", ["column-a2"]))

    database.execute("DELETE FROM projects WHERE id=?", ("project-a",))

    for table in ("column_types", "column_type_assignments", "column_type_rejections", "column_type_actions"):
        assert database.one(f"SELECT COUNT(*) AS n FROM {table} WHERE project_id='project-a'")["n"] == 0
    assert database.one("SELECT id FROM projects WHERE id='project-b'")


def test_used_type_still_cannot_be_deleted_directly(isolated_db):
    confirmed = store.confirm_column_type("project-a", _proposal())
    with pytest.raises(sqlite3.IntegrityError):
        database.execute("DELETE FROM column_types WHERE id=?", (confirmed["id"],))
    assert store.list_column_types("project-a")[0]["id"] == confirmed["id"]


def test_reconfirmation_can_restore_cleared_members_with_reversible_history(isolated_db):
    original = store.confirm_column_type("project-a", _proposal())
    store.assign_column_type("column-a1", None)
    restored = store.confirm_column_type("project-a", _proposal())
    assert restored["id"] == original["id"]
    assert restored["changed"] is True
    assert store.list_column_types("project-a")[0]["member_element_ids"] == ["column-a1"]
    store.undo_column_type_action(restored["action_id"])
    assert store.list_column_types("project-a")[0]["member_element_ids"] == []


def test_reconfirmation_does_not_overwrite_another_confirmed_assignment(isolated_db):
    store.confirm_column_type("project-a", _proposal())
    other = store.confirm_column_type("project-a", _proposal("other", ["column-a2"]))
    store.assign_column_type("column-a1", other["id"])
    with pytest.raises(ValueError, match="assignments changed"):
        store.confirm_column_type("project-a", _proposal())
