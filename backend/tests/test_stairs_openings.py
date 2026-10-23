"""Stair flights and wall openings: synthetic clouds with a known answer."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from scan2bim.bim.ifc import export_ifc
from scan2bim.geometry.section import CloudGeometry
from scan2bim.recognition.geometric import DetectedElement
from scan2bim.recognition.openings import detect_openings
from scan2bim.recognition.stairs import detect_stairs


def _cloud(points: np.ndarray, tmp_path: Path) -> CloudGeometry:
    path = tmp_path / "positions.npy"
    np.save(path, points.astype(np.float32))
    return CloudGeometry(
        positions_path=path,
        origin=np.zeros(3),
        bbox_min=points.min(axis=0),
        bbox_max=points.max(axis=0),
        count=int(points.shape[0]),
    )


def _stair_cloud() -> np.ndarray:
    gx, gy = np.meshgrid(np.arange(0.0, 6.01, 0.10), np.arange(0.0, 4.01, 0.10))
    floor = np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)])
    upper = floor.copy()
    upper[:, 2] = 3.0
    # Flight: 3.0 m run, 1.2 m wide, rising 2.8 m from x=0.4 to x=3.4.
    t = np.arange(0.0, 3.001, 0.03)
    y = np.arange(2.0, 3.201, 0.03)
    tt, yy = np.meshgrid(t, y)
    flight = np.column_stack([0.4 + tt.ravel(), yy.ravel(), 0.1 + tt.ravel() * (2.8 / 3.0)])
    return np.vstack([floor, upper, flight])


def _wall_cloud(gap: tuple[float, float, float, float] | None = None) -> np.ndarray:
    xs = np.arange(0.0, 6.001, 0.05)
    zs = np.arange(0.0, 2.801, 0.05)
    parts = []
    for face_y in (-0.1, 0.1):
        xx, zz = np.meshgrid(xs, zs)
        mask = np.ones_like(xx, dtype=bool)
        if gap is not None:
            gx0, gx1, gz0, gz1 = gap
            mask &= ~((xx >= gx0) & (xx <= gx1) & (zz >= gz0) & (zz <= gz1))
        parts.append(np.column_stack([xx[mask], np.full(int(mask.sum()), face_y), zz[mask]]))
    return np.vstack(parts)


def _wall_element() -> DetectedElement:
    return DetectedElement(
        class_name="wall",
        geometry={
            "kind": "oriented_box",
            "center": [3.0, 0.0, 1.4],
            "sizes": {"length": 6.0, "thickness": 0.2, "height": 2.8},
            "rotation_z": 0.0,
        },
        bbox={"min": [0.0, -0.1, 0.0], "max": [6.0, 0.1, 2.8]},
        confidence=0.7,
        dimensions={"length_m": 6.0, "thickness_m": 0.2, "height_m": 2.8},
    )


def _levels() -> list[dict]:
    return [{"z": 0.0, "z_local": 0.0}, {"z": 3.0, "z_local": 3.0}]


# ---------------------------------------------------------------------- stairs
def test_stair_flight_detected_between_levels(tmp_path: Path):
    cloud = _cloud(_stair_cloud(), tmp_path)
    stairs = detect_stairs(cloud, _levels())
    assert len(stairs) == 1, [s.dimensions for s in stairs]
    stair = stairs[0]
    dims = stair.dimensions
    assert stair.class_name == "stair"
    assert 2.0 <= dims["rise_m"] <= 3.0, dims
    assert 0.9 <= dims["width_m"] <= 1.5, dims
    assert 30.0 <= dims["slope_deg"] <= 55.0, dims
    assert stair.inferred is True
    p0, p1 = stair.geometry["p0"], stair.geometry["p1"]
    assert abs(p0[2] - p1[2]) >= 2.0


def test_flat_slabs_are_not_stairs(tmp_path: Path):
    points = _stair_cloud()[:2400]  # floor and upper slab only
    cloud = _cloud(points, tmp_path)
    assert detect_stairs(cloud, _levels()) == []


def test_stairs_need_two_levels(tmp_path: Path):
    cloud = _cloud(_stair_cloud(), tmp_path)
    assert detect_stairs(cloud, [{"z": 0.0, "z_local": 0.0}]) == []


# -------------------------------------------------------------------- openings
def test_door_opening_detected(tmp_path: Path):
    cloud = _cloud(_wall_cloud(gap=(2.4, 3.4, 0.0, 2.1)), tmp_path)
    openings = detect_openings(cloud, [_wall_element()], _levels())
    assert len(openings) == 1, [(o.dimensions, o.metadata) for o in openings]
    opening = openings[0]
    dims = opening.dimensions
    assert dims["opening_kind"] == "door"
    assert 0.9 <= dims["width_m"] <= 1.1, dims
    assert 1.9 <= dims["height_m"] <= 2.3, dims
    assert dims["sill_m"] == 0.0
    assert opening.inferred is True


def test_window_opening_detected(tmp_path: Path):
    cloud = _cloud(_wall_cloud(gap=(2.4, 3.4, 1.0, 2.2)), tmp_path)
    openings = detect_openings(cloud, [_wall_element()], _levels())
    assert len(openings) == 1, [(o.dimensions, o.metadata) for o in openings]
    dims = openings[0].dimensions
    assert dims["opening_kind"] == "window"
    assert 0.9 <= dims["sill_m"] <= 1.1, dims
    assert 0.9 <= dims["height_m"] <= 1.3, dims


def test_unscanned_strip_is_not_an_opening(tmp_path: Path):
    # No points at all in the strip: this is a hole in the scan, not a void
    # in the wall. The missing lintel must veto the hypothesis.
    cloud = _cloud(_wall_cloud(gap=(2.4, 3.4, 0.0, 2.8)), tmp_path)
    assert detect_openings(cloud, [_wall_element()], _levels()) == []


def test_intact_wall_has_no_openings(tmp_path: Path):
    cloud = _cloud(_wall_cloud(), tmp_path)
    assert detect_openings(cloud, [_wall_element()], _levels()) == []


# ------------------------------------------------------------------------- IFC
def _ifc_element(element_id: str, class_name: str, geometry: dict, bbox: dict) -> dict:
    return {
        "id": element_id,
        "class_name": class_name,
        "geometry": geometry,
        "bbox": bbox,
        "confidence": 0.5,
        "confidence_kind": "heuristic",
        "measured": True,
        "inferred": True,
        "source": "geometric",
        "dimensions": {},
        "metadata": {},
        "review_status": "unreviewed",
    }


def test_ifc_exports_stair_and_opening_entities(tmp_path: Path):
    import ifcopenshell

    model = {
        "project": {"name": "test"},
        "levels": [{"z": 0.0}],
        "elements": [
            _ifc_element(
                "stair-0001",
                "stair",
                {
                    "kind": "member",
                    "p0": [0.0, 2.0, 0.1],
                    "p1": [3.0, 2.0, 2.9],
                    "section_m": 1.2,
                },
                {"min": [0.0, 1.4, 0.1], "max": [3.0, 2.6, 2.9]},
            ),
            _ifc_element(
                "opening-0001",
                "opening",
                {
                    "kind": "oriented_box",
                    "center": [2.9, 0.0, 1.05],
                    "sizes": {"length": 1.0, "thickness": 0.2, "height": 2.1},
                    "rotation_z": 0.0,
                },
                {"min": [2.4, -0.1, 0.0], "max": [3.4, 0.1, 2.1]},
            ),
        ],
    }
    path = export_ifc(model, tmp_path / "model.ifc", project_name="test")
    ifc = ifcopenshell.open(str(path))
    stairs = ifc.by_type("IfcStair")
    openings = ifc.by_type("IfcOpeningElement")
    assert len(stairs) == 1
    assert len(openings) == 1
    assert stairs[0].Representation is not None
    assert openings[0].Representation is not None
