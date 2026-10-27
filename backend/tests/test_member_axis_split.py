from __future__ import annotations

import math

import pytest

from scan2bim.services import split_oriented_box_along_member_axis


def test_member_axis_split_preserves_rotation_and_creates_contiguous_world_boxes():
    parent = {
        "kind": "oriented_box",
        "center": [10.0, 20.0, 4.0],
        "sizes": {"length": 10.0, "thickness": 2.0, "height": 1.0},
        "rotation_z": math.pi / 6,
        "note": "candidate member",
    }

    parts = split_oriented_box_along_member_axis(parent, 4.0)

    assert [part["geometry"]["sizes"]["length"] for part in parts] == [4.0, 6.0]
    assert all(part["geometry"]["rotation_z"] == pytest.approx(math.pi / 6) for part in parts)
    assert parts[0]["geometry"]["center"] == pytest.approx(
        [10 - 3 * math.cos(math.pi / 6), 20 - 3 * math.sin(math.pi / 6), 4],
        abs=5e-5,
    )
    assert parts[1]["geometry"]["center"] == pytest.approx(
        [10 + 2 * math.cos(math.pi / 6), 20 + 2 * math.sin(math.pi / 6), 4],
        abs=5e-5,
    )
    assert parts[0]["bbox"]["max"][2] == pytest.approx(4.5)
    assert parts[1]["bbox"]["min"][2] == pytest.approx(3.5)
    direction = [math.cos(math.pi / 6), math.sin(math.pi / 6)]
    gap = [parts[1]["geometry"]["center"][i] - parts[0]["geometry"]["center"][i] for i in range(2)]
    assert sum(gap[i] * direction[i] for i in range(2)) == pytest.approx(5.0, abs=5e-4)


@pytest.mark.parametrize("offset", [0, 0.005, 9.995, 10])
def test_member_axis_split_rejects_endpoints_and_non_finite_offsets(offset: float):
    parent = {
        "kind": "oriented_box", "center": [0, 0, 0],
        "sizes": {"length": 10, "thickness": 1, "height": 1}, "rotation_z": 0,
    }

    with pytest.raises(ValueError, match="inside the member"):
        split_oriented_box_along_member_axis(parent, offset)

    with pytest.raises(ValueError, match="finite"):
        split_oriented_box_along_member_axis(parent, float("nan"))


def test_member_axis_split_rejects_invalid_or_axis_aligned_geometry():
    with pytest.raises(ValueError, match="oriented_box"):
        split_oriented_box_along_member_axis({"kind": "member"}, 2)

    parent = {
        "kind": "oriented_box", "center": [0, 0, 0],
        "sizes": {"length": 10, "thickness": 1, "height": 1}, "rotation_z": float("inf"),
    }
    with pytest.raises(ValueError, match="finite"):
        split_oriented_box_along_member_axis(parent, 2)
