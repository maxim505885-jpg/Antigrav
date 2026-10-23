from pathlib import Path
from types import SimpleNamespace
import locale

import pytest

from scan2bim.formats import recap_decap


def test_calls_autodesk_decap_and_requires_linked_rcs(tmp_path, monkeypatch):
    decap = tmp_path / "DeCap.exe"
    decap.touch()
    source = tmp_path / "station.rcs"
    source.write_bytes(b"source")
    monkeypatch.setattr(recap_decap, "find_decap", lambda: decap)

    def run(command, **_kwargs):
        root = Path(command[2])
        name = command[3]
        (root / f"{name}.rcp").write_bytes(b"native-project")
        support = root / f"{name} Support"
        support.mkdir()
        (support / "station.rcs").write_bytes(b"indexed-scan")
        assert "--importWithLicense" in command
        assert source.as_posix() in (root / "scan-list.txt").read_text(encoding=locale.getpreferredencoding(False)).replace("\\", "/")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(recap_decap.subprocess, "run", run)
    result = recap_decap.create_recap_project(tmp_path / "out", "Hall", [{"path": str(source)}])
    assert result["status"] == "created_by_autodesk_decap"
    assert result["linked_rcs_count"] == 1


def test_rejects_missing_sources_and_never_claims_empty_decap_output(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="Unsupported or missing"):
        recap_decap.create_recap_project(tmp_path, "Hall", [{"path": str(tmp_path / "missing.rcs")}])
    decap = tmp_path / "DeCap.exe"
    decap.touch()
    source = tmp_path / "station.rcs"
    source.touch()
    monkeypatch.setattr(recap_decap, "find_decap", lambda: decap)
    monkeypatch.setattr(recap_decap.subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    with pytest.raises(RuntimeError, match="complete RCP bundle"):
        recap_decap.create_recap_project(tmp_path / "out", "Hall", [{"path": str(source)}])


def test_rejects_decap_output_that_reports_any_failed_scan(tmp_path, monkeypatch):
    decap = tmp_path / "DeCap.exe"
    decap.touch()
    source = tmp_path / "station.rcs"
    source.touch()
    monkeypatch.setattr(recap_decap, "find_decap", lambda: decap)

    def run(command, **_kwargs):
        root, name = Path(command[2]), command[3]
        (root / f"{name}.rcp").touch()
        support = root / f"{name} Support"
        support.mkdir()
        (support / "partial.rcs").touch()
        return SimpleNamespace(returncode=0, stdout="[P][1 Failed]", stderr="")

    monkeypatch.setattr(recap_decap.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="failed scans 1"):
        recap_decap.create_recap_project(tmp_path / "out", "Hall", [{"path": str(source)}])
