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
    visible = np.abs(along) > 0.08  # a small occluded gap through the middle
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
    proposal = girder.metadata["member_proposal"]
    assert proposal["id"] == girder.metadata["member_proposal_id"]
    assert proposal["role"] == {"value": "crane_girder", "status": "proposed"}
    expected_start = [-3.0 * direction[0], -3.0 * direction[1], 5.0]
    expected_end = [3.0 * direction[0], 3.0 * direction[1], 5.0]
    assert proposal["axis"]["start"] == pytest.approx(expected_start, abs=0.001)
    assert proposal["axis"]["end"] == pytest.approx(expected_end, abs=0.001)
    assert proposal["source_point_ids"] == ids
    assert proposal["source_point_ids_sampled"] is True
    assert proposal["support_evidence"]["start"]["status"] == "unknown"
    assert proposal["support_evidence"]["end"]["status"] == "unknown"
    assert proposal["review_state"] == "proposed"
    assert proposal["unresolved_fields"] == [
        "physical_role_review", "physical_span_boundary", "start_support",
        "end_support", "cross_section", "joint_locations",
    ]
