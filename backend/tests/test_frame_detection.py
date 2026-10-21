"""Real failure modes: biased crop PCA and beam widths polluted by neighbours."""
import math

import numpy as np


def test_orientation_follows_orthogonal_members_instead_of_crop_pca():
    from scan2bim.recognition.steel import _axis_from_segments
    true = math.radians(10)
    segments = [{"angle":true+math.radians(j*.1),"length":10.} for j in range(-5,6)]
    segments += [{"angle":true+math.pi/2,"length":8.} for _ in range(8)]
    segments += [{"angle":math.radians(a),"length":3.} for a in (30,42,53,70,140)]
    measured = _axis_from_segments(segments,math.radians(19))
    assert abs(measured-true) < math.radians(.2)


def test_orientation_keeps_longitudinal_choice_and_wraps_at_90_degrees():
    from scan2bim.recognition.steel import _axis_from_segments
    segments = [{"angle":math.radians(a),"length":10.} for a in (89.5,90,90.5,179.5,0,.5)]
    assert abs(_axis_from_segments(segments,math.pi/2)-math.pi/2) < .01
    assert _axis_from_segments([],None) is None


def test_dense_thin_beam_is_not_made_wide_by_sparse_neighbouring_clutter():
    from scan2bim.recognition.steel import _measure_strip
    rng=np.random.default_rng(17)
    along=rng.uniform(-3,3,12000)
    across=np.concatenate([rng.normal(0,.045,9000),rng.uniform(-.8,.8,3000)])
    xyz=np.column_stack([along,across,rng.uniform(0,.5,len(along))])
    width,z0,z1,support=_measure_strip(xyz[:,:2],xyz[:,2],np.zeros(2),np.array([1.,0.]),6.)
    assert .10 < width < .4
    assert z1-z0 > .4
    assert support > 5000


def test_broad_surface_is_not_shrunk_to_a_thin_member():
    from scan2bim.recognition.steel import _measure_strip
    rng=np.random.default_rng(18)
    xy=np.column_stack([rng.uniform(-3,3,12000),rng.uniform(-.8,.8,12000)])
    width,*_=_measure_strip(xy,np.ones(len(xy)),np.zeros(2),np.array([1.,0.]),6.)
    assert width > .7


def test_individual_six_metre_member_can_be_a_runway_candidate(tmp_path):
    from scan2bim.geometry.section import CloudGeometry
    from scan2bim.recognition.steel import _horizontal_members
    rng=np.random.default_rng(21)
    xyz=np.column_stack([rng.uniform(-3,3,16000),rng.uniform(-.1,.1,16000),rng.uniform(4.9,5.1,16000)])
    path=tmp_path / 'positions.npy'
    np.save(path,xyz.astype(np.float32))
    geom=CloudGeometry(path,np.zeros(3),np.array([-4.,-1.,0.]),np.array([4.,1.,10.]),len(xyz))
    levels=[{'z':z,'z_local':z} for z in (0.,3.,5.,7.,10.)]
    grid={'band_occ':np.zeros((22,22,82),dtype=bool),'res':.1,'min':[-4.,-1.,0.]}
    elements,*_=_horizontal_members(geom,levels,grid)
    candidates=[e for e in elements if e.dimensions.get('role')=='crane_girder']
    assert candidates
    assert any(5.5 < e.dimensions['length_m'] < 6.2 for e in candidates)
