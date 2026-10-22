"""Structural steel frame stage: bracing, column typing, structural-only output.

These guard three real defects found on the 40M-point production scan:

* horizontal bracing was rejected because the raw strip width saturates at
  1.3..1.55 m on a busy roof -- acceptance must come from point CONCENTRATION
  on the line, not from width;
* column section typing produced all-zero areas because the footprint was
  placed with a world centre on a raster indexed from the local origin -- the
  world->raster transform must subtract both ``origin`` and ``grid["min"]``;
* non-structural ``unknown`` fragments had to be excluded ("только
  конструктив, лишнего не надо").
"""
from __future__ import annotations

import math

import numpy as np

from scan2bim.geometry.section import CloudGeometry
from scan2bim.recognition.geometric import DetectedElement, structural_only
from scan2bim.recognition.steel import (
    BRACE_MIN_CONCENTRATION,
    COLUMN_TYPE_SOLID,
    COLUMN_TYPE_STEPPED,
    _dedup_brace_candidates,
    _diagonals_in_slices,
    _group_line,
    _group_segments,
    _line_concentration,
    classify_column_sections,
    measure_column_sections,
    typify_column_sections,
)


# ---------------------------------------------------------------- concentration
def _concentration_for_points(xy: np.ndarray) -> float:
    """Concentration of a horizontal line through the origin."""
    center = np.array([0.0, 0.0])
    direction = np.array([1.0, 0.0])
    length = float(xy[:, 0].max() - xy[:, 0].min())
    return _line_concentration(xy, center, direction, length)


def test_thin_member_scores_high_concentration():
    # A real brace: points hug the centreline within ~0.10 m.
    rng = np.random.default_rng(7)
    along = rng.uniform(-3.0, 3.0, 4000)
    across = rng.normal(0.0, 0.03, 4000)
    xy = np.column_stack([along, across])
    assert _concentration_for_points(xy) >= BRACE_MIN_CONCENTRATION


def test_uniform_clutter_scores_low_concentration():
    # Fill the whole +-0.60 m window evenly: no member on the line, only
    # background. Core share tends to core/window = 0.25.
    rng = np.random.default_rng(11)
    along = rng.uniform(-3.0, 3.0, 12000)
    across = rng.uniform(-0.6, 0.6, 12000)
    xy = np.column_stack([along, across])
    assert _concentration_for_points(xy) < BRACE_MIN_CONCENTRATION


def test_clutter_next_to_member_does_not_mask_it():
    # The production failure mode: a thin brace inside a crowded roof band.
    # Width saturates (~1.4 m), yet the core share still separates member
    # from the surrounding clutter.
    rng = np.random.default_rng(23)
    member_along = rng.uniform(-3.0, 3.0, 2500)
    member_across = rng.normal(0.0, 0.03, 2500)
    noise_along = rng.uniform(-3.0, 3.0, 2500)
    noise_across = rng.uniform(-0.6, 0.6, 2500)
    xy = np.column_stack(
        [
            np.concatenate([member_along, noise_along]),
            np.concatenate([member_across, noise_across]),
        ]
    )
    assert _concentration_for_points(xy) >= BRACE_MIN_CONCENTRATION


def test_concentration_is_zero_for_empty_or_tiny_neighbourhood():
    direction = np.array([1.0, 0.0])
    center = np.array([0.0, 0.0])
    assert _line_concentration(np.zeros((0, 2)), center, direction, 5.0) == 0.0
    few = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]])
    assert _line_concentration(few, center, direction, 5.0) == 0.0


# ---------------------------------------------------------------- column typing
def _grid_with_column_profile(occ_ratio_by_band: dict[int, float]) -> dict:
    """Occupancy grid where a column footprint is filled per band.

    Raster: 0.10 m cells, 120 x 120, 24 bands of 0.50 m. ``grid['min']`` is a
    NON-zero LOCAL origin so the world->raster transform is actually exercised.
    """
    res = 0.10
    nv = nu = 120
    nbands = 24
    band_occ = np.zeros((nbands, nv, nu), dtype=bool)
    # Column footprint: 6 x 6 cells at raster cell (60, 60).
    fp = np.zeros((nv, nu), dtype=bool)
    fp[57:63, 57:63] = True
    for band, ratio in occ_ratio_by_band.items():
        band_occ[band] = fp if ratio >= 1.0 else (fp & (np.arange(nv)[:, None] < 57 + int(6 * ratio)))
    return {
        "res": res,
        "nu": nu,
        "nv": nv,
        "nbands": nbands,
        "band_occ": band_occ,
        "min": np.array([100.0, -50.0, -2.0]),
        "total": 1000,
        "assumed_band_height": 0.50,
    }


def _column_element(origin: np.ndarray, z0_world: float, z1_world: float) -> DetectedElement:
    """Column whose WORLD centre sits above raster cell (60, 60)."""
    grid_min = np.array([100.0, -50.0, -2.0])
    res = 0.10
    centre_local = np.array([(60 + 0.5) * res, (60 + 0.5) * res])
    centre_world = centre_local + np.array([origin[0], origin[1]]) + grid_min[:2]
    length = thickness = 0.60
    zc = (z0_world + z1_world) / 2
    return DetectedElement(
        class_name="column",
        geometry={
            "kind": "oriented_box",
            "center": [float(centre_world[0]), float(centre_world[1]), zc],
            "sizes": {"length": length, "thickness": thickness, "height": z1_world - z0_world},
            "rotation_z": 0.0,
        },
        bbox={
            "min": [float(centre_world[0]) - length / 2, float(centre_world[1]) - thickness / 2, z0_world],
            "max": [float(centre_world[0]) + length / 2, float(centre_world[1]) + thickness / 2, z1_world],
        },
        confidence=0.6,
        dimensions={"length_m": length, "thickness_m": thickness, "height_m": z1_world - z0_world},
    )


def test_column_typing_uses_world_to_raster_transform():
    # Regression: the footprint used to be placed with a world centre on a
    # locally-indexed raster, so every area came out 0 and every column fell
    # back to "section undetermined".
    origin = np.array([3.5, -7.25, 1.5])
    grid_min = np.array([100.0, -50.0, -2.0])
    # World z range covering raster bands 4..19 (local z = world - origin_z).
    band_h = 0.50
    z0_world = float(grid_min[2] + origin[2] + 4 * band_h)
    z1_world = float(grid_min[2] + origin[2] + 19 * band_h)
    grid = _grid_with_column_profile({b: 1.0 for b in range(4, 20)})
    column = _column_element(origin, z0_world, z1_world)

    stats = classify_column_sections(grid, [column], origin)

    assert stats["columns_typed"] == 1
    assert column.dimensions["base_area_m2"] > 0
    assert column.dimensions["section_fill"] > 0


def test_stepped_crane_column_is_typed_from_area_profile():
    # Wide base, narrow top => stepped (crane column with a corbel step).
    origin = np.array([0.0, 0.0, 0.0])
    grid_min = np.array([100.0, -50.0, -2.0])
    band_h = 0.50
    z0_world = float(grid_min[2] + 4 * band_h)
    z1_world = float(grid_min[2] + 19 * band_h)
    occ = {b: 1.0 for b in range(4, 12)}   # base half: full 6x6 footprint
    occ.update({b: 0.34 for b in range(12, 20)})  # top half: only ~2 cells wide
    grid = _grid_with_column_profile(occ)
    column = _column_element(origin, z0_world, z1_world)

    classify_column_sections(grid, [column], origin)

    assert column.dimensions["column_type"] == COLUMN_TYPE_STEPPED
    assert column.dimensions["top_area_m2"] < column.dimensions["base_area_m2"]


def test_uniform_column_is_typed_solid():
    origin = np.array([0.0, 0.0, 0.0])
    grid_min = np.array([100.0, -50.0, -2.0])
    band_h = 0.50
    z0_world = float(grid_min[2] + 4 * band_h)
    z1_world = float(grid_min[2] + 19 * band_h)
    grid = _grid_with_column_profile({b: 1.0 for b in range(4, 20)})
    column = _column_element(origin, z0_world, z1_world)

    classify_column_sections(grid, [column], origin)

    assert column.dimensions["column_type"] == COLUMN_TYPE_SOLID
    assert column.dimensions["section_coverage"] > 0.9


def test_sparse_profile_is_reported_not_invented():
    # A column seen in only two scattered bands: the section cannot be
    # measured, and the code must NOT fabricate a type from empty bands.
    origin = np.array([0.0, 0.0, 0.0])
    grid_min = np.array([100.0, -50.0, -2.0])
    band_h = 0.50
    z0_world = float(grid_min[2] + 4 * band_h)
    z1_world = float(grid_min[2] + 19 * band_h)
    grid = _grid_with_column_profile({4: 1.0})  # a single measured band
    column = _column_element(origin, z0_world, z1_world)

    stats = classify_column_sections(grid, [column], origin)

    # <2 measured bands -> skipped entirely, no invented type.
    assert stats["columns_typed"] == 0
    assert "column_type" not in column.dimensions


# ---------------------------------------------------------------- structural only
def _element(class_name: str) -> DetectedElement:
    return DetectedElement(
        class_name=class_name,
        geometry={"kind": "oriented_box", "center": [0, 0, 0], "sizes": {"length": 1, "thickness": 1, "height": 1}},
        bbox={"min": [0, 0, 0], "max": [1, 1, 1]},
        confidence=0.5,
    )


def test_unknown_fragments_are_excluded_from_structural_model():
    elements = [
        _element("wall"),
        _element("column"),
        _element("slab"),
        _element("beam"),
        _element("truss"),
        _element("brace"),
        _element("unknown"),
        _element("unknown"),
    ]
    kept, dropped = structural_only(elements)

    assert dropped == 2
    assert [e.class_name for e in kept] == ["wall", "column", "slab", "beam", "truss", "brace"]


def test_structural_only_is_noop_when_no_unknowns():
    elements = [_element("wall"), _element("column")]
    kept, dropped = structural_only(elements)
    assert dropped == 0
    assert len(kept) == 2


# ------------------------------------------------- bracing across thin slices
def _candidate(
    center: tuple[float, float],
    angle_deg: float,
    length: float,
    conc: float,
    z0: float = 4.2,
    z1: float = 4.25,
) -> tuple:
    angle = math.radians(angle_deg)
    direction = np.array([math.cos(angle), math.sin(angle)])
    return (
        np.array(center, dtype=float),
        direction,
        length,
        conc,
        0.20,
        z0,
        z1,
        500,
    )


def test_dedup_keeps_one_member_found_in_overlapping_slices():
    # The same member, clipped differently by two slices: one candidate is
    # 5.2 m long at 0.61 concentration, the other 4.0 m at 0.88.
    first = _candidate((0.0, 0.0), 40.0, 5.2, 0.61)
    second = _candidate((0.3, 0.2), 38.0, 4.0, 0.88)

    merged = _dedup_brace_candidates([first, second])

    assert len(merged) == 1
    # The better supported fragment wins over the longer, diluter one.
    assert merged[0][3] == 0.88


def test_dedup_keeps_parallel_members_in_different_bays():
    # Cross bracing has two diagonals per bay; parallel members 3 m apart are
    # DIFFERENT members and must not collapse into one.
    left = _candidate((0.0, 0.0), 40.0, 6.0, 0.8)
    right = _candidate((0.0, 3.0), 40.0, 6.0, 0.8)

    merged = _dedup_brace_candidates([left, right])

    assert len(merged) == 2


def test_dedup_keeps_members_at_different_heights():
    low = _candidate((0.0, 0.0), 40.0, 6.0, 0.8, z0=4.2, z1=4.25)
    high = _candidate((0.0, 0.0), 40.0, 6.0, 0.8, z0=7.2, z1=7.25)

    merged = _dedup_brace_candidates([low, high])

    assert len(merged) == 2


def test_thin_slice_finds_brace_hidden_under_dense_deck_plane():
    # Production failure mode: the bracing member sits just above a densely
    # sampled roof deck. Measure the whole band and the deck dominates the
    # raster and the +-0.6 m window; a thin slice above the deck isolates the
    # member. `_diagonals_in_slices` must return it.
    rng = np.random.default_rng(5)
    angle = math.radians(40.0)
    direction = np.array([math.cos(angle), math.sin(angle)])
    along = rng.uniform(0.0, 6.0, 3000)
    across = rng.normal(0.0, 0.03, 3000)
    brace_xy = np.outer(along, direction) + np.outer(across, np.array([-direction[1], direction[0]]))
    brace = np.column_stack(
        [brace_xy[:, 0], brace_xy[:, 1], np.full(3000, 1.20)]
    )

    deck_x, deck_y = np.mgrid[-2.0:8.0:0.05, -2.0:8.0:0.05]
    deck = np.column_stack(
        [deck_x.ravel(), deck_y.ravel(), np.full(deck_x.size, 0.80)]
    )
    # A level band has thickness: sparse points above the member (truss
    # top-chord nodes, purlins) keep the slice loop running past it, so a slice
    # exists that contains the brace and NOT the deck plane.
    above = np.column_stack(
        [rng.uniform(-2.0, 8.0, 120), rng.uniform(-2.0, 8.0, 120), rng.uniform(1.50, 1.58, 120)]
    )
    points = np.vstack([brace, deck, above]).astype(np.float32)

    behind_deck = _line_concentration(
        brace_xy.astype(np.float32), brace_xy.mean(axis=0).astype(np.float32), direction, 6.0
    )
    candidates = _diagonals_in_slices(points, axis=0.0)

    assert behind_deck >= BRACE_MIN_CONCENTRATION  # the member itself is clean
    assert len(candidates) >= 1
    found = max(candidates, key=lambda item: item[2])
    assert found[2] >= 5.0           # the whole member, not a stub
    assert found[3] >= BRACE_MIN_CONCENTRATION


def _hough_segment(p0: tuple[float, float], p1: tuple[float, float]) -> dict:
    start = np.array(p0, dtype=float)
    end = np.array(p1, dtype=float)
    delta = end - start
    length = float(np.linalg.norm(delta))
    angle = math.atan2(float(delta[1]), float(delta[0]))
    return {
        "p0": start,
        "p1": end,
        "mid": (start + end) / 2,
        "dir": np.array([math.cos(angle), math.sin(angle)]),
        "angle": angle,
        "angle_deg": math.degrees(angle) % 180.0,
        "length": length,
    }


def test_collinear_diagonal_fragments_merge_into_one_member():
    # Production failure mode: one inter-truss diagonal leaves the Hough as
    # three overlapping pieces; without merging, the model shows three braces
    # where the hall has one.
    fragments = [
        _hough_segment((0.0, 0.0), (1.2, 1.2)),
        _hough_segment((1.0, 1.0), (2.1, 2.1)),
        _hough_segment((2.0, 2.0), (3.0, 3.0)),
    ]

    merged = [_group_line(group) for group in _group_segments(fragments)]

    assert len(merged) == 1
    assert merged[0][2] > 3.5  # merged extent, not a 1.7 m stub


def test_parallel_diagonals_of_a_cross_brace_stay_separate():
    # X bracing: two diagonals crossing in the same plane are different members.
    rising = _hough_segment((0.0, 0.0), (3.0, 3.0))
    falling = _hough_segment((0.0, 3.0), (3.0, 0.0))

    merged = [_group_line(group) for group in _group_segments([rising, falling])]

    assert len(merged) == 2


# ------------------------------------- column section completion / typification
def _section_grid(specs: list[tuple[float, float, float, float, str]]) -> dict:
    """Occupancy raster with synthetic column faces.

    ``faces`` is what the scanner saw of the section: all four sides, a corner
    of two adjacent sides, two opposite sides, or a single side.
    """
    res = 0.10
    n = 80
    plan = np.zeros((n, n), dtype=bool)
    band = 1.5 * res
    for cx, cy, length, thickness, faces in specs:
        x0, x1 = cx - length / 2, cx + length / 2
        y0, y1 = cy - thickness / 2, cy + thickness / 2
        for j in range(max(0, int(y0 / res)), min(n, int(y1 / res) + 1)):
            for i in range(max(0, int(x0 / res)), min(n, int(x1 / res) + 1)):
                x, y = (i + 0.5) * res, (j + 0.5) * res
                if not (x0 <= x <= x1 and y0 <= y <= y1):
                    continue
                on_x0 = x <= x0 + band
                on_x1 = x >= x1 - band
                on_y0 = y <= y0 + band
                on_y1 = y >= y1 - band
                keep = {
                    "all": True,
                    "corner": on_x1 or on_y1,
                    "opposite": on_x0 or on_x1,
                    "one": on_x1,
                }[faces]
                plan[j, i] = bool(keep)
    return {
        "res": res,
        "band_occ": plan[None, :, :],
        "min": np.array([0.0, 0.0, 0.0]),
        "nu": n,
        "nv": n,
        "nbands": 1,
        "assumed_band_height": 0.5,
        "total": int(plan.sum()),
    }


def _section_column(cx: float, cy: float, length: float, thickness: float) -> DetectedElement:
    return DetectedElement(
        class_name="column",
        geometry={
            "kind": "oriented_box",
            "center": [cx, cy, 2.0],
            "sizes": {"length": length, "thickness": thickness, "height": 3.0},
            "rotation_z": 0.0,
        },
        bbox={
            "min": [cx - length / 2, cy - thickness / 2, 0.5],
            "max": [cx + length / 2, cy + thickness / 2, 3.5],
        },
        confidence=0.6,
        dimensions={
            "length_m": length,
            "thickness_m": thickness,
            "height_m": 3.0,
            "footprint_area_m2": length * thickness,
        },
    )


def test_section_is_completed_from_two_visible_sides():
    # A corner of two adjacent faces is enough to draw the full rectangle: a
    # leg of the corner spans the whole length, the other spans the whole
    # thickness.
    grid = _section_grid([(2.0, 2.0, 0.40, 0.30, "corner")])
    column = _section_column(2.0, 2.0, 0.40, 0.30)

    typify_column_sections(grid, [column], np.zeros(3))

    assert column.dimensions["sides_visible"] == 2
    assert column.dimensions["section_status"] == "completed_from_2_sides"
    assert abs(column.geometry["sizes"]["length"] - 0.40) <= 0.005
    assert abs(column.geometry["sizes"]["thickness"] - 0.30) <= 0.005


def test_section_is_completed_from_two_opposite_sides():
    # 0.60 m: at 0.40 m the two face bands of a 0.10 m raster would overlap and
    # the synthetic section would look solid from every side.
    grid = _section_grid([(2.0, 2.0, 0.60, 0.60, "opposite")])
    column = _section_column(2.0, 2.0, 0.60, 0.60)

    typify_column_sections(grid, [column], np.zeros(3))

    assert column.dimensions["sides_visible"] == 2
    assert column.dimensions["section_status"] == "completed_from_2_sides"


def test_single_visible_side_is_made_square():
    # One face fixes one axis only; the other is mirrored so the plan drawing
    # still gets a closed rectangle.
    grid = _section_grid([(2.0, 2.0, 0.60, 0.60, "one")])
    column = _section_column(2.0, 2.0, 0.60, 0.60)

    typify_column_sections(grid, [column], np.zeros(3))

    assert column.dimensions["sides_visible"] == 1
    assert column.dimensions["section_status"] == "completed_square_1_side"
    assert abs(column.geometry["sizes"]["length"] - column.geometry["sizes"]["thickness"]) <= 0.005


def test_corner_cells_do_not_fake_extra_visible_sides():
    # Cells of the perpendicular face sit at the ends of this side; they must
    # not turn a 2-side corner into a 4-side measurement.
    grid = _section_grid([(2.0, 2.0, 0.40, 0.40, "corner")])
    column = _section_column(2.0, 2.0, 0.40, 0.40)

    typify_column_sections(grid, [column], np.zeros(3))

    assert column.dimensions["sides_visible"] == 2


def test_column_sections_snap_to_shared_types():
    specs = [
        (1.0, 1.0, 0.39, 0.39, "all"),
        (3.0, 1.0, 0.41, 0.40, "all"),
        (5.0, 1.0, 0.40, 0.41, "corner"),
        (1.0, 4.0, 0.54, 0.54, "all"),
        (3.0, 4.0, 0.56, 0.55, "all"),
        (5.0, 4.0, 0.55, 0.56, "all"),
    ]
    grid = _section_grid(specs)
    columns = [_section_column(*spec[:4]) for spec in specs]

    stats = typify_column_sections(grid, columns, np.zeros(3))

    assert len(stats["column_section_types"]) == 2
    sizes = {
        (round(c.geometry["sizes"]["length"], 2), round(c.geometry["sizes"]["thickness"], 2))
        for c in columns
    }
    assert sizes == {(0.40, 0.40), (0.55, 0.55)}
    assert all(c.dimensions["section_source"] == "nominal" for c in columns)
    assert all(c.dimensions["section_type"] in {"К1", "К2"} for c in columns)


def test_off_type_column_keeps_its_measured_size():
    specs = [
        (1.0, 1.0, 0.40, 0.40, "all"),
        (3.0, 1.0, 0.41, 0.40, "all"),
        (5.0, 1.0, 0.80, 0.80, "all"),
    ]
    grid = _section_grid(specs)
    columns = [_section_column(*spec[:4]) for spec in specs]

    stats = typify_column_sections(grid, columns, np.zeros(3))

    assert len(stats["column_section_types"]) == 1
    big = columns[2]
    assert big.dimensions["section_source"] == "measured"
    assert big.dimensions["section_status"] == "unique_section"
    assert abs(big.geometry["sizes"]["length"] - 0.80) <= 0.01


def test_typification_keeps_the_measured_section_as_evidence():
    specs = [(1.0, 1.0, 0.39, 0.41, "all"), (3.0, 1.0, 0.41, 0.39, "all")]
    grid = _section_grid(specs)
    columns = [_section_column(*spec[:4]) for spec in specs]

    typify_column_sections(grid, columns, np.zeros(3))

    for column, spec in zip(columns, specs):
        measured = column.dimensions["measured_section_m"]
        assert measured == [round(spec[2], 3), round(spec[3], 3)]
        assert column.dimensions["section_residual_mm"] >= 0


def _column_cloud(
    length: float,
    thickness: float,
    tmp_path,
    center: tuple[float, float] = (0.0, 0.0),
) -> CloudGeometry:
    """Hollow rectangular column as a point cloud (four faces, 1 cm sampling)."""
    rng = np.random.default_rng(3)
    along = np.arange(-length / 2, length / 2 + 1e-9, 0.01)
    across = np.arange(-thickness / 2, thickness / 2 + 1e-9, 0.01)
    faces = []
    for z in (0.5, 1.0, 1.5, 2.0):
        for x in (-length / 2, length / 2):
            faces.append(np.column_stack([np.full(across.size, x), across, np.full(across.size, z)]))
        for y in (-thickness / 2, thickness / 2):
            faces.append(np.column_stack([along, np.full(along.size, y), np.full(along.size, z)]))
    points = np.vstack(faces)
    points[:, 0] += center[0]
    points[:, 1] += center[1]
    points = points + rng.normal(0.0, 0.004, points.shape)
    path = tmp_path / "positions.npy"
    np.save(path, points.astype(np.float32))
    return CloudGeometry(
        positions_path=path,
        origin=np.zeros(3),
        bbox_min=points.min(axis=0) - 0.10,
        bbox_max=points.max(axis=0) + 0.10,
        count=int(points.shape[0]),
    )


def test_section_is_measured_from_points_not_grid_cells(tmp_path):
    # The occupancy grid found this column as 0.50 x 0.30 (cell steps); the
    # points say 0.42 x 0.21. The drawn section must follow the points.
    geom = _column_cloud(0.42, 0.21, tmp_path)
    column = _section_column(0.0, 0.0, 0.50, 0.30)

    measured = measure_column_sections(geom, [column])

    record = measured[0]
    assert abs(record["length"] - 0.42) <= 0.03
    assert abs(record["thickness"] - 0.21) <= 0.03
    assert record["faces_along"] == 2
    assert record["faces_across"] == 2
    assert abs(math.sin(2 * record["angle"])) <= 0.10


def test_point_measurement_keeps_the_column_position(tmp_path):
    # Regression: the centre was computed in window coordinates and the window
    # origin was not added back, so every column collapsed onto the cloud
    # origin and the whole hall showed ten column positions.
    geom = _column_cloud(0.42, 0.21, tmp_path, center=(3.0, -4.0))
    column = _section_column(3.0, -4.0, 0.50, 0.30)

    measured = measure_column_sections(geom, [column])

    assert abs(measured[0]["center"][0] - 3.0) <= 0.05
    assert abs(measured[0]["center"][1] + 4.0) <= 0.05


def test_point_measurement_feeds_the_type_size(tmp_path):
    geom = _column_cloud(0.42, 0.21, tmp_path)
    column = _section_column(0.0, 0.0, 0.50, 0.30)
    sibling = _section_column(0.0, 0.0, 0.50, 0.30)
    measured = measure_column_sections(geom, [column])

    # Two columns of the same real size: with point measurements they land in
    # ONE type, and the coarse 0.50 x 0.30 footprint is replaced.
    stats = typify_column_sections(
        _section_grid([]), [column, sibling], np.zeros(3), {0: measured[0], 1: measured[0]}
    )

    assert len(stats["column_section_types"]) == 1
    assert abs(column.geometry["sizes"]["length"] - 0.42) <= 0.03
    assert abs(column.geometry["sizes"]["thickness"] - 0.21) <= 0.03


def test_slices_do_not_invent_bracing_from_uniform_clutter():
    rng = np.random.default_rng(17)
    clutter = np.column_stack(
        [
            rng.uniform(0.0, 8.0, 40000),
            rng.uniform(0.0, 8.0, 40000),
            rng.uniform(0.8, 1.6, 40000),
        ]
    ).astype(np.float32)

    assert _diagonals_in_slices(clutter, axis=0.0) == []
