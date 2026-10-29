from __future__ import annotations

import json
import zipfile
import importlib
from types import SimpleNamespace
from pathlib import Path

from scan2bim.db import one
from scan2bim.job_tasks import _run_rcp_batch, execute_ingest_task

api_module = importlib.import_module("scan2bim.api.app")


def _run_queued_ingest(job_id: str, monkeypatch, progress=lambda _fraction, _message="": None):
    monkeypatch.setenv("S2B_INGEST_MODE", "worker")
    row = one("SELECT task_payload_json FROM jobs WHERE id = ?", (job_id,))
    task = json.loads(row["task_payload_json"])
    return execute_ingest_task(task["task_type"], task["payload"], progress)


def _node(name: str, rcs_name: str) -> str:
    return f'''<VoxelTreeRunTime Id="{{node-{name}}}">
      <Translation x="1" y="2" z="3"/><Rotation x="0" y="0" z="0"/>
      <Scale x="1" y="1" z="1"/><Registered Value="1"/><NodeName Value="{name}"/>
      <Path Value="{rcs_name}"/><RelativePath Value="{rcs_name}"/><NumPoints Value="42"/>
      <HasRGB Value="1"/><HasIntensity Value="0"/><HasNormals Value="1"/>
    </VoxelTreeRunTime>'''


def _write_rcp(path: Path, nodes: list[str]) -> None:
    xml = '<Autodesk><ProjectId UUID="batch-project"/><Nodes>' + ''.join(nodes) + '</Nodes></Autodesk>'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('project.xml', xml)


def test_multi_node_rcp_preflights_and_creates_distinct_station_clouds(client, tmp_path, monkeypatch):
    monkeypatch.setenv('S2B_INGEST_MODE', 'worker')
    project = client.post('/api/v1/projects', json={'name': 'RCP batch test'}).json()
    support = tmp_path / 'plant Support'
    support.mkdir()
    rcs_paths = [support / 'station-a.rcs', support / 'station-b.rcs']
    for path in rcs_paths:
        path.write_bytes(b'RCS fixture')
    rcp = tmp_path / 'plant.rcp'
    _write_rcp(rcp, [_node('Station A', 'station-a.rcs'), _node('Station B', 'station-b.rcs')])
    processed = []
    def fake_ingest(_project_id, cloud_id):
        def run(progress):
            processed.append(cloud_id)
            progress(1.0, "ready")
            return {"status": "ready"}
        return run

    monkeypatch.setattr(api_module, '_ingest_work', fake_ingest)
    monkeypatch.setattr('scan2bim.formats.rcs_native.native_available', lambda: {'dll_exists': True})

    response = client.post(
        f"/api/v1/projects/{project['id']}/rcp/import-path",
        json={'path': str(rcp), 'max_points': 0},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result['node_count'] == 2
    task_row = one("SELECT task_payload_json FROM jobs WHERE id = ?", (result['import_job_id'],))
    task = json.loads(task_row['task_payload_json'])
    assert task['task_type'] == 'rcp_batch_ingest'
    clouds = [station['cloud'] for station in result['stations']]
    assert len({cloud['id'] for cloud in clouds}) == 2
    assert [station['node_name'] for station in result['stations']] == ['Station A', 'Station B']
    for cloud, source in zip(clouds, rcs_paths):
        assert Path(cloud['source_path']) == source.resolve()
        project_meta = cloud['metadata']['recap_project']
        assert cloud['metadata']['max_points'] == 0
        assert project_meta['transform_applied'] is False
        assert project_meta['selected_node']['translation'] == [1.0, 2.0, 3.0]
        assert project_meta['project_sha256'] == result['project_sha256']
    assert [path.read_bytes() for path in rcs_paths] == [b'RCS fixture', b'RCS fixture']
    worker_result = _run_queued_ingest(result['import_job_id'], monkeypatch)
    assert processed == [cloud['id'] for cloud in clouds]
    assert worker_result['ready_count'] == 2
    assert worker_result['failed_count'] == 0


def test_multi_node_rcp_unresolved_station_fails_before_creating_clouds(client, tmp_path, monkeypatch):
    project = client.post('/api/v1/projects', json={'name': 'RCP preflight test'}).json()
    available = tmp_path / 'available.rcs'
    available.write_bytes(b'RCS fixture')
    rcp = tmp_path / 'broken.rcp'
    _write_rcp(rcp, [_node('Station A', 'available.rcs'), _node('Station B', 'missing.rcs')])
    monkeypatch.setattr('scan2bim.formats.rcs_native.native_available', lambda: {'dll_exists': True})
    before = client.get(f"/api/v1/projects/{project['id']}/clouds").json()

    response = client.post(f"/api/v1/projects/{project['id']}/rcp/import-path", json={'path': str(rcp)})

    assert response.status_code == 409
    assert 'unresolved_nodes' in response.json()['detail']
    after = client.get(f"/api/v1/projects/{project['id']}/clouds").json()
    assert after == before


def test_full_resolution_rcp_fails_before_cloud_rows_when_disk_is_insufficient(
    client, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    project = client.post('/api/v1/projects', json={'name': 'RCP disk preflight test'}).json()
    for name in ('station-a.rcs', 'station-b.rcs'):
        (tmp_path / name).write_bytes(b'RCS fixture')
    rcp = tmp_path / 'low-disk.rcp'
    _write_rcp(rcp, [_node('Station A', 'station-a.rcs'), _node('Station B', 'station-b.rcs')])
    monkeypatch.setattr('scan2bim.formats.rcs_native.native_available', lambda: {'dll_exists': True})
    monkeypatch.setattr(api_module.shutil, 'disk_usage', lambda _path: SimpleNamespace(free=1))
    before = client.get(f"/api/v1/projects/{project['id']}/clouds").json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/rcp/import-path",
        json={'path': str(rcp), 'max_points': 0},
    )

    assert response.status_code == 507, response.text
    assert response.json()['detail']['required_bytes'] > 1
    assert response.json()['detail']['available_bytes'] == 1
    assert client.get(f"/api/v1/projects/{project['id']}/clouds").json() == before
    assert client.get(f"/api/v1/projects/{project['id']}/jobs").json() == []


def test_full_resolution_single_node_rcp_fails_before_cloud_row_when_disk_is_insufficient(
    client, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    project = client.post('/api/v1/projects', json={'name': 'Single RCP disk preflight test'}).json()
    source = tmp_path / 'station.rcs'
    source.write_bytes(b'RCS fixture')
    rcp = tmp_path / 'single.rcp'
    _write_rcp(rcp, [_node('Station', 'station.rcs')])
    monkeypatch.setattr('scan2bim.formats.rcs_native.native_available', lambda: {'dll_exists': True})
    monkeypatch.setattr(api_module.shutil, 'disk_usage', lambda _path: SimpleNamespace(free=1))

    response = client.post(
        f"/api/v1/projects/{project['id']}/clouds/import-path",
        json={'path': str(rcp), 'max_points': 0},
    )

    assert response.status_code == 507, response.text
    assert client.get(f"/api/v1/projects/{project['id']}/clouds").json() == []
    assert client.get(f"/api/v1/projects/{project['id']}/jobs").json() == []


def test_full_resolution_rcp_fails_before_cloud_rows_when_storage_cannot_be_checked(
    client, tmp_path, monkeypatch
):
    project = client.post('/api/v1/projects', json={'name': 'RCP inaccessible storage test'}).json()
    for name in ('station-a.rcs', 'station-b.rcs'):
        (tmp_path / name).write_bytes(b'RCS fixture')
    rcp = tmp_path / 'inaccessible-storage.rcp'
    _write_rcp(rcp, [_node('Station A', 'station-a.rcs'), _node('Station B', 'station-b.rcs')])
    monkeypatch.setattr('scan2bim.formats.rcs_native.native_available', lambda: {'dll_exists': True})

    def inaccessible(_path):
        raise PermissionError('storage volume is not accessible')

    monkeypatch.setattr(api_module.shutil, 'disk_usage', inaccessible)
    before = client.get(f"/api/v1/projects/{project['id']}/clouds").json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/rcp/import-path",
        json={'path': str(rcp), 'max_points': 0},
    )

    assert response.status_code == 503, response.text
    assert response.json()['detail']['storage_check'] == 'unavailable'
    assert client.get(f"/api/v1/projects/{project['id']}/clouds").json() == before
    assert client.get(f"/api/v1/projects/{project['id']}/jobs").json() == []


def test_full_resolution_rcp_checks_storage_when_manifest_point_count_is_missing(
    client, tmp_path, monkeypatch
):
    project = client.post('/api/v1/projects', json={'name': 'RCP unknown-count storage test'}).json()
    for name in ('station-a.rcs', 'station-b.rcs'):
        (tmp_path / name).write_bytes(b'RCS fixture')
    rcp = tmp_path / 'unknown-count.rcp'
    nodes = [
        _node('Station A', 'station-a.rcs').replace('<NumPoints Value="42"/>', '<NumPoints Value="0"/>'),
        _node('Station B', 'station-b.rcs').replace('<NumPoints Value="42"/>', '<NumPoints Value="0"/>'),
    ]
    _write_rcp(rcp, nodes)
    monkeypatch.setattr('scan2bim.formats.rcs_native.native_available', lambda: {'dll_exists': True})

    def inaccessible(_path):
        raise PermissionError('storage volume is not accessible')

    monkeypatch.setattr(api_module.shutil, 'disk_usage', inaccessible)
    monkeypatch.setenv('S2B_INGEST_MODE', 'worker')

    response = client.post(
        f"/api/v1/projects/{project['id']}/rcp/import-path",
        json={'path': str(rcp), 'max_points': 0},
    )

    assert response.status_code == 503, response.text
    assert response.json()['detail']['storage_check'] == 'unavailable'
    assert client.get(f"/api/v1/projects/{project['id']}/clouds").json() == []
    assert client.get(f"/api/v1/projects/{project['id']}/jobs").json() == []


def test_batch_worker_continues_after_station_failure(client, tmp_path, monkeypatch):
    project = client.post('/api/v1/projects', json={'name': 'RCP partial batch test'}).json()
    for name in ('station-a.rcs', 'station-b.rcs'):
        (tmp_path / name).write_bytes(b'RCS fixture')
    rcp = tmp_path / 'partial.rcp'
    _write_rcp(rcp, [_node('Station A', 'station-a.rcs'), _node('Station B', 'station-b.rcs')])
    monkeypatch.setenv('S2B_INGEST_MODE', 'worker')
    attempted = []

    def fake_ingest(_project_id, cloud_id):
        def run(progress):
            attempted.append(cloud_id)
            if len(attempted) == 1:
                api_module.execute("UPDATE clouds SET status='failed', error='fixture failure' WHERE id=?", (cloud_id,))
                raise RuntimeError('fixture failure')
            api_module.execute("UPDATE clouds SET status='ready' WHERE id=?", (cloud_id,))
            progress(1.0, 'ready')
        return run

    monkeypatch.setattr(api_module, '_ingest_work', fake_ingest)
    monkeypatch.setattr('scan2bim.formats.rcs_native.native_available', lambda: {'dll_exists': True})
    response = client.post(f"/api/v1/projects/{project['id']}/rcp/import-path", json={'path': str(rcp)})
    assert response.status_code == 200, response.text
    result = _run_queued_ingest(response.json()['import_job_id'], monkeypatch)

    assert attempted == [item['cloud']['id'] for item in response.json()['stations']]
    assert result['ready_count'] == 1
    assert result['failed_count'] == 1
    assert result['failures'][0]['node_name'] == 'Station A'


def test_batch_worker_marks_not_started_stations_cancelled(client, tmp_path, monkeypatch):
    from scan2bim.jobs import JobCancelled

    project = client.post('/api/v1/projects', json={'name': 'RCP cancel batch test'}).json()
    for name in ('station-a.rcs', 'station-b.rcs'):
        (tmp_path / name).write_bytes(b'RCS fixture')
    rcp = tmp_path / 'cancel.rcp'
    _write_rcp(rcp, [_node('Station A', 'station-a.rcs'), _node('Station B', 'station-b.rcs')])
    monkeypatch.setenv('S2B_INGEST_MODE', 'worker')

    def cancelled_ingest(_project_id, cloud_id):
        def run(_progress):
            api_module.execute("UPDATE clouds SET status='cancelled' WHERE id=?", (cloud_id,))
            raise JobCancelled('test cancellation')
        return run

    monkeypatch.setattr(api_module, '_ingest_work', cancelled_ingest)
    monkeypatch.setattr('scan2bim.formats.rcs_native.native_available', lambda: {'dll_exists': True})
    response = client.post(f"/api/v1/projects/{project['id']}/rcp/import-path", json={'path': str(rcp)})
    assert response.status_code == 200, response.text
    stations = response.json()['stations']

    import pytest
    with pytest.raises(JobCancelled):
        _run_queued_ingest(response.json()['import_job_id'], monkeypatch)
    statuses = [client.get(f"/api/v1/clouds/{item['cloud']['id']}").json()['status'] for item in stations]
    assert statuses == ['cancelled', 'cancelled']


def test_rcp_declared_count_is_compared_to_source_count_not_decimated_sample(
    client, tmp_path, monkeypatch
):
    project = client.post('/api/v1/projects', json={'name': 'RCP point count semantics'}).json()
    source = tmp_path / 'station.rcs'
    source.write_bytes(b'RCS fixture')
    rcp = tmp_path / 'count-check.rcp'
    node = _node('Station', 'station.rcs').replace('<NumPoints Value="42"/>', '<NumPoints Value="995"/>')
    _write_rcp(rcp, [node])
    monkeypatch.setenv('S2B_INGEST_MODE', 'worker')
    monkeypatch.setattr('scan2bim.formats.rcs_native.native_available', lambda: {'dll_exists': True})

    response = client.post(f"/api/v1/projects/{project['id']}/rcp/import-path", json={'path': str(rcp)})
    assert response.status_code == 200, response.text
    cloud_id = response.json()['stations'][0]['cloud']['id']

    def fake_ingest(_project_id, ingest_cloud_id, _source_path, _progress, **_options):
        api_module.execute(
            "UPDATE clouds SET point_count=1000, ingested_count=25, decimated=1, status='ready' WHERE id=?",
            (ingest_cloud_id,),
        )
        return {'status': 'ready'}

    monkeypatch.setattr(api_module, 'ingest_cloud', fake_ingest)
    result = _run_queued_ingest(response.json()['import_job_id'], monkeypatch)

    assert result['ready_count'] == 1
    recap = client.get(f'/api/v1/clouds/{cloud_id}').json()['metadata']['recap_project']
    assert recap['actual_source_point_count'] == 1000
    assert recap['actual_ingested_point_count'] == 25
    assert recap['declared_point_count_difference'] == -5


def test_batch_resume_skips_stations_already_ready(monkeypatch):
    processed: list[str] = []
    updates: list[tuple[float, str]] = []
    api = SimpleNamespace(
        _ingest_work=lambda _project_id, cloud_id: lambda _progress: processed.append(cloud_id)
    )
    monkeypatch.setattr(
        "scan2bim.job_tasks.one", lambda _sql, _params: {"status": "ready"}
    )

    result = _run_rcp_batch(
        api,
        {"project_id": "project", "stations": [
            {"cloud_id": "ready-cloud", "node_name": "Station 001"},
        ]},
        lambda fraction, message: updates.append((fraction, message)),
    )

    assert processed == []
    assert result["ready_count"] == 1
    assert result["failed_count"] == 0
    assert updates[-1][0] == 1.0
    assert "уже готова, пропуск" in updates[-1][1]


def test_failed_rcp_batch_can_resume_after_failed_station_succeeds(client, tmp_path, monkeypatch):
    monkeypatch.setenv("S2B_INGEST_MODE", "worker")
    # Earlier API tests persist queued rows in the session-scoped test database;
    # keep run_once focused on the jobs created by this lifecycle test.
    api_module.execute(
        "UPDATE jobs SET status='cancelled', cancel_requested=1 "
        "WHERE status='queued' AND task_payload_json IS NOT NULL"
    )
    project = client.post("/api/v1/projects", json={"name": "RCP batch retry"}).json()
    support = tmp_path / "retry Support"
    support.mkdir()
    for name in ("station-a.rcs", "station-b.rcs"):
        (support / name).write_bytes(b"RCS fixture")
    rcp = tmp_path / "retry.rcp"
    _write_rcp(rcp, [_node("Station A", "station-a.rcs"), _node("Station B", "station-b.rcs")])
    monkeypatch.setattr("scan2bim.formats.rcs_native.native_available", lambda: {"dll_exists": True})

    imported = client.post(
        f"/api/v1/projects/{project['id']}/rcp/import-path",
        json={"path": str(rcp), "max_points": 1},
    )
    assert imported.status_code == 200, imported.text
    batch_job_id = imported.json()["import_job_id"]
    clouds = imported.json()["stations"]
    ready_cloud_id = clouds[0]["cloud"]["id"]
    failed_cloud_id = clouds[1]["cloud"]["id"]
    failed_once = False

    def fake_ingest_work(_project_id, cloud_id):
        def run(_progress):
            nonlocal failed_once
            if cloud_id == failed_cloud_id and not failed_once:
                failed_once = True
                api_module.execute(
                    "UPDATE clouds SET status='failed', error='simulated SMB denial' WHERE id=?",
                    (cloud_id,),
                )
                raise PermissionError("simulated SMB denial")
            api_module.execute(
                "UPDATE clouds SET status='ready', error=NULL, point_count=42, ingested_count=42 WHERE id=?",
                (cloud_id,),
            )
            return {"status": "ready"}
        return run

    monkeypatch.setattr(api_module, "_ingest_work", fake_ingest_work)
    from scan2bim.worker import run_once

    assert run_once("batch-first-attempt") is True
    assert one("SELECT status FROM jobs WHERE id=?", (batch_job_id,))["status"] == "failed"
    assert one("SELECT status FROM clouds WHERE id=?", (ready_cloud_id,))["status"] == "ready"

    station_retry = client.post(f"/api/v1/clouds/{failed_cloud_id}/resume")
    assert station_retry.status_code == 200, station_retry.text
    active_batch_resume = client.post(
        f"/api/v1/projects/{project['id']}/jobs/{batch_job_id}/resume"
    )
    assert active_batch_resume.status_code == 409
    assert one("SELECT status FROM jobs WHERE id=?", (batch_job_id,))["status"] == "failed"
    assert run_once("station-retry") is True
    assert one("SELECT status FROM clouds WHERE id=?", (failed_cloud_id,))["status"] == "ready"

    resumed = client.post(f"/api/v1/projects/{project['id']}/jobs/{batch_job_id}/resume")
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["id"] == batch_job_id
    assert run_once("batch-retry") is True

    job = client.get(f"/api/v1/projects/{project['id']}/jobs").json()[0]
    assert job["id"] == batch_job_id
    assert job["status"] == "succeeded"
    assert job["result"]["ready_count"] == 2
    assert job["result"]["failed_count"] == 0
    assert len(client.get(f"/api/v1/projects/{project['id']}/clouds").json()) == 2
    duplicate_resume = client.post(
        f"/api/v1/projects/{project['id']}/jobs/{batch_job_id}/resume"
    )
    assert duplicate_resume.status_code == 409
