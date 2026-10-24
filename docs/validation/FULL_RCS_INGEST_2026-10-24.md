# Full-resolution FARO RCS import acceptance run

Date: 2026-10-24  
Result: **PASS for both supplied RCS files imported separately at full resolution. Stage 2 remains open.**

## Source and isolation

- Source: `C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\1.rcs`
- Source size: 7,196,593,757 bytes
- SHA-256 before and after the run: `315edab40b6a92eb36c1d01454355465c6ae69872b0870f067c481cff188e63a`
- Source modification timestamp (`mtime_ns`) before and after: `1791897939956361000`
- Reader: installed Autodesk ReCap `AdskRcExport.dll`, isolated in a child process
- API/database: separate local API on port 8012 with data under ignored `data/validation/full_rcs_stage2/`; the production API and project database were not used for this run.
- Validation cloud: `56d2366c3ad440a99796a4fe7d6671c4`; validation project: `888d2126a670446ca7dd36fc0399efb2`.

Second source: `C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\2.rcs`, 13,906,332,111 bytes, `mtime_ns = 1792142068232257900`; SHA-256 before/after: `784c2235541c89fbf78e02e28af8756a1040d46ff18111df3581b9b6b75b3792`. It was imported into the same isolated project as its own cloud `8c6e31792fb942e2ba21c5433734f179`, retaining its own source path, name and fingerprint.

## Verified result

- API job ended `succeeded`; cloud ended `ready`.
- `point_count = ingested_count = source_point_count = stored_point_count = 297,873,927`.
- `decimated = false`, `dropped_non_finite = 0`, and RGB is present.
- Reopened memory-mapped arrays: `positions.npy` is `(297873927, 3)` `float32`; `colors.npy` is `(297873927, 3)` `uint8`.
- A complete chunked scan of the positions array found only finite coordinates.
- File sizes: positions 3,574,487,252 bytes; colors 893,621,909 bytes; preview 37,500,000 bytes; metadata 1,326 bytes.
- Cloud metadata records `source_unchanged = true`; an independent SHA-256 after finalization matched the source identity.
- After shutting down and restarting the isolated API with the same data directory, `/health` returned `ok` and the cloud reopened as `ready` with the same full point count, decimation flag, and source checksum.

The second source also completed with `point_count = ingested_count = 574,367,742`, `decimated = false`, `dropped_non_finite = 0`, and RGB present. Reopened arrays are `positions.npy` `(574367742, 3)` `float32` (6,892,413,032 bytes) and `colors.npy` `(574367742, 3)` `uint8` (1,723,103,354 bytes); preview is 37,500,000 bytes and metadata 1,329 bytes. A complete chunked coordinate scan found only finite values. Independent hashes for both source files matched their recorded identities. After a second API restart, both distinct cloud IDs reopened as `ready` with their respective counts and checksums.

## Recovery and limits

The first attempt stopped at 87,250,000 points because Windows returned `WinError 5` while atomically replacing `stream.json`. The prior committed checkpoint and raw stream remained intact. Checkpoint replacement now retries transient `PermissionError`s up to five times. A focused smoke check injected two temporary locks and confirmed the third replacement succeeded; the full import was then resumed and completed. The focused pytest module could not start in this environment because pytest was denied access to its temporary directory (`WinError 5`); the checkpoint retry smoke and the full API import run were executed directly instead.

The two full imports completed without an out-of-memory failure, and the importer's disk-reserve guard passed before allocating each final dataset. However, a continuous peak-RAM trace was not collected, and the two `.rcs` source filenames are not proof of native FARO station IDs or complete FLS/RCP project metadata. This run also does not prove recovery from user cancellation during the full route, registration accuracy or a ReCap RCP round trip. Those remain acceptance work; the two separate RCS source records alone do not close Stage 2.

## Linked single-node ReCap project follow-up — 2026-10-24

The supplied `10.rcp` is a ZIP containing one XML manifest and one `VoxelTreeRunTime` node (`10`). The manifest declares 295,836,062 points; it references `C:\Users\maxim\Desktop\ФОТО ЛУГАНСК\10 Support\10.rcs`, declares RGB, intensity and normals, and stores translation `[-9.47617950106483, 42.9205067460918, 5.89918721754716]`, zero rotation, unit scale and `Registered=0`. The bounded parser resolved the linked source without extracting or writing the RCP.

The linked `10.rcs` was imported separately, at full resolution, in the isolated project: **295,591,803** points, RGB retained, zero non-finite drops, no decimation, positions `(295591803, 3)` float32 and colors `(295591803, 3)` uint8. Source size was 7,130,808,277 bytes; SHA-256 before/after was `a11497ab0e4649e18480a31eceb00e8552051ff2209f1ca031c2be5b1f693a4a`. The ReCap manifest count is **244,259 points (0.0825%) higher** than the native reader count; no cause has been proven, so completeness against the project declaration is not accepted.

An isolated TestClient route smoke on the real RCP returned HTTP 200, resolved the linked RCS as the cloud's `source_format=rcs`, and exposed node metadata. That smoke replaced job submission with a no-op; it proves the RCP route resolution/metadata contract, not a second full import. Three parser regression functions, real path resolution, and Python compilation passed in direct checks. Automated pytest did not pass in this environment: fixture setup/teardown hit Windows `WinError 5` around pytest temporary directories.

The API currently accepts single-node RCP projects only. RCP scan transforms are preserved as provenance and explicitly marked `transform_applied=false`; they are not applied until the coordinate convention is independently checked. Multi-node station import, resolving the point-count mismatch, transform application, measured peak RAM, and cancellation/resume remain open. The aggregate three separate RCS clouds contain 1,167,833,472 points; they are not presented as one registered/stiched cloud.

## Recorded node-10 extent consistency follow-up — 2026-10-24

The full linked-RCS extents recorded in the isolated validation database were compared with the axis-aligned `AssetBoundingBox` values from the earlier real `10.rcp` route check. Maximum difference across six box faces is 0.0003724746 raw coordinate units, below the 0.001 metadata-consistency epsilon. This is consistent with the linked RCS already occupying the RCP asset-bounds frame, so the application now records `do_not_apply_for_this_node` for this node and leaves the coordinates untouched.

This follow-up did not reopen the original RCP file; it used the manifest values preserved in the earlier route report and the full RCS extents stored in the isolated DB. The node is `Registered=0`; unit conversion is not inferred. Bounds agreement does not prove pointwise equivalence, survey tolerance, transformed/rotated assets, or other RCP projects. The 244,259-point manifest/read discrepancy remains unexplained. See [`RCP_COORDINATE_BOUNDS_AUDIT_2026-10-24.json`](RCP_COORDINATE_BOUNDS_AUDIT_2026-10-24.json).

The new application callback was exercised through an isolated TestClient route using a synthetic single-node RCP, with ingestion mocked to report the already recorded full-resolution RCS bounds. The cloud became `ready`; metadata persisted `rcs_bounds_match_rcp_asset_bounds`, `do_not_apply_for_this_node`, and the exact 244,259 declared-minus-imported count difference. This checks route wiring and metadata persistence, not another native import.
