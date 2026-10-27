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

At the time of this original follow-up the API accepted single-node RCP projects only. A later implementation added a multi-node batch route, covered by synthetic worker/API tests. The new route was subsequently smoke-tested on this real one-node `10.rcp` in an isolated database and resolved node `10` to the linked source without running an ingest job. Multi-node import against a real project, resolving the point-count mismatch, transform application, measured peak RAM, and cancellation/resume through the native reader remain open. RCP scan transforms are preserved as provenance and explicitly marked `transform_applied=false`; they are not applied until the coordinate convention is independently checked. The aggregate three separate RCS clouds contain 1,167,833,472 points; they are not presented as one registered/stitched cloud.

## Recorded node-10 extent consistency follow-up — 2026-10-24

The full linked-RCS extents recorded in the isolated validation database were compared with the axis-aligned `AssetBoundingBox` values from the earlier real `10.rcp` route check. Maximum difference across six box faces is 0.0003724746 raw coordinate units, below the 0.001 metadata-consistency epsilon. This is consistent with the linked RCS already occupying the RCP asset-bounds frame, so the application now records `do_not_apply_for_this_node` for this node and leaves the coordinates untouched.

This follow-up did not reopen the original RCP file; it used the manifest values preserved in the earlier route report and the full RCS extents stored in the isolated DB. The node is `Registered=0`; unit conversion is not inferred. Bounds agreement does not prove pointwise equivalence, survey tolerance, transformed/rotated assets, or other RCP projects. The 244,259-point manifest/read discrepancy remains unexplained. See [`RCP_COORDINATE_BOUNDS_AUDIT_2026-10-24.json`](RCP_COORDINATE_BOUNDS_AUDIT_2026-10-24.json).

The new application callback was exercised through an isolated TestClient route using a synthetic single-node RCP, with ingestion mocked to report the already recorded full-resolution RCS bounds. The cloud became `ready`; metadata persisted `rcs_bounds_match_rcp_asset_bounds`, `do_not_apply_for_this_node`, and the exact 244,259 declared-minus-imported count difference. This checks route wiring and metadata persistence, not another native import.


## Live full-resolution import in the main Studio project — 2026-10-24

The production API imported the original `1.rcs` read-only into `workshop_project` as cloud `1c8f6d596518476b8b74055d5414609b`. Job `2b793863c4ae4b34b174603e8a5ad29c` ended `succeeded`; the cloud reopened through the project API as `ready`. Source, ingested, and stored counts all equal **297,873,927**. The arrays reopened as `positions.npy` `(297873927, 3)` float32 and `colors.npy` `(297873927, 3)` uint8. An independent chunked scan verified every XYZ coordinate is finite; metadata records RGB, `decimated=false`, `dropped_non_finite=0`, and `source_unchanged=true`. Source SHA-256 is `315edab40b6a92eb36c1d01454355465c6ae69872b0870f067c481cff188e63a`; the recorded source path, size (7,196,593,757 bytes), and modification time match the original identity.

A two-second process monitor collected 437 samples from 78.25M source points (26.27% of the scan) through terminal success. It recorded an observed working-set peak of **12,612,169,728 bytes (12.61 GB)** and a private-memory peak of **1,797,079,040 bytes** while writing full-resolution arrays. The monitor began after native parsing had started, so this is not a continuous resource trace from job submission. During finalization, free disk space temporarily approached 2.0 GB and recovered to about 10.0 GB after cleanup of intermediate files. Full JSON evidence: [`FULL_RCS_INGEST_LIVE_STUDIO_2026-10-24.json`](FULL_RCS_INGEST_LIVE_STUDIO_2026-10-24.json).

This live run verifies one full-resolution RCS source in the main project and confirms that the existing streaming reader completes on the target application. It does not close Stage 2: a real multi-node FARO RCP, the 244,259-point `10.rcp` count mismatch, resource tracing from job submission, native-reader cancellation/restart, and FARO/ReCap round-trip remain open.


## Этап 2 — настоящий одноузловой ReCap RCP в основном проекте, 24 октября 2026

Файл `10.rcp` прошёл production batch-route preflight: один узел `10`, связанный источник `10 Support\10.rcs` доступен, станция создана отдельно с сохранёнными ProjectId, node ID, объявленным числом точек и translation/rotation/scale; `transform_applied=false`. Для безопасного live smoke использован лимит 5 млн, поэтому готовое облако содержит равномерную reservoir-выборку 5 000 000 из 295 591 803 точек и RGB (`decimated=true`). Независимо проверены формы `(5000000, 3)` float32/uint8 и конечность всех сохранённых XYZ. В манифесте объявлено 295 836 062 точек — на 244 259 больше reader count; причина не установлена. SHA-256 исходного RCS — `a11497ab0e4649e18480a31eceb00e8552051ff2209f1ca031c2be5b1f693a4a`, RCP — `3d3a00acd971b42bee11a8fb73f43356ea162d10855edefde84aaa83d27918fd`; размеры/mtime совпали после операции. Evidence: [`LIVE_RCP_STATION_10_2026-10-24.json`](LIVE_RCP_STATION_10_2026-10-24.json).

Первый batch job выявил две ошибки реализации: limited-mode subprocess пытался писать в запрещённый системный `%TEMP%`, а завершение batch с ошибкой станции всё равно помечало job как `succeeded`. Reader scratch перенесён в DATA_DIR с явной очисткой; native failure detail больше не теряется за общей подсказкой; частичный batch теперь становится `failed`, сохраняя per-station result и error event. Целевые тест-функции scratch placement, cancellation cleanup, error-detail preservation и partial job state прошли напрямую; `py_compile` прошёл. Из-за sandbox отказа pytest при очистке basetemp стандартный запуск pytest не засчитывался. Повтор импорта той же станции через resume завершился `succeeded`, облако `ready`; trace 177 замеров/2 секунды: observed peak working set 438 886 400 байт, private memory 1 957 453 824 байт.

Это подтверждает одну реальную RCP станцию в ограниченном режиме и исправляет выявленные ошибки. Stage 2 остаётся открыт для multi-node FARO RCP, причины расхождения count, полного RCP full-resolution cancellation/restart и ReCap round-trip. Приём остаётся 3/12.


## Live two-station batch smoke via production API

A synthetic two-node RCP manifest linked the original read-only `1.rcs` and `2.rcs` sources to the production `rcp/import-path` route. In 572 seconds the sequential batch job succeeded with 2/2 stations ready and zero failures. Each station stores a separate one-million-point RGB sample after scanning the full source count: 297,873,927 and 574,367,742. Independently reopened XYZ arrays are finite, float32; RGB arrays are uint8. Both source hashes, sizes and mtimes match the prior source audit. The validation project and its derived clouds remain available in Studio for review. This is a live batch-route check over two real FARO RCS files, not a native multi-node ReCap RCP, so Stage 2 remains open. Evidence: [`LIVE_TWO_SOURCE_RCP_BATCH_2026-10-24.json`](LIVE_TWO_SOURCE_RCP_BATCH_2026-10-24.json).


## Live cancellation and resume smoke

The sampled production import of `1.rcs` was cancelled after 10 million source points. The job and cloud reached `cancelled` with zero points reported ingested. Resuming the same cloud started a new job, completed a full source pass, and left the derived cloud `ready` with a 1,000,000-point RGB sample. Independently reopened arrays had finite XYZ. Source identity still matched SHA-256, size and mtime. This verifies sampled-route cancellation and resume; it does not establish full-resolution cancellation/restart. Full evidence: [`LIVE_RCS_CANCEL_RESUME_2026-10-24.json`](LIVE_RCS_CANCEL_RESUME_2026-10-24.json).
