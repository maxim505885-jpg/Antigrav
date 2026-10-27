# Headless worker

SCAN can run long point-cloud operations in a separate process on the same machine. The API and worker must share the same `S2B_DATA_DIR` (and therefore the same SQLite database and project files).

Supported persistent task types:

- Cloud ingestion and RCP batch ingestion
- Structural recognition jobs
- Station panorama rendering
- Cloud cleanup into a derived artifact
- Cloud export to E57, LAS, LAZ, PLY, or XYZ

## Start

The desktop launcher starts the API and its durable same-host worker by default, passing the same resolved `S2B_DATA_DIR` to both processes; it stops both when its native application window closes. Set `S2B_INGEST_MODE=local` before launching to opt into the in-process job mode. If the API is already running, the launcher does not start a worker against an unverified data root; start the worker manually with the exact same data path as that API.

Set the same data path for both processes, enable worker mode for the API, then start one or more worker processes from the backend environment:

```powershell
$env:S2B_DATA_DIR = 'C:\ScanStudio\data'
$env:S2B_INGEST_MODE = 'worker'
$env:PYTHONPATH = 'backend'
python backend\run.py --host 127.0.0.1 --port 8000
```

In another terminal, set the same data path and run the worker loop:

```powershell
$env:S2B_DATA_DIR = 'C:\ScanStudio\data'
$env:S2B_INGEST_MODE = 'worker'
$env:PYTHONPATH = 'backend'
python -m scan2bim.worker
```

To claim and process at most one queued task, use `python -m scan2bim.worker --once`. The loop polls the SQLite queue every two seconds by default; `--poll-seconds N` changes the delay. Worker jobs use expiring leases, heartbeat renewal, persisted cancellation, and reclaim after a worker stops.

## Current boundaries

The SQLite queue is for processes sharing one host and one data directory. It is not a multi-host queue and must not be placed on a network filesystem as a substitute for a broker. Other analysis jobs still run in the API process. For multiple machines, SCAN needs a shared transactional queue, shared artifact storage, and deployment-level locking/monitoring. CUDA execution has not been accepted on the current workstation.
