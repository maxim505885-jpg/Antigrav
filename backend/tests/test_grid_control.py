import math

import numpy as np
import pytest


def test_rotated_six_metre_grid_keeps_measured_residuals_and_missing_station():
    from scan2bim.structure.grid import station_pitch_report
    angle=math.radians(10)
    direction=np.array([math.cos(angle),math.sin(angle)])
    origin=np.array([1e6,-2e6])
    xy=origin+np.array([0.,6.012,12.004,24.011])[:,None]*direction
    report=station_pitch_report(xy,angle,nominal_pitch_m=6.)
    assert report['nominal_pitch_m']==6.
    assert report['acceptance_status']=='tolerance_not_specified'
    assert [r['nominal_intervals'] for r in report['intervals']]==[1,1,2]
    np.testing.assert_allclose([r['residual_mm'] for r in report['intervals']],[12,-8,7],atol=.001)
    np.testing.assert_array_equal(xy,origin+np.array([0.,6.012,12.004,24.011])[:,None]*direction)


def test_grid_control_does_not_silently_remove_duplicates_or_declare_pass():
    from scan2bim.structure.grid import station_pitch_report
    report=station_pitch_report([[0,0],[0,0],[6.1,0]],0,6.)
    assert report['intervals'][0]['nominal_intervals']==0
    assert report['intervals'][0]['status']=='duplicate_or_close_candidate'
    assert report['intervals'][1]['residual_mm']==pytest.approx(100)
    assert 'passed' not in report


@pytest.mark.parametrize('points,pitch', [([[0,0]],0),([[float('nan'),0]],6),([[0,0,0]],6)])
def test_grid_control_rejects_bad_inputs(points,pitch):
    from scan2bim.structure.grid import station_pitch_report
    with pytest.raises(ValueError):
        station_pitch_report(points,0,pitch)
