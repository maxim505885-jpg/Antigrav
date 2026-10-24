from pathlib import Path
from types import SimpleNamespace
import locale

import pytest

from scan2bim.formats import recap_decap


def test_decap_path_uses_ascii_short_path_for_unicode_windows_paths(tmp_path, monkeypatch):
    source = tmp_path / "облако FARO.rcs"
    monkeypatch.setattr(recap_decap, "_short_windows_path", lambda _path: r"C:\SCAN~1\FARO.RCS")
    assert recap_decap._decap_compatible_path(source) == r"C:\SCAN~1\FARO.RCS"


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
        assert "--controlFile" in command
        control = Path(command[command.index("--controlFile") + 1])
        expected_source = recap_decap._decap_compatible_path(source)
        assert expected_source in control.read_text(encoding=locale.getpreferredencoding(False))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(recap_decap.subprocess, "run", run)
    result = recap_decap.create_recap_project(tmp_path / "out", "Hall", [{"path": str(source)}])
    assert result["status"] == "created_by_autodesk_decap"
    assert result["linked_rcs_count"] == 1
    assert result["package_verified"] is True
    assert result["rcp_size_bytes"] == len(b"native-project")
    assert result["linked_rcs_size_bytes"] == len(b"indexed-scan")
    assert source.read_bytes() == b"source"


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


@pytest.mark.parametrize("empty_part", ["project", "scan"])
def test_rejects_empty_files_in_decap_bundle(tmp_path, monkeypatch, empty_part):
    decap = tmp_path / "DeCap.exe"
    decap.touch()
    source = tmp_path / "station.rcs"
    source.write_bytes(b"source")
    monkeypatch.setattr(recap_decap, "find_decap", lambda: decap)

    def run(command, **_kwargs):
        root, name = Path(command[2]), command[3]
        (root / f"{name}.rcp").write_bytes(b"" if empty_part == "project" else b"native-project")
        support = root / f"{name} Support"
        support.mkdir()
        (support / "station.rcs").write_bytes(b"" if empty_part == "scan" else b"indexed-scan")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(recap_decap.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="empty"):
        recap_decap.create_recap_project(tmp_path / "out", "Hall", [{"path": str(source)}])
