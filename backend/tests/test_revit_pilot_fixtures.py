"""Revit importer fixtures encode repeat/update/preserve/rollback scenarios."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "integrations" / "revit" / "pilot"
SCHEMA = json.loads((ROOT / "contracts" / "scan2bim.bim-1.0.schema.json").read_text(encoding="utf-8"))


def _load(name, *, validate=True):
    model = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    if validate:
        Draft202012Validator(SCHEMA).validate(model)
    return model


def test_revit_v1_v2_fixtures_cover_update_and_preserve_absent_ids():
    first = _load("import-run-1.json")
    second = _load("import-run-2.json")
    first_elements = {item["id"]: item for item in first["elements"]}
    second_elements = {item["id"]: item for item in second["elements"]}

    assert set(first_elements) == {
        "SCAN-COL-KEEP", "SCAN-COL-CHANGE", "SCAN-COL-OMIT", "SCAN-BEAM-KEEP",
    }
    assert set(second_elements) == {
        "SCAN-COL-KEEP", "SCAN-COL-CHANGE", "SCAN-BEAM-KEEP", "SCAN-TRUSS-UNSUPPORTED",
    }
    assert first_elements["SCAN-COL-CHANGE"]["id"] == second_elements["SCAN-COL-CHANGE"]["id"]
    assert first_elements["SCAN-COL-CHANGE"]["geometry"] != second_elements["SCAN-COL-CHANGE"]["geometry"]
    assert second_elements["SCAN-TRUSS-UNSUPPORTED"]["class_name"] == "truss"


def test_revit_rollback_fixture_fails_after_a_valid_element_is_seen():
    model = _load("rollback-invalid-geometry.json", validate=False)
    assert len(model["elements"]) == 2
    assert model["elements"][0]["geometry"]["kind"] == "oriented_box"
    assert model["elements"][1]["geometry"]["kind"] == "member"
    assert "p0" in model["elements"][1]["geometry"]
    assert "p1" not in model["elements"][1]["geometry"]
