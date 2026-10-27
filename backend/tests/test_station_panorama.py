import json
import math
from pathlib import Path

import numpy as np
import pytest

from scan2bim.processing.panorama import (
    angular_resolution_deg,
    generate_station_depth_panorama,
    measure_between,
    panorama_pick,
    project_point_to_uv,
    project_uv_to_ray,
    render_cloud_panorama,
    render_cloud_panorama_streaming,
    station_catalog,
    station_points,
)


def test_project_uv_to_ray_cardinal_directions():
    # Center u=0.5, v=0.5 -> looking along +Y
    ray_front = project_uv_to_ray(0.5, 0.5)
    assert np.allclose(ray_front, [0.0, 1.0, 0.0], atol=1e-5)

    # Top u=0.5, v=0.0 -> looking straight UP (+Z)
    ray_up = project_uv_to_ray(0.5, 0.0)
    assert np.allclose(ray_up, [0.0, 0.0, 1.0], atol=1e-5)

    # Bottom u=0.5, v=1.0 -> looking straight DOWN (-Z)
    ray_down = project_uv_to_ray(0.5, 1.0)
    assert np.allclose(ray_down, [0.0, 0.0, -1.0], atol=1e-5)


def test_project_point_to_uv_roundtrip():
    station = np.array([10.0, 20.0, 1.5])
    pt = np.array([10.0, 30.0, 1.5])  # 10m directly along +Y

    u, v, dist = project_point_to_uv(pt, station)
    assert math.isclose(dist, 10.0, abs_tol=1e-5)
    assert math.isclose(u, 0.5, abs_tol=1e-4)
    assert math.isclose(v, 0.5, abs_tol=1e-4)

    ray = project_uv_to_ray(u, v)
    reconstructed_pt = station + ray * dist
    assert np.allclose(pt, reconstructed_pt, atol=1e-4)


def test_project_uv_rejects_out_of_range():
    with pytest.raises(ValueError):
        project_uv_to_ray(1.5, 0.5)


def test_generate_station_depth_panorama():
    station = np.array([0.0, 0.0, 0.0])
    # 4 points at 5m in 4 directions
    pts = np.array([
        [0.0, 5.0, 0.0],
        [5.0, 0.0, 0.0],
        [0.0, -5.0, 0.0],
        [-5.0, 0.0, 0.0],
    ])

    depth = generate_station_depth_panorama(pts, station, width=128, height=64)
    assert depth.shape == (64, 128)
    valid_pixels = ~np.isnan(depth)
    assert np.sum(valid_pixels) >= 4
    assert np.allclose(depth[valid_pixels], 5.0, atol=1e-3)


def test_depth_panorama_keeps_nearest_point_per_pixel():
    station = np.zeros(3)
    pts = np.array([[0.0, 30.0, 0.0], [0.0, 10.0, 0.0], [0.0, 20.0, 0.0]])
    depth = generate_station_depth_panorama(pts, station, width=256, height=128)
    centre = depth[64, 128]
    assert math.isclose(float(centre), 10.0, abs_tol=1e-3)


def test_render_cloud_panorama_reports_real_coverage_and_source():
    # A ring of points around the anchor at 10 m in the horizontal plane.
    angles = np.linspace(0.0, 2.0 * math.pi, 360, endpoint=False)
    pts = np.column_stack([np.sin(angles) * 10.0, np.cos(angles) * 10.0, np.zeros_like(angles)])
    rendered = render_cloud_panorama(pts, np.zeros(3), width=256, height=128, max_range_m=25.0)

    assert rendered["rgb"].shape == (128, 256, 3)
    assert rendered["depth"].shape == (128, 256)
    assert rendered["rendered_points"] == 360
    assert rendered["color_source"] == "height_ramp"
    assert 0.0 < rendered["coverage"] < 0.2  # a ring covers a thin band, not the sky
    valid = np.isfinite(rendered["depth"])
    assert np.allclose(rendered["depth"][valid], 10.0, atol=1e-2)


def test_render_uses_cloud_colours_when_shapes_match():
    pts = np.array([[0.0, 5.0, 0.0], [5.0, 0.0, 0.0]])
    colors = np.array([[255, 0, 0], [0, 0, 255]], dtype=np.uint8)
    rendered = render_cloud_panorama(pts, np.zeros(3), width=256, height=128, colors=colors)
    assert rendered["color_source"] == "cloud_rgb"
    painted = rendered["rgb"].reshape(-1, 3)
    assert any(np.array_equal(row, [255, 0, 0]) for row in painted)
    assert any(np.array_equal(row, [0, 0, 255]) for row in painted)


def test_render_rejects_odd_or_tiny_width():
    pts = np.array([[0.0, 5.0, 0.0]])
    with pytest.raises(ValueError):
        render_cloud_panorama(pts, np.zeros(3), width=255, height=128)
    with pytest.raises(ValueError):
        render_cloud_panorama(pts, np.zeros(3), width=128, height=64)


def test_pick_returns_measured_point_and_precision():
    anchor = np.array([1.0, 2.0, 0.5])
    point = anchor + np.array([0.0, 8.0, 0.0])
    depth = generate_station_depth_panorama(np.array([point]), anchor, width=512, height=256)
    pick = panorama_pick(depth, anchor, 0.5, 0.5)

    assert pick["resolved"] is True
    assert math.isclose(pick["distance_m"], 8.0, abs_tol=1e-3)
    # The depth is exact; the lateral position can only be as good as one pixel,
    # and the pick states that precision instead of pretending to be exact.
    lateral_error = float(np.linalg.norm(np.asarray(pick["point"]) - point))
    assert lateral_error <= pick["lateral_precision_m"]
    assert pick["depth_source"] == "point_cloud"
    assert pick["lateral_precision_m"] > 0
    horizontal, vertical = angular_resolution_deg(512, 256)
    assert math.isclose(horizontal, 360.0 / 512)
    assert math.isclose(vertical, 180.0 / 256)


def test_pick_reports_missing_data_instead_of_guessing():
    depth = np.full((64, 128), np.nan, dtype=np.float32)
    pick = panorama_pick(depth, np.zeros(3), 0.5, 0.5)
    assert pick["resolved"] is False
    assert "no points" in pick["reason"]
    assert "point" not in pick


def test_measure_between_known_points():
    anchor = np.zeros(3)
    a = np.array([5.0, 0.0, 0.0])
    b = np.array([0.0, 12.0, 0.0])
    depth = generate_station_depth_panorama(np.array([a, b]), anchor, width=1024, height=512)
    u_a, v_a, _ = project_point_to_uv(a, anchor)
    u_b, v_b, _ = project_point_to_uv(b, anchor)

    result = measure_between(depth, anchor, (u_a, v_a), (u_b, v_b))
    assert result["resolved"] is True
    assert result["distance_mm"] == pytest.approx(13000.0, rel=1e-3)
    assert result["precision_mm"] > 0


def test_measure_between_refuses_when_one_direction_is_empty():
    anchor = np.zeros(3)
    a = np.array([5.0, 0.0, 0.0])
    depth = generate_station_depth_panorama(np.array([a]), anchor, width=256, height=128)
    u_a, v_a, _ = project_point_to_uv(a, anchor)

    result = measure_between(depth, anchor, (u_a, v_a), (0.25, 0.25))
    assert result["resolved"] is False
    assert "no depth data" in result["reason"]
    assert "distance_mm" not in result


def test_pick_marks_a_continuous_surface_as_stable():
    # A slightly slanted plane is still one surface: the gap between adjacent
    # depths stays small, so the pick is not flagged as an edge.
    depth = np.full((256, 512), np.nan, dtype=np.float32)
    depth[100:110, 200:220] = np.linspace(9.98, 10.02, 20, dtype=np.float32)
    pick = panorama_pick(depth, np.zeros(3), 205.0 / 512.0, 105.0 / 256.0)

    assert pick["resolved"] is True
    assert pick["stable"] is True
    assert pick["stability"] == "continuous_surface"
    assert pick["max_depth_gap_m"] < pick["stability_tolerance_m"]


def test_pick_marks_a_depth_discontinuity_as_unstable():
    # Two surfaces 45 m apart meet inside the search window: a ray that shifts
    # by half a pixel would land on the other one, so the answer must be marked.
    depth = np.full((128, 256), np.nan, dtype=np.float32)
    depth[:, :128] = 5.0
    depth[:, 128:] = 50.0
    pick = panorama_pick(depth, np.zeros(3), 128.0 / 256.0, 0.5)

    assert pick["resolved"] is True
    assert pick["stable"] is False
    assert pick["stability"] == "depth_discontinuity"
    assert pick["max_depth_gap_m"] > 40.0
    assert pick["depth_spread_m"] > 40.0


def test_measure_reports_unreliable_when_an_endpoint_sits_on_an_edge():
    depth = np.full((128, 256), np.nan, dtype=np.float32)
    depth[:, :128] = 5.0
    depth[:, 128:] = 50.0
    result = measure_between(depth, np.zeros(3), (128.0 / 256.0, 0.5), (40.0 / 256.0, 0.5))

    assert result["resolved"] is True
    assert result["reliable"] is False
    assert result["unstable_endpoints"] == ["a"]
    assert "разрыве глубин" in result["warning"]


def _streaming_cloud(tmp_path: Path, count: int = 400):
    angles = np.linspace(0.0, 2.0 * math.pi, count, endpoint=False)
    points = np.column_stack(
        [np.sin(angles) * 12.0, np.cos(angles) * 12.0, np.linspace(-2.0, 2.0, count)]
    ).astype(np.float32)
    colors = np.clip(
        np.column_stack([np.linspace(0, 255, count), np.full(count, 40), np.full(count, 200)]),
        0,
        255,
    ).astype(np.uint8)
    positions = tmp_path / "positions.npy"
    colors_path = tmp_path / "colors.npy"
    np.save(positions, points)
    np.save(colors_path, colors)
    entry = {
        "station_id": "st-01",
        "row_start": 0,
        "row_end": count,
        "point_count": count,
        "anchor_local": [0.0, 0.0, 0.0],
    }
    return positions, colors_path, entry, points, colors


def test_streaming_render_matches_the_sampled_render(tmp_path):
    positions, colors_path, entry, points, colors = _streaming_cloud(tmp_path)
    sampled = render_cloud_panorama(
        points, np.zeros(3), width=256, height=128, max_range_m=30.0, colors=colors
    )
    streamed = render_cloud_panorama_streaming(
        positions, entry, width=256, height=128, max_range_m=30.0, colors_path=colors_path
    )

    assert np.array_equal(np.asarray(streamed["rgb"]), np.asarray(sampled["rgb"]))
    assert np.allclose(streamed["depth"], sampled["depth"], equal_nan=True, atol=1e-5)
    assert streamed["coverage"] == pytest.approx(sampled["coverage"], abs=1e-6)
    assert streamed["full_resolution"] is True
    assert streamed["stride"] == 1
    assert streamed["points_examined"] == entry["point_count"]


def test_streaming_render_reads_every_point_of_a_large_station(tmp_path):
    positions, colors_path, entry, points, _ = _streaming_cloud(tmp_path, count=120)
    progress_updates = []
    rendered = render_cloud_panorama_streaming(
        positions,
        entry,
        width=256,
        height=128,
        max_range_m=30.0,
        colors_path=colors_path,
        block_rows=25,
        progress=lambda fraction, message: progress_updates.append((fraction, message)),
    )
    # Blocks must not lose or duplicate rows: every stored point is inspected once.
    assert rendered["blocks"] == math.ceil(entry["point_count"] / 25)
    assert rendered["points_examined"] == entry["point_count"]
    assert rendered["rendered_points"] == entry["point_count"]
    assert rendered["source_points"] == len(points)
    assert progress_updates[0][0] == 0.0
    assert progress_updates[-1][0] == 1.0
    assert all(left[0] <= right[0] for left, right in zip(progress_updates, progress_updates[1:]))
    assert "обработано блоков" in progress_updates[-1][1]


def test_streaming_render_counts_points_beyond_the_range(tmp_path):
    positions, _, entry, _, _ = _streaming_cloud(tmp_path, count=200)
    rendered = render_cloud_panorama_streaming(
        positions, entry, width=256, height=128, max_range_m=6.0, colors_path=None
    )
    assert rendered["beyond_range_points"] == entry["point_count"]
    assert rendered["rendered_points"] == 0
    assert rendered["coverage"] == 0.0
    assert rendered["color_source"] == "height_ramp"


def test_streaming_render_rejects_rows_outside_the_file(tmp_path):
    positions, _, entry, _, _ = _streaming_cloud(tmp_path, count=50)
    entry["row_end"] = 51
    with pytest.raises(ValueError):
        render_cloud_panorama_streaming(positions, entry, width=256, height=128)


def _write_cloud(tmp_path: Path, with_stations: bool):
    station_a = np.array(
        [
            [5.0, 0.0, 0.0],
            [-5.0, 0.0, 0.0],
            [0.0, 5.0, 0.0],
            [0.0, -5.0, 0.0],
        ],
        dtype=np.float32,
    )
    station_b = station_a + np.array([20.0, 0.0, 0.0], dtype=np.float32)
    points = np.vstack([station_a, station_b])
    positions = tmp_path / "positions.npy"
    np.save(positions, points)
    metadata = {"origin": [100.0, 200.0, 0.0], "station_count": 2}
    if with_stations:
        metadata["station_row_ranges"] = [
            {
                "station_id": "st-01",
                "source_row_start": 0,
                "source_row_end_exclusive": 4,
                "source_row_count": 4,
                "source_row_index_base": 0,
            },
            {
                "station_id": "st-02",
                "source_row_start": 4,
                "source_row_end_exclusive": 8,
                "source_row_count": 4,
                "source_row_index_base": 0,
            },
        ]
    return positions, metadata, points


def test_station_catalog_reads_real_station_ranges(tmp_path):
    positions, metadata, _ = _write_cloud(tmp_path, with_stations=True)
    entries = station_catalog(positions, metadata)

    assert [entry["station_id"] for entry in entries] == ["st-01", "st-02"]
    assert [entry["point_count"] for entry in entries] == [4, 4]
    assert entries[0]["station_source"] == "station_row_ranges"
    # Anchor is the measured centroid of the station's own points, in world coordinates.
    assert entries[0]["anchor"] == pytest.approx([100.0, 200.0, 0.0], abs=1e-4)
    assert entries[1]["anchor"] == pytest.approx([120.0, 200.0, 0.0], abs=1e-4)
    assert entries[0]["anchor_kind"] == "point_centroid"


def test_station_catalog_marks_single_station_cloud(tmp_path):
    positions, metadata, points = _write_cloud(tmp_path, with_stations=False)
    entries = station_catalog(positions, metadata)

    assert len(entries) == 1
    assert entries[0]["station_id"] == "cloud"
    assert entries[0]["station_source"] == "cloud"
    assert entries[0]["point_count"] == len(points)


def test_station_catalog_rejects_out_of_bounds_ranges(tmp_path):
    positions, metadata, _ = _write_cloud(tmp_path, with_stations=True)
    metadata["station_row_ranges"][1]["source_row_end_exclusive"] = 99
    with pytest.raises(ValueError):
        station_catalog(positions, metadata)


def test_station_points_aligns_with_stride(tmp_path):
    positions, metadata, points = _write_cloud(tmp_path, with_stations=True)
    entry = station_catalog(positions, metadata)[0]
    block, step = station_points(positions, entry, max_points=2)
    assert step == 2
    assert len(block) == 2


def test_station_catalogue_cache_payload_is_json_serialisable(tmp_path):
    positions, metadata, _ = _write_cloud(tmp_path, with_stations=True)
    entries = station_catalog(positions, metadata)
    payload = json.loads(json.dumps({"stations": entries}))
    assert payload["stations"][1]["station_id"] == "st-02"
