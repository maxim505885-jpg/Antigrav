from __future__ import annotations

from pathlib import Path

import pytest

from scan2bim.formats import rcs_native
from scan2bim.jobs import JobCancelled


def test_cancelling_native_reader_terminates_child_and_removes_temporary_output(tmp_path, monkeypatch):
    child_output_dir: Path | None = None
    monkeypatch.setattr(rcs_native, "DATA_DIR", tmp_path, raising=False)

    class FakeProcess:
        stdout = ["PROGRESS 0 100 read (100 pts/s, 100 kept)\n"]

        def __init__(self):
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout=None):
            return self.returncode or 0

        def kill(self):
            self.returncode = -9

    child = FakeProcess()

    def fake_popen(command, **kwargs):
        nonlocal child_output_dir
        child_output_dir = Path(command[4])
        return child

    monkeypatch.setattr(rcs_native, "native_available", lambda: {"dll_exists": True, "dll_path": "stub", "abi": "test"})
    monkeypatch.setattr(rcs_native.subprocess, "Popen", fake_popen)

    def cancel(_value, _message):
        raise JobCancelled("cancel requested")

    with pytest.raises(JobCancelled):
        rcs_native.read_rcs_native(tmp_path / "never-opened.rcs", max_points=1, progress=cancel)

    assert child.terminated is True
    assert child_output_dir is not None and not child_output_dir.exists()


def test_native_reader_keeps_scratch_files_under_application_data(tmp_path, monkeypatch):
    import numpy as np

    app_data = tmp_path / "app-data"
    app_data.mkdir()

    class FinishedProcess:
        stdout = ["DONE 1 SEEN 1\n"]

        def __init__(self, command, **_kwargs):
            out_dir = Path(command[4])
            np.save(out_dir / "xyz.npy", np.array([[1.0, 2.0, 3.0]], dtype=np.float32))
            np.save(out_dir / "rgb.npy", np.array([[10, 20, 30]], dtype=np.uint8))

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(rcs_native, "DATA_DIR", app_data, raising=False)
    monkeypatch.setattr(rcs_native.uuid, "uuid4", lambda: type("Token", (), {"hex": "fixture"})())
    monkeypatch.setattr(rcs_native, "native_available", lambda: {"dll_exists": True, "dll_path": "fake.dll", "abi": "test"})
    monkeypatch.setattr(rcs_native.subprocess, "Popen", FinishedProcess)

    result = rcs_native.read_rcs_native(tmp_path / "scan.rcs", max_points=1)

    assert result.xyz.tolist() == [[1.0, 2.0, 3.0]]
    assert result.rgb.tolist() == [[10, 20, 30]]
    assert not (app_data / "s2b_rcs_fixture").exists()
