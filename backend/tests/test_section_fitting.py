"""Observed faces and explicit dimensions must stay distinct from completion."""
import math

import numpy as np
import pytest

from scan2bim.structure.section_fitting import fit_rectangular_section


def rectangle(*, sides=(0.5, 0.4), edges=(0, 1, 2, 3), angle=0.0, origin=(0.0, 0.0), noise=.0006):
    rng = np.random.default_rng(19)
    a, b = sides
    corners = np.array([[0, 0], [a, 0], [a, b], [0, b]], dtype=float)
    points = np.concatenate([corners[i] + np.linspace(0, 1, 200)[:, None] * (corners[(i + 1) % 4] - corners[i])
        for i in edges])
    points += rng.normal(0, noise, points.shape)
    rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    return points @ rotation.T + origin


def test_four_observed_faces_propose_a_measured_envelope_without_catalog_name():
    result = fit_rectangular_section(rectangle(angle=.17))
    assert result["status"] == "proposed"
    item = result["hypotheses"][0]
    assert sorted(item["side_lengths_m"]) == pytest.approx([.4, .5], abs=.008)
    assert item["observed_edge_count"] == 4 and item["inferred_edge_count"] == 0
    assert len(item["corners_world_m"]) == 4
    assert item["review_required"] is True
    assert item["shape_interpretation"] == "outer_envelope_only"
    assert all(edge["coverage_fraction"] > .9 for edge in item["edge_observation_coverage"])


def test_two_adjacent_faces_with_known_sides_complete_four_edges_as_a_hypothesis():
    points = rectangle(edges=(0, 3), angle=.35)
    result = fit_rectangular_section(points, known_sides_m=(.5, .4))
    assert result["status"] == "proposed"
    item = result["hypotheses"][0]
    assert sorted(item["side_lengths_m"]) == pytest.approx([.4, .5])
    assert item["observed_edge_count"] == 2 and item["inferred_edge_count"] == 2
    assert item["dimension_source"] == "explicit_input"
    assert item["review_required"] is True and item["inferred"] is True


def test_hypothesis_reports_observed_edge_coverage_and_keeps_inferred_edges_unobserved():
    result = fit_rectangular_section(rectangle(edges=(0, 3)), known_sides_m=(.7, .6))
    item = result["hypotheses"][0]
    coverage = item["edge_observation_coverage"]
    assert len(coverage) == 4
    measured = [edge for edge in coverage if edge["source_face_ids"]]
    unobserved = [edge for edge in coverage if not edge["source_face_ids"]]
    assert len(measured) == 2 and len(unobserved) == 2
    assert all(0 < edge["coverage_fraction"] < 1 for edge in measured)
    assert all(edge["coverage_fraction"] == 0 and edge["unobserved_fraction"] == 1 for edge in unobserved)
    assert all(edge["length_m"] > 0 for edge in coverage)


def test_partial_corner_without_known_sides_does_not_invent_full_dimensions():
    result = fit_rectangular_section(rectangle(edges=(0, 3)))
    assert result["status"] == "open_section"
    assert result["hypotheses"] == []
    assert result["open_corners"]
    assert all(face["span_kind"] == "observed_span_lower_bound" for face in result["observed_faces"])


def test_a_single_face_and_a_round_contour_do_not_become_rectangles():
    line = rectangle(edges=(0,))
    circle = np.column_stack([np.cos(np.linspace(0, 2 * math.pi, 800)), np.sin(np.linspace(0, 2 * math.pi, 800))]) * .2
    for points in (line, circle):
        assert fit_rectangular_section(points, known_sides_m=(.5, .4))["hypotheses"] == []


def test_closed_observation_conflicting_with_known_sides_is_not_snapped():
    result = fit_rectangular_section(rectangle(sides=(.7, .4)), known_sides_m=(.5, .4))
    assert all(sorted(item["side_lengths_m"]) != [.4, .5] for item in result["hypotheses"])
    assert result["dimension_conflicts"]


def test_parallel_clutter_does_not_inflate_two_known_sides():
    points = rectangle(edges=(0, 3))
    clutter = np.random.default_rng(4).uniform([-.1, -.1], [.8, .8], size=(100, 2))
    result = fit_rectangular_section(np.vstack([points, clutter]), known_sides_m=(.5, .4))
    assert any(sorted(item["side_lengths_m"]) == [.4, .5] for item in result["hypotheses"])


def test_world_coordinates_and_input_order_preserve_fit_and_source_indices():
    points = rectangle(angle=.21, origin=(4_000_000., 6_000_000.))
    before = points.copy()
    result = fit_rectangular_section(points)
    shuffled = fit_rectangular_section(points[np.random.default_rng(8).permutation(len(points))])
    assert result["status"] == shuffled["status"] == "proposed"
    assert sorted(result["hypotheses"][0]["side_lengths_m"]) == pytest.approx(sorted(shuffled["hypotheses"][0]["side_lengths_m"]), abs=.001)
    assert np.array_equal(points, before)
    assert all(0 <= index < len(points) for face in result["observed_faces"] for index in face["input_point_indices"])


@pytest.mark.parametrize("kwargs", [{"distance_tolerance_m": 0}, {"known_sides_m": (.5, -1)}, {"known_sides_m": (float("nan"), .4)}])
def test_invalid_measurement_settings_fail_explicitly(kwargs):
    with pytest.raises(ValueError):
        fit_rectangular_section(rectangle(), **kwargs)
