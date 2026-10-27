from pathlib import Path
from types import SimpleNamespace
import locale
import zipfile
import pytest
from xml.sax.saxutils import escape

from scan2bim.formats import recap_decap
from scan2bim.formats.rcp_manifest import read_rcp_manifest


def _write_rcp(path: Path, source_path: Path) -> None:
    xml = (
        '<Autodesk><ProjectId UUID="test-project"/><Nodes>'
        '<VoxelTreeRunTime Id="{scan-1}">'
        '<Translation x="0" y="0" z="0"/><Rotation x="0" y="0" z="0"/>'
        '<Scale x="1" y="1" z="1"/><Registered Value="0"/>'
        '<NodeName Value="station"/><Path Value="' + escape(str(source_path)) + '"/>'
        '<RelativePath Value=""/><NumPoints Value="100"/>'
        '<HasRGB Value="1"/><HasIntensity Value="0"/><HasNormals Value="1"/>'
        '</VoxelTreeRunTime></Nodes></Autodesk>'
    )
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('project.xml', xml)


def test_non_ascii_source_path_is_copied_to_persistent_ascii_decap_cache(tmp_path, monkeypatch):
    source_dir = tmp_path / 'исходные данные'
    source_dir.mkdir()
    source = source_dir / 'station.rcs'
    source.write_bytes(b'original FARO station bytes')
    cache_home = tmp_path / 'localappdata'
    monkeypatch.setenv('LOCALAPPDATA', str(cache_home))
    monkeypatch.setattr(recap_decap, '_short_windows_path', lambda _path: None)
    decap = tmp_path / 'DeCap.exe'
    decap.touch()
    monkeypatch.setattr(recap_decap, 'find_decap', lambda: decap)

    def run(command, **_kwargs):
        root, name = Path(command[2]), command[3]
        control = Path(command[command.index('--controlFile') + 1])
        listed = control.read_text(encoding=locale.getpreferredencoding(False)).splitlines()
        assert len(listed) == 1
        copied = Path(listed[0])
        assert copied.is_file()
        assert copied != source
        assert str(copied).isascii()
        assert copied.read_bytes() == source.read_bytes()
        (root / f'{name} Support').mkdir()
        _write_rcp(root / f'{name}.rcp', copied)
        return SimpleNamespace(returncode=0, stdout='ok', stderr='')

    monkeypatch.setattr(recap_decap.subprocess, 'run', run)
    result = recap_decap.create_recap_project(tmp_path / 'out', 'Hall', [{'path': str(source)}])

    assert result['source_files_copied_for_decap'] is True
    cache = Path(result['source_cache_path'])
    assert cache.is_dir()
    manifest = read_rcp_manifest(result['rcp_path'])
    linked_path = Path(manifest['nodes'][0]['resolved_rcs_path'])
    assert linked_path.is_file()
    assert linked_path.parent == cache
    assert result['package_verified'] is False
    assert source.read_bytes() == b'original FARO station bytes'

def test_failed_output_staging_removes_unreferenced_source_cache(tmp_path, monkeypatch):
    source_dir = tmp_path / 'исходные данные'
    source_dir.mkdir()
    source = source_dir / 'station.rcs'
    source.write_bytes(b'original FARO station bytes')
    cache_home = tmp_path / 'localappdata'
    monkeypatch.setenv('LOCALAPPDATA', str(cache_home))
    monkeypatch.setattr(recap_decap, '_short_windows_path', lambda _path: None)
    decap = tmp_path / 'DeCap.exe'
    decap.touch()
    monkeypatch.setattr(recap_decap, 'find_decap', lambda: decap)

    make_staging = recap_decap._new_staging_dir

    def fail_project_staging(root, prefix):
        if prefix == '.s2b_decap_':
            raise OSError('simulated output staging failure')
        return make_staging(root, prefix)

    monkeypatch.setattr(recap_decap, '_new_staging_dir', fail_project_staging)

    with pytest.raises(OSError, match='simulated output staging failure'):
        recap_decap.create_recap_project(tmp_path / 'out', 'Hall', [{'path': str(source)}])

    cache_root = cache_home / 'SCANStudio' / 'ReCapSourceCache'
    assert not list(cache_root.glob('export_*'))
    assert source.read_bytes() == b'original FARO station bytes'