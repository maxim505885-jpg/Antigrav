"""Project-scoped persistence for confirmed column types and reversible review."""
from __future__ import annotations

import math
import re
from typing import Any

from .. import db


def _normalise_proposal(proposal: dict[str, Any]) -> tuple[str, list[str], dict[str, float], str]:
    key = str(proposal.get("proposal_key") or "").strip()
    if not key:
        raise ValueError("proposal_key is required")
    if proposal.get("status") != "proposed":
        raise ValueError("only proposed column types can be confirmed")
    members = proposal.get("member_element_ids")
    if not isinstance(members, list) or not members:
        raise ValueError("a proposal must contain at least one member element")
    member_ids = sorted({str(member_id).strip() for member_id in members if str(member_id).strip()})
    if len(member_ids) != len(members):
        raise ValueError("proposal member IDs must be non-empty and unique")
    sides = proposal.get("representative_sides_m")
    if not isinstance(sides, dict):
        raise ValueError("representative_sides_m is required")
    result_sides: dict[str, float] = {}
    for side in ("long", "short"):
        value = sides.get(side)
        if isinstance(value, bool):
            raise ValueError(f"representative {side} side must be positive and finite")
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = math.nan
        if not math.isfinite(number) or number <= 0:
            raise ValueError(f"representative {side} side must be positive and finite")
        result_sides[side] = number
    if result_sides["long"] < result_sides["short"]:
        raise ValueError("representative long side must be greater than or equal to short side")
    morphology = str(proposal.get("morphology") or "unknown")
    return key, member_ids, result_sides, morphology


def _next_mark(con, project_id: str) -> str:
    existing = {row[0] for row in con.execute(
        "SELECT mark FROM column_types WHERE project_id=?", (project_id,)
    )}
    index = 1
    while f"К{index}" in existing:
        index += 1
    return f"К{index}"


def _validate_project_members(con, project_id: str, member_ids: list[str]) -> None:
    if con.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None:
        raise ValueError("project does not exist")
    placeholders = ",".join("?" for _ in member_ids)
    members = con.execute(
        f"SELECT id,project_id,class_name,measured,inferred FROM elements WHERE id IN ({placeholders})",
        tuple(member_ids),
    ).fetchall()
    if len(members) != len(member_ids):
        raise ValueError("proposal contains an unknown element")
    if any(item["project_id"] != project_id for item in members):
        raise ValueError("all proposal members must belong to the same project")
    if any(item["class_name"] != "column" or not item["measured"] or item["inferred"] for item in members):
        raise ValueError("proposal members must be measured, non-inferred columns")


def _read_assignments(con, project_id: str, element_ids: list[str]) -> dict[str, str | None]:
    if not element_ids:
        return {}
    placeholders = ",".join("?" for _ in element_ids)
    rows = con.execute(
        f"SELECT element_id,type_id FROM column_type_assignments "
        f"WHERE project_id=? AND element_id IN ({placeholders})",
        (project_id, *element_ids),
    ).fetchall()
    found = {row["element_id"]: row["type_id"] for row in rows}
    return {element_id: found.get(element_id) for element_id in element_ids}


def _save_assignments(
    con,
    project_id: str,
    assignments: dict[str, str | None],
    engineer: str,
    note: str,
) -> None:
    for element_id, type_id in assignments.items():
        if type_id is None:
            con.execute(
                "DELETE FROM column_type_assignments WHERE project_id=? AND element_id=?",
                (project_id, element_id),
            )
        else:
            con.execute(
                "INSERT INTO column_type_assignments "
                "(project_id,element_id,type_id,assigned_at,engineer,note) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(element_id) DO UPDATE SET project_id=excluded.project_id, "
                "type_id=excluded.type_id,assigned_at=excluded.assigned_at, "
                "engineer=excluded.engineer,note=excluded.note",
                (project_id, element_id, type_id, db.utcnow(), engineer, note),
            )


def _record_action(
    con,
    *,
    project_id: str,
    action: str,
    before: dict[str, str | None],
    after: dict[str, str | None],
    engineer: str,
    note: str,
    created_type_id: str | None = None,
    target_action_id: str | None = None,
) -> str:
    action_id = db.new_id()
    con.execute(
        "INSERT INTO column_type_actions "
        "(id,project_id,action,target_action_id,created_type_id,before_json,after_json,engineer,note,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            action_id, project_id, action, target_action_id, created_type_id,
            db.dumps(before), db.dumps(after), engineer, note, db.utcnow(),
        ),
    )
    return action_id


def list_column_types(project_id: str) -> list[dict[str, Any]]:
    """List a project's confirmed types with their current element memberships."""
    with db.db() as con:
        type_rows = con.execute(
            "SELECT * FROM column_types WHERE project_id=?", (project_id,)
        ).fetchall()
        types = []
        for type_row in type_rows:
            assignments = con.execute(
                "SELECT element_id FROM column_type_assignments WHERE type_id=? ORDER BY element_id",
                (type_row["id"],),
            ).fetchall()
            mark = type_row["mark"]
            number = int(match.group(1)) if (match := re.fullmatch(r"К(\d+)", mark)) else math.inf
            types.append({
                "id": type_row["id"],
                "project_id": type_row["project_id"],
                "proposal_key": type_row["proposal_key"],
                "mark": mark,
                "prototype": db.loads(type_row["prototype_json"], {}),
                "member_element_ids": [row["element_id"] for row in assignments],
                "member_count": len(assignments),
                "status": "confirmed",
                "engineer": type_row["engineer"],
                "note": type_row["note"],
                "created_at": type_row["created_at"],
                "_sort_key": (number, mark),
            })
        types.sort(key=lambda item: item["_sort_key"])
        for item in types:
            item.pop("_sort_key")
        return types


def confirm_column_type(
    project_id: str,
    proposal: dict[str, Any],
    mark: str | None = None,
    engineer: str = "engineer",
    note: str = "",
) -> dict[str, Any]:
    """Confirm a proposal and assign its existing measured elements atomically."""
    proposal_key, member_ids, sides, morphology = _normalise_proposal(proposal)
    engineer = str(engineer or "engineer").strip()
    mark = str(mark or "").strip()
    note = str(note or "")
    prototype = dict(proposal)
    prototype["member_element_ids"] = member_ids
    prototype["representative_sides_m"] = sides
    prototype["morphology"] = morphology
    with db.db() as con:
        if con.execute(
            "SELECT 1 FROM column_type_rejections WHERE project_id=? AND proposal_key=?",
            (project_id, proposal_key),
        ).fetchone():
            raise ValueError("proposal was rejected; undo rejection before confirming")
        existing = con.execute(
            "SELECT id,mark,prototype_json FROM column_types WHERE project_id=? AND proposal_key=?",
            (project_id, proposal_key),
        ).fetchone()
        if existing:
            if db.loads(existing["prototype_json"], {}) != prototype:
                raise ValueError("proposal key already confirms a different proposal")
            if mark and mark != existing["mark"]:
                raise ValueError("proposal key already confirms a type with another mark")
            _validate_project_members(con, project_id, member_ids)
            action = con.execute(
                "SELECT id FROM column_type_actions WHERE project_id=? AND action='confirm' "
                "AND created_type_id=? ORDER BY created_at LIMIT 1",
                (project_id, existing["id"]),
            ).fetchone()
            assignments = _read_assignments(con, project_id, member_ids)
            if any(value is not None and value != existing["id"] for value in assignments.values()):
                raise ValueError("column type assignments changed; use explicit reassignment")
            changed = any(value is None for value in assignments.values())
            action_id = action["id"] if action else None
            if changed:
                after = {element_id: existing["id"] for element_id in member_ids}
                _save_assignments(con, project_id, after, engineer, note)
                action_id = _record_action(con, project_id=project_id, action="reconfirm",
                    before=assignments, after=after, engineer=engineer, note=note)
            return {
                "id": existing["id"], "project_id": project_id,
                "proposal_key": proposal_key, "mark": existing["mark"],
                "member_element_ids": member_ids,
                "status": "confirmed", "action_id": action_id,
                "changed": changed,
            }

        if con.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None:
            raise ValueError("project does not exist")
        placeholders = ",".join("?" for _ in member_ids)
        member_rows = con.execute(
            f"SELECT id,project_id,class_name,measured,inferred FROM elements WHERE id IN ({placeholders})",
            tuple(member_ids),
        ).fetchall()
        by_id = {row["id"]: row for row in member_rows}
        if len(by_id) != len(member_ids):
            raise ValueError("proposal contains an unknown element")
        if any(row["project_id"] != project_id for row in member_rows):
            raise ValueError("all proposal members must belong to the same project")
        if any(row["class_name"] != "column" or not row["measured"] or row["inferred"] for row in member_rows):
            raise ValueError("proposal members must be measured, non-inferred columns")

        assigned_mark = mark or _next_mark(con, project_id)
        if con.execute(
            "SELECT 1 FROM column_types WHERE project_id=? AND mark=?", (project_id, assigned_mark)
        ).fetchone():
            raise ValueError("column type mark is already used in this project")

        type_id = db.new_id()
        now = db.utcnow()
        con.execute(
            "INSERT INTO column_types "
            "(id,project_id,proposal_key,mark,prototype_json,engineer,note,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (type_id, project_id, proposal_key, assigned_mark, db.dumps(prototype), engineer, note, now, now),
        )
        before = _read_assignments(con, project_id, member_ids)
        after = {element_id: type_id for element_id in member_ids}
        _save_assignments(con, project_id, after, engineer, note)
        action_id = _record_action(
            con, project_id=project_id, action="confirm", before=before, after=after,
            engineer=engineer, note=note, created_type_id=type_id,
        )
        return {
            "id": type_id, "project_id": project_id,
            "proposal_key": proposal_key, "mark": assigned_mark,
            "representative_sides_m": sides, "morphology": morphology,
            "member_element_ids": member_ids, "status": "confirmed",
            "action_id": action_id, "changed": True,
        }


def assign_column_type(
    element_id: str,
    type_id: str | None,
    engineer: str = "engineer",
    note: str = "",
) -> dict[str, Any]:
    """Assign or clear one measured column's project type and record the change."""
    engineer = str(engineer or "engineer").strip()
    note = str(note or "")
    with db.db() as con:
        element = con.execute(
            "SELECT project_id,class_name,measured,inferred FROM elements WHERE id=?", (element_id,)
        ).fetchone()
        if element is None:
            raise ValueError("element does not exist")
        if element["class_name"] != "column" or not element["measured"] or element["inferred"]:
            raise ValueError("only measured, non-inferred columns can be assigned")
        project_id = element["project_id"]
        if type_id is not None:
            target = con.execute(
                "SELECT project_id FROM column_types WHERE id=?", (type_id,)
            ).fetchone()
            if target is None:
                raise ValueError("column type does not exist")
            if target["project_id"] != project_id:
                raise ValueError("element and column type must belong to the same project")

        before = _read_assignments(con, project_id, [element_id])
        if before[element_id] == type_id:
            return {
                "element_id": element_id, "project_id": project_id,
                "type_id": type_id, "action_id": None, "changed": False,
            }
        after = {element_id: type_id}
        _save_assignments(con, project_id, after, engineer, note)
        action_id = _record_action(
            con, project_id=project_id, action="assign" if type_id else "clear",
            before=before, after=after, engineer=engineer, note=note,
        )
        return {
            "element_id": element_id, "project_id": project_id,
            "type_id": type_id, "action_id": action_id, "changed": True,
        }


def list_rejected_column_types(project_id: str) -> list[dict[str, Any]]:
    with db.db() as con:
        records = con.execute(
            "SELECT r.proposal_key,r.proposal_json,r.action_id,a.engineer,a.note,a.created_at "
            "FROM column_type_rejections r JOIN column_type_actions a ON a.id=r.action_id "
            "WHERE r.project_id=? ORDER BY a.rowid", (project_id,),
        ).fetchall()
        return [{
            "proposal_key": item["proposal_key"], "proposal": db.loads(item["proposal_json"], {}),
            "action_id": item["action_id"], "status": "rejected",
            "engineer": item["engineer"], "note": item["note"], "created_at": item["created_at"],
        } for item in records]


def reject_column_type(
    project_id: str, proposal: dict[str, Any], engineer: str = "engineer", note: str = "",
) -> dict[str, Any]:
    """Reject a grouping proposal without rejecting or modifying its columns."""
    key, member_ids, sides, morphology = _normalise_proposal(proposal)
    snapshot = dict(proposal)
    snapshot.update(member_element_ids=member_ids, representative_sides_m=sides, morphology=morphology)
    with db.db() as con:
        _validate_project_members(con, project_id, member_ids)
        if con.execute(
            "SELECT 1 FROM column_types WHERE project_id=? AND proposal_key=?", (project_id, key),
        ).fetchone():
            raise ValueError("proposal already confirms a type; undo confirmation before rejecting")
        existing = con.execute(
            "SELECT action_id,proposal_json FROM column_type_rejections WHERE project_id=? AND proposal_key=?",
            (project_id, key),
        ).fetchone()
        if existing:
            if db.loads(existing["proposal_json"], {}) != snapshot:
                raise ValueError("proposal key already rejects a different proposal")
            return {"action_id": existing["action_id"], "status": "rejected", "changed": False}
        action_id = _record_action(
            con, project_id=project_id, action="reject_proposal", before={}, after={"proposal_key": key},
            engineer=str(engineer or "engineer"), note=str(note or ""),
        )
        con.execute(
            "INSERT INTO column_type_rejections (project_id,proposal_key,proposal_json,action_id) VALUES (?,?,?,?)",
            (project_id, key, db.dumps(snapshot), action_id),
        )
        return {"action_id": action_id, "status": "rejected", "changed": True}


def undo_column_type_action(action_id: str, engineer: str = "engineer", note: str = "") -> dict[str, Any]:
    """Append an undo action and restore the exact prior assignment snapshot."""
    engineer = str(engineer or "engineer").strip()
    note = str(note or "")
    with db.db() as con:
        original = con.execute(
            "SELECT * FROM column_type_actions WHERE id=?", (action_id,)
        ).fetchone()
        if original is None:
            raise ValueError("column type action does not exist")
        if original["action"] == "undo":
            raise ValueError("undo actions cannot themselves be undone")
        prior_undo = con.execute(
            "SELECT id FROM column_type_actions WHERE target_action_id=?", (action_id,)
        ).fetchone()
        if prior_undo:
            return {"action_id": prior_undo["id"], "target_action_id": action_id, "status": "undone", "changed": False}

        before = db.loads(original["before_json"], {})
        after = db.loads(original["after_json"], {})
        if original["action"] == "reject_proposal":
            rejection = con.execute(
                "SELECT action_id FROM column_type_rejections WHERE project_id=? AND proposal_key=?",
                (original["project_id"], after.get("proposal_key")),
            ).fetchone()
            if not rejection or rejection["action_id"] != action_id:
                raise ValueError("proposal rejection changed after this action")
            con.execute(
                "DELETE FROM column_type_rejections WHERE project_id=? AND proposal_key=?",
                (original["project_id"], after["proposal_key"]),
            )
            undo_id = _record_action(
                con, project_id=original["project_id"], action="undo", before=after, after=before,
                engineer=engineer, note=note, target_action_id=action_id,
            )
            return {"action_id": undo_id, "target_action_id": action_id, "status": "undone", "changed": True}
        if not isinstance(before, dict) or not isinstance(after, dict) or set(before) != set(after):
            raise ValueError("stored column type action has invalid assignment snapshots")
        member_ids = sorted(after)
        current = _read_assignments(con, original["project_id"], member_ids)
        if current != after:
            raise ValueError("column type assignments changed after this action; undo later actions first")
        created_type_id = original["created_type_id"]
        if created_type_id:
            count = con.execute(
                "SELECT COUNT(*) FROM column_type_assignments WHERE type_id=? AND element_id NOT IN "
                f"({','.join('?' for _ in member_ids)})",
                (created_type_id, *member_ids),
            ).fetchone()[0]
            if count:
                raise ValueError("created type has later assignments; undo later actions first")

        _save_assignments(con, original["project_id"], before, engineer, note)
        if created_type_id:
            con.execute("DELETE FROM column_types WHERE id=?", (created_type_id,))
        undo_id = _record_action(
            con, project_id=original["project_id"], action="undo",
            before=after, after=before, engineer=engineer, note=note,
            target_action_id=action_id,
        )
        return {"action_id": undo_id, "target_action_id": action_id, "status": "undone", "changed": True}
