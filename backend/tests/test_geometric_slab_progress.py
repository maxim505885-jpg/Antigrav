import numpy as np

from scan2bim.geometry.section import CloudGeometry
from scan2bim.recognition import geometric


def test_slab_progress_reports_each_chunk_and_stays_inside_phase(tmp_path, monkeypatch):
    positions = np.zeros((120, 3), dtype=np.float32)
    positions[:60, 2] = 0.0
    positions[60:, 2] = 1.0
    path = tmp_path / "positions.npy"
    np.save(path, positions)
    geometry = CloudGeometry(
        positions_path=path,
        origin=np.zeros(3),
        bbox_min=np.array([0.0, 0.0, 0.0]),
        bbox_max=np.array([1.0, 1.0, 1.0]),
        count=len(positions),
    )
    monkeypatch.setattr(geometric, "CHUNK", 20)
    monkeypatch.setattr(
        geometric,
        "vectorize_2d",
        lambda *_args, **_kwargs: {"polygons": []},
    )
    updates = []

    result = geometric._slab_elements(
        geometry,
        [{"z_local": 0.0, "z": 0.0}, {"z_local": 1.0, "z": 1.0}],
        lambda value, message: updates.append((value, message)),
    )

    assert result == []
    assert len(updates) == 12
    values = [value for value, _message in updates]
    assert values == sorted(values)
    assert values[0] > 0.75
    assert values[-1] == 0.84
    assert all("контуры плит" in message and "чанк" in message for _value, message in updates)
