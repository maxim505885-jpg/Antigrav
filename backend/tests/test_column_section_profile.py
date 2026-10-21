"""Section evidence must not depend on the column's raster height offset."""
import math

import numpy as np
import pytest

from scan2bim.recognition.geometric import DetectedElement
from scan2bim.recognition import steel


def classify_at_height(b0, monkeypatch):
    monkeypatch.setitem(steel._GRID_STATE, "band", 0.5)
    center = np.array([2., 2.])
    footprint = steel._footprint_cells(center, 0, 1, 1, .1, 40, 40)
    occupied = np.zeros((30, 40, 40), dtype=bool)
    occupied[b0:b0 + 3] = footprint
    occupied[b0 + 3:b0 + 6, 19:21, 19:21] = True
    z0, z1 = b0 * .5, (b0 + 5.9) * .5
    element = DetectedElement("column", {"center": [2, 2, (z0 + z1) / 2], "rotation_z": 0},
        {"min": [1.5, 1.5, z0], "max": [2.5, 2.5, z1]}, .8,
        dimensions={"length_m": 1., "thickness_m": 1.})
    grid = {"res": .1, "band_occ": occupied, "min": np.zeros(3)}
    steel.classify_column_sections(grid, [element], np.zeros(3))
    return element


def test_stepped_profile_is_invariant_to_height_offset(monkeypatch):
    low = classify_at_height(0, monkeypatch)
    raised = classify_at_height(10, monkeypatch)
    assert low.dimensions["column_type"] == steel.COLUMN_TYPE_STEPPED
    for key in ("column_type", "base_area_m2", "top_area_m2", "section_fill", "section_coverage"):
        assert raised.dimensions[key] == low.dimensions[key]
    assert raised.dimensions["section_profile"][0]["z"] - low.dimensions["section_profile"][0]["z"] == pytest.approx(5)


def test_rotated_square_footprint_does_not_lose_corner_cells():
    areas = [steel._footprint_cells(np.array([3., 3.]), angle, 2., 2., .01, 600, 600).sum() * .01 ** 2
        for angle in (0, math.pi / 4)]
    assert areas[1] == pytest.approx(areas[0], rel=.02)


def test_empty_middle_band_uses_actual_densest_band_for_flange_signature(monkeypatch):
    monkeypatch.setitem(steel._GRID_STATE, "band", 0.5)
    results = []
    for b0 in (0, 10):
        occupied = np.zeros((30, 100, 100), dtype=bool)
        for band in (b0, b0 + 1, b0 + 5):
            occupied[band, 32:35, 32:68] = True
            occupied[band, 65:68, 32:68] = True
        z0, z1 = b0 * .5, (b0 + 5.9) * .5
        element = DetectedElement("column", {"center": [2.5, 2.5, (z0 + z1) / 2], "rotation_z": 0},
            {"min": [1.5, 1.5, z0], "max": [3.5, 3.5, z1]}, .8,
            dimensions={"length_m": 2., "thickness_m": 2.})
        steel.classify_column_sections({"res": .05, "band_occ": occupied, "min": np.zeros(3)}, [element], np.zeros(3))
        results.append(element.dimensions["column_type"])
    assert results == [steel.COLUMN_TYPE_BUILT_UP, steel.COLUMN_TYPE_BUILT_UP]


def test_merged_column_rectangle_matches_its_envelope_when_long_side_follows_y():
    from scan2bim.recognition.consolidate import _merge_column_group, _plan_polygon
    fragments = [DetectedElement("column", {"center": [2, 3, z + 1], "rotation_z": math.pi / 2},
        {"min": [1.8, 2.7, z], "max": [2.2, 3.3, z + 2]}, .8,
        dimensions={"length_m": .6, "thickness_m": .4}) for z in (0, 2)]
    merged = _merge_column_group(fragments)
    assert _plan_polygon(merged).bounds == pytest.approx((1.8, 2.7, 2.2, 3.3), abs=.001)
