"""Compare measured station positions to a nominal pitch, never snap geometry."""
from __future__ import annotations

import math
import numpy as np


def station_pitch_report(points_xy, angle_rad: float, nominal_pitch_m: float = 6.) -> dict:
    points = np.asarray(points_xy,dtype=np.float64)
    if (points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all()
            or not math.isfinite(angle_rad) or not math.isfinite(nominal_pitch_m)
            or nominal_pitch_m <= 0):
        raise ValueError('finite Nx2 positions, finite angle and positive nominal pitch required')
    origin = points[0] if len(points) else np.zeros(2)
    direction = np.array([math.cos(angle_rad),math.sin(angle_rad)])
    normal = np.array([-direction[1],direction[0]])
    along = (points-origin) @ direction
    across = (points-origin) @ normal
    order = np.argsort(along,kind='stable')
    intervals=[]
    for left,right in zip(order[:-1],order[1:]):
        measured=float(along[right]-along[left])
        multiple=int(math.floor(measured/nominal_pitch_m+.5))
        intervals.append({'from_index':int(left),'to_index':int(right),'measured_m':measured,
                          'nominal_intervals':multiple,
                          'residual_mm':(measured-multiple*nominal_pitch_m)*1000,
                          'cross_axis_offset_m':float(across[right]-across[left]),
                          'status':'duplicate_or_close_candidate' if multiple==0 else 'requires_review'})
    return {'schema':'scan.station-pitch/1','nominal_pitch_m':nominal_pitch_m,
            'angle_rad':angle_rad,'projection_origin':origin.tolist(),
            'input_points':points.tolist(),'sorted_input_indices':order.tolist(),
            'intervals':intervals,'acceptance_status':'tolerance_not_specified',
            'note':'Candidates must belong to the same physical row. No geometry was moved.'}
