"""Tests for SP 70.13330 deformation and verticality inspection."""
import numpy as np
import pytest
from scan2bim.structure.deformation_inspection import compute_column_verticality_inspection


def test_column_verticality_steel_compliant():
    # 8-meter vertical steel column with 6mm slight lean (under 8mm limit for H=8m)
    height_m = 8.0
    z = np.linspace(0.0, height_m, 200)
    # Slight tilt of 6mm along X
    x = (z / height_m) * 0.006 + np.random.normal(0, 0.001, 200)
    y = np.random.normal(0, 0.001, 200)
    pts = np.column_stack([x, y, z])

    res = compute_column_verticality_inspection(
        column_id="COL_01",
        points=pts,
        column_height_m=height_m,
        material_type="steel",
    )

    assert res["status"] == "compliant"
    assert res["limit_deviation_mm"] == 8.0  # H/1000 = 8000/1000 = 8mm
    assert 5.0 < res["top_deviation_total_mm"] < 7.0
    assert res["margin_mm"] > 0
    assert len(res["elevation_slices"]) >= 3


def test_column_verticality_exceeded():
    # 10-meter column with 25mm lean (exceeds 10mm limit)
    height_m = 10.0
    z = np.linspace(0.0, height_m, 200)
    x = (z / height_m) * 0.025
    y = np.zeros_like(z)
    pts = np.column_stack([x, y, z])

    res = compute_column_verticality_inspection(
        column_id="COL_02",
        points=pts,
        column_height_m=height_m,
        material_type="steel",
    )

    assert res["status"] == "exceeded"
    assert res["limit_deviation_mm"] == 10.0
    assert res["top_deviation_total_mm"] >= 24.0
    assert res["margin_mm"] < 0
