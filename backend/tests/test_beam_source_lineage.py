import math
from pathlib import Path

import numpy as np
import pytest

from scan2bim.geometry.section import CloudGeometry
from scan2bim.recognition import steel


def test_band_sampling_preserves_original_cloud_row_ids_across_chunks(monkeypatch):
    xyz = np.array([
        [0.0, 0.0, 1.0],
        [1.0, 0.0, 1.5],
        [2.0, 0.0, 2.0],
        [3.0, 0.0, 2.5],
        [4.0, 0.0, 3.0],
    ])
    chunks = [xyz[:2], xyz[2:4], xyz[4:]]
    monkeypatch.setattr(steel, "_iter_positions", lambda _path: iter(chunks))
    cloud = CloudGeometry(Path("derived.npy"), np.zeros(3), xyz.min(0), xyz.max(0), len(xyz))

    bands = steel._bands_points_with_source_ids(cloud, [(1.0, 2.0), (2.0, 3.0)])

    assert bands[0][0].tolist() == xyz[[0, 1]].tolist()
    assert bands[0][1].tolist() == [0, 1]
    assert bands[0][2] == 2
    assert bands[1][0].tolist() == xyz[[2, 3]].tolist()
    assert bands[1][1].tolist() == [2, 3]
    assert bands[1][2] == 2


def test_band_sampling_reports_full_count_and_marks_downsampling(monkeypatch):
    xyz = np.array([[float(i), 0.0, 1.0] for i in range(5)])
    monkeypatch.setattr(steel, "_iter_positions", lambda _path: iter([xyz]))
    monkeypatch.setattr(steel, "BAND_CAP_POINTS", 2)
    cloud = CloudGeometry(Path("derived.npy"), np.zeros(3), xyz.min(0), xyz.max(0), len(xyz))

    (points, source_rows, full_count), = steel._bands_points_with_source_ids(cloud, [(0.0, 2.0)])

    assert len(points) == 2
    assert source_rows.tolist() == [0, 3]
    assert full_count == 5


def test_band_sampling_caps_before_collecting_uncapped_chunks(monkeypatch):
    xyz = np.array([[float(i), 0.0, 1.0] for i in range(5)], dtype=np.float32)
    chunks = [xyz[:2], xyz[2:]]
    monkeypatch.setattr(steel, "_iter_positions", lambda _path: iter(chunks))
    monkeypatch.setattr(steel, "BAND_CAP_POINTS", 2)

    def fail_concatenate(*_args, **_kwargs):
        raise AssertionError("band sampling must not concatenate all uncapped points")

    monkeypatch.setattr(steel.np, "concatenate", fail_concatenate)
    cloud = CloudGeometry(Path("derived.npy"), np.zeros(3), xyz.min(0), xyz.max(0), len(xyz))

    (points, source_rows, full_count), = steel._bands_points_with_source_ids(cloud, [(0.0, 2.0)])

    assert points.tolist() == xyz[[0, 3]].tolist()
    assert source_rows.tolist() == [0, 3]
    assert full_count == 5


def test_strip_measurement_can_return_exact_local_support_rows():
    xy = np.array([
        [-2.0, 0.0], [-1.0, 0.0], [0.0, 0.0], [1.0, 0.0], [2.0, 0.0],
        [0.0, 1.2],
    ])
    z = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.2])

    measured = steel._measure_strip(
        xy, z, np.zeros(2), np.array([1.0, 0.0]), 4.0, return_indices=True,
    )

    assert measured[3] == 5
    assert measured[4].tolist() == [0, 1, 2, 3, 4]


def test_vertical_profile_reports_separated_layers_without_assigning_a_rail_role():
    rng = np.random.default_rng(905)
    lower = rng.normal(4.96, 0.018, 700)
    upper = rng.normal(5.20, 0.018, 500)
    profile = steel._vertical_layer_evidence(np.concatenate((lower, upper)))

    assert profile is not None
    assert profile["layer_centers_m"] == pytest.approx([4.96, 5.20], abs=0.02)
    assert profile["layer_separation_m"] == pytest.approx(0.24, abs=0.03)
    assert profile["interpretation"] == "ambiguous_vertical_profile"


def test_single_vertical_profile_does_not_trigger_layer_ambiguity():
    rng = np.random.default_rng(907)
    profile = steel._vertical_layer_evidence(rng.normal(5.0, 0.045, 1500))

    assert profile is None


def test_terminal_cross_strip_is_reported_as_ambiguous_end_detail():
    rng = np.random.default_rng(908)
    along = rng.uniform(-3.0, 3.0, 2400)
    across = rng.normal(0.0, 0.035, len(along))
    beam = np.column_stack((along, across))
    end_plate = np.column_stack((
        rng.normal(2.99, 0.012, 400), rng.uniform(-0.28, 0.28, 400),
    ))

    evidence = steel._beam_terminal_evidence(
        np.concatenate((beam, end_plate)), np.zeros(2), np.array([1.0, 0.0]), 6.0,
    )

    assert evidence is not None
    assert evidence["ambiguous_end_regions"] == ["end"]
    assert evidence["interpretation"] == "possible_end_plate_or_connection_detail"


def test_internal_beam_gap_candidate_keeps_source_rows_on_both_sides():
    rng = np.random.default_rng(911)
    along = np.concatenate((np.arange(-3.0, -0.30, 0.01), np.arange(0.30, 3.0, 0.01)))
    across = rng.normal(0.0, 0.025, len(along))
    points_xy = np.column_stack((along, across))
    source_rows = np.arange(20_000, 20_000 + len(along), dtype=np.int64)

    evidence = steel._beam_internal_gap_evidence(
        points_xy, source_rows, np.zeros(2), np.array([1.0, 0.0]), 6.0,
    )

    assert len(evidence) == 1
    gap = evidence[0]
    assert gap["kind"] == "gap"
    assert gap["position_m"] == pytest.approx(3.0, abs=0.1)
    assert "occlusion" in gap["reason"]
    assert len(gap["source_point_ids"]) >= 6
    assert set(gap["source_point_ids"]) <= set(source_rows.tolist())


def test_continuous_beam_core_does_not_create_internal_gap_candidate():
    rng = np.random.default_rng(912)
    along = rng.uniform(-3.0, 3.0, 2400)
    across = rng.normal(0.0, 0.025, len(along))
    points_xy = np.column_stack((along, across))
    source_rows = np.arange(30_000, 30_000 + len(along), dtype=np.int64)

    assert steel._beam_internal_gap_evidence(
        points_xy, source_rows, np.zeros(2), np.array([1.0, 0.0]), 6.0,
    ) == []


def test_uniform_beam_section_has_no_terminal_ambiguity():
    rng = np.random.default_rng(909)
    points = np.column_stack((rng.uniform(-3.0, 3.0, 2400), rng.normal(0.0, 0.035, 2400)))

    assert steel._beam_terminal_evidence(
        points, np.zeros(2), np.array([1.0, 0.0]), 6.0,
    ) is None


def test_horizontal_beam_candidate_flags_end_detail_without_moving_its_axis(monkeypatch):
    rng = np.random.default_rng(910)
    along = rng.uniform(-3.0, 3.0, 2400)
    across = rng.normal(0.0, 0.035, len(along))
    beam = np.column_stack((along, across, rng.normal(5.0, 0.015, len(along))))
    plate = np.column_stack((
        rng.normal(2.99, 0.012, 400), rng.uniform(-0.28, 0.28, 400),
        rng.normal(5.0, 0.015, 400),
    ))
    xyz = np.concatenate((beam, plate))
    monkeypatch.setattr(steel, "_iter_positions", lambda _path: iter([xyz]))
    direction = np.array([1.0, 0.0])
    segment = {
        "p0": np.array([-3.0, 0.0]), "p1": np.array([3.0, 0.0]),
        "mid": np.zeros(2), "dir": direction, "angle": 0.0, "length": 6.0,
    }
    monkeypatch.setattr(steel, "_plan_segments", lambda _xy, **_kwargs: [segment])
    monkeypatch.setattr(steel, "_axis_from_segments", lambda *_args: 0.0)
    monkeypatch.setattr(steel, "_wall_continued", lambda *_args: False)
    cloud = CloudGeometry(
        Path("derived.npy"), np.zeros(3), np.array([-4.0, -1.0, 0.0]),
        np.array([4.0, 1.0, 10.0]), len(xyz),
    )
    levels = [{"z": z, "z_local": z} for z in (0.0, 3.0, 5.0, 7.0, 10.0)]
    grid = {"res": 0.1, "min": [-4.0, -1.0, 0.0], "band_occ": np.zeros((2, 2, 2), dtype=bool)}

    elements, *_ = steel._horizontal_members(cloud, levels, grid)

    girder = next(item for item in elements if item.dimensions.get("role") == "crane_girder")
    assert girder.metadata["terminal_evidence"]["ambiguous_end_regions"] == ["end"]
    proposal = girder.metadata["member_proposal"]
    assert proposal["axis"]["start"] == pytest.approx([-3.0, 0.0, 5.0], abs=0.01)
    assert proposal["axis"]["end"] == pytest.approx([3.0, 0.0, 5.0], abs=0.01)
    assert proposal["support_evidence"]["end"]["status"] == "unknown"


def test_beam_element_keeps_sampled_source_rows_as_explicit_evidence():
    cloud = CloudGeometry(
        Path("derived.npy"), np.array([100.0, 200.0, 0.0]),
        np.zeros(3), np.ones(3), 4,
    )

    member = steel._beam_element(
        cloud, np.array([1.0, 2.0]), np.array([1.0, 0.0]), 6.0, 0.2,
        4.9, 5.1, role="crane_girder", role_note="candidate", confidence=0.6,
        band_label="5 m", support=4, source_point_ids=np.array([7, 13, 29, 41]),
    )

    assert member.metadata["source_point_ids"] == [7, 13, 29, 41]
    assert member.metadata["support_count_in_processing_sample"] == 4
    assert member.metadata["source_point_ids_sampled"] is False


@pytest.mark.parametrize("angle_rad", [0.0, math.radians(30.0)])
def test_crane_girder_detection_traces_measured_points_back_to_cloud_rows(monkeypatch, angle_rad):
    rng = np.random.default_rng(44)
    along = rng.uniform(-3.0, 3.0, 1200)
    across = rng.normal(0.0, 0.035, 1200)
    direction = np.array([math.cos(angle_rad), math.sin(angle_rad)])
    normal = np.array([-direction[1], direction[0]])
    visible = np.abs(along) > 0.25  # an internal gap is evidence, not a confirmed joint
    xyz = np.column_stack((
        (along[visible, None] * direction + across[visible, None] * normal),
        rng.uniform(4.95, 5.05, int(visible.sum())),
    ))
    monkeypatch.setattr(steel, "_iter_positions", lambda _path: iter([xyz]))
    def segment(start_m, end_m):
        p0 = start_m * direction
        p1 = end_m * direction
        return {
            "p0": p0, "p1": p1, "mid": (p0 + p1) / 2,
            "dir": direction, "angle": angle_rad, "length": end_m - start_m,
        }

    hough_fragments = [segment(-3.0, 0.1), segment(-0.1, 3.0)]
    monkeypatch.setattr(
        steel, "_plan_segments", lambda xy, **_kwargs: hough_fragments if len(xy) >= 500 else [],
    )
    monkeypatch.setattr(
        steel, "_axis_from_segments", lambda segments, _reference: angle_rad if segments else None,
    )
    monkeypatch.setattr(steel, "_wall_continued", lambda *_args: False)
    cloud = CloudGeometry(
        Path("derived.npy"), np.zeros(3), np.array([-4.0, -1.0, 0.0]),
        np.array([4.0, 1.0, 10.0]), len(xyz),
    )
    levels = [{"z": z, "z_local": z} for z in (0.0, 3.0, 5.0, 7.0, 10.0)]
    grid = {"res": 0.1, "min": [-4.0, -1.0, 0.0], "band_occ": np.zeros((2, 2, 2), dtype=bool)}

    elements, *_ = steel._horizontal_members(cloud, levels, grid)

    girder = next(item for item in elements if item.dimensions.get("role") == "crane_girder")
    ids = girder.metadata["source_point_ids"]
    assert girder.metadata["support_count_in_processing_sample"] == len(xyz)
    assert girder.metadata["source_band_point_count"] == len(xyz)
    assert girder.metadata["source_band_points_used"] == len(xyz)
    assert girder.metadata["source_point_ids_sampled"] is True
    assert len(ids) == 512
    assert len(set(ids)) == len(ids)
    assert set(ids).issubset(set(range(len(xyz))))
    bbox_min = np.asarray(girder.bbox["min"], dtype=float)
    bbox_max = np.asarray(girder.bbox["max"], dtype=float)
    linked_points = xyz[np.asarray(ids, dtype=np.int64)]
    assert np.all(linked_points >= bbox_min - 0.05)
    assert np.all(linked_points <= bbox_max + 0.05)
    proposal = girder.metadata["member_proposal"]
    assert proposal["id"] == girder.metadata["member_proposal_id"]
    assert proposal["role"] == {"value": "crane_girder", "status": "proposed"}
    expected_start = [-3.0 * direction[0], -3.0 * direction[1], 5.0]
    expected_end = [3.0 * direction[0], 3.0 * direction[1], 5.0]
    assert proposal["axis"]["start"] == pytest.approx(expected_start, abs=0.001)
    assert proposal["axis"]["end"] == pytest.approx(expected_end, abs=0.001)
    assert len(proposal["joint_gaps"]) == 1
    gap = proposal["joint_gaps"][0]
    assert gap["kind"] == "gap"
    assert gap["position_m"] == pytest.approx(3.0, abs=0.15)
    assert set(gap["source_point_ids"]) <= set(proposal["source_point_ids"])
    assert "occlusion" in gap["reason"]
    assert proposal["source_point_ids"] == ids
    assert proposal["source_point_ids_sampled"] is True
    assert proposal["support_evidence"]["start"]["status"] == "unknown"
    assert proposal["support_evidence"]["end"]["status"] == "unknown"
    assert proposal["review_state"] == "proposed"
    assert proposal["unresolved_fields"] == [
        "physical_role_review", "physical_span_boundary", "start_support",
        "end_support", "cross_section", "joint_locations",
    ]


def test_crane_girder_with_multiple_height_layers_stays_an_ambiguous_review_candidate(monkeypatch):
    rng = np.random.default_rng(906)
    x = rng.uniform(-3.0, 3.0, 1200)
    y = rng.normal(0.0, 0.035, len(x))
    lower = rng.normal(4.96, 0.018, len(x))
    upper = rng.normal(5.20, 0.018, len(x))
    xyz = np.concatenate((np.column_stack((x, y, lower)), np.column_stack((x, y, upper))))
    monkeypatch.setattr(steel, "_iter_positions", lambda _path: iter([xyz]))
    angle = 0.0
    direction = np.array([1.0, 0.0])
    segments = [{
        "p0": np.array([-3.0, 0.0]), "p1": np.array([3.0, 0.0]),
        "mid": np.zeros(2), "dir": direction, "angle": angle, "length": 6.0,
    }]
    monkeypatch.setattr(steel, "_plan_segments", lambda xy, **_kwargs: segments)
    monkeypatch.setattr(steel, "_axis_from_segments", lambda *_args: angle)
    monkeypatch.setattr(steel, "_wall_continued", lambda *_args: False)
    cloud = CloudGeometry(
        Path("derived.npy"), np.zeros(3), np.array([-4.0, -1.0, 0.0]),
        np.array([4.0, 1.0, 10.0]), len(xyz),
    )
    levels = [{"z": z, "z_local": z} for z in (0.0, 3.0, 5.0, 7.0, 10.0)]
    grid = {"res": 0.1, "min": [-4.0, -1.0, 0.0], "band_occ": np.zeros((2, 2, 2), dtype=bool)}

    elements, *_ = steel._horizontal_members(cloud, levels, grid)

    girder = next(item for item in elements if item.dimensions.get("role") == "crane_girder")
    evidence = girder.metadata["vertical_profile_evidence"]
    assert evidence["interpretation"] == "ambiguous_vertical_profile"
    assert evidence["layer_centers_m"] == pytest.approx([4.96, 5.20], abs=0.02)
    assert evidence["role_assignment"] == "unresolved"
    assert "автоматически не разделены" in girder.metadata["notes"]


def test_cylindrical_duct_lookalike_remains_an_unconfirmed_geometric_candidate(monkeypatch):
    rng = np.random.default_rng(913)
    count = 2400
    along = rng.uniform(-3.0, 3.0, count)
    angle = rng.uniform(0.0, 2.0 * np.pi, count)
    radius = 0.10
    xyz = np.column_stack((along, radius * np.cos(angle), 5.0 + radius * np.sin(angle)))
    monkeypatch.setattr(steel, "_iter_positions", lambda _path: iter([xyz]))
    direction = np.array([1.0, 0.0])
    segment = {
        "p0": np.array([-3.0, 0.0]), "p1": np.array([3.0, 0.0]),
        "mid": np.zeros(2), "dir": direction, "angle": 0.0, "length": 6.0,
    }
    monkeypatch.setattr(steel, "_plan_segments", lambda xy, **_kwargs: [segment])
    monkeypatch.setattr(steel, "_axis_from_segments", lambda *_args: 0.0)
    monkeypatch.setattr(steel, "_wall_continued", lambda *_args: False)
    cloud = CloudGeometry(
        Path("derived.npy"), np.zeros(3), np.array([-4.0, -1.0, 0.0]),
        np.array([4.0, 1.0, 10.0]), len(xyz),
    )
    levels = [{"z": z, "z_local": z} for z in (0.0, 3.0, 5.0, 7.0, 10.0)]
    grid = {"res": 0.1, "min": [-4.0, -1.0, 0.0], "band_occ": np.zeros((2, 2, 2), dtype=bool)}

    elements, *_ = steel._horizontal_members(cloud, levels, grid)

    candidate = next(item for item in elements if item.dimensions.get("role") == "crane_girder")
    proposal = candidate.metadata["member_proposal"]
    assert candidate.dimensions["role_status"] == "proposed"
    assert candidate.dimensions["profile_status"] == "not_fitted"
    assert candidate.metadata["column_support_context"]["status"] == "insufficient_context"
    assert proposal["role"] == {"value": "crane_girder", "status": "proposed"}
    assert "physical_role_review" in proposal["unresolved_fields"]
    assert proposal["review_state"] == "proposed"
