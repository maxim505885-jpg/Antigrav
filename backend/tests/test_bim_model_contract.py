"""The neutral BIM exchange model must be safe for CAD/BIM consumers."""
import copy
import math

import pytest

from scan2bim.bim.model import build_model, validate_bim_model


def _inputs():
    project = {"id": "project-1", "name": "Workshop"}
    cloud = {"id": "cloud-1", "name": "FARO pilot", "source_format": "e57",
        "origin_x": 100.0, "origin_y": 200.0, "origin_z": 0.0, "point_count": 42}
    element = {
        "id": "column-1", "class_name": "column",
        "geometry": {"kind": "oriented_box", "center": [10.0, 20.0, 4.0],
            "sizes": {"length": 0.5, "thickness": 0.4, "height": 8.0}, "rotation_z": 0.0},
        "bbox": {"min": [9.75, 19.8, 0.0], "max": [10.25, 20.2, 8.0]},
        "confidence": 0.7, "measured": True, "inferred": False, "source": "geometric",
        "review_status": "unreviewed", "dimensions": {},
    }
    return project, cloud, element


def test_bim_exchange_declares_source_cloud_coordinate_frame_in_metres():
    project, cloud, element = _inputs()

    model = build_model(project, cloud, [element])

    assert model["schema"] == "scan2bim.bim/1.0"
    assert model["units"] == "m"
    assert model["coordinate_frame"] == {
        "id": "source_cloud_world", "units": "m", "vertical_axis": "Z",
    }


def test_bim_exchange_preserves_recognition_metadata_for_reproducible_review():
    project, cloud, element = _inputs()
    element["metadata"] = {
        "method": "vertical occupancy grid",
        "support_points": 128,
        "source_point_ids": [2, 8, 21],
    }

    model = build_model(project, cloud, [element])

    assert model["elements"][0]["metadata"] == element["metadata"]


def test_bim_v1_payload_without_additive_metadata_remains_valid():
    project, cloud, element = _inputs()
    model = build_model(project, cloud, [element])
    del model["elements"][0]["metadata"]

    validate_bim_model(model)


def test_bim_exchange_rejects_duplicate_element_ids():
    project, cloud, element = _inputs()

    with pytest.raises(ValueError, match="unique.*element IDs"):
        build_model(project, cloud, [element, copy.deepcopy(element)])


def test_bim_exchange_derives_missing_bbox_from_supported_geometry_without_mutating_input():
    from scan2bim.structure.column_annotations import column_snapshot_sha256

    project, cloud, element = _inputs()
    element["bbox"] = {}

    model = build_model(project, cloud, [element])

    assert model["elements"][0]["bbox"] == {
        "min": [9.75, 19.8, 0.0], "max": [10.25, 20.2, 8.0],
    }
    assert element["bbox"] == {}
    assert column_snapshot_sha256([element], cloud) == column_snapshot_sha256(model["elements"], cloud)


def test_bim_exchange_does_not_invent_member_thickness_when_section_is_unknown():
    project, cloud, element = _inputs()
    element["geometry"] = {"kind": "member", "p0": [1.0, 2.0, 3.0], "p1": [4.0, 6.0, 8.0]}
    element["bbox"] = {}

    model = build_model(project, cloud, [element])

    assert model["elements"][0]["bbox"] == {
        "min": [1.0, 2.0, 3.0], "max": [4.0, 6.0, 8.0],
    }
    assert "section_m" not in model["elements"][0]["geometry"]


def test_bim_exchange_expands_member_bounds_only_by_explicit_section():
    project, cloud, element = _inputs()
    element["geometry"] = {
        "kind": "member", "p0": [1.0, 2.0, 3.0], "p1": [4.0, 6.0, 8.0], "section_m": 0.2,
    }
    element["bbox"] = {}

    model = build_model(project, cloud, [element])

    assert model["elements"][0]["bbox"] == {
        "min": [0.9, 1.9, 2.9], "max": [4.1, 6.1, 8.1],
    }


def test_ifc_export_revalidates_versioned_exchange_contract(tmp_path):
    from scan2bim.bim.ifc import export_ifc

    project, cloud, element = _inputs()
    model = build_model(project, cloud, [element])
    model["coordinate_frame"]["units"] = "mm"

    with pytest.raises(ValueError, match="coordinate_frame.units"):
        export_ifc(model, tmp_path / "invalid.ifc")


@pytest.mark.parametrize("mutation", [
    lambda element: element["geometry"]["center"].__setitem__(0, math.nan),
    lambda element: element["geometry"]["sizes"].__setitem__("height", 0.0),
    lambda element: element["bbox"]["max"].__setitem__(2, -1.0),
])
def test_bim_exchange_rejects_nonfinite_or_degenerate_geometry(mutation):
    project, cloud, element = _inputs()
    mutation(element)

    with pytest.raises(ValueError):
        build_model(project, cloud, [element])
