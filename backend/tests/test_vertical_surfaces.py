"""Vertical plane extraction preserves every source row represented by a voxel."""
from __future__ import annotations

import numpy as np

from scan2bim.structure.vertical_surfaces import extract_vertical_surfaces


def test_vertical_surface_point_indices_refer_to_every_source_row_in_consensus():
    z_values = np.linspace(0.0, 2.0, 41)
    along_values = np.linspace(-0.4, 0.4, 31)
    first = np.array([(0.5, along, z) for z in z_values for along in along_values])
    second = np.array([(-0.5, along, z) for z in z_values for along in along_values])
    points = np.concatenate((first, second))

    result = extract_vertical_surfaces(
        points,
        distance_tolerance_m=0.005,
        voxel_m=0.01,
        min_support=30,
        min_vertical_span_m=0.5,
        max_planes=4,
        max_trials=64,
    )

    assert len(result["surfaces"]) == 2
    found_rows = [row for surface in result["surfaces"] for row in surface["input_point_indices"]]
    assert sorted(found_rows) == list(range(len(points)))
    for surface in result["surfaces"]:
        source_rows = np.asarray(surface["input_point_indices"], dtype=np.int64)
        assert np.allclose(np.ptp(points[source_rows, 0]), 0.0, atol=0.005)
        assert len(np.unique(source_rows)) == len(source_rows)
