import numpy as np
import pytest

from scan2bim.recognition.geometric import DetectedElement
from scan2bim.recognition.steel import _runway_column_context


def column(x, y=0, top=8, bottom=0):
    return DetectedElement('column', {},
                           {'min': [x-.2, y-.2, bottom],
                            'max': [x+.2, y+.2, top]}, .6)


def context(columns):
    return _runway_column_context(np.array([3., 0.]), np.array([1., 0.]),
                                  6., 5., np.zeros(3), columns)


def test_two_columns_along_beam_supply_context_but_not_confirmation():
    result = context([column(0), column(6)])
    assert result['status'] == 'supported_hypothesis'
    assert result['support_spacing_m'] == pytest.approx(6.)
    assert result['requires_review'] is True


def test_two_interior_columns_do_not_stand_in_for_end_supports():
    result = context([column(1), column(5)])
    assert result['status'] == 'insufficient_context'
    assert result['end_supports']['start'] is None
    assert result['end_supports']['end'] is None


@pytest.mark.parametrize('columns', [[], [column(0)], [column(0), column(0)],
    [column(0), column(6, y=3)], [column(0), column(6, top=3)],
    [column(0), column(6, bottom=6)]])
def test_absent_duplicate_remote_or_wrong_height_columns_do_not_support_runway(columns):
    assert context(columns)['status'] == 'insufficient_context'


def test_parallel_column_row_outside_beam_footprint_does_not_support_runway():
    # The old fixed 0.8 m lateral allowance could associate a narrow girder
    # with a separate parallel row of columns.
    result = context([column(0, y=0.7), column(6, y=0.7)])
    assert result['status'] == 'insufficient_context'
    assert result['supports'] == []


def test_rotated_column_aabb_cannot_create_false_support_for_diagonal_runway():
    direction = np.array([np.sqrt(0.5), np.sqrt(0.5)])
    normal = np.array([-direction[1], direction[0]])
    beam_center = np.array([3., 3.])
    columns = []
    for along in (-3., 3.):
        center = beam_center + direction * along + normal * 0.6
        column_candidate = column(float(center[0]), float(center[1]))
        aabb_half_width = np.sqrt(0.5) * 0.6
        column_candidate.bbox = {
            'min': [center[0] - aabb_half_width,
                    center[1] - aabb_half_width, 0.],
            'max': [center[0] + aabb_half_width,
                    center[1] + aabb_half_width, 8.],
        }
        column_candidate.geometry = {
            'kind': 'oriented_box',
            'sizes': {'length': 1., 'thickness': 0.2, 'height': 8.},
            'rotation_z': np.pi / 4,
        }
        columns.append(column_candidate)

    result = _runway_column_context(
        beam_center, direction, 6., 5., np.zeros(3), columns
    )

    # Their global AABBs project to 0.6 m across the runway, but the measured
    # rotated footprint projects to only 0.1 m; at 0.6 m offset these columns
    # are outside the beam strip and must not be reported as supports.
    assert result['status'] == 'insufficient_context'
    assert result['supports'] == []


def test_oriented_footprint_uses_its_measured_center_not_aabb_center():
    columns = []
    for x in (0., 6.):
        column_candidate = column(x, y=0.3)
        column_candidate.geometry = {
            'kind': 'oriented_box',
            'center': [x, 0., 4.],
            'sizes': {'length': 0.4, 'thickness': 0.4, 'height': 8.},
            'rotation_z': 0.,
        }
        columns.append(column_candidate)

    result = context(columns)

    assert result['status'] == 'supported_hypothesis'
    assert all(item['axis_offset_m'] == 0. for item in result['supports'])


def test_rotated_translated_hall_uses_world_coordinates():
    result = _runway_column_context(np.array([0., 3.]), np.array([0., 1.]),
        6., 5., np.array([100., 200., 30.]),
        [column(100, 200, 38, 30), column(100, 206, 38, 30)])
    assert result['status'] == 'supported_hypothesis'
