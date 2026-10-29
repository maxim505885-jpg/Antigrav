from pathlib import Path
from types import SimpleNamespace
import locale
import zipfile
from xml.sax.saxutils import escape

import pytest

from scan2bim.formats import recap_decap


def _write_rcp(path: Path, scans: list[tuple[str, str]]) -> None:
    nodes = []
    for index, (name, source_path) in enumerate(scans):
        nodes.append(
            f'<VoxelTreeRunTime Id="{{scan-{index}}}">'
            '<Translation x="0" y="0" z="0"/><Rotation x="0" y="0" z="0"/>'
            '<Scale x="1" y="1" z="1"/><Registered Value="0"/>'
            f'<NodeName Value="{escape(name)}"/><Path Value="{escape(source_path)}"/>'
            '<RelativePath Value=""/><NumPoints Value="50000"/>'
            '<HasRGB Value="1"/><HasIntensity Value="0"/><HasNormals Value="1"/>'
            '</VoxelTreeRunTime>'
        )
    xml = '<Autodesk><ProjectId UUID="test-project"/><Nodes>' + ''.join(nodes) + '</Nodes></Autodesk>'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('project.xml', xml)


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
        support = root / f"{name} Support"
        support.mkdir(exist_ok=True)
        linked = support / "station.rcs"
        assert Path(_kwargs["cwd"]) == root
        control = Path(command[command.index("--controlFile") + 1])
        listed = control.read_text(encoding=locale.getpreferredencoding(False)).splitlines()
        assert listed == [str(Path(name + " Support") / "station.rcs")]
        assert (root / listed[0]).read_bytes() == source.read_bytes()
        linked.write_bytes(b"indexed-scan")
        _write_rcp(root / f"{name}.rcp", [("station", listed[0])])
        assert "--importWithLicense" in command
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(recap_decap.subprocess, "run", run)
    result = recap_decap.create_recap_project(tmp_path / "out", "Hall", [{"path": str(source)}])
    assert result["status"] == "created_by_autodesk_decap"
    assert result["linked_rcs_count"] == 1
    assert result["package_verified"] is True
    assert result["project_verified"] is True
    assert result["rcp_node_count"] == 1
    assert result["external_rcs_count"] == 0
    assert result["rcp_size_bytes"] > 0
    assert result["linked_rcs_size_bytes"] == len(b"indexed-scan")
    from scan2bim.formats.rcp_manifest import read_rcp_manifest
    manifest = read_rcp_manifest(result["rcp_path"])
    assert manifest["node_count"] == 1
    assert Path(manifest["nodes"][0]["resolved_rcs_path"]).is_file()
    assert source.read_bytes() == b"source"


def test_accepts_autodesk_rcp_that_references_existing_source_rcs_without_copying_it(tmp_path, monkeypatch):
    decap = tmp_path / "DeCap.exe"
    decap.touch()
    source = tmp_path / "station.rcs"
    source.write_bytes(b"original indexed station")
    monkeypatch.setattr(recap_decap, "find_decap", lambda: decap)

    def run(command, **_kwargs):
        root, name = Path(command[2]), command[3]
        support = root / f"{name} Support"
        support.mkdir(exist_ok=True)
        _write_rcp(root / f"{name}.rcp", [("station", str(source))])
        return SimpleNamespace(returncode=0, stdout="linked input RCS", stderr="")

    monkeypatch.setattr(recap_decap.subprocess, "run", run)
    result = recap_decap.create_recap_project(tmp_path / "out", "Hall", [{"path": str(source)}])

    assert result["status"] == "created_by_autodesk_decap"
    assert result["project_verified"] is True
    assert result["package_verified"] is False
    assert result["rcp_node_count"] == 1
    assert result["linked_rcs_count"] == 1
    assert result["external_rcs_count"] == 1
    assert result["external_rcs_paths"] == [str(source.resolve())]
    from scan2bim.formats.rcp_manifest import read_rcp_manifest
    node = read_rcp_manifest(result["rcp_path"])["nodes"][0]
    assert node["resolved_rcs_path"] == str(source.resolve())
    assert source.read_bytes() == b"original indexed station"


def test_decap_disk_preflight_rejects_before_starting_import(tmp_path, monkeypatch):
    decap = tmp_path / "DeCap.exe"
    decap.touch()
    source = tmp_path / "station.rcs"
    source.write_bytes(b"source station")
    monkeypatch.setattr(recap_decap, "find_decap", lambda: decap)
    monkeypatch.setattr(recap_decap.shutil, "disk_usage", lambda _path: SimpleNamespace(free=1024))
    started = False

    def should_not_run(*_args, **_kwargs):
        nonlocal started
        started = True
        raise AssertionError("DeCap must not run when the output volume lacks space")

    monkeypatch.setattr(recap_decap.subprocess, "run", should_not_run)
    with pytest.raises(recap_decap.InsufficientStorageError) as exc_info:
        recap_decap.create_recap_project(tmp_path / "out", "Hall", [{"path": str(source)}])
    assert started is False
    assert exc_info.value.source_bytes == source.stat().st_size
    assert exc_info.value.required_bytes == source.stat().st_size + recap_decap.RCP_OUTPUT_FREE_SPACE_RESERVE_BYTES
    assert list((tmp_path / "out").iterdir()) == []


def test_decap_unresolved_source_error_includes_bounded_diagnostics_and_cleans_staging(tmp_path, monkeypatch):
    decap = tmp_path / "DeCap.exe"
    decap.touch()
    source = tmp_path / "station.rcs"
    source.write_bytes(b"source")
    output = tmp_path / "out"
    monkeypatch.setattr(recap_decap, "find_decap", lambda: decap)

    def run(command, **_kwargs):
        root, name = Path(command[2]), command[3]
        support = root / f"{name} Support"
        support.mkdir(exist_ok=True)
        _write_rcp(root / f"{name}.rcp", [("missing", str(tmp_path / "missing.rcs"))])
        return SimpleNamespace(returncode=0, stdout="No indexed scans were produced", stderr="diagnostic detail")

    monkeypatch.setattr(recap_decap.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="No indexed scans were produced") as exc_info:
        recap_decap.create_recap_project(output, "Hall", [{"path": str(source)}])

    assert "diagnostic detail" in str(exc_info.value)
    assert list(output.iterdir()) == []


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
        support.mkdir(exist_ok=True)
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
        support.mkdir(exist_ok=True)
        (support / "station.rcs").write_bytes(b"" if empty_part == "scan" else b"indexed-scan")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(recap_decap.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="empty"):
        recap_decap.create_recap_project(tmp_path / "out", "Hall", [{"path": str(source)}])
