import math
from pathlib import Path

import numpy as np
import pytest

from scan2bim.geometry.section import CloudGeometry
from scan2bim.geometry.bounds import derive_bbox
from scan2bim.recognition import steel


def test_truss_internal_role_requires_both_ends_to_reach_measured_chords():
    top = [(np.array([0.0, 6.0]), np.array([8.0, 0.0]), 8.0)]
    bottom = [(np.array([0.0, 4.0]), np.array([8.0, 0.0]), 8.0)]

    post_role, post_evidence = steel._classify_truss_internal_member_role(
        (np.array([3.0, 5.0]), np.array([0.0, 1.0]), 2.0), top, bottom,
    )
    web_role, web_evidence = steel._classify_truss_internal_member_role(
        (np.array([3.0, 5.0]), np.array([1.0, 1.0]) / math.sqrt(2), 2.0 * math.sqrt(2)),
        top, bottom,
    )

    assert post_role == "truss_post"
    assert web_role == "truss_web"
    assert post_evidence["status"] == web_evidence["status"] == "proposed"
    assert post_evidence["supported_chords"] == ["bottom", "top"]
    assert web_evidence["supported_chords"] == ["bottom", "top"]


def test_truss_internal_role_is_unknown_when_member_does_not_connect_chords():
    top = [(np.array([0.0, 6.0]), np.array([8.0, 0.0]), 8.0)]
    bottom = [(np.array([0.0, 4.0]), np.array([8.0, 0.0]), 8.0)]
    line = (np.array([3.0, 5.0]), np.array([1.0, 1.0]) / math.sqrt(2), 1.0)

    role, evidence = steel._classify_truss_internal_member_role(line, top, bottom)

    assert role == "unknown"
    assert evidence["status"] == "unknown"
    assert evidence["reason"] == "member_axis_does_not_reach_both_measured_chords"
    assert evidence["supported_chords"] != ["bottom", "top"]


def test_truss_internal_role_is_unknown_when_endpoint_mapping_is_ambiguous():
    top = [(np.array([0.0, 4.1]), np.array([8.0, 0.0]), 8.0)]
    bottom = [(np.array([0.0, 4.0]), np.array([8.0, 0.0]), 8.0)]
    short_bar = (np.array([4.0, 4.05]), np.array([0.0, 1.0]), 0.1)

    role, evidence = steel._classify_truss_internal_member_role(short_bar, top, bottom)

    assert role == "unknown"
    assert evidence["reason"] == "ambiguous_endpoint_to_chord_assignment"


def test_truss_internal_role_is_unknown_when_point_support_is_non_planar():
    top = [(np.array([0.0, 6.0]), np.array([8.0, 0.0]), 8.0)]
    bottom = [(np.array([0.0, 4.0]), np.array([8.0, 0.0]), 8.0)]
    line = (np.array([3.0, 5.0]), np.array([1.0, 1.0]) / math.sqrt(2), 2.0 * math.sqrt(2))

    role, evidence = steel._classify_truss_internal_member_role(
        line, top, bottom, plane_support_p95_m=0.31,
    )

    assert role == "unknown"
    assert evidence["status"] == "unknown"
    assert evidence["reason"] == "member_point_support_is_non_planar"


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


def test_vertical_hough_keeps_occlusion_separated_chord_fragments_distinct():
    rng = np.random.default_rng(890)
    parts = []
    for start, stop in ((-8.0, -5.0), (5.0, 8.0)):
        v = np.linspace(start, stop, 900)
        z = rng.normal(6.0, 0.012, len(v))
        parts.append(np.column_stack((v, z)))
    observed = np.vstack(parts)

    segments, _fill = steel._vertical_hough(observed, res=0.05, min_len_m=0.8)
    horizontal_segments = [
        segment for segment in segments
        if segment["angle_deg"] <= 15 or segment["angle_deg"] >= 165
    ]
    fragments = [
        steel._group_line(group) for group in steel._group_segments(horizontal_segments)
    ]

    assert len(fragments) == 2
    assert all(length < steel.TRUSS_MIN_CHORD_M for _center, _direction, length in fragments)
    assert sorted(float(center[0]) for center, _direction, _length in fragments) == pytest.approx(
        [-6.5, 6.5], abs=0.25,
    )


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
    assert all("section_m" not in item.geometry for item in members)
    assert all(item.bbox == derive_bbox(item.geometry) for item in members)


def test_roof_truss_candidate_emits_source_linked_chords_and_posts(monkeypatch):
    rng = np.random.default_rng(84)
    section_lines = [
        ((-8.0, 6.0), (8.0, 6.0)),  # top chord
        ((-8.0, 4.0), (8.0, 4.0)),  # bottom chord
        ((-4.0, 4.0), (-4.0, 6.0)),
        ((0.0, 4.0), (0.0, 6.0)),
        ((4.0, 4.0), (4.0, 6.0)),
        ((-4.0, 4.0), (0.0, 6.0)),
        ((0.0, 6.0), (4.0, 4.0)),
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
    for line_index, ((v0, z0), (v1, z1)) in enumerate(section_lines):
        t = rng.uniform(0.0, 1.0, 520)
        cloud_rows.append(np.column_stack((
            rng.normal(0.35 if line_index == 6 else 0.0, 0.02, len(t)),
            v0 + (v1 - v0) * t + rng.normal(0.0, 0.015, len(t)),
            z0 + (z1 - z0) * t + rng.normal(0.0, 0.015, len(t)),
        )))
    xyz = np.vstack(cloud_rows)
    source_rows = np.arange(5000, 5000 + len(xyz), dtype=np.int64)
    monkeypatch.setattr(steel, "_collect_zone_with_source_ids", lambda *_args: (xyz, source_rows, False))
    monkeypatch.setattr(steel, "_vertical_hough", lambda *_args, **_kwargs: (section, 0.1))
    monkeypatch.setattr(
        "scipy.signal.find_peaks",
        lambda hist, **_kwargs: (np.array([int(np.argmax(hist))]), {}),
    )

    cloud = CloudGeometry(Path("derived.npy"), np.zeros(3), xyz.min(0), xyz.max(0), len(xyz))
    elements, _planes, stats = steel._detect_trusses(cloud, (2.5, 6.5), axis=0.0)

    members = [item for item in elements if item.geometry.get("kind") == "member"]
    envelope = next(item for item in elements if item.class_name == "truss")
    assert stats["truss_count"] == 1
    assert len(members) == 7
    assert {item.dimensions["role"] for item in members} == {
        "truss_top_chord", "truss_bottom_chord", "truss_post", "truss_web", "unknown",
    }
    assert all(item.metadata["member_proposal"]["source_point_ids"] for item in members)
    assert all(item.metadata["member_proposal"]["review_state"] == "proposed" for item in members)
    assert all("section_m" not in item.geometry for item in members)
    assert all(item.bbox == derive_bbox(item.geometry) for item in members)
    assert envelope.metadata["member_count_traced"] == len(members)
    assert set(envelope.metadata["member_proposal_ids"]) == {
        item.metadata["member_proposal_id"] for item in members
    }
    assembly = envelope.metadata["assembly_proposal"]
    assert assembly["member_proposal_ids"] == sorted(envelope.metadata["member_proposal_ids"])
    assert assembly["node_candidates"]
    assert all(node["status"] == "proposed" for node in assembly["node_candidates"])
    assert all(set(node["candidate_member_proposal_ids"]).issubset(assembly["member_proposal_ids"])
               for node in assembly["node_candidates"])
    assert all(len(node["source_point_ids"]) >= 5 for node in assembly["node_candidates"])
    assert assembly["review_state"] == "proposed"
    for item in members:
        role = item.dimensions["role"]
        own_line = {
            "truss_top_chord": 0,
            "truss_bottom_chord": 1,
            "truss_post": 2 + int(round((item.geometry["p0"][1] + 4.0) / 4.0)),
        }.get(role)
        rows = set(item.metadata["member_proposal"]["source_point_ids"])
        if own_line is not None:
            own_rows = set(source_rows[own_line * 520 : (own_line + 1) * 520].tolist())
            # Intersections intentionally share scan rows within the selector's
            # endpoint buffer; isolated-member tests enforce stronger purity.
            assert len(rows & own_rows) / len(rows) > 0.50
        if role in {"truss_post", "truss_web"}:
            assert item.metadata["role_evidence"]["status"] == "proposed"
            assert item.metadata["role_evidence"]["supported_chords"] == ["bottom", "top"]
        if role == "unknown":
            proposal = item.metadata["member_proposal"]
            assert proposal["role"] == {"value": "unknown", "status": "unknown"}
            assert item.metadata["role_evidence"]["reason"] == "member_point_support_is_non_planar"
            assert item.metadata["member_proposal_id"] in envelope.metadata["member_proposal_ids"]


def test_partial_roof_truss_keeps_observed_members_without_filling_missing_posts(monkeypatch):
    rng = np.random.default_rng(86)
    lines = [
        ((-8.0, 6.0), (8.0, 6.0)),
        ((-8.0, 4.0), (8.0, 4.0)),
        ((-4.0, 4.0), (-4.0, 6.0)),
        ((4.0, 4.0), (4.0, 6.0)),
    ]

    def hough_segment(p0, p1):
        start, end = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
        delta = end - start
        length = float(np.linalg.norm(delta))
        direction = delta / length
        angle = math.atan2(float(direction[1]), float(direction[0]))
        return {
            "p0": start, "p1": end, "mid": (start + end) / 2,
            "dir": direction, "angle": angle,
            "angle_deg": math.degrees(angle) % 180.0, "length": length,
        }

    section = [hough_segment(*line) for line in lines]
    chunks = []
    for (v0, z0), (v1, z1) in lines:
        t = rng.uniform(0.0, 1.0, 600)
        chunks.append(np.column_stack((
            rng.normal(0.0, 0.015, len(t)),
            v0 + (v1 - v0) * t + rng.normal(0.0, 0.01, len(t)),
            z0 + (z1 - z0) * t + rng.normal(0.0, 0.01, len(t)),
        )))
    xyz = np.vstack(chunks)
    source_rows = np.arange(12000, 12000 + len(xyz), dtype=np.int64)
    monkeypatch.setattr(steel, "_collect_zone_with_source_ids", lambda *_args: (xyz, source_rows, False))
    monkeypatch.setattr(steel, "_vertical_hough", lambda *_args, **_kwargs: (section, 0.1))
    monkeypatch.setattr(
        "scipy.signal.find_peaks",
        lambda hist, **_kwargs: (np.array([int(np.argmax(hist))]), {}),
    )
    cloud = CloudGeometry(Path("derived.npy"), np.zeros(3), xyz.min(0), xyz.max(0), len(xyz))

    elements, planes, stats = steel._detect_trusses(cloud, (2.5, 6.5), axis=0.0)

    members = [item for item in elements if item.geometry.get("kind") == "member"]
    envelope = next((item for item in elements if item.class_name == "truss"), None)
    assert envelope is not None
    assert stats["truss_count"] == 1
    assert stats["truss_complete_count"] == 0
    assert stats["truss_partial_count"] == 1
    assert planes[0]["kind"] == "truss_partial"
    assert envelope.dimensions["completeness"] == "partial"
    assert envelope.dimensions["span_status"] == "observed_extent_only"
    assert envelope.dimensions["observed_panels"] == 2
    assert envelope.dimensions["required_minimum_posts"] == steel.TRUSS_MIN_POSTS
    assert envelope.dimensions["missing_evidence"] == ["additional_vertical_posts"]
    assert len(members) == 4
    post_positions = [round(item.geometry["p0"][1], 1) for item in members
                      if item.dimensions["role"] == "truss_post"]
    assert len(post_positions) == 2
    assert set(post_positions) == {-4.0, 4.0}
    assert all(item.metadata["member_proposal"]["source_point_ids"] for item in members)
    assert set(envelope.metadata["member_proposal_ids"]) == {
        item.metadata["member_proposal_id"] for item in members
    }
    assert envelope.metadata["assembly_proposal"]["review_state"] == "proposed"
    assert envelope.metadata["assembly_proposal"]["assembly_type"] == {
        "value": "roof_truss_partial", "status": "proposed",
    }


def test_overlapping_truss_projections_keep_distinct_planes_and_source_rows(monkeypatch):
    rng = np.random.default_rng(87)
    lines = [
        ((-8.0, 6.0), (8.0, 6.0)),
        ((-8.0, 4.0), (8.0, 4.0)),
        ((-5.0, 4.0), (-5.0, 6.0)),
        ((0.0, 4.0), (0.0, 6.0)),
        ((5.0, 4.0), (5.0, 6.0)),
    ]

    def hough_segment(p0, p1):
        start, end = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
        delta = end - start
        length = float(np.linalg.norm(delta))
        direction = delta / length
        angle = math.atan2(float(direction[1]), float(direction[0]))
        return {
            "p0": start, "p1": end, "mid": (start + end) / 2,
            "dir": direction, "angle": angle,
            "angle_deg": math.degrees(angle) % 180.0, "length": length,
        }

    section = [hough_segment(*line) for line in lines]
    point_chunks = []
    for plane_u in (-1.5, 1.5):
        for (v0, z0), (v1, z1) in lines:
            t = rng.uniform(0.0, 1.0, 700)
            point_chunks.append(np.column_stack((
                rng.normal(plane_u, 0.015, len(t)),
                v0 + (v1 - v0) * t + rng.normal(0.0, 0.01, len(t)),
                z0 + (z1 - z0) * t + rng.normal(0.0, 0.01, len(t)),
            )))
    boundary_clutter = np.column_stack((
        np.repeat((-2.5, 2.5), 60),
        rng.uniform(-10.0, 10.0, 120),
        rng.uniform(2.6, 6.4, 120),
    ))
    xyz = np.vstack((*point_chunks, boundary_clutter))
    source_rows = np.arange(20000, 20000 + len(xyz), dtype=np.int64)
    points_per_plane = len(lines) * 700
    first_plane_rows = set(source_rows[:points_per_plane].tolist())
    second_plane_rows = set(source_rows[points_per_plane:].tolist())
    monkeypatch.setattr(steel, "_collect_zone_with_source_ids", lambda *_args: (xyz, source_rows, False))
    monkeypatch.setattr(steel, "_vertical_hough", lambda *_args, **_kwargs: (section, 0.1))
    cloud = CloudGeometry(Path("derived.npy"), np.zeros(3), xyz.min(0), xyz.max(0), len(xyz))

    elements, planes, stats = steel._detect_trusses(cloud, (2.5, 6.5), axis=0.0)

    envelopes = [item for item in elements if item.class_name == "truss"]
    assert len(envelopes) == stats["truss_count"] == 2
    assert len(planes) == 2
    assert all(plane["kind"] == "truss" for plane in planes)
    assert abs(envelopes[0].geometry["center"][0] - envelopes[1].geometry["center"][0]) > 2.5
    member_by_id = {
        item.metadata["member_proposal_id"]: item
        for item in elements if item.metadata.get("member_proposal_id")
    }
    envelope_planes = []
    total_member_count = 0
    for envelope in envelopes:
        child_rows = [
            set(member_by_id[member_id].metadata["member_proposal"]["source_point_ids"])
            for member_id in envelope.metadata["member_proposal_ids"]
        ]
        total_member_count += len(child_rows)
        assert all(rows for rows in child_rows)
        if all(rows <= first_plane_rows for rows in child_rows):
            envelope_planes.append("first")
        elif all(rows <= second_plane_rows for rows in child_rows):
            envelope_planes.append("second")
        else:
            assert False, "one truss assembly mixed source rows from separate projected planes"
    assert total_member_count == 10
    assert set(envelope_planes) == {"first", "second"}


def test_partial_roof_truss_with_one_missing_chord_keeps_only_observed_members(monkeypatch):
    rng = np.random.default_rng(88)
    lines = [
        ((-8.0, 6.0), (8.0, 6.0)),
        ((-4.0, 4.0), (-4.0, 6.0)),
        ((4.0, 4.0), (4.0, 6.0)),
    ]

    def hough_segment(p0, p1):
        start, end = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
        delta = end - start
        length = float(np.linalg.norm(delta))
        direction = delta / length
        angle = math.atan2(float(direction[1]), float(direction[0]))
        return {
            "p0": start, "p1": end, "mid": (start + end) / 2,
            "dir": direction, "angle": angle,
            "angle_deg": math.degrees(angle) % 180.0, "length": length,
        }

    section = [hough_segment(*line) for line in lines]
    chunks = []
    for (v0, z0), (v1, z1) in lines:
        t = rng.uniform(0.0, 1.0, 800)
        chunks.append(np.column_stack((
            rng.normal(0.0, 0.01, len(t)),
            v0 + (v1 - v0) * t + rng.normal(0.0, 0.01, len(t)),
            z0 + (z1 - z0) * t + rng.normal(0.0, 0.01, len(t)),
        )))
    xyz = np.vstack(chunks)
    source_rows = np.arange(30000, 30000 + len(xyz), dtype=np.int64)
    monkeypatch.setattr(steel, "_collect_zone_with_source_ids", lambda *_args: (xyz, source_rows, False))
    monkeypatch.setattr(steel, "_vertical_hough", lambda *_args, **_kwargs: (section, 0.1))
    monkeypatch.setattr(
        "scipy.signal.find_peaks",
        lambda hist, **_kwargs: (np.array([int(np.argmax(hist))]), {}),
    )
    cloud = CloudGeometry(Path("derived.npy"), np.zeros(3), xyz.min(0), xyz.max(0), len(xyz))

    elements, planes, stats = steel._detect_trusses(cloud, (2.5, 6.5), axis=0.0)

    envelope = next((item for item in elements if item.class_name == "truss"), None)
    members = [item for item in elements if item.geometry.get("kind") == "member"]
    assert envelope is not None
    assert stats["truss_partial_count"] == 1
    assert planes[0]["kind"] == "truss_partial"
    assert envelope.dimensions["completeness"] == "partial"
    assert envelope.dimensions["missing_evidence"] == ["bottom_chord", "additional_vertical_posts"]
    assert envelope.dimensions["bottom_chord_z"] is None
    assert envelope.dimensions["top_chord_z"] == 6.0
    assert envelope.dimensions["height_status"] == "observed_extent_only"
    assert len(members) == 3
    assert {item.dimensions["role"] for item in members} == {
        "truss_top_chord", "unknown",
    }
    assert all(item.metadata["member_proposal"]["source_point_ids"] for item in members)
    assert envelope.metadata["assembly_proposal"]["assembly_type"] == {
        "value": "roof_truss_partial_missing_bottom_chord", "status": "proposed",
    }


def test_severe_chord_occlusion_keeps_observed_extent_without_completing_missing_chord(monkeypatch):
    """A short visible chord may support a partial proposal, never a full-span chord."""
    rng = np.random.default_rng(90)
    # Only 4.2 m of the 14 m observed truss extent remains visible on the top
    # chord. Three point-supported posts keep the partial truss reviewable.
    lines = [
        ((-2.1, 6.0), (2.1, 6.0)),
        ((-7.0, 4.0), (-7.0, 6.0)),
        ((0.0, 4.0), (0.0, 6.0)),
        ((7.0, 4.0), (7.0, 6.0)),
    ]

    def hough_segment(p0, p1):
        start, end = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
        delta = end - start
        length = float(np.linalg.norm(delta))
        direction = delta / length
        angle = math.atan2(float(direction[1]), float(direction[0]))
        return {
            "p0": start, "p1": end, "mid": (start + end) / 2,
            "dir": direction, "angle": angle,
            "angle_deg": math.degrees(angle) % 180.0, "length": length,
        }

    section = [hough_segment(*line) for line in lines]
    chunks = []
    for (v0, z0), (v1, z1) in lines:
        t = rng.uniform(0.0, 1.0, 800)
        chunks.append(np.column_stack((
            rng.normal(0.0, 0.01, len(t)),
            v0 + (v1 - v0) * t + rng.normal(0.0, 0.01, len(t)),
            z0 + (z1 - z0) * t + rng.normal(0.0, 0.01, len(t)),
        )))
    xyz = np.vstack(chunks)
    source_rows = np.arange(70000, 70000 + len(xyz), dtype=np.int64)
    monkeypatch.setattr(steel, "_collect_zone_with_source_ids", lambda *_args: (xyz, source_rows, False))
    monkeypatch.setattr(steel, "_vertical_hough", lambda *_args, **_kwargs: (section, 0.1))
    monkeypatch.setattr(
        "scipy.signal.find_peaks",
        lambda hist, **_kwargs: (np.array([int(np.argmax(hist))]), {}),
    )
    cloud = CloudGeometry(Path("derived.npy"), np.zeros(3), xyz.min(0), xyz.max(0), len(xyz))

    elements, planes, stats = steel._detect_trusses(cloud, (2.5, 6.5), axis=0.0)

    envelope = next((item for item in elements if item.class_name == "truss"), None)
    members = [item for item in elements if item.geometry.get("kind") == "member"]
    observed_top_chords = [
        item for item in members if item.dimensions["role"] == "truss_top_chord"
    ]
    assert envelope is not None
    assert stats["truss_partial_count"] == 1
    assert planes[0]["kind"] == "truss_partial"
    assert envelope.dimensions["completeness"] == "partial"
    assert envelope.dimensions["missing_evidence"] == ["bottom_chord"]
    assert envelope.dimensions["bottom_chord_z"] is None
    assert envelope.dimensions["span_m"] == pytest.approx(14.0, abs=0.2)
    assert len(observed_top_chords) == 1
    observed_chord = observed_top_chords[0]
    assert np.linalg.norm(
        np.asarray(observed_chord.geometry["p1"]) - np.asarray(observed_chord.geometry["p0"])
    ) == pytest.approx(4.2, abs=0.2)
    chord_source_ids = set(observed_chord.metadata["member_proposal"]["source_point_ids"])
    assert chord_source_ids
    assert chord_source_ids <= set(source_rows)
    assert len(chord_source_ids & set(source_rows[:800])) / len(chord_source_ids) >= 0.8
    assert len(members) == 4


def test_partial_truss_preserves_short_occluded_chord_fragments_as_unknown(monkeypatch):
    rng = np.random.default_rng(89)
    lines = [
        ((-8.0, 6.0), (-5.0, 6.0)),
        ((5.0, 6.0), (8.0, 6.0)),
        ((-8.0, 4.0), (8.0, 4.0)),
        ((-4.0, 4.0), (-4.0, 6.0)),
        ((0.0, 4.0), (0.0, 6.0)),
        ((4.0, 4.0), (4.0, 6.0)),
    ]

    def hough_segment(p0, p1):
        start, end = np.asarray(p0, dtype=float), np.asarray(p1, dtype=float)
        delta = end - start
        length = float(np.linalg.norm(delta))
        direction = delta / length
        angle = math.atan2(float(direction[1]), float(direction[0]))
        return {
            "p0": start, "p1": end, "mid": (start + end) / 2,
            "dir": direction, "angle": angle,
            "angle_deg": math.degrees(angle) % 180.0, "length": length,
        }

    section = [hough_segment(*line) for line in lines]
    chunks = []
    for (v0, z0), (v1, z1) in lines:
        t = rng.uniform(0.0, 1.0, 800)
        chunks.append(np.column_stack((
            rng.normal(0.0, 0.01, len(t)),
            v0 + (v1 - v0) * t + rng.normal(0.0, 0.01, len(t)),
            z0 + (z1 - z0) * t + rng.normal(0.0, 0.01, len(t)),
        )))
    xyz = np.vstack(chunks)
    source_rows = np.arange(50000, 50000 + len(xyz), dtype=np.int64)
    monkeypatch.setattr(steel, "_collect_zone_with_source_ids", lambda *_args: (xyz, source_rows, False))
    monkeypatch.setattr(steel, "_vertical_hough", lambda *_args, **_kwargs: (section, 0.1))
    monkeypatch.setattr(
        "scipy.signal.find_peaks",
        lambda hist, **_kwargs: (np.array([int(np.argmax(hist))]), {}),
    )
    cloud = CloudGeometry(Path("derived.npy"), np.zeros(3), xyz.min(0), xyz.max(0), len(xyz))

    elements, _planes, stats = steel._detect_trusses(cloud, (2.5, 6.5), axis=0.0)

    envelope = next((item for item in elements if item.class_name == "truss"), None)
    members = [item for item in elements if item.geometry.get("kind") == "member"]
    short_top_fragments = [
        item for item in members
        if item.dimensions["role"] == "unknown"
        and abs(item.geometry["p0"][2] - 6.0) < 0.1
        and np.linalg.norm(np.asarray(item.geometry["p1"]) - np.asarray(item.geometry["p0"]))
        < steel.TRUSS_MIN_CHORD_M
    ]
    assert envelope is not None
    assert stats["truss_partial_count"] == 1
    assert envelope.dimensions["top_chord_z"] is None
    assert envelope.dimensions["missing_evidence"] == ["top_chord"]
    assert len(short_top_fragments) == 2
    assert all(item.metadata["member_proposal"]["source_point_ids"] for item in short_top_fragments)
    assert all(item.metadata["role_evidence"]["reason"] == "horizontal_fragment_below_minimum_chord_span"
               for item in short_top_fragments)
    ordered_fragments = sorted(
        short_top_fragments,
        key=lambda item: (item.geometry["p0"][0] + item.geometry["p1"][0]) / 2,
    )
    left_rows = set(ordered_fragments[0].metadata["member_proposal"]["source_point_ids"])
    right_rows = set(ordered_fragments[1].metadata["member_proposal"]["source_point_ids"])
    assert left_rows.isdisjoint(right_rows)
    assert left_rows <= set(source_rows[:800].tolist())
    assert right_rows <= set(source_rows[800: 2 * 800].tolist())


def test_horizontal_brace_candidate_carries_only_its_near_axis_rows():
    rng = np.random.default_rng(85)
    direction = np.array([math.sqrt(0.5), math.sqrt(0.5)])
    normal = np.array([-direction[1], direction[0]])
    along = rng.uniform(-3.0, 3.0, 600)
    across = rng.normal(0.0, 0.025, len(along))
    brace_xy = along[:, None] * direction + across[:, None] * normal
    brace_xyz = np.column_stack((brace_xy, rng.uniform(4.95, 5.05, len(along))))
    clutter_xy = along[:, None] * direction + 0.5 * normal
    clutter_xyz = np.column_stack((clutter_xy, rng.uniform(4.95, 5.05, len(along))))
    xyz = np.vstack((brace_xyz, clutter_xyz))
    source_rows = np.arange(8000, 8000 + len(xyz), dtype=np.int64)
    candidate = (np.zeros(2), direction, 6.0, 0.9, 0.08, 4.95, 5.05, len(along))
    cloud = CloudGeometry(Path("derived.npy"), np.zeros(3), xyz.min(0), xyz.max(0), len(xyz))

    members = steel._emit_horizontal_braces(
        cloud, [candidate], source_points=xyz, source_rows=source_rows,
    )

    assert len(members) == 1
    proposal = members[0].metadata["member_proposal"]
    selected = set(proposal["source_point_ids"])
    assert selected
    assert selected <= set(source_rows[: len(along)].tolist())
    assert proposal["role"] == {"value": "brace", "status": "proposed"}
    assert "section_m" not in members[0].geometry
    assert members[0].bbox == derive_bbox(members[0].geometry)


def test_truss_node_rejects_nearby_clutter_without_support_on_member_axes():
    members = [
        ((np.array([0.0, 0.0]), np.array([1.0, 0.0]), 4.0), "horizontal"),
        ((np.array([0.0, 0.0]), np.array([0.0, 1.0]), 4.0), "vertical"),
    ]
    rng = np.random.default_rng(860)
    # This cluster sits inside the node radius but 0.12 m from both axes.
    clutter = rng.normal(loc=(0.12, 0.12), scale=0.003, size=(12, 2))

    proposals = steel._section_node_evidence(members, clutter, np.arange(100, 112))

    assert proposals == []


def test_truss_node_stays_unproposed_when_one_member_has_no_local_point_support():
    members = [
        ((np.array([0.0, 0.0]), np.array([1.0, 0.0]), 4.0), "horizontal"),
        ((np.array([0.0, 0.0]), np.array([0.0, 1.0]), 4.0), "vertical"),
    ]
    along = np.linspace(-0.15, 0.15, 8)
    horizontal_points = np.column_stack((along, np.zeros_like(along)))

    proposals = steel._section_node_evidence(members, horizontal_points, np.arange(200, 208))

    assert proposals == []


def test_truss_node_candidate_requires_local_evidence_from_both_member_axes():
    members = [
        ((np.array([0.0, 0.0]), np.array([1.0, 0.0]), 4.0), "horizontal"),
        ((np.array([0.0, 0.0]), np.array([0.0, 1.0]), 4.0), "vertical"),
    ]
    along = np.linspace(-0.15, 0.15, 8)
    points = np.vstack((
        np.column_stack((along, np.zeros_like(along))),
        np.column_stack((np.zeros_like(along), along)),
    ))
    source_rows = np.arange(300, 300 + len(points))

    proposals = steel._section_node_evidence(members, points, source_rows)

    assert len(proposals) == 1
    assert proposals[0]["candidate_member_proposal_ids"] == {"horizontal", "vertical"}
    assert proposals[0]["source_point_ids"] == set(source_rows.tolist())


def test_truss_node_rejects_projected_crossing_from_separate_planes():
    members = [
        ((np.array([0.0, 0.0]), np.array([1.0, 0.0]), 4.0), "horizontal"),
        ((np.array([0.0, 0.0]), np.array([0.0, 1.0]), 4.0), "vertical"),
    ]
    along = np.linspace(-0.15, 0.15, 8)
    points = np.vstack((
        np.column_stack((along, np.zeros_like(along))),
        np.column_stack((np.zeros_like(along), along)),
    ))
    source_rows = np.arange(400, 400 + len(points))
    plane_coordinates = np.concatenate((np.zeros(8), np.full(8, 0.30)))

    proposals = steel._section_node_evidence(
        members, points, source_rows, plane_coordinates=plane_coordinates,
    )

    assert proposals == []


def test_truss_node_rejects_consistent_points_from_the_wrong_candidate_plane():
    members = [
        ((np.array([0.0, 0.0]), np.array([1.0, 0.0]), 4.0), "horizontal"),
        ((np.array([0.0, 0.0]), np.array([0.0, 1.0]), 4.0), "vertical"),
    ]
    along = np.linspace(-0.15, 0.15, 8)
    points = np.vstack((
        np.column_stack((along, np.zeros_like(along))),
        np.column_stack((np.zeros_like(along), along)),
    ))
    source_rows = np.arange(550, 550 + len(points))

    proposals = steel._section_node_evidence(
        members, points, source_rows,
        plane_coordinates=np.full(len(points), 0.36),
        reference_plane_m=0.0,
    )

    assert proposals == []


def test_truss_node_excludes_mixed_plane_points_hidden_by_matching_medians():
    members = [
        ((np.array([0.0, 0.0]), np.array([1.0, 0.0]), 4.0), "horizontal"),
        ((np.array([0.0, 0.0]), np.array([0.0, 1.0]), 4.0), "vertical"),
    ]
    along = np.linspace(-0.15, 0.15, 8)
    points = np.vstack((
        np.column_stack((along, np.zeros_like(along))),
        np.column_stack((np.zeros_like(along), along)),
    ))
    # Half of the local horizontal evidence is 0.36 m out of plane. Its
    # median still matches the vertical member's median, masking two layers.
    planes = np.concatenate((np.repeat((0.0, 0.36), 4), np.zeros(8)))
    source_rows = np.arange(600, 600 + len(points))

    proposals = steel._section_node_evidence(
        members, points, source_rows, plane_coordinates=planes,
    )

    assert len(proposals) == 1
    assert proposals[0]["candidate_member_proposal_ids"] == {"horizontal", "vertical"}
    assert proposals[0]["source_point_ids"].isdisjoint(set(range(604, 608)))


def test_truss_node_stays_unknown_when_both_member_lines_have_a_scan_gap_at_crossing():
    members = [
        ((np.array([0.0, 0.0]), np.array([1.0, 0.0]), 4.0), "horizontal"),
        ((np.array([0.0, 0.0]), np.array([0.0, 1.0]), 4.0), "vertical"),
    ]
    along = np.concatenate((np.linspace(-1.2, -0.4, 8), np.linspace(0.4, 1.2, 8)))
    points = np.vstack((
        np.column_stack((along, np.zeros_like(along))),
        np.column_stack((np.zeros_like(along), along)),
    ))

    proposals = steel._section_node_evidence(
        members, points, np.arange(500, 500 + len(points)),
    )

    assert proposals == []
