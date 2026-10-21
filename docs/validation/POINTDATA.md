# Point access and spatial-index validation

Status updated 22 October 2026. This validation uses synthetic fixtures and previously prepared derived arrays only. It does not open or modify the original FARO `1.rcs`.

## Contract

`NpyPointProvider` and `IndexedPointProvider` expose finite world-space coordinates in metres and preserve zero-based rows from the stored derived array as `source_indices`. Local float arrays are promoted to float64 before adding the survey origin. Point queries use inclusive axis-aligned world bounds; callers may then apply an exact rotated local-frame mask. The index accelerates the broad-phase query and is not allowed to change returned coordinates or row identity.

The row index stores source row numbers and offsets; it does not duplicate XYZ/RGB. It fingerprints source path/size/mtime, origin, color source and point count. An index without a final manifest, with changed source metadata, or with malformed offsets is rejected. It skips non-finite stored points while keeping their original row IDs stable.

## Reproducible checks

- `backend/tests/test_pointdata.py`: 19 tests passed on the latest targeted run. The tests cover inclusive cell-boundary queries, a rotated 27° narrow footprint, empty and long-extent queries, RGB correspondence, float64 world transforms, source-row identity, stale/corrupt index detection and indexed section extraction.
- `backend/tests/test_structural_dxf.py` and `backend/tests/test_structural_drawings.py`: 25 tests passed in the last separate run.
- Full backend suite after the latest pointdata regressions: 241 tests collected; full run completed with exit code 0 (one existing Starlette/httpx deprecation warning).
- Current implementation evidence is in `backend/scan2bim/pointdata/provider.py`, `backend/scan2bim/pointdata/index.py`, and `backend/tests/test_pointdata.py`.

## Derived 40-million-point benchmark

The existing benchmark indexed 40,000,000 stored rows in 14.047 seconds. The `rows.npy` index occupied about 320 MB and contained no copied XYZ/RGB. For ROI A (4,004,372 rows), the first recorded linear/indexed reads took 3.8573/1.4111 seconds and returned identical rows. A later real-cloud thin-slab query selected 322,763 slab points and 80,387 region points; sorted UV values matched exactly, but the linear/indexed times were 0.451/3.580 seconds.

Therefore the index remains explicit opt-in for section geometry; it is not enabled automatically. A query planner or another storage layout is required before the index can be selected by default for broad, thin workloads.

## Open acceptance gates

The baseline reports 297,873,927 points in the working derived cloud, of which 40,000,000 are currently stored. A complete read-only route for the full local scan has not been accepted. Recount, omission and quantization checks, full-route runtime/RAM/disk, cancellation/restart, idempotent finalization, canonical format choice (NPY/index versus COPC/E57), backup/restore and a before/after original-RCS metadata check remain open. The nominal 6,000 mm column pitch is not a point-query tolerance or a coordinate snap.
