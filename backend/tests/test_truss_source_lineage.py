import math
from pathlib import Path

import numpy as np

from scan2bim.geometry.section import CloudGeometry
from scan2bim.recognition import steel


def test_truss_zone_sampling_preserves_source_positions_rows_across_chunks(monkeypatch):
    xyz = np.array([
        [0.0, 0.0, 0.5],
        [1.0, 0.0, 1.0],
        [2.0, 0.0, 1.5],
        [3.0, 0.0, 2.0],
        [4.0, 0.0, 2.5],
    ])
    monkeypatch.setattr(steel, "_iter_positions", lambda _path: iter([xyz[:2], xyz[2:]]))
    cloud = CloudGeometry(Path("derived.npy"), np.zeros(3), xyz.min(0), xyz.max(0), len(xyz))

    points, source_rows, was_sampled = steel._collect_zone_with_source_ids(cloud, 1.0, 2.5)

    assert points.tolist() == xyz[[1, 2, 3]].tolist()
    assert source_rows.tolist() == [1, 2, 3]
    assert was_sampled is False


def test_truss_zone_sampling_marks_downsampled_source_rows(monkeypatch):
    xyz = np.array([[float(i), 0.0, 1.0] for i in range(5)])
    monkeypatch.setattr(steel, "_iter_positions", lambda _path: iter([xyz]))
    monkeypatch.setattr(steel, "TRUSS_ZONE_CAP_POINTS", 2)
    cloud = CloudGeometry(Path("derived.npy"), np.zeros(3), xyz.min(0), xyz.max(0), len(xyz))

    points, source_rows, was_sampled = steel._collect_zone_with_source_ids(cloud, 0.0, 2.0)

    assert len(points) == len(source_rows) == 2
    assert was_sampled is True


def test_brace_member_proposal_keeps_source_rows_and_stays_unconfirmed():
    cloud = CloudGeometry(Path("derived.npy"), np.array([10.0, 20.0, 1.0]), np.zeros(3), np.ones(3), 8)

    element = steel._member_element(
        cloud,
        np.array([10.0, 20.0, 1.0]),
        np.array([13.0, 20.0, 4.0]),
        section_m=0.15,
        role="brace",
        orientation="vertical",
        confidence=0.6,
        method="synthetic test",
        source_point_ids=np.array([2, 4, 6, 7]),
        source_point_ids_sampled=True,
    )

    assert element.metadata["member_proposal"]["source_point_ids"] == [2, 4, 6, 7]
    assert element.metadata["member_proposal"]["role"] == {"value": "brace", "status": "proposed"}
    assert element.metadata["member_proposal"]["source_point_ids_sampled"] is True
    assert element.metadata["member_proposal"]["review_state"] == "proposed"
    assert element.metadata["member_proposal"]["support_evidence"]["start"]["status"] == "unknown"


def test_vertical_brace_detection_links_each_crossing_member_to_its_own_rows(monkeypatch):
    rng = np.random.default_rng(83)
    along = np.linspace(-2.8, 2.8, 1400)
    noise_a = rng.normal(0, 0.015, len(along))
    noise_b = rng.normal(0, 0.015, len(along))
    rising = np.column_stack((along, 3.0 + (along + 2.8) * 0.5))
    falling = np.column_stack((along, 6.0 - (along + 2.8) * 0.5))
    xyz_a = np.column_stack((rng.normal(0, 0.02, len(along)), rising[:, 0], rising[:, 1]))
    xyz_b = np.column_stack((rng.normal(0, 0.02, len(along)), falling[:, 0], falling[:, 1]))
    xyz = np.vstack((xyz_a, xyz_b))
    source_rows = np.arange(1000, 1000 + len(xyz), dtype=np.int64)

    def segment(p0, p1):
        start = np.asarray(p0, dtype=float)
        end = np.asarray(p1, dtype=float)
        delta = end - start
        length = float(np.linalg.norm(delta))
        direction = delta / length
        angle = math.atan2(float(direction[1]), float(direction[0]))
        return {
            "p0": start, "p1": end, "mid": (start + end) / 2,
            "dir": direction, "angle": angle,
            "angle_deg": math.degrees(angle) % 180.0, "length": length,
        }

    sections = [segment((-2.8, 3.0), (2.8, 5.8)), segment((-2.8, 5.8), (2.8, 3.0))]
    monkeypatch.setattr(steel, "_collect_zone_with_source_ids", lambda *_args: (xyz, source_rows, False))
    monkeypatch.setattr(steel, "_vertical_hough", lambda *_args, **_kwargs: (sections, 0.1))
    monkeypatch.setattr("scipy.signal.find_peaks", lambda *_args, **_kwargs: (np.array([0]), {}))

    cloud = CloudGeometry(Path("derived.npy"), np.zeros(3), xyz.min(0), xyz.max(0), len(xyz))
    members, _planes, stats = steel._detect_trusses(cloud, (2.5, 6.5), axis=0.0)

    assert stats["brace_vertical"] == 2
    assert len(members) == 2
    first_ids = set(members[0].metadata["member_proposal"]["source_point_ids"])
    second_ids = set(members[1].metadata["member_proposal"]["source_point_ids"])
    assert first_ids and second_ids
    # Crossing points near the shared node may support both proposals; away
    # from the node each proposal must trace predominantly to its own bar.
    first_bar_rows = set(source_rows[: len(along)].tolist())
    second_bar_rows = set(source_rows[len(along) :].tolist())
    assert len(first_ids & first_bar_rows) / len(first_ids) > 0.80
    assert len(second_ids & second_bar_rows) / len(second_ids) > 0.80
    assert first_ids | second_ids <= set(source_rows.tolist())
    assert all(item.metadata["member_proposal"]["review_state"] == "proposed" for item in members)


def test_roof_truss_candidate_emits_source_linked_chords_and_posts(monkeypatch):
    rng = np.random.default_rng(84)
    section_lines = [
        ((-8.0, 6.0), (8.0, 6.0)),  # top chord
        ((-8.0, 4.0), (8.0, 4.0)),  # bottom chord
        ((-4.0, 4.0), (-4.0, 6.0)),
        ((0.0, 4.0), (0.0, 6.0)),
        ((4.0, 4.0), (4.0, 6.0)),
    ]

    def segment(p0, p1):
        start = np.asarray(p0, dtype=float)
        end = np.asarray(p1, dtype=float)
        delta = end - start
        length = float(np.linalg.norm(delta))
        direction = delta / length
        angle = math.atan2(float(direction[1]), float(direction[0]))
        return {
            "p0": start, "p1": end, "mid": (start + end) / 2,
            "dir": direction, "angle": angle,
            "angle_deg": math.degrees(angle) % 180.0, "length": length,
        }

    section = [segment(*line) for line in section_lines]
    cloud_rows = []
    for (v0, z0), (v1, z1) in section_lines:
        t = rng.uniform(0.0, 1.0, 520)
        cloud_rows.append(np.column_stack((
            rng.normal(0.0, 0.02, len(t)),
            v0 + (v1 - v0) * t + rng.normal(0.0, 0.015, len(t)),
            z0 + (z1 - z0) * t + rng.normal(0.0, 0.015, len(t)),
        )))
    xyz = np.vstack(cloud_rows)
    source_rows = np.arange(5000, 5000 + len(xyz), dtype=np.int64)
    monkeypatch.setattr(steel, "_collect_zone_with_source_ids", lambda *_args: (xyz, source_rows, False))
    monkeypatch.setattr(steel, "_vertical_hough", lambda *_args, **_kwargs: (section, 0.1))
    monkeypatch.setattr("scipy.signal.find_peaks", lambda *_args, **_kwargs: (np.array([0]), {}))

    cloud = CloudGeometry(Path("derived.npy"), np.zeros(3), xyz.min(0), xyz.max(0), len(xyz))
    elements, _planes, stats = steel._detect_trusses(cloud, (2.5, 6.5), axis=0.0)

    members = [item for item in elements if item.geometry.get("kind") == "member"]
    envelope = next(item for item in elements if item.class_name == "truss")
    assert stats["truss_count"] == 1
    assert len(members) == 5
    assert {item.dimensions["role"] for item in members} == {
        "truss_top_chord", "truss_bottom_chord", "truss_post",
    }
    assert all(item.metadata["member_proposal"]["source_point_ids"] for item in members)
    assert all(item.metadata["member_proposal"]["review_state"] == "proposed" for item in members)
    assert envelope.metadata["member_count_traced"] == len(members)
    assert set(envelope.metadata["member_proposal_ids"]) == {
        item.metadata["member_proposal_id"] for item in members
    }
    assembly = envelope.metadata["assembly_proposal"]
    assert assembly["member_proposal_ids"] == sorted(envelope.metadata["member_proposal_ids"])
    assert assembly["node_candidates"] == []
    assert assembly["review_state"] == "proposed"
    for item in members:
        role = item.dimensions["role"]
        own_line = {
            "truss_top_chord": 0,
            "truss_bottom_chord": 1,
            "truss_post": 2 + int(round((item.geometry["p0"][1] + 4.0) / 4.0)),
        }[role]
        rows = set(item.metadata["member_proposal"]["source_point_ids"])
        own_rows = set(source_rows[own_line * 520 : (own_line + 1) * 520].tolist())
        assert len(rows & own_rows) / len(rows) > 0.70
