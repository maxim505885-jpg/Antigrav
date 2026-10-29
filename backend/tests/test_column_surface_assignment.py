"""Surface-to-OBB matching is evidence for review, never structural confirmation."""
import math

import numpy as np
import pytest

from scan2bim.structure.column_surface_assignment import (
    associate_surfaces_to_column,
    cluster_column_surface_tracks,
    estimate_surface_axis_orientation,
)
from scan2bim.structure.column_section_series import fit_column_track_sections


def box(center=(1_000_000.0, -1_000_000.0, 5.0), angle=0.35):
    return {
        "kind": "oriented_box",
        "center": list(center),
        "sizes": {"length": 0.5, "thickness": 0.4, "height": 10.0},
        "rotation_z": angle,
    }


def face(geometry, *, axis="u", side=1, offset_delta=0.0, z=(0.0, 10.0), bins=None,
         span=(-0.18, 0.18), plane_id=None, point_indices=None):
    angle = geometry["rotation_z"]
    normal = (math.cos(angle), math.sin(angle)) if axis == "u" else (-math.sin(angle), math.cos(angle))
    center = geometry["center"]
    half = geometry["sizes"]["length" if axis == "u" else "thickness"] / 2
    offset = normal[0] * center[0] + normal[1] * center[1] + side * half + offset_delta
    return {
        "plane_id": plane_id or f"{axis}{side}",
        "normal_xy": list(normal),
        "line_offset_m": offset,
        "line_direction_xy": [-normal[1], normal[0]],
        "line_anchor_xy_world_m": [center[0] + normal[0] * (side * half + offset_delta),
                                   center[1] + normal[1] * (side * half + offset_delta)],
        "line_span_bounds_from_anchor_m": list(span),
        "z_bounds_world_m": list(z),
        "longest_consecutive_vertical_span_m": z[1] - z[0] if bins is None else .25 * len(bins),
        "occupied_z_bin_ids": list(bins if bins is not None else range(math.floor(z[0] / .25), math.ceil(z[1] / .25))),
        "point_count": 500,
        "input_point_indices": list(point_indices if point_indices is not None else [0, 1, 2]),
    }


def test_rotated_world_surface_matches_one_candidate_face_but_stays_unconfirmed():
    geometry = box()
    surface = face(geometry, axis="u", side=1)

    result = associate_surfaces_to_column(geometry, {"surfaces": [surface], "adjacent_face_pairs": []})

    match = result["surface_associations"][0]
    assert match["association_status"] == "candidate_face"
    assert match["candidate_edge_id"] == "u+"
    assert match["normal_deviation_degrees"] == pytest.approx(0.0, abs=1e-6)
    assert match["boundary_offset_m"] == pytest.approx(0.0, abs=1e-6)
    assert result["structural_role"] == "unknown"
    assert result["engineering_status"] == "not_assessed"
    assert result["confirmed"] is False
    assert surface["input_point_indices"] == [0, 1, 2]


def test_surface_axis_orientation_proposes_observed_direction_without_confirming_box():
    geometry = box(angle=math.radians(52.8))
    measured_angle = math.radians(7.8)
    surfaces = [
        {"plane_id": "a", "normal_xy": [math.cos(measured_angle), math.sin(measured_angle)],
         "longest_consecutive_vertical_span_m": 5.25},
        {"plane_id": "b", "normal_xy": [math.cos(measured_angle + math.pi / 2), math.sin(measured_angle + math.pi / 2)],
         "longest_consecutive_vertical_span_m": 5.25},
        {"plane_id": "c", "normal_xy": [math.cos(measured_angle + math.radians(2)), math.sin(measured_angle + math.radians(2))],
         "longest_consecutive_vertical_span_m": 0.75},
        {"plane_id": "d", "normal_xy": [math.cos(measured_angle + math.pi / 2 - math.radians(2)), math.sin(measured_angle + math.pi / 2 - math.radians(2))],
         "longest_consecutive_vertical_span_m": 0.75},
    ]

    result = estimate_surface_axis_orientation(surfaces, geometry["rotation_z"])

    assert result["status"] == "surface_axis_candidate"
    assert result["estimated_axis_angle_degrees_mod_90"] == pytest.approx(7.8, abs=0.1)
    assert result["candidate_axis_deviation_degrees"] == pytest.approx(45.0, abs=0.1)
    assert result["supporting_plane_ids"] == ["a", "b", "c", "d"]
    assert result["review_required"] is True
    assert result["confirmed"] is False


def test_surface_axis_orientation_refuses_parallel_planes_without_corner_evidence():
    result = estimate_surface_axis_orientation([
        {"plane_id": "a", "normal_xy": [1.0, 0.0], "vertical_span_m": 4.0},
        {"plane_id": "b", "normal_xy": [0.999, 0.045], "vertical_span_m": 4.0},
    ], 0.0)

    assert result["status"] == "no_orthogonal_surface_families"
    assert result["estimated_axis_angle_degrees_mod_90"] is None
    assert result["confirmed"] is False


def test_parallel_neighbor_outside_candidate_footprint_is_not_attached():
    geometry = box(angle=0.0)
    neighbor = face(geometry, axis="u", side=1, offset_delta=0.25)

    result = associate_surfaces_to_column(geometry, {"surfaces": [neighbor], "adjacent_face_pairs": []})

    assert result["surface_associations"][0]["association_status"] == "outside_candidate_boundary"
    assert result["surface_associations"][0]["candidate_edge_id"] is None


def test_short_neighbor_is_not_mislabeled_as_candidate_face_with_weak_support():
    geometry = box(angle=0.0)
    neighbor = face(geometry, axis="u", side=1, offset_delta=0.25, z=(4.5, 5.5))

    result = associate_surfaces_to_column(geometry, {"surfaces": [neighbor], "adjacent_face_pairs": []})

    assert result["surface_associations"][0]["association_status"] == "outside_candidate_boundary"
    assert result["surface_associations"][0]["potential_candidate_edges"] == []


def test_short_vertical_fragment_remains_weak_evidence_for_a_face():
    geometry = box(angle=0.0)
    fragment = face(geometry, axis="u", side=1, z=(4.5, 5.5))

    result = associate_surfaces_to_column(geometry, {"surfaces": [fragment], "adjacent_face_pairs": []})

    assert result["surface_associations"][0]["association_status"] == "insufficient_vertical_support"
    assert result["surface_associations"][0]["candidate_edge_id"] is None
    assert result["surface_associations"][0]["potential_candidate_edges"] == ["u+"]
    assert result["candidate_edge_count"] == 0


def test_four_observed_candidate_edges_are_a_review_candidate_not_a_confirmed_column():
    geometry = box(angle=0.0)
    surfaces = [
        face(geometry, axis="u", side=1),
        face(geometry, axis="u", side=-1),
        face(geometry, axis="v", side=1),
        face(geometry, axis="v", side=-1),
    ]

    result = associate_surfaces_to_column(geometry, {"surfaces": surfaces, "adjacent_face_pairs": []})

    assert result["candidate_edge_count"] == 4
    assert result["association_status"] == "four_candidate_faces"
    assert result["confirmed"] is False
    assert result["structural_role"] == "unknown"


def test_nonfinite_or_degenerate_candidate_geometry_is_rejected():
    with pytest.raises(ValueError):
        associate_surfaces_to_column(box(center=(float("nan"), 0.0, 0.0)), {"surfaces": []})


def test_contiguous_same_face_observations_form_one_provenance_preserving_track():
    geometry = box(angle=0.0)
    first = face(geometry, axis="u", side=1, z=(0.0, 5.0), bins=range(0, 20),
                 span=(-0.18, 0.06), plane_id="lower", point_indices=[1, 2])
    second = face(geometry, axis="u", side=1, z=(4.75, 10.0), bins=range(19, 40),
                  span=(-0.06, 0.18), plane_id="upper", point_indices=[3, 4])
    result = associate_surfaces_to_column(geometry, {"surfaces": [first, second]})

    tracks = cluster_column_surface_tracks(geometry, {"surfaces": [first, second]}, result)

    assert len(tracks) == 1
    assert tracks[0]["candidate_edge_id"] == "u+"
    assert tracks[0]["surface_ids"] == ["lower", "upper"]
    assert tracks[0]["source_point_indices"] == [1, 2, 3, 4]
    assert tracks[0]["vertical_support_fraction"] == pytest.approx(1.0)
    assert tracks[0]["confirmed"] is False


def test_disconnected_height_bands_remain_separate_tracks():
    geometry = box(angle=0.0)
    lower = face(geometry, axis="u", side=1, z=(0.0, 4.0), bins=range(0, 16),
                 plane_id="lower", point_indices=[10])
    upper = face(geometry, axis="u", side=1, z=(6.0, 10.0), bins=range(24, 40),
                 plane_id="upper", point_indices=[20])
    result = associate_surfaces_to_column(geometry, {"surfaces": [lower, upper]})

    tracks = cluster_column_surface_tracks(geometry, {"surfaces": [lower, upper]}, result)

    assert len(tracks) == 2
    assert {tuple(track["surface_ids"]) for track in tracks} == {("lower",), ("upper",)}


@pytest.mark.parametrize("gap_m,bin_m", [
    (0.5, 0.25), (1.0, 0.25), (2.0, 0.25),
    (0.5, 0.5), (1.0, 0.5), (2.0, 0.5),
])
def test_missing_middle_band_never_bridges_surface_tracks(gap_m, bin_m):
    geometry = box(angle=0.0)
    lower_end = 4.0
    upper_start = lower_end + gap_m
    lower = face(geometry, axis="u", side=1, z=(0.0, lower_end),
                 bins=range(0, int(lower_end / bin_m)), plane_id="lower")
    upper = face(geometry, axis="u", side=1, z=(upper_start, 10.0),
                 bins=range(int(upper_start / bin_m), int(10.0 / bin_m)), plane_id="upper")
    result = associate_surfaces_to_column(geometry, {"surfaces": [lower, upper]}, vertical_bin_m=bin_m)

    tracks = cluster_column_surface_tracks(geometry, {"surfaces": [lower, upper]}, result, vertical_bin_m=bin_m)

    assert len(tracks) == 2
    assert all(track["confirmed"] is False for track in tracks)


def test_scan_band_stripes_without_shared_height_bins_do_not_join():
    geometry = box(angle=0.0)
    stripes = [
        face(geometry, axis="u", side=1, z=(0.0, 10.0), bins=bins,
             plane_id=f"stripe-{index}", point_indices=[index])
        for index, bins in enumerate(([0, 1], [8, 9], [16, 17], [24, 25], [32, 33]))
    ]
    result = associate_surfaces_to_column(geometry, {"surfaces": stripes})

    tracks = cluster_column_surface_tracks(geometry, {"surfaces": stripes}, result)

    assert len(tracks) == len(stripes)
    assert all(track["track_status"] == "weak_candidate_track" for track in tracks)
    assert {tuple(track["source_point_indices"]) for track in tracks} == {(i,) for i in range(5)}


def test_face_from_adjacent_six_metre_column_stays_outside_this_candidate():
    candidate = box(center=(0.0, 0.0, 5.0), angle=0.0)
    adjacent_column = box(center=(6.0, 0.0, 5.0), angle=0.0)
    adjacent_face = face(adjacent_column, axis="u", side=-1, plane_id="adjacent-u-")
    result = associate_surfaces_to_column(candidate, {"surfaces": [adjacent_face]})

    tracks = cluster_column_surface_tracks(candidate, {"surfaces": [adjacent_face]}, result)

    assert result["surface_associations"][0]["association_status"] == "outside_candidate_boundary"
    assert tracks[0]["candidate_edge_id"] is None
    assert tracks[0]["source_point_indices"] == [0, 1, 2]


def test_same_face_line_fragments_without_endpoint_support_remain_separate():
    geometry = box(angle=0.0)
    first = face(geometry, axis="u", side=1, span=(-0.18, -0.08), plane_id="left")
    second = face(geometry, axis="u", side=1, span=(0.08, 0.18), plane_id="right")
    result = associate_surfaces_to_column(geometry, {"surfaces": [first, second]})

    tracks = cluster_column_surface_tracks(geometry, {"surfaces": [first, second]}, result)

    assert len(tracks) == 2


def test_same_face_fragments_join_only_when_observed_endpoints_support_continuity():
    geometry = box(angle=0.0)
    first = face(geometry, axis="u", side=1, span=(-0.18, 0.0), plane_id="left")
    second = face(geometry, axis="u", side=1, span=(0.04, 0.18), plane_id="right")
    result = associate_surfaces_to_column(geometry, {"surfaces": [first, second]})

    tracks = cluster_column_surface_tracks(geometry, {"surfaces": [first, second]}, result)

    assert len(tracks) == 1
    assert tracks[0]["surface_ids"] == ["left", "right"]
    assert tracks[0]["link_evidence"][0]["endpoint_gap_m"] == pytest.approx(0.04)


def test_unassigned_surface_track_keeps_its_measured_vertical_support():
    geometry = box(angle=0.0)
    surface = face(geometry, axis="u", side=1, z=(2.0, 8.0), bins=range(8, 32),
                   offset_delta=0.3, plane_id="nearby-wall", point_indices=[70, 71])
    result = associate_surfaces_to_column(geometry, {"surfaces": [surface]})

    tracks = cluster_column_surface_tracks(geometry, {"surfaces": [surface]}, result)

    assert len(tracks) == 1
    assert tracks[0]["candidate_edge_id"] is None
    assert tracks[0]["vertical_support_fraction"] == pytest.approx(0.6)
    assert tracks[0]["source_point_indices"] == [70, 71]


def test_beam_above_candidate_head_does_not_become_a_column_face_track():
    geometry = box(angle=0.0)
    beam = face(geometry, axis="u", side=1, z=(10.25, 11.5), bins=range(41, 46),
                plane_id="head-beam")
    result = associate_surfaces_to_column(geometry, {"surfaces": [beam]})

    tracks = cluster_column_surface_tracks(geometry, {"surfaces": [beam]}, result)

    assert tracks[0]["candidate_edge_id"] is None
    assert tracks[0]["track_status"] == "unassigned_surface_track"


def test_nearby_touching_wall_inside_loose_match_but_outside_track_boundary_stays_unassigned():
    geometry = box(angle=0.0)
    wall = face(geometry, axis="u", side=1, offset_delta=0.08, plane_id="near-wall")
    result = associate_surfaces_to_column(geometry, {"surfaces": [wall]})

    tracks = cluster_column_surface_tracks(geometry, {"surfaces": [wall]}, result)

    assert result["surface_associations"][0]["association_status"] == "candidate_face"
    assert tracks[0]["candidate_edge_id"] is None
    assert tracks[0]["track_status"] == "unassigned_surface_track"
    assert tracks[0]["exclusion_reasons"] == ["track_boundary_delta_exceeds_limit"]
    report = fit_column_track_sections(geometry, tracks, np.empty((0, 3)), np.empty(0, dtype=np.int64))
    assert report["excluded_tracks"] == [{
        "track_id": tracks[0]["track_id"],
        "reason": "track_boundary_delta_exceeds_limit",
        "detail_reasons": ["track_boundary_delta_exceeds_limit"],
    }]


def test_coplanar_wall_match_remains_unowned_and_unconfirmed():
    geometry = box(angle=0.0)
    wall = face(geometry, axis="u", side=1, plane_id="coplanar-wall")
    result = associate_surfaces_to_column(geometry, {"surfaces": [wall]})
    tracks = cluster_column_surface_tracks(geometry, {"surfaces": [wall]}, result)

    assert result["surface_associations"][0]["association_status"] == "candidate_face"
    assert result["structural_role"] == "unknown"
    assert tracks[0]["candidate_edge_id"] == "u+"
    assert tracks[0]["structural_role"] == "unknown"
    assert tracks[0]["confirmed"] is False
    assert tracks[0]["review_required"] is True


def test_pipe_arc_tangent_planes_near_candidate_do_not_form_column_tracks():
    geometry = box(angle=0.0)
    surfaces = []
    for index, degrees in enumerate((0.0, 30.0, 60.0)):
        angle = math.radians(degrees)
        normal = (math.cos(angle), math.sin(angle))
        tangent = (-normal[1], normal[0])
        center = geometry["center"]
        radius = 0.30
        anchor = [center[0] + normal[0] * radius, center[1] + normal[1] * radius]
        surfaces.append({
            "plane_id": f"pipe-arc-{index}", "normal_xy": list(normal),
            "line_offset_m": normal[0] * anchor[0] + normal[1] * anchor[1],
            "line_direction_xy": list(tangent), "line_anchor_xy_world_m": anchor,
            "line_span_bounds_from_anchor_m": [-0.15, 0.15],
            "z_bounds_world_m": [0.0, 10.0], "occupied_z_bin_ids": list(range(40)),
            "input_point_indices": [100 + index],
        })
    result = associate_surfaces_to_column(geometry, {"surfaces": surfaces})

    tracks = cluster_column_surface_tracks(geometry, {"surfaces": surfaces}, result)

    assert len(tracks) == 3
    assert all(track["candidate_edge_id"] is None for track in tracks)
    assert all(track["track_status"] == "unassigned_surface_track" for track in tracks)


def test_partial_l_corner_keeps_the_two_observed_candidate_faces_distinct():
    geometry = box(angle=0.0)
    surfaces = [face(geometry, axis="u", side=1, plane_id="side-a", point_indices=[11]),
                face(geometry, axis="v", side=1, plane_id="side-b", point_indices=[22])]
    result = associate_surfaces_to_column(geometry, {"surfaces": surfaces})

    tracks = cluster_column_surface_tracks(geometry, {"surfaces": surfaces}, result)

    assert {track["candidate_edge_id"] for track in tracks} == {"u+", "v+"}
    assert {tuple(track["source_point_indices"]) for track in tracks} == {(11,), (22,)}
