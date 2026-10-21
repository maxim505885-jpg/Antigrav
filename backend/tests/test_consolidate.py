"""Consolidation: fragments must become engineering constructions, not counts."""
from __future__ import annotations

import math

from scan2bim.recognition.consolidate import consolidate
from scan2bim.recognition.geometric import DetectedElement


def _box(
    class_name: str,
    center: tuple[float, float, float],
    length: float,
    thickness: float,
    height: float,
    angle: float = 0.0,
) -> DetectedElement:
    cx, cy, cz = center
    z0, z1 = cz - height / 2, cz + height / 2
    ca, sa = math.cos(angle), math.sin(angle)
    corners = []
    for lx, ly in (
        (-length / 2, -thickness / 2),
        (length / 2, -thickness / 2),
        (length / 2, thickness / 2),
        (-length / 2, thickness / 2),
    ):
        corners.append((cx + lx * ca - ly * sa, cy + lx * sa + ly * ca))
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return DetectedElement(
        class_name=class_name,
        geometry={
            "kind": "oriented_box",
            "center": [cx, cy, cz],
            "sizes": {"length": length, "thickness": thickness, "height": height},
            "rotation_z": angle,
        },
        bbox={
            "min": [min(xs), min(ys), z0],
            "max": [max(xs), max(ys), z1],
        },
        confidence=0.6,
        dimensions={
            "length_m": length,
            "thickness_m": thickness,
            "height_m": height,
            "footprint_area_m2": length * thickness,
        },
        metadata={"material": None},
    )


LEVELS = [
    {"z": 0.0, "z_local": 0.0, "point_count": 1000, "confidence": 0.8, "method": "test"},
    {"z": 3.0, "z_local": 3.0, "point_count": 1000, "confidence": 0.8, "method": "test"},
    {"z": 6.0, "z_local": 6.0, "point_count": 1000, "confidence": 0.8, "method": "test"},
]


def test_collinear_wall_fragments_merge_into_one_wall():
    # Three fragments of one 12 m facade with doorway gaps of ~0.8 m.
    fragments = [
        _box("wall", (0.0, 5.0, 1.5), 4.0, 0.3, 3.0, angle=0.0),
        _box("wall", (4.8, 5.0, 1.5), 4.0, 0.3, 3.0, angle=0.0),
        _box("wall", (9.6, 5.0, 1.5), 4.0, 0.3, 3.0, angle=0.0),
    ]
    result, report = consolidate(fragments, LEVELS)
    walls = [e for e in result if e.class_name == "wall"]
    assert len(walls) == 1, [e.dimensions for e in walls]
    wall = walls[0]
    # ~13.6 m including the gaps: the doorway positions are now inside one wall.
    assert 13.0 < wall.dimensions["length_m"] < 14.2
    assert wall.dimensions["merged_from"] == 3
    assert 0.5 < wall.dimensions["merged_gap_m"] <= 1.2
    assert report.walls_produced == 1
    assert wall.dimensions["storey_count"] == 1
    assert wall.dimensions["level_base_z"] == 0.0
    assert wall.dimensions["level_top_z"] == 3.0


def test_non_collinear_walls_stay_separate():
    fragments = [
        _box("wall", (0.0, 5.0, 1.5), 4.0, 0.3, 3.0, angle=0.0),
        _box("wall", (5.0, 0.0, 1.5), 4.0, 0.3, 3.0, angle=math.pi / 2),
    ]
    result, _ = consolidate(fragments, LEVELS)
    assert len([e for e in result if e.class_name == "wall"]) == 2


def test_walls_on_parallel_lines_do_not_merge():
    # Same direction but 1.5 m apart: two different walls, not one.
    fragments = [
        _box("wall", (0.0, 5.0, 1.5), 4.0, 0.3, 3.0, angle=0.0),
        _box("wall", (0.0, 6.5, 1.5), 4.0, 0.3, 3.0, angle=0.0),
    ]
    result, _ = consolidate(fragments, LEVELS)
    assert len([e for e in result if e.class_name == "wall"]) == 2


def test_column_fragments_merge_into_one_shaft():
    # One physical column seen as two fragments: base part and upper part,
    # overlapping footprints, touching height ranges.
    fragments = [
        _box("column", (8.0, 8.0, 1.5), 0.5, 0.5, 3.0),
        _box("column", (8.05, 8.0, 4.4), 0.5, 0.5, 2.8),
    ]
    result, report = consolidate(fragments, LEVELS)
    columns = [e for e in result if e.class_name == "column"]
    assert len(columns) == 1, [e.dimensions for e in columns]
    shaft = columns[0]
    assert shaft.dimensions["merged_from"] == 2
    # Shaft spans from the base fragment bottom to the top fragment top.
    assert 5.5 < shaft.dimensions["height_m"] < 6.5
    assert shaft.dimensions["storey_count"] == 2
    assert report.columns_produced == 1


def test_columns_on_different_footprints_stay_separate():
    # Full-height columns (2 storeys): far apart, so no shaft merge.
    fragments = [
        _box("column", (2.0, 2.0, 3.0), 0.5, 0.5, 6.0),
        _box("column", (9.0, 9.0, 3.0), 0.5, 0.5, 6.0),
    ]
    result, _ = consolidate(fragments, LEVELS)
    assert len([e for e in result if e.class_name == "column"]) == 2


def test_single_storey_column_is_demoted_to_unknown():
    # A 2 m object on storey 2 only, in a 3-storey building: not a column.
    clutter = _box("column", (4.0, 4.0, 4.2), 0.4, 0.4, 2.0)
    real = _box("column", (7.0, 7.0, 3.0), 0.5, 0.5, 6.0)
    result, report = consolidate([clutter, real], LEVELS)
    columns = [e for e in result if e.class_name == "column"]
    unknowns = [e for e in result if e.class_name == "unknown"]
    assert len(columns) == 1
    assert columns[0].dimensions["height_m"] == 6.0
    assert len(unknowns) == 1
    assert unknowns[0].dimensions["demoted_from"] == "column"
    # The measured geometry survives: nothing is deleted, only reclassified.
    assert unknowns[0].dimensions["length_m"] == 0.4
    assert report.columns_demoted == 1


def test_column_spanning_two_storeys_survives():
    tall = _box("column", (7.0, 7.0, 3.0), 0.5, 0.5, 6.0)
    result, report = consolidate([tall], LEVELS)
    assert [e for e in result if e.class_name == "column"]
    assert report.columns_demoted == 0


def test_slab_binds_to_nearest_level():
    slab = DetectedElement(
        class_name="slab",
        geometry={"kind": "slab", "polygon": [[0, 0], [10, 0], [10, 8], [0, 8]], "z": 3.05},
        bbox={"min": [0, 0, 2.95], "max": [10, 8, 3.15]},
        confidence=0.5,
        dimensions={"area_m2": 80.0},
        metadata={"material": None},
    )
    result, _ = consolidate([slab], LEVELS)
    assert result[0].dimensions["level_index"] == 1
    assert result[0].dimensions["storey_count"] == 1


def test_single_storey_building_keeps_all_columns():
    # A one-storey shed: every column is legitimately single-storey.
    levels = LEVELS[:2]  # two levels -> one inter-level zone -> no demotion
    columns = [
        _box("column", (2.0, 2.0, 1.5), 0.4, 0.4, 3.0),
        _box("column", (6.0, 6.0, 1.5), 0.4, 0.4, 3.0),
    ]
    result, report = consolidate(columns, levels)
    assert len([e for e in result if e.class_name == "column"]) == 2
    assert report.columns_demoted == 0
