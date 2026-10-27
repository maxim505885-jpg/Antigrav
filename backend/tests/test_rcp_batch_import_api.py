from __future__ import annotations

import json
import zipfile
import importlib
from pathlib import Path

from scan2bim.db import one
from scan2bim.job_tasks import execute_ingest_task

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
