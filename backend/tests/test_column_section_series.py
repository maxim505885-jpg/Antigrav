"""Surface-track rows feed multi-height sections without losing provenance."""
import numpy as np
import pytest

from scan2bim.structure.column_section_series import fit_column_track_sections
from scan2bim.structure.section_fitting import fit_rectangular_section


def geometry(sides=(0.5, 0.4), height=2.0):
    return {
        "id": "column-candidate",
        "kind": "oriented_box",
        "center": [0.0, 0.0, height / 2],
        "sizes": {"length": sides[0], "thickness": sides[1], "height": height},
        "rotation_z": 0.0,
    }


def cloud_tracks(*, lower_sides=(0.5, 0.4), upper_sides=None, missing_bins=(), edge_ids=("u+", "u-", "v+", "v-")):
    geom = geometry(sides=(max(lower_sides[0], (upper_sides or lower_sides)[0]), lower_sides[1]))
    point_parts, row_parts, tracks = [], [], []
    next_id = 1000
    segment_index = {"u+": 3, "u-": 2, "v+": 1, "v-": 0}
    for edge_id in edge_ids:
        track_ids = []
        for z_bin in range(8):
            if z_bin in missing_bins:
                continue
            z = (z_bin + 0.5) * 0.25
            sides = lower_sides if upper_sides is None or z < 1.0 else upper_sides
            half_a, half_b = sides[0] / 2, sides[1] / 2
            segment = (
                np.column_stack((np.linspace(-half_a, half_a, 64), np.full(64, -half_b))),
                np.column_stack((np.linspace(-half_a, half_a, 64), np.full(64, half_b))),
                np.column_stack((np.full(64, -half_a), np.linspace(-half_b, half_b, 64))),
                np.column_stack((np.full(64, half_a), np.linspace(-half_b, half_b, 64))),
            )[segment_index[edge_id]]
            xyz = np.column_stack((segment, np.full(len(segment), z)))
            point_ids = np.arange(next_id, next_id + len(xyz), dtype=np.int64)
            next_id += len(xyz)
            point_parts.append(xyz)
            row_parts.append(point_ids)
            track_ids.extend(point_ids.tolist())
        tracks.append({
            "track_id": f"track-{edge_id}",
            "candidate_edge_id": edge_id,
            "track_status": "candidate_track",
            "source_point_indices": track_ids,
        })
    xyz = np.concatenate(point_parts) if point_parts else np.empty((0, 3))
    source_ids = np.concatenate(row_parts) if row_parts else np.empty(0, dtype=np.int64)
    return geom, tracks, xyz, source_ids


def test_four_candidate_face_tracks_reconstruct_each_section_with_source_rows():
    geom, tracks, xyz, source_ids = cloud_tracks()
    xyz_before, ids_before = xyz.copy(), source_ids.copy()

    report = fit_column_track_sections(geom, tracks, xyz, source_ids)

    series = report["section_series"]
    assert report["candidate_track_count"] == 4
    assert len(series["section_slices"]) == 8
    assert all(section["status"] == "proposed" for section in series["section_slices"])
    for section in series["section_slices"]:
        assert sorted(section["hypotheses"][0]["side_lengths_m"]) == pytest.approx([0.4, 0.5], abs=0.01)
        assert len(section["hypotheses"][0]["source_point_ids"]) == 256
        assert len(section["track_evidence"]) == 4
    assert report["engineering_status"] == "not_assessed"
    assert np.array_equal(xyz, xyz_before)
    assert np.array_equal(source_ids, ids_before)


def test_known_sides_complete_only_two_observed_candidate_tracks():
    geom, tracks, xyz, source_ids = cloud_tracks(edge_ids=("u+", "v+"))

    report = fit_column_track_sections(geom, tracks, xyz, source_ids, known_sides_m=(0.5, 0.4))

    first = report["section_series"]["section_slices"][0]
    assert first["status"] == "proposed"
    hypothesis = first["hypotheses"][0]
    corners = np.asarray(hypothesis["corners_world_m"], dtype=np.float64)
    edge_lengths = np.linalg.norm(np.roll(corners, -1, axis=0) - corners, axis=1)
    assert corners.shape == (4, 2)
    assert sorted(edge_lengths) == pytest.approx([0.4, 0.4, 0.5, 0.5], abs=0.01)
    assert hypothesis["side_lengths_m"] == pytest.approx([0.5, 0.4])
    assert hypothesis["observed_edge_count"] == 2
    assert hypothesis["inferred_edge_count"] == 2
    assert hypothesis["edge_evidence"].count("observed") == 2
    assert hypothesis["edge_evidence"].count("inferred") == 2
    assert hypothesis["dimension_source"] == "explicit_input"
    assert hypothesis["review_required"] is True
    assert hypothesis["inferred"] is True
    observed_slice_ids = set(source_ids[np.isclose(xyz[:, 2], first["z_m"])].tolist())
    assert set(hypothesis["source_point_ids"]) == observed_slice_ids
    assert {item["edge_id"] for item in first["track_evidence"]} == {"u+", "v+"}


def test_known_sides_complete_four_partial_faces_without_conflicting_with_lower_bounds():
    side = 0.4
    half = side / 2
    partial_start, partial_end = np.linspace(-0.15, 0.15, 64), np.linspace(-0.15, 0.15, 64)
    points = np.concatenate([
        np.column_stack((np.full(64, -half), partial_start)),
        np.column_stack((np.full(64, half), partial_end)),
        np.column_stack((partial_start, np.full(64, -half))),
        np.column_stack((partial_end, np.full(64, half))),
    ])

    result = fit_rectangular_section(points, known_sides_m=(side, side))

    assert result["status"] == "proposed"
    assert result["dimension_conflicts"] == []
    assert len(result["hypotheses"]) == 1
    expected_corners = {(-half, -half), (-half, half), (half, -half), (half, half)}
    assert any(
        {tuple(np.round(point, 6)) for point in hypothesis["corners_world_m"]} == expected_corners
        and hypothesis["observed_edge_count"] == 2
        and hypothesis["inferred_edge_count"] == 2
        and hypothesis["edge_evidence"].count("inferred") == 2
        and hypothesis["dimension_source"] == "explicit_input"
        and set(hypothesis["source_face_ids"]) == {"F1", "F2", "F3", "F4"}
        and hypothesis["review_required"] is True
        for hypothesis in result["hypotheses"]
    )


def test_overlapping_tracks_count_unique_rows_and_keep_negative_height_boundaries():
    geom = {
        "id": "negative-z-column",
        "kind": "oriented_box",
        "center": [0.0, 0.0, -0.5],
        "sizes": {"length": 0.5, "thickness": 0.4, "height": 1.0},
        "rotation_z": 0.0,
    }
    xyz = np.array([[0.25, 0.2, z] for z in (-1.0, -0.75, -0.5, -0.25, 0.0)])
    source_ids = np.array([100, 101, 102, 103, 104], dtype=np.int64)
    tracks = [
        {"track_id": "right", "candidate_edge_id": "v+", "track_status": "candidate_track",
         "source_point_indices": [102]},
        {"track_id": "front", "candidate_edge_id": "u+", "track_status": "candidate_track",
         "source_point_indices": [100, 101, 102, 103, 104]},
    ]

    report = fit_column_track_sections(geom, tracks, xyz, source_ids, vertical_bin_m=0.25)

    bins = report["height_bins"]
    assert [item["bin_id"] for item in bins] == [-4, -3, -2, -1]
    assert [item["source_point_count"] for item in bins] == [1, 1, 1, 2]
    assert bins[-1]["track_evidence"][0]["source_point_count"] == 2
    assert [item["track_id"] for item in bins[2]["track_evidence"]] == ["front", "right"]
    overlap = {item["track_id"]: item["source_point_count"] for item in bins[2]["track_evidence"]}
    assert overlap == {"front": 1, "right": 1}
    assert report["section_series"]["section_slices"][-1]["source_point_ids"] == [103, 104]


def test_unassigned_tracks_are_excluded_and_sections_remain_unknown():
    geom, tracks, xyz, source_ids = cloud_tracks()
    for track in tracks:
        track["candidate_edge_id"] = None
        track["track_status"] = "unassigned_surface_track"

    report = fit_column_track_sections(geom, tracks, xyz, source_ids)

    assert report["candidate_track_count"] == 0
    assert len(report["excluded_tracks"]) == 4
    assert all(section["status"] == "unknown" for section in report["section_series"]["section_slices"])


def test_missing_height_remains_unknown_and_step_dimensions_remain_visible():
    geom, tracks, xyz, source_ids = cloud_tracks(
        lower_sides=(0.5, 0.4), upper_sides=(0.7, 0.4), missing_bins=(3, 4))

    report = fit_column_track_sections(geom, tracks, xyz, source_ids)

    sections = report["section_series"]["section_slices"]
    assert [item["status"] for item in sections] == ["proposed"] * 3 + ["unknown"] * 2 + ["proposed"] * 3
    assert report["section_series"]["profile_variation_status"] == "incomplete"
    assert report["section_series"]["dimension_ranges_m"]["long_side"]["range_m"] == pytest.approx(0.2, abs=0.01)


def test_track_source_row_mismatch_or_duplicate_input_ids_fails_closed():
    geom, tracks, xyz, source_ids = cloud_tracks()
    with pytest.raises(ValueError, match="source rows.*unique"):
        fit_column_track_sections(geom, tracks, xyz, np.zeros_like(source_ids))
    missing_row_ids = source_ids.copy()
    missing_row_ids[-1] += 1000000
    with pytest.raises(ValueError, match="missing.*source rows"):
        fit_column_track_sections(geom, tracks, xyz, missing_row_ids)
