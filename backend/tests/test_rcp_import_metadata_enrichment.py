"""Legacy cloud metadata can show provenance from its unchanged source RCP."""
from __future__ import annotations

import json
import importlib

api_module = importlib.import_module("scan2bim.api.app")


def _cloud_row(project_file, project_sha256):
    return {
        "id": "cloud-a",
        "project_id": "project-a",
        "name": "station-a",
        "source_path": "station-a.rcs",
        "source_format": "rcs",
        "size_bytes": 123,
        "point_count": 1000,
        "ingested_count": 800,
        "decimated": 0,
        "origin_x": None,
        "bbox_min_x": None,
        "has_color": 0,
        "has_intensity": 1,
        "status": "ready",
        "error": None,
        "created_at": "now",
        "updated_at": "now",
        "metadata_json": json.dumps({
            "recap_project": {
                "project_file": str(project_file),
                "project_sha256": project_sha256,
                "actual_source_point_count": 800,
                "selected_node": {
                    "node_id": "node-a",
                    "declared_point_count": 1000,
                },
            }
        }),
    }


def test_cloud_response_restores_import_settings_from_hash_matched_rcp(tmp_path, monkeypatch):
    project_file = tmp_path / "project.rcp"
    project_file.write_bytes(b"unchanged project fixture")
    api_module._cached_rcp_import_settings.cache_clear()
    monkeypatch.setattr(api_module, "sha256_file", lambda _path: "a" * 64)
    monkeypatch.setattr(api_module, "read_rcp_manifest", lambda _path: {
        "nodes": [
            {"node_id": "other-node", "source_import": {"noise_filter_level": "NONE"}},
            {"node_id": "node-a", "source_import": {
                "raw_scan_path": r"E:\\stations\\11064.e57",
                "noise_filter_level": "MEDIUM",
                "intensity_clip_max": "100",
                "decimation_density": "7",
            }},
        ]
    })

    result = api_module._cloud_out(_cloud_row(project_file, "a" * 64))

    assert result["metadata"]["recap_project"]["selected_node"]["source_import"] == {
        "raw_scan_path": r"E:\\stations\\11064.e57",
        "noise_filter_level": "MEDIUM",
        "intensity_clip_max": "100",
        "decimation_density": "7",
    }
    assert "фильтр помех: MEDIUM" in result["warning"]
    assert "сырой параметр density из RCP" in result["warning"]
    assert "импорте E57 близкие эквивалентные точки могут объединяться или удаляться даже при decimation=0" in result["warning"]
    assert "возможный фактор; его вклад для этой станции не измерен" in result["warning"]
    api_module._cached_rcp_import_settings.cache_clear()


def test_cloud_response_does_not_attach_settings_when_rcp_hash_changed(tmp_path, monkeypatch):
    project_file = tmp_path / "changed.rcp"
    project_file.write_bytes(b"changed project fixture")
    api_module._cached_rcp_import_settings.cache_clear()
    monkeypatch.setattr(api_module, "sha256_file", lambda _path: "b" * 64)

    def unexpected_manifest_read(_path):
        raise AssertionError("hash mismatch must stop manifest parsing")

    monkeypatch.setattr(api_module, "read_rcp_manifest", unexpected_manifest_read)
    result = api_module._cloud_out(_cloud_row(project_file, "a" * 64))

    assert "source_import" not in result["metadata"]["recap_project"]["selected_node"]
    assert "фильтр помех" not in result["warning"]
    api_module._cached_rcp_import_settings.cache_clear()


def test_cloud_response_does_not_claim_e57_filtering_for_las_source(tmp_path, monkeypatch):
    project_file = tmp_path / "project.rcp"
    project_file.write_bytes(b"unchanged project fixture")
    api_module._cached_rcp_import_settings.cache_clear()
    monkeypatch.setattr(api_module, "sha256_file", lambda _path: "c" * 64)
    monkeypatch.setattr(api_module, "read_rcp_manifest", lambda _path: {
        "nodes": [{"node_id": "node-a", "source_import": {"raw_scan_path": "station.las"}}]
    })

    result = api_module._cloud_out(_cloud_row(project_file, "c" * 64))

    assert "импорте E57" not in result["warning"]
    api_module._cached_rcp_import_settings.cache_clear()
