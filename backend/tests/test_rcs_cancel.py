from __future__ import annotations

from pathlib import Path

import pytest

from scan2bim.formats import rcs_native
from scan2bim.jobs import JobCancelled


def test_cancelling_native_reader_terminates_child_and_removes_temporary_output(tmp_path, monkeypatch):
    child_output_dir: Path | None = None

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
