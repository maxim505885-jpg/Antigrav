import pytest
from conftest import wait_cloud

def test_spds_album_pdf_endpoint(client):
    # Create demo cloud
    demo_res = client.post("/api/v1/demo")
    assert demo_res.status_code == 200
    cloud = wait_cloud(client, demo_res.json()["cloud"]["id"])
    assert cloud["status"] == "ready"

    # Request SPDS album PDF
    res = client.get(f"/api/v1/clouds/{cloud['id']}/spds-album.pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert len(res.content) > 1000

    # Request SPDS album ZIP
    zip_res = client.get(f"/api/v1/clouds/{cloud['id']}/spds-album.zip")
    assert zip_res.status_code == 200
    assert zip_res.headers["content-type"] == "application/zip"
    assert len(zip_res.content) > 1000
