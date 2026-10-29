from pathlib import Path
from shutil import copytree
from types import SimpleNamespace
import locale
import zipfile
from xml.sax.saxutils import escape

from scan2bim.formats import recap_decap
from scan2bim.formats.rcp_manifest import read_rcp_manifest


def _write_rcp(path: Path, source_path: str) -> None:
    xml = (
        '<Autodesk><ProjectId UUID="test-project"/><Nodes>'
        '<VoxelTreeRunTime Id="{scan-1}">'
        '<Translation x="0" y="0" z="0"/><Rotation x="0" y="0" z="0"/>'
        '<Scale x="1" y="1" z="1"/><Registered Value="0"/>'
        '<NodeName Value="station"/><Path Value="' + escape(source_path) + '"/>'
        '<RelativePath Value=""/><NumPoints Value="100"/>'
        '<HasRGB Value="1"/><HasIntensity Value="0"/><HasNormals Value="1"/>'
        '</VoxelTreeRunTime></Nodes></Autodesk>'
    )
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('project.xml', xml)


def test_non_ascii_source_is_packaged_and_rcp_survives_moving_whole_bundle(tmp_path, monkeypatch):
    source_dir = tmp_path / 'исходные данные'
    source_dir.mkdir()
    source = source_dir / 'station.rcs'
    source.write_bytes(b'original FARO station bytes')
    decap = tmp_path / 'DeCap.exe'
    decap.touch()
    monkeypatch.setattr(recap_decap, 'find_decap', lambda: decap)

    def run(command, **kwargs):
        root, name = Path(command[2]), command[3]
        assert Path(kwargs['cwd']) == root
        control = Path(command[command.index('--controlFile') + 1])
        listed = control.read_text(encoding=locale.getpreferredencoding(False)).splitlines()
        assert listed == [str(Path('Hall Support') / 'station.rcs')]
        staged = root / listed[0]
        assert staged.is_file()
        assert staged.read_bytes() == source.read_bytes()
        _write_rcp(root / f'{name}.rcp', listed[0])
        return SimpleNamespace(returncode=0, stdout='ok', stderr='')

    monkeypatch.setattr(recap_decap.subprocess, 'run', run)
    result = recap_decap.create_recap_project(tmp_path / 'out', 'Hall', [{'path': str(source)}])

    assert result['source_files_copied_for_decap'] is True
    assert result['source_cache_path'] is None
    assert result['package_verified'] is True
    assert result['external_rcs_count'] == 0
    assert result['linked_rcs_count'] == 1
    manifest = read_rcp_manifest(result['rcp_path'])
    linked = Path(manifest['nodes'][0]['resolved_rcs_path'])
    assert linked.is_file()
    assert linked.read_bytes() == source.read_bytes()

    moved = tmp_path / 'moved' / 'Hall'
    copytree(Path(result['rcp_path']).parent, moved)
    moved_manifest = read_rcp_manifest(moved / 'Hall.rcp')
    moved_link = Path(moved_manifest['nodes'][0]['resolved_rcs_path'])
    assert moved_link.is_file()
    assert moved_link.parent == moved / 'Hall Support'
    assert moved_link.read_bytes() == source.read_bytes()
    assert source.read_bytes() == b'original FARO station bytes'


def test_failed_output_staging_leaves_no_source_cache_or_partial_package(tmp_path, monkeypatch):
    source_dir = tmp_path / 'исходные данные'
    source_dir.mkdir()
    source = source_dir / 'station.rcs'
    source.write_bytes(b'original FARO station bytes')
    cache_home = tmp_path / 'localappdata'
    monkeypatch.setenv('LOCALAPPDATA', str(cache_home))
    decap = tmp_path / 'DeCap.exe'
    decap.touch()
    monkeypatch.setattr(recap_decap, 'find_decap', lambda: decap)

    def fail_project_staging(_root, prefix):
        if prefix == '.s2b_decap_':
            raise OSError('simulated output staging failure')
        raise AssertionError(f'unexpected staging directory {prefix}')

    monkeypatch.setattr(recap_decap, '_new_staging_dir', fail_project_staging)

    import pytest
    with pytest.raises(OSError, match='simulated output staging failure'):
        recap_decap.create_recap_project(tmp_path / 'out', 'Hall', [{'path': str(source)}])

    assert list((tmp_path / 'out').iterdir()) == []
    cache_root = cache_home / 'SCANStudio' / 'ReCapSourceCache'
    assert not cache_root.exists()
    assert source.read_bytes() == b'original FARO station bytes'
def _write_rcp_nodes(path: Path, nodes: list[tuple[str, str]]) -> None:
    entries = []
    for index, (name, source_path) in enumerate(nodes, start=1):
        entries.append(
            f'<VoxelTreeRunTime Id="{{scan-{index}}}">'
            '<Translation x="0" y="0" z="0"/><Rotation x="0" y="0" z="0"/>'
            '<Scale x="1" y="1" z="1"/><Registered Value="0"/>'
            f'<NodeName Value="{escape(name)}"/><Path Value="{escape(source_path)}"/>'
            '<RelativePath Value=""/><NumPoints Value="100"/>'
            '<HasRGB Value="1"/><HasIntensity Value="0"/><HasNormals Value="1"/>'
            '</VoxelTreeRunTime>'
        )
    xml = '<Autodesk><ProjectId UUID="pair-project"/><Nodes>' + ''.join(entries) + '</Nodes></Autodesk>'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('project.xml', xml)


def test_two_unicode_station_sources_are_portable_after_relocation(tmp_path, monkeypatch):
    sources = []
    for folder, content in [('первая станция', b'FARO station one'), ('вторая станция', b'FARO station two')]:
        source_dir = tmp_path / folder
        source_dir.mkdir()
        source = source_dir / 'станция.rcs'
        source.write_bytes(content)
        sources.append(source)
    original_bytes = [path.read_bytes() for path in sources]
    decap = tmp_path / 'DeCap.exe'
    decap.touch()
    monkeypatch.setattr(recap_decap, 'find_decap', lambda: decap)
    relative_paths = [
        Path('Pair Support') / 'station_0001.rcs',
        Path('Pair Support') / 'station_0002.rcs',
    ]

    def run(command, **kwargs):
        root, name = Path(command[2]), command[3]
        assert Path(kwargs['cwd']) == root
        control = Path(command[command.index('--controlFile') + 1])
        listed = [Path(line) for line in control.read_text(encoding=locale.getpreferredencoding(False)).splitlines()]
        assert listed == relative_paths
        for source, relative in zip(sources, listed):
            assert (root / relative).read_bytes() == source.read_bytes()
        _write_rcp_nodes(root / f'{name}.rcp', [(f'station-{i}', str(relative)) for i, relative in enumerate(listed, start=1)])
        return SimpleNamespace(returncode=0, stdout='ok', stderr='')

    monkeypatch.setattr(recap_decap.subprocess, 'run', run)
    result = recap_decap.create_recap_project(tmp_path / 'out', 'Pair', [{'path': str(path)} for path in sources])

    assert result['package_verified'] is True
    assert result['input_scan_count'] == 2
    assert result['rcp_node_count'] == 2
    assert result['linked_rcs_count'] == 2
    assert result['external_rcs_count'] == 0
    manifest = read_rcp_manifest(result['rcp_path'])
    links = [Path(node['resolved_rcs_path']) for node in manifest['nodes']]
    assert len(links) == 2
    assert all(path.is_file() and path.parent == Path(result['support_dir']) for path in links)
    assert {path.read_bytes() for path in links} == set(original_bytes)

    moved = tmp_path / 'relocated project' / 'Pair'
    copytree(Path(result['rcp_path']).parent, moved)
    moved_manifest = read_rcp_manifest(moved / 'Pair.rcp')
    moved_links = [Path(node['resolved_rcs_path']) for node in moved_manifest['nodes']]
    assert len(moved_links) == 2
    assert all(path.is_file() and path.parent == moved / 'Pair Support' for path in moved_links)
    assert {path.read_bytes() for path in moved_links} == set(original_bytes)
    assert [path.read_bytes() for path in sources] == original_bytes
