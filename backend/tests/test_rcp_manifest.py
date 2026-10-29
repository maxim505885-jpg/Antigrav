from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from scan2bim.formats import rcp_manifest
from scan2bim.formats.rcp_manifest import (
    RcpManifestError,
    compare_axis_aligned_asset_bounds,
    read_rcp_manifest,
)


def _write_rcp(path: Path, nodes: list[str], extra: str = "") -> None:
    xml = (
        '<Autodesk Version="1.0"><ProjectId UUID="project-123"/><Nodes>'
        + "".join(nodes)
        + "</Nodes>"
        + extra
        + "</Autodesk>"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.xml", xml)


def _node(name: str, path: str, declared: int = 42) -> str:
    return f"""<VoxelTreeRunTime Id="{{node-{name}}}">
      <Translation x="1.25" y="-2" z="3"/><Rotation x="0" y="0" z="0"/>
      <Scale x="1" y="1" z="1"/><Registered Value="1"/><NodeName Value="{name}"/>
      <Path Value="{path}"/><RelativePath Value=""/><NumPoints Value="{declared}"/>
      <HasRGB Value="1"/><HasIntensity Value="0"/><HasNormals Value="1"/>
    </VoxelTreeRunTime>"""


def test_reads_single_station_metadata_and_resolves_moved_support_path(tmp_path: Path):
    rcp = tmp_path / "hall.rcp"
    linked = tmp_path / "hall Support" / "station 01.rcs"
    linked.parent.mkdir()
    linked.write_bytes(b"source stays untouched")
    _write_rcp(rcp, [_node("Station 01", r"Z:\old\hall Support\station 01.rcs")])

    result = read_rcp_manifest(rcp)

    assert result["project_id"] == "project-123"
    assert result["node_count"] == 1
    node = result["nodes"][0]
    assert node["name"] == "Station 01"
    assert node["resolved_rcs_path"] == str(linked.resolve())
    assert node["declared_point_count"] == 42
    assert node["has_rgb"] is True
    assert node["has_intensity"] is False
    assert node["translation"] == [1.25, -2.0, 3.0]
    assert node["registered"] is True
    assert linked.read_bytes() == b"source stays untouched"


def test_direct_support_links_skip_recursive_support_index(tmp_path: Path, monkeypatch):
    rcp = tmp_path / "hall.rcp"
    linked = tmp_path / "hall Support" / "station 01.rcs"
    linked.parent.mkdir()
    linked.write_bytes(b"source stays untouched")
    _write_rcp(
        rcp,
        [_node("Station 01", r".\hall Support\station 01.rcs")],
    )

    def unexpected_index(_support_root: Path):
        raise AssertionError("direct RCS links must not trigger a Support tree walk")

    monkeypatch.setattr(rcp_manifest, "_index_support_scans", unexpected_index)

    result = read_rcp_manifest(rcp)

    assert result["nodes"][0]["resolved_rcs_path"] == str(linked.resolve())


def test_relative_direct_support_links_return_resolved_path(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rcp = Path("hall.rcp")
    linked = Path("hall Support") / "station 01.rcs"
    linked.parent.mkdir()
    linked.write_bytes(b"source stays untouched")
    _write_rcp(
        rcp,
        [_node("Station 01", r".\hall Support\station 01.rcs")],
    )

    result = read_rcp_manifest(rcp)

    resolved = Path(result["nodes"][0]["resolved_rcs_path"])
    assert resolved.is_absolute()
    assert resolved == linked.resolve()
    assert linked.read_bytes() == b"source stays untouched"

def test_direct_path_is_still_checked_when_support_listing_fails(tmp_path: Path, monkeypatch):
    rcp = tmp_path / "hall.rcp"
    linked = tmp_path / "hall Support" / "station 01.rcs"
    linked.parent.mkdir()
    linked.write_bytes(b"source stays untouched")
    _write_rcp(
        rcp,
        [_node("Station 01", r".\hall Support\station 01.rcs")],
    )

    monkeypatch.setattr(rcp_manifest, "_index_direct_support_scans", lambda _root: None)
    monkeypatch.setattr(
        rcp_manifest,
        "_index_support_scans",
        lambda _root: (_ for _ in ()).throw(AssertionError("unexpected recursive index")),
    )

    result = read_rcp_manifest(rcp)

    assert result["nodes"][0]["resolved_rcs_path"] == str(linked.resolve())


def test_moved_support_paths_build_recursive_index_once_for_all_nodes(tmp_path: Path, monkeypatch):
    rcp = tmp_path / "hall.rcp"
    support = tmp_path / "hall Support"
    support.mkdir()
    nested_support = support / "nested"
    nested_support.mkdir()
    first = nested_support / "station-01.rcs"
    second = nested_support / "station-02.rcs"
    first.write_bytes(b"station 01")
    second.write_bytes(b"station 02")
    _write_rcp(
        rcp,
        [
            _node("Station 01", r"Z:\old\hall Support\station-01.rcs"),
            _node("Station 02", r"Z:\old\hall Support\station-02.rcs"),
        ],
    )
    original_index = rcp_manifest._index_support_scans
    calls = 0

    def count_index_calls(support_root: Path):
        nonlocal calls
        calls += 1
        return original_index(support_root)

    monkeypatch.setattr(rcp_manifest, "_index_support_scans", count_index_calls)

    result = read_rcp_manifest(rcp)

    assert [node["resolved_rcs_path"] for node in result["nodes"]] == [
        str(first.resolve()),
        str(second.resolve()),
    ]
    assert calls == 1


def test_reads_station_specific_source_import_filter_provenance(tmp_path: Path):
    rcp = tmp_path / "filters.rcp"
    shot_info = """<ShotInfo name="Station 01" id="shot-1" PCPid="{node-Station 01}"
        rawScanPath="E:/raw/station.e57" path="filters Support/station.rcc">
      <ScanImportSettings>
        <ScanImportFilterSettings>
          <NoiseFilter level="MEDIUM"/>
          <IntensityClip min="10" max="100"/>
          <RangeClip min="2" max="80"/>
        </ScanImportFilterSettings>
        <ScanImportAdvancedSettings density="7" upDirection="Z"/>
      </ScanImportSettings>
    </ShotInfo>"""
    _write_rcp(rcp, [_node("Station 01", "station.rcs")], f"<Shots>{shot_info}</Shots>")

    node = read_rcp_manifest(rcp)["nodes"][0]

    assert node["source_import"] == {
        "raw_scan_path": "E:/raw/station.e57",
        "rcc_path": "filters Support/station.rcc",
        "noise_filter_level": "MEDIUM",
        "intensity_clip_min": "10",
        "intensity_clip_max": "100",
        "range_clip_min": "2",
        "range_clip_max": "80",
        "decimation_density": "7",
        "up_direction": "Z",
    }


def test_recovers_cp1251_shot_paths_when_rcp_declares_utf8(tmp_path: Path):
    rcp = tmp_path / "legacy-paths.rcp"
    raw_scan_path = r"E:\Сканирование\сырьё\station-01.e57"
    rcc_path = r"D:\Проект\Поддержка\station-01.rcc"
    shot = f'''<Shots><ShotInfo PCPid="{{node-Station 01}}"
        rawScanPath="{raw_scan_path}" path="{rcc_path}">
      <ScanImportSettings><ScanImportAdvancedSettings density="7" upDirection="Z"/></ScanImportSettings>
    </ShotInfo></Shots>'''
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Autodesk Version="1.0"><ProjectId UUID="project-123"/><Nodes>'
        + _node("Station 01", "station.rcs")
        + '</Nodes>'
        + shot
        + '</Autodesk>'
    )
    xml_bytes = xml.encode("utf-8")
    for value in (raw_scan_path, rcc_path):
        xml_bytes = xml_bytes.replace(value.encode("utf-8"), value.encode("cp1251"))
    with zipfile.ZipFile(rcp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.xml", xml_bytes)

    node = read_rcp_manifest(rcp)["nodes"][0]

    assert node["source_import"]["raw_scan_path"] == raw_scan_path
    assert node["source_import"]["rcc_path"] == rcc_path

def test_does_not_attach_ambiguous_shot_info_to_station(tmp_path: Path):
    rcp = tmp_path / "ambiguous-shot.rcp"
    shot = """<ShotInfo PCPid="{node-Station 01}" rawScanPath="a.e57">
      <ScanImportSettings><ScanImportFilterSettings><NoiseFilter level="HIGH"/></ScanImportFilterSettings></ScanImportSettings>
    </ShotInfo>"""
    _write_rcp(rcp, [_node("Station 01", "station.rcs")], f"<Shots>{shot}{shot}</Shots>")

    node = read_rcp_manifest(rcp)["nodes"][0]

    assert node["source_import"] is None

def test_prefers_named_support_copy_over_same_basename_workspace_file(tmp_path: Path):
    rcp = tmp_path / "10.rcp"
    support_copy = tmp_path / "10 Support" / "10.rcs"
    unrelated_copy = tmp_path / "10.rcs"
    support_copy.parent.mkdir()
    support_copy.write_bytes(b"manifest-linked station")
    unrelated_copy.write_bytes(b"unrelated same-name station")
    _write_rcp(
        rcp,
        [_node("10", r"C:\\old-project\\10 Support\\10.rcs")],
    )

    result = read_rcp_manifest(rcp)

    assert result["nodes"][0]["resolved_rcs_path"] == str(support_copy.resolve())
    assert support_copy.read_bytes() == b"manifest-linked station"
    assert unrelated_copy.read_bytes() == b"unrelated same-name station"


def test_rejects_non_finite_transform_values(tmp_path: Path):
    rcp = tmp_path / "invalid.rcp"
    _write_rcp(rcp, [_node("bad", "missing.rcs").replace('x="1.25"', 'x="nan"')])

    with pytest.raises(RcpManifestError, match="non-finite"):
        read_rcp_manifest(rcp)


def test_rejects_ambiguous_project_manifest(tmp_path: Path):
    rcp = tmp_path / "ambiguous.rcp"
    with zipfile.ZipFile(rcp, "w") as archive:
        archive.writestr("a.xml", "<Autodesk><Nodes/></Autodesk>")
        archive.writestr("b.xml", "<Autodesk><Nodes/></Autodesk>")

    with pytest.raises(RcpManifestError, match="exactly one XML"):
        read_rcp_manifest(rcp)


def test_preserves_axis_aligned_asset_bounds_for_later_coordinate_frame_check(tmp_path: Path):
    rcp = tmp_path / "bounded.rcp"
    asset = """<AssetCollection><AssetInfo AssetName="scan-a">
      <AssetBoundingBox sizeX="4" sizeY="6" sizeZ="8"><tform><T x="10" y="20" z="30"/></tform></AssetBoundingBox>
    </AssetInfo></AssetCollection>"""
    node = _node("scan-a", "missing.rcs").replace(
        '<Translation x="1.25" y="-2" z="3"/>',
        '<Translation x="0" y="0" z="0"/>',
    )
    _write_rcp(rcp, [node], asset)

    result = read_rcp_manifest(rcp)["nodes"][0]["asset_bounds"]

    assert result == {
        "tform_translation": [10.0, 20.0, 30.0],
        "size": [4.0, 6.0, 8.0],
        "axis_aligned_interpretation_supported": True,
        "min": [10.0, 20.0, 30.0],
        "max": [14.0, 26.0, 38.0],
    }


def test_coordinate_frame_check_matches_full_linked_rcs_extents_without_reapplying_translation():
    bounds = {
        "axis_aligned_interpretation_supported": True,
        "min": [-50.8636486709028, -28.3974500969408, -3.12890562964454],
        "max": [31.9112896687731, 114.23846358912421, 14.927280064738861],
    }
    actual_min = [-50.86330842804833, -28.397686644383462, -3.1290869562622454]
    actual_max = [31.910917194172782, 114.23818402069409, 14.927187217547159]

    result = compare_axis_aligned_asset_bounds(actual_min, actual_max, bounds, "0")

    assert result["status"] == "rcs_bounds_match_rcp_asset_bounds"
    assert result["translation_reapplication"] == "do_not_apply_for_this_node"
    assert result["max_absolute_delta_in_coordinate_units"] == pytest.approx(0.0003724746003)
    assert result["epsilon_is_engineering_tolerance"] is False
    assert result["unit_type_raw"] == "0"


def test_coordinate_frame_check_keeps_transform_unresolved_when_extents_differ():
    bounds = {
        "axis_aligned_interpretation_supported": True,
        "min": [0.0, 0.0, 0.0],
        "max": [1.0, 1.0, 1.0],
    }

    result = compare_axis_aligned_asset_bounds([5.0, 0.0, 0.0], [6.0, 1.0, 1.0], bounds)

    assert result["status"] == "rcs_bounds_differ_from_rcp_asset_bounds"
    assert result["translation_reapplication"] == "unresolved; do not auto-apply"


def test_coordinate_frame_check_rejects_non_finite_extents():
    bounds = {
        "axis_aligned_interpretation_supported": True,
        "min": [0.0, 0.0, 0.0],
        "max": [1.0, 1.0, 1.0],
    }

    with pytest.raises(RcpManifestError, match="non-finite"):
        compare_axis_aligned_asset_bounds([0.0, float("nan"), 0.0], [1.0, 1.0, 1.0], bounds)
