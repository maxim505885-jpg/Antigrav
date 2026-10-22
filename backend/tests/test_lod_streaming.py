import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path("backend").resolve()))

from scan2bim.api.app import create_app
from scan2bim.pointdata.octree import StreamingLodBuilder, PREVIEW_DTYPE


@pytest.fixture
def client(tmp_path):
    app = create_app()
    return TestClient(app)


def test_streaming_lod_builder_synthetic(tmp_path):
    import numpy as np
    
    # 10,000 test points
    positions = np.random.uniform(-50, 50, (10000, 3)).astype(np.float32)
    pos_file = tmp_path / "positions.npy"
    np.save(pos_file, positions)
    
    builder = StreamingLodBuilder()
    lod_dir = tmp_path / "lod"
    manifest = builder.build_lod_pyramid(pos_file, lod_dir, cloud_id="test_cloud")
    
    assert manifest["total_points"] == 10000
    assert len(manifest["levels"]) == 3
    for lvl in manifest["levels"]:
        bin_path = lod_dir / lvl["file"]
        assert bin_path.is_file()
        assert bin_path.stat().st_size == lvl["points_count"] * 15


def test_unified_lod_manifest_api(client):
    res = client.get("/api/v1/clouds/unified/lod/manifest")
    assert res.status_code == 200
    data = res.json()
    assert data["cloud_id"] == "unified"
    assert data["total_points"] == 43500000
    assert len(data["levels"]) == 3
    assert data["levels"][0]["level"] == 0
    assert data["levels"][0]["points_count"] == 50000
    assert data["levels"][1]["level"] == 1
    assert data["levels"][1]["points_count"] == 250000
    assert data["levels"][2]["level"] == 2
    assert data["levels"][2]["points_count"] == 1000000


def test_unified_lod_binary_stream_api(client):
    # Level 0 (50k points)
    res0 = client.get("/api/v1/clouds/unified/lod/0")
    assert res0.status_code == 200
    assert len(res0.content) == 50000 * 15
    assert res0.headers.get("content-type") == "application/octet-stream"

    # Level 1 (250k points)
    res1 = client.get("/api/v1/clouds/unified/lod/1")
    assert res1.status_code == 200
    assert len(res1.content) == 250000 * 15

    # Invalid level 99
    res99 = client.get("/api/v1/clouds/unified/lod/99")
    assert res99.status_code == 404
