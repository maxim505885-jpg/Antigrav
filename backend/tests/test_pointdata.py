"""Spatial queries must preserve measured coordinates and point identity."""
import numpy as np
import pytest


def provider(tmp_path, xyz, colors=None, origin=(1000.0, -2000.0, 30.0)):
    from scan2bim.pointdata import NpyPointProvider
    points_path = tmp_path / "positions.npy"
    np.save(points_path, np.array(xyz, dtype=np.float32))
    color_path = None
    if colors is not None:
        color_path = tmp_path / "colors.npy"
        np.save(color_path, np.array(colors, dtype=np.uint8))
    return NpyPointProvider(points_path, origin=origin, colors_path=color_path, chunk_size=2)


def test_world_bounds_include_faces_across_chunks_and_keep_rgb(tmp_path):
    from scan2bim.pointdata import PointQuery
    p = provider(tmp_path, [[0, 0, 0], [1, 1, 1], [2, 2, 2], [3, 3, 3]],
                 [[10, 0, 0], [20, 0, 0], [30, 0, 0], [40, 0, 0]])
    before = p.positions_path.read_bytes()
    batches = list(p.iter_points(PointQuery((1001, -1999, 31, 1002, -1998, 32))))
    np.testing.assert_array_equal(np.concatenate([b.source_indices for b in batches]), [1, 2])
    np.testing.assert_array_equal(np.concatenate([b.xyz for b in batches]),
                                  [[1001, -1999, 31], [1002, -1998, 32]])
    np.testing.assert_array_equal(np.concatenate([b.rgb for b in batches]), [[20, 0, 0], [30, 0, 0]])
    assert before == p.positions_path.read_bytes()
    assert all(len(b.xyz) <= 2 for b in batches)


def test_empty_and_nonfinite_points_are_not_returned(tmp_path):
    from scan2bim.pointdata import PointQuery
    p = provider(tmp_path, [[0, 0, 0], [float("nan"), 0, 0], [float("inf"), 1, 1]])
    assert list(p.iter_points(PointQuery((0, 0, 0, 1, 1, 1)))) == []
    batches = list(p.iter_points(PointQuery((999, -2001, 29, 1001, -1999, 31))))
    assert sum(len(b.xyz) for b in batches) == 1
    assert batches[0].rgb is None


@pytest.mark.parametrize("bounds", [(2, 0, 0, 1, 1, 1), (0, 0, 0, float("inf"), 1, 1), (0, 1)])
def test_invalid_query_bounds_fail_explicitly(bounds):
    from scan2bim.pointdata import PointQuery
    with pytest.raises(ValueError):
        PointQuery(bounds)


def test_mismatched_colors_and_invalid_chunk_are_rejected(tmp_path):
    from scan2bim.pointdata import NpyPointProvider
    np.save(tmp_path / "p.npy", np.zeros((3, 3), dtype=np.float32))
    np.save(tmp_path / "c.npy", np.zeros((2, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="colors"):
        NpyPointProvider(tmp_path / "p.npy", origin=(0, 0, 0), colors_path=tmp_path / "c.npy")
    with pytest.raises(ValueError, match="chunk_size"):
        NpyPointProvider(tmp_path / "p.npy", origin=(0, 0, 0), chunk_size=0)


def test_roundtrip_does_not_lose_local_detail_at_large_world_origin(tmp_path):
    from scan2bim.pointdata import PointQuery
    p = provider(tmp_path, [[0.001, 0.002, 0.003]], origin=(1e7, -1e7, 100))
    b = next(p.iter_points(PointQuery((1e7, -1e7, 100, 1e7+1, -1e7+1, 101))))
    assert b.xyz.dtype == np.float64
    np.testing.assert_allclose(b.xyz - p.origin, [[0.001, 0.002, 0.003]], atol=2e-9)


def test_spatial_index_matches_scan_including_tile_edges_and_rgb(tmp_path):
    from scan2bim.pointdata import PointQuery
    from scan2bim.pointdata.index import build_index, IndexedPointProvider
    p = provider(tmp_path, [[i, i % 3, i % 2] for i in range(12)],
                 [[i, i+1, i+2] for i in range(12)])
    build_index(p, tmp_path / "index", cell_size=2)
    indexed = IndexedPointProvider(p, tmp_path / "index")
    query = PointQuery((1002, -2000, 30, 1008, -1998, 31))
    def collected(reader):
        batches = list(reader.iter_points(query))
        ids = np.concatenate([b.source_indices for b in batches])
        order = np.argsort(ids)
        return (ids[order], np.concatenate([b.xyz for b in batches])[order],
                np.concatenate([b.rgb for b in batches])[order])
    for measured, expected in zip(collected(indexed), collected(p)):
        np.testing.assert_array_equal(measured, expected)
    assert list(indexed.iter_points(PointQuery((-20, -20, -20, -10, -10, -10)))) == []


def test_index_refuses_changed_origin_and_incomplete_directory(tmp_path):
    from scan2bim.pointdata import NpyPointProvider
    from scan2bim.pointdata.index import build_index, IndexedPointProvider
    p = provider(tmp_path, [[0, 0, 0]])
    build_index(p, tmp_path / "index")
    moved = NpyPointProvider(p.positions_path, origin=(0, 0, 0))
    with pytest.raises(ValueError, match="source"):
        IndexedPointProvider(moved, tmp_path / "index")
    (tmp_path / "incomplete").mkdir()
    with pytest.raises(ValueError, match="incomplete"):
        IndexedPointProvider(p, tmp_path / "incomplete")


def test_index_skips_nonfinite_points_without_changing_source_ids(tmp_path):
    from scan2bim.pointdata import PointQuery
    from scan2bim.pointdata.index import build_index, IndexedPointProvider
    p = provider(tmp_path, [[0, 0, 0], [float("nan"), 0, 0], [3, 2, 1]])
    meta = build_index(p, tmp_path / "index")
    assert meta["finite_count"] == 2
    batches = list(IndexedPointProvider(p, tmp_path / "index").iter_points(
        PointQuery((999,-2001,29,1004,-1997,32))))
    np.testing.assert_array_equal(np.sort(np.concatenate([b.source_indices for b in batches])), [0, 2])


def test_index_invalid_cell_size_and_existing_directory_fail(tmp_path):
    from scan2bim.pointdata.index import build_index
    p = provider(tmp_path, [[0, 0, 0]])
    for size in (0, -1, float("nan")):
        with pytest.raises(ValueError):
            build_index(p, tmp_path / "bad", cell_size=size)
    (tmp_path / "existing").mkdir()
    with pytest.raises(FileExistsError):
        build_index(p, tmp_path / "existing")


def test_index_point_query_on_large_world_coordinate_tile_boundary(tmp_path):
    from scan2bim.pointdata import PointQuery
    from scan2bim.pointdata.index import build_index, IndexedPointProvider
    p = provider(tmp_path, [[0.1,0.1,0.1]],origin=(1e12,1e12,1e12))
    build_index(p,tmp_path / "index",cell_size=.1)
    world = (np.array([.1,.1,.1],dtype=np.float32).astype(np.float64)+p.origin).tolist()
    query = PointQuery(tuple(world+world))
    assert sum(len(b.xyz) for b in p.iter_points(query)) == 1
    assert sum(len(b.xyz) for b in IndexedPointProvider(p,tmp_path / "index").iter_points(query)) == 1


def test_existing_reader_refuses_source_replacement(tmp_path):
    import os
    from scan2bim.pointdata import PointQuery
    from scan2bim.pointdata.index import build_index, IndexedPointProvider
    p = provider(tmp_path, [[0,0,0],[1,1,1]])
    build_index(p,tmp_path / "index")
    reader = IndexedPointProvider(p,tmp_path / "index")
    original = p.positions_path.stat()
    os.utime(p.positions_path,ns=(original.st_atime_ns,original.st_mtime_ns+10_000_000_000))
    with pytest.raises(ValueError,match="source changed"):
        list(reader.iter_points(PointQuery((0,0,0,1,1,1))))


def test_corrupt_offsets_are_rejected(tmp_path):
    from scan2bim.pointdata.index import build_index, IndexedPointProvider
    p = provider(tmp_path, [[0,0,0],[1,1,1]])
    build_index(p,tmp_path / "index")
    offsets = np.load(tmp_path / "index" / "offsets.npy")
    offsets[-1] += 1
    np.save(tmp_path / "index" / "offsets.npy",offsets)
    with pytest.raises(ValueError,match="corrupt"):
        IndexedPointProvider(p,tmp_path / "index")


@pytest.mark.parametrize("kind,axis,position",[("horizontal",None,31),("vertical","x",1001),("vertical","y",-1999)])
def test_indexed_sections_preserve_local_coordinates_and_slab_counts(tmp_path,kind,axis,position):
    from dataclasses import replace
    from scan2bim.pointdata.index import build_index
    from scan2bim.geometry.section import CloudGeometry,build_frame,collect_slice
    points = [[x,y,z] for x in (0.,.95,1.,1.05,2.) for y in (0.,1.,2.) for z in (0.,1.,2.)]
    p = provider(tmp_path,points)
    build_index(p,tmp_path / "index",cell_size=.5)
    geom = CloudGeometry(p.positions_path,p.origin,p.origin,p.origin+2,len(points))
    indexed = replace(geom,spatial_index_path=tmp_path / "index")
    frame = build_frame(geom,kind,axis,position,.2)
    ordinary = collect_slice(geom,frame,region=(.5,1.5,.5,1.5))
    selected = collect_slice(indexed,frame,region=(.5,1.5,.5,1.5))
    assert ordinary[2] == selected[2]
    np.testing.assert_array_equal(np.sort(ordinary[0]),np.sort(selected[0]))
    np.testing.assert_array_equal(np.sort(ordinary[1]),np.sort(selected[1]))
