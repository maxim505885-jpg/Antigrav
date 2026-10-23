import math
import numpy as np
import pytest

from scan2bim.processing.panorama import (
    project_uv_to_ray,
    project_point_to_uv,
    generate_station_depth_panorama,
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
