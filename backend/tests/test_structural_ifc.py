import math
import json
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid
from ifcopenshell.util.element import get_psets

from scan2bim.bim import export_ifc


def test_ifc_preserves_structural_id_rotation_levels_units_and_guids(tmp_path: Path):
    stable_id = "b34b89cd-1d91-4c88-8d73-4a2df852903d"
    model = {
        "project": {"id": "project-1", "name": "Workshop"},
        "levels": [
            {"name": "0.000", "elevation": 0.0},
            {"name": "+4.000", "elevation": 4.0},
        ],
        "elements": [{
            "id": stable_id,
            "class_name": "column",
            "geometry": {
                "kind": "oriented_box",
                "center": [6.0, 2.0, 10.0],
                "sizes": {"length": 0.5, "thickness": 0.4, "height": 4.0},
                "rotation_z": math.pi / 2,
            },
            "confidence": 0.95,
            "measured": True,
            "inferred": False,
            "review_status": "confirmed",
            "metadata": {"method": "measured section", "source_point_ids": [3, 9]},
        }],
    }

    ifc_path = export_ifc(model, tmp_path / "structural.ifc", project_name="Workshop")
    ifc = ifcopenshell.open(ifc_path)

    assert ifc.schema == "IFC4"
    project = ifc.by_type("IfcProject")[0]
    length_units = [
        unit for unit in project.UnitsInContext.Units
        if unit.UnitType == "LENGTHUNIT"
    ]
    assert [(unit.Name, unit.Prefix) for unit in length_units] == [("METRE", None)]

    column = ifc.by_type("IfcColumn")[0]
    assert column.GlobalId
    assert len(ifcopenshell.guid.expand(column.GlobalId)) == 32
    assert get_psets(column)["Pset_ScanToBIM"]["ElementId"] == stable_id
    assert get_psets(column)["Pset_ScanToBIM"]["GeometryStatus"] == "supported"
    assert json.loads(get_psets(column)["Pset_ScanToBIM"]["MetadataJSON"]) == model["elements"][0]["metadata"]
    solid = column.Representation.Representations[0].Items[0]
    assert (solid.SweptArea.XDim, solid.SweptArea.YDim) == (0.5, 0.4)
    assert all(
        math.isclose(actual, expected, abs_tol=1e-12)
        for actual, expected in zip(solid.Position.RefDirection.DirectionRatios, (0.0, 1.0, 0.0))
    )

    storeys = ifc.by_type("IfcBuildingStorey")
    assert [storey.Elevation for storey in storeys] == [0.0, 4.0]
    assert any(column in relation.RelatedElements and relation.RelatingStructure == storeys[1]
               for relation in ifc.by_type("IfcRelContainedInSpatialStructure"))
    global_ids = [entity.GlobalId for entity in ifc.by_type("IfcRoot")]
    assert len(global_ids) == len(set(global_ids))
    assert not ifc.by_type("IfcElementAssembly")


def test_ifc_preserves_unknown_member_without_inventing_a_section(tmp_path: Path):
    stable_id = "1c6d4f59-72f4-46bb-80a7-4231fb751cc2"
    model = {
        "project": {"id": "project-1", "name": "Workshop"},
        "levels": [{"name": "Level 1", "elevation": 0.0}],
        "elements": [{
            "id": stable_id,
            "class_name": "brace",
            "geometry": {"kind": "member", "p0": [0.0, 0.0, 0.0], "p1": [4.0, 3.0, 2.0]},
            "confidence": 0.4,
            "measured": True,
            "inferred": False,
            "review_status": "unreviewed",
        }],
    }

    path = export_ifc(model, tmp_path / "unknown-member.ifc")
    ifc = ifcopenshell.open(path)
    member = ifc.by_type("IfcBuildingElementProxy")[0]

    assert member.Representation is None
    pset = get_psets(member)["Pset_ScanToBIM"]
    assert pset["ElementId"] == stable_id
    assert pset["GeometryStatus"] == "unsupported_missing_section"
    assert not ifc.by_type("IfcExtrudedAreaSolid")


def test_ifc_marks_member_square_section_as_an_approximation(tmp_path: Path):
    model = {
        "project": {"id": "project-1", "name": "Workshop"},
        "levels": [{"name": "Level 1", "elevation": 0.0}],
        "elements": [{
            "id": "6b7912f3-2c7f-4293-8e2e-96ec6677f0db",
            "class_name": "brace",
            "geometry": {
                "kind": "member", "p0": [0.0, 0.0, 0.0],
                "p1": [4.0, 3.0, 2.0], "section_m": 0.12,
            },
        }],
    }

    path = export_ifc(model, tmp_path / "approximated-member.ifc")
    ifc = ifcopenshell.open(path)
    member = ifc.by_type("IfcBuildingElementProxy")[0]

    assert member.Representation is not None
    pset = get_psets(member)["Pset_ScanToBIM"]
    assert pset["GeometryStatus"] == "square_envelope_approximation"
    solid = ifc.by_type("IfcExtrudedAreaSolid")[0]
    assert (solid.SweptArea.XDim, solid.SweptArea.YDim) == (0.12, 0.12)
