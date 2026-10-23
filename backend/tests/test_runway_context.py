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


@pytest.mark.parametrize('columns', [[], [column(0)], [column(0), column(0)],
    [column(0), column(6, y=3)], [column(0), column(6, top=3)],
    [column(0), column(6, bottom=6)]])
def test_absent_duplicate_remote_or_wrong_height_columns_do_not_support_runway(columns):
    assert context(columns)['status'] == 'insufficient_context'


def test_rotated_translated_hall_uses_world_coordinates():
    result = _runway_column_context(np.array([0., 3.]), np.array([0., 1.]),
        6., 5., np.array([100., 200., 30.]),
        [column(100, 200, 38, 30), column(100, 206, 38, 30)])
    assert result['status'] == 'supported_hypothesis'
