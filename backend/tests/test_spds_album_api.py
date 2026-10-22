from __future__ import annotations

import io
import json
import zipfile

from conftest import wait_cloud


def test_spds_album_endpoint_returns_draft_dxf_pdf_and_manifest(client):
    demo = client.post("/api/v1/demo")
    assert demo.status_code == 200, demo.text
    cloud = wait_cloud(client, demo.json()["cloud"]["id"])

    response = client.get(f"/api/v1/clouds/{cloud['id']}/spds-album.zip")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["issue"] == "draft"
        assert manifest["release_ready"] is False
        assert len(manifest["source_elements_sha256"]) == 64
        assert manifest["grid_alignment_version"] == "repeat-density-v1"
        assert len(manifest["sheets"]) == 4
        assert all(sheet["issue"] == "draft" for sheet in manifest["sheets"])
        assert "C:\\" not in json.dumps(manifest)
        assert manifest["album_pdf_path"] == "spds_album.pdf"
        assert all("/" not in sheet["dxf_path"] and "\\" not in sheet["dxf_path"] for sheet in manifest["sheets"])
        assert len([name for name in names if name.endswith(".dxf")]) == 4
        assert len([name for name in names if name.endswith(".pdf")]) == 5
