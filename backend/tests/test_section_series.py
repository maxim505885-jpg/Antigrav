"""Multi-height section series keep measured changes and unknowns explicit."""
import numpy as np
import pytest

from scan2bim.structure.section_fitting import fit_column_section_series


def rectangle_points(sides=(0.5, 0.4), edges=(0, 1, 2, 3), origin=(0.0, 0.0)):
    a, b = sides
    corners = np.asarray([[0.0, 0.0], [a, 0.0], [a, b], [0.0, b]]) + origin
    return np.concatenate([
        corners[index] + np.linspace(0.0, 1.0, 80)[:, None]
        * (corners[(index + 1) % 4] - corners[index])
        for index in edges
    ])


def test_section_series_preserves_steps_and_dimension_ranges():
    lower = rectangle_points((0.5, 0.4))
    upper = rectangle_points((0.7, 0.4), origin=(10.0, -3.0))
    lower_before, upper_before = lower.copy(), upper.copy()

    result = fit_column_section_series([
        {"z_m": 6.0, "points_xy": upper, "source_point_ids": list(range(1000, 1320))},
        {"z_m": 1.0, "points_xy": lower, "source_point_ids": list(range(320))},
    ])

    assert [item["z_m"] for item in result["section_slices"]] == [1.0, 6.0]
    measured = [item["hypotheses"][0]["side_lengths_m"] for item in result["section_slices"]]
    assert sorted(measured[0]) == pytest.approx([0.4, 0.5], abs=0.005)
    assert sorted(measured[1]) == pytest.approx([0.4, 0.7], abs=0.005)
    assert result["profile_variation_status"] == "observed_variation"
    assert result["dimension_ranges_m"]["short_side"]["range_m"] == pytest.approx(0.0, abs=0.005)
    assert result["dimension_ranges_m"]["long_side"]["range_m"] == pytest.approx(0.2, abs=0.01)
    assert result["engineering_status"] == "not_assessed"
    assert np.array_equal(lower, lower_before)
    assert np.array_equal(upper, upper_before)


def test_section_series_reports_repeatable_dimensions_without_assigning_a_type():
    first = rectangle_points((0.5, 0.4))
    second = rectangle_points((0.5, 0.4), origin=(6.0, 1.0))

    result = fit_column_section_series([
        {"z_m": 1.0, "points_xy": first},
        {"z_m": 8.0, "points_xy": second},
    ])

    assert result["profile_variation_status"] == "no_variation_observed"
    assert result["dimension_ranges_m"]["short_side"]["range_m"] == pytest.approx(0.0, abs=1e-9)
    assert result["dimension_ranges_m"]["long_side"]["range_m"] == pytest.approx(0.0, abs=1e-9)
    assert all("type_id" not in item for item in result["section_slices"])
    assert result["engineering_status"] == "not_assessed"


def test_section_series_keeps_sparse_heights_unknown_and_maps_source_ids():
    points = rectangle_points()
    source_ids = list(range(9000, 9320))
    result = fit_column_section_series([
        {"z_m": 2.0, "points_xy": points, "source_point_ids": source_ids},
        {"z_m": 7.0, "points_xy": [[0.0, 0.0]], "source_point_ids": [42]},
    ])

    complete, sparse = result["section_slices"]
    assert complete["status"] == "proposed"
    assert complete["observed_faces"][0]["source_point_ids"]
    assert set(complete["observed_faces"][0]["source_point_ids"]).issubset(source_ids)
    assert sparse["status"] == "unknown"
    assert sparse["source_point_ids"] == [42]
    assert result["profile_variation_status"] == "insufficient"
    assert result["review_required"] is True


def test_section_series_does_not_call_profile_constant_across_an_unknown_height():
    points = rectangle_points()
    result = fit_column_section_series([
        {"z_m": 1.0, "points_xy": points},
        {"z_m": 5.0, "points_xy": []},
        {"z_m": 9.0, "points_xy": points},
    ])

    assert result["profile_variation_status"] == "incomplete"
    assert result["section_slices"][1]["status"] == "unknown"


def test_section_series_completes_only_explicit_known_dimensions():
    points = rectangle_points(edges=(0, 3))
    result = fit_column_section_series([
        {"z_m": 3.5, "points_xy": points, "source_point_ids": list(range(160))},
    ], known_sides_m=(0.5, 0.4))

    item = result["section_slices"][0]["hypotheses"][0]
    assert item["dimension_source"] == "explicit_input"
    assert item["observed_edge_count"] == 2
    assert item["inferred_edge_count"] == 2
    assert item["inferred"] is True
    assert item["source_point_ids"]
    assert result["engineering_status"] == "not_assessed"


def test_section_series_rejects_duplicate_z_and_bad_source_mapping():
    points = rectangle_points()
    source_ids = list(range(len(points)))
    with pytest.raises(ValueError, match="unique.*z_m"):
        fit_column_section_series([
            {"z_m": 1.0, "points_xy": points},
            {"z_m": 1.0, "points_xy": points},
        ])
    with pytest.raises(ValueError, match="source_point_ids.*match"):
        fit_column_section_series([
            {"z_m": 1.0, "points_xy": points, "source_point_ids": source_ids[:-1]},
        ])


def test_circle_section_is_reported_as_a_source_linked_non_rectangular_candidate():
    angles = np.linspace(0, 2 * np.pi, 720, endpoint=False)
    circle = np.column_stack((2.0 + 0.25 * np.cos(angles), -1.0 + 0.25 * np.sin(angles)))
    source_ids = np.arange(5000, 5000 + len(circle), dtype=np.int64)

    result = fit_column_section_series([{
        "z_m": 4.0,
        "points_xy": circle,
        "source_point_ids": source_ids.tolist(),
    }], known_sides_m=(0.5, 0.4))

    section = result["section_slices"][0]
    assert section["status"] == "unknown"
    assert section["hypotheses"] == []
    circle = section["shape_hypotheses"][0]
    assert circle["shape"] == "circle"
    assert circle["diameter_m"] == pytest.approx(0.5, abs=0.008)
    assert circle["review_required"] is True
    assert circle["engineering_status"] == "not_assessed"
    assert set(circle["source_point_ids"]).issubset(set(source_ids.tolist()))


def test_circular_sections_keep_diameter_change_visible_across_height_with_clutter():
    angles = np.linspace(0, 2 * np.pi, 720, endpoint=False)
    first = np.column_stack((0.25 * np.cos(angles), 0.25 * np.sin(angles)))
    second = np.column_stack((2.0 + 0.30 * np.cos(angles), -1.0 + 0.30 * np.sin(angles)))
    clutter = np.random.default_rng(7).uniform(-0.5, 0.5, size=(180, 2))

    result = fit_column_section_series([
        {"z_m": 7.0, "points_xy": second},
        {"z_m": 1.0, "points_xy": np.vstack((first, clutter))},
    ])

    assert [item["z_m"] for item in result["shape_measurements_by_height_m"]] == [1.0, 7.0]
    assert [item["diameter_m"] for item in result["shape_measurements_by_height_m"]] == pytest.approx([0.5, 0.6], abs=0.01)
    assert result["shape_diameter_range_m"]["range_m"] == pytest.approx(0.1, abs=0.015)
    assert result["shape_variation_status"] == "observed_variation"
    assert result["engineering_status"] == "not_assessed"


def test_partial_circular_arc_stays_unknown_instead_of_becoming_a_full_circle():
    angles = np.linspace(0, np.deg2rad(190), 400)
    arc = np.column_stack((0.25 * np.cos(angles), 0.25 * np.sin(angles)))

    result = fit_column_section_series([{"z_m": 2.0, "points_xy": arc}], known_sides_m=(0.5, 0.4))

    section = result["section_slices"][0]
    assert section["shape_hypotheses"] == []
    assert section["status"] in {"unknown", "open_section"}


def test_built_up_i_section_is_not_forced_into_a_circular_or_rectangular_type():
    outline = np.asarray([
        [0.0, 0.0], [0.4, 0.0], [0.4, 0.1], [0.28, 0.1],
        [0.28, 0.3], [0.4, 0.3], [0.4, 0.4], [0.0, 0.4],
        [0.0, 0.3], [0.12, 0.3], [0.12, 0.1], [0.0, 0.1],
    ])
    points = np.concatenate([
        start + np.linspace(0, 1, 80)[:, None] * (end - start)
        for start, end in zip(outline, np.roll(outline, -1, axis=0))
    ])

    result = fit_column_section_series([{"z_m": 3.0, "points_xy": points}], known_sides_m=(0.4, 0.4))

    section = result["section_slices"][0]
    assert section["shape_hypotheses"] == []
    assert section["shape_status"] == "unknown"
    assert section["status"] == "ambiguous"
    assert all(item["shape_interpretation"] == "outer_envelope_only" for item in section["hypotheses"])
    assert result["shape_variation_status"] == "insufficient"
