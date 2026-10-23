# Point access and spatial-index validation

Status updated 23 October 2026. This validation uses synthetic fixtures and previously prepared derived arrays only. It does not open or modify the original FARO `1.rcs`.

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

Therefore the index remains explicit opt-in for section geometry; it is not enabled automatically for all clouds. When a caller provides an index, the section reader now estimates broad-phase candidate rows from the grid offsets and uses the index only when that estimate is at most 20% of stored rows. Broader requests stream linearly.

## Full stored-array index profile — 43.5 million derived points

On 23 October 2026, the default 5 m grid index was built over all 43,500,000 rows in `data/projects/workshop_project/clouds/workshop_cloud/positions.npy` (float32 XYZ, 522,000,128 bytes). All rows were finite. Build time was 16.457 s; the completed index occupied 348,160,792 bytes. This profile compares query semantics and speed on the available derived array only; the registration manifest is still unverified and this is not the protected FARO `1.rcs`.

For each query, the full-length source-row membership masks from linear and indexed reads matched exactly. Every returned XYZ was also compared exactly with its referenced source NPY row, and both readers were checked against the inclusive query bounds.

| Query | Rows returned | Linear | Indexed | Result |
|---|---:|---:|---:|---|
| Existing pilot ROI bounds `[-65,35,-5.27]..[-45,55,10.69]` m | 716 | 3.330 s | 0.013 s | 266× faster |
| Local column neighborhood | 0 | 3.530 s | 0.002 s | empty in this derived coordinate frame |
| Thin beam slab | 0 | 3.285 s | 0.003 s | empty in this derived coordinate frame |
| Broad workshop level | 12,749,244 | 4.345 s | 4.435 s | effectively equal; indexed 2% slower |
| Whole derived-cloud bounds | 43,500,000 | 6.268 s | 10.261 s | indexed 1.64× slower |

The ROI coordinates select far fewer rows here than in the earlier 40-million-point pilot; this is not evidence that these locations contain the expected workshop structures. The coordinate frame and FARO station alignment have not been accepted. No RGB comparison was made in the query benchmark because its NPY provider was instantiated without a color array. The original full argsort build measured 1,472,552,960 bytes (1,404.3 MiB) peak working set; the chunk-bucket rebuild reduced this to 984,432,640 bytes (938.8 MiB), still measured on the 43.5M derived rows and including file-backed pages. Neither measurement establishes resource use for the full 297.9M-point source. JSON evidence is `docs/validation/A2_INDEX_CHUNKED_PROFILE_2026-10-23.json`.

Keep the index opt-in. The 20% candidate-row policy selected the index for the small ROI (72,340 candidates; 0.17%) and empty local query (94 candidates), and selected linear reads for the broad level (22,688,507 candidates; 52.16%) and whole cloud. An indexed horizontal section over the full cloud also matched the linear section exactly: 588 slab points at Z=2.71 m with 0.2 m thickness, even when the test metadata bbox was deliberately too small. Section queries use conservative index bounds so stale bbox metadata does not make indexed and linear reads disagree. This is a performance routing policy, not a geometry or registration acceptance test.

## Chunked full-scale index rebuild — 23 October 2026

The full 43.5M-row index builder was changed to count cells in one source pass, then stable-sort cell IDs within 500,000-row chunks and append source row IDs to a file-backed bucket array. It no longer allocates full-cloud key and argsort arrays. Per-cell source row order is preserved across chunks, including when non-finite rows are skipped. The focused regression was extended for stable row order. Pytest 9.1.1 is installed, but the targeted suite could not complete because the Windows sandbox denied pytest temporary-directory traversal/cleanup with WinError 5; the synthetic executable smoke check and complete derived-cloud comparison were run directly.

The new build completed in 16.942 s and produced the same 348,160,792-byte index for all 43,500,000 finite rows. Windows `PeakWorkingSet64` measured 984,432,640 bytes (938.8 MiB), 33.2% below the previous argsort build's 1,472,552,960 bytes (1,404.3 MiB). This working-set figure includes file-backed NPY pages and is not a measure of private committed memory. Five full-cloud query comparisons again matched source row masks and exact XYZ, with the same planner choices. The source array size and modification time were unchanged. Detailed measurements are in `docs/validation/A2_INDEX_CHUNKED_PROFILE_2026-10-23.json`.

## Open acceptance gates

The baseline reports 297,873,927 points in the working derived cloud, of which 40,000,000 were stored in the earlier pilot; the available derived PLY contains 43,500,000 rows. A complete read-only route for the full local scan has not been accepted. Recount/omission/quantization of the complete source, full-route RAM/disk, idempotent finalization, canonical format choice (NPY/index versus COPC/E57), backup/restore, full native-RCS cancellation/restart and a before/after original-RCS metadata check remain open. Checkpoint cancellation after 500,000 committed rows and fresh-process restart were verified for the derived 43.5M PLY only. The nominal 6,000 mm column pitch is not a point-query tolerance or a coordinate snap.
