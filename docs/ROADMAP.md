# ROADMAP — SCAN: Intelligent Point Cloud Studio

Last Updated: October 24, 2026
Status: Active Industrial Pilot Development  
Current Focus: Stage 6 — AI / Geometric Recognition, with point-cloud streaming and source provenance continuing in parallel.

This document defines the 12 core development phases of SCAN according to the product Master Prompt specifications.

---

## Stage Summary Status Matrix

| Phase | Title | Status | Passing Tests | Primary Deliverables |
|---|---|:---:|:---:|---|
| **Stage 1** | Architecture & Base Services | **DONE** | 65 | FastAPI Gateway, Async Job Engine, SQLite Schemas, Base Contracts |
| **Stage 2** | Import & Storage | **IN PROGRESS** | 42 focused tests + three full-resolution RCS runs (1.168B points combined); RCP route/parser and bounds-comparison checks | Three source RCS files reopen separately with source provenance; RCP declared-count mismatch, multi-node import, measured peak resources and cancellation/restart acceptance remain open |
| **Stage 3** | Professional 3D Visualization | **IN PROGRESS** | 55 (FE) | API-backed UI, adaptive camera-distance LOD, synthetic 1M-point rendering, and an in-view FPS meter are implemented; target-workstation 60 FPS acceptance remains open |
| **Stage 4** | Multi-Station Registration | **TESTING** | 34 synthetic/contract tests | 2D FFT angle search, Point-to-Plane ICP and Kabsch; independent multi-station FARO RMSE < 10 mm is not measured |
| **Stage 5** | Cleaning & Preparation | **DONE** | 18 | Исходник неизменен по SHA-256; сечение повторно читается как сохранённый audit snapshot; очистка создаёт скачиваемую производную копию |
| **Stage 6** | AI / Geometric Recognition | **IN PROGRESS** | 117 related BE tests | Review-only structural candidates and generic IoU implementation; independent physical labels and field accuracy are missing |
| **Stage 7** | Learning & Annotation Pipeline | **IN PROGRESS** | 40 focused tests | Review/undo, revision-safe storage, leakage-safe split, and synthetic-data invalidation; invalidated synthetic rows are excluded from independent annotation; independently labeled pilot elements and real holdout metrics are missing |
| **Stage 8** | Parametric 3D Geometry | **IN PROGRESS** | 86 focused tests | Synthetic section fitting and review-only catalogue candidates; real FARO sections, engineering limits and field accuracy remain unverified |
| **Stage 9** | Automated SPDS / CAD Drafting | **TESTING** | 72 generated-sheet tests | Five-sheet DXF/PDF album is generated; opening, editing, Cyrillic text, line weights and printing in AutoCAD 2026 are unverified |
| **Stage 10** | Export & Interoperability | **TESTING** | 61 format/contract tests + synthetic DeCap smoke test | DWG/IFC and point-cloud interchange exist; native RCP package generation passes on synthetic XYZ; AutoCAD 2026/Revit 2027 acceptance and FARO/ReCap round-trip remain unverified |
| **Stage 11** | Enterprise, GPU & Big Data | **IN PROGRESS** | 34 focused tests | Chunked CPU/GPU paths exist; CUDA-device run and representative 100M/billion-point performance acceptance remain open |
| **Stage 12** | Release Engineering & Acceptance | **IN PROGRESS** | 15 focused tests | Installer and checks exist; full regression, supported-workstation installation and user acceptance remain open |

Test counts above are focused test evidence, not proof that a whole stage meets acceptance. Mark a stage DONE only after its listed acceptance criteria have passed. Stages 1 and 5 are closed (2/12); all other stages remain open, partial, or under testing. Current Stage 6 labeling target: registered FARO RCS `2621e5a320df49949d04aa1b7399539e` has 267 pending live columns. The 16-column pilot JSON references the same source cloud, but its candidate IDs are from a separate recognition snapshot and are not automatically mapped.

---

## Detailed Stage Breakdown

### Stage 1 — Architecture & Core Foundation
- **Goal**: Unified modular framework, typed REST API, asynchronous jobs, persistence, and audit logging.
- **Completed**:
  - FastAPI application structure (`backend/scan2bim/api`).
  - Asynchronous background worker threads with cancellation and progress reporting.
  - SQLite database migration and revision management.
- **Criteria**: All endpoints pass OpenAPI schema validation and route tests.
- **Status**: **DONE**

### Stage 2 — Ingestion & Spatial Indexing
- **Goal**: Ingest point clouds of any size while keeping raw files strictly read-only.
- **Completed**:
  - Memory-mapped float32 position tables (`positions.npy`) with sub-second random access.
  - Morton-ordered spatial chunking and bounding boxes.
  - Tested ingestion routes for several interchange formats and a large derived PLY.
  - Full-resolution read-only imports of the two supplied FARO source files completed as separate clouds in an isolated database: `1.rcs` has 297,873,927 points and `2.rcs` has 574,367,742 points. Both retained RGB, had no decimation or non-finite coordinates, and reopened with exact float32 position and uint8 color shapes. Independent post-import SHA-256, sizes, and modification timestamps match the recorded source identities. A transient Windows `WinError 5` during checkpoint replacement was fixed with bounded retries. Evidence: [`FULL_RCS_INGEST_2026-10-24.md`](validation/FULL_RCS_INGEST_2026-10-24.md).
  - Read and routed the supplied single-node `10.rcp` manifest to its linked FARO `10.rcs`; the actual API route smoke returned the resolved RCS as a separate cloud and preserved the RCP project/node identity, declared count, source hash, and translation/rotation/scale in metadata. Three full-resolution RCS clouds now account for 1,167,833,472 points in the isolated project; `10.rcs` itself has 295,591,803 finite RGB points. Evidence and mismatch are documented in [`FULL_RCS_INGEST_2026-10-24.md`](validation/FULL_RCS_INGEST_2026-10-24.md).
  - For node `10`, the preserved axis-aligned RCP `AssetBoundingBox` was compared against all points in the independently full-ingested linked RCS. The largest face difference is 0.0003725 raw coordinate units, within the 0.001 metadata-consistency epsilon. This supports not reapplying translation for this node only; it is not a pointwise, unit, engineering-tolerance, or general RCP transform validation. The comparison logic has direct regression checks. Evidence: [`RCP_COORDINATE_BOUNDS_AUDIT_2026-10-24.json`](validation/RCP_COORDINATE_BOUNDS_AUDIT_2026-10-24.json).
- **Open**: The 10.rcp manifest declares 295,836,062 points, 244,259 more than the linked RCS reader produced; the cause is unresolved. Direct import supports a one-node RCP only; multi-node projects need a station collection/import flow. FARO station identity outside project metadata, continuous peak RAM, and full-route cancellation/restart acceptance remain open. The node bounds check does not apply a transform, prove every point's coordinate mapping, or generalize to other scans. Original RCP/RCS sources remain read-only.
- **Criteria**: Ingest each supplied FARO station with metadata and provenance, without memory starvation, then reopen the project with station identity intact.
- **Status**: **IN PROGRESS**

### Stage 3 — 3D Visualization & Inspection
- **Goal**: High-performance interactive 3D viewport.
- **Completed**:
  - Three.js WebGL engine embedded in React with custom point cloud shaders.
  - Real-time 3D SPDS structural grid with circular axis bubbles.
  - View presets (all elements, structural skeleton only, columns/beams only).
  - The production entry point renders the API-backed `App`, replacing the static presentation prototype.
  - Viewer selects and streams a LOD level from camera distance, debounces camera changes, cancels stale requests, and retains the visible cloud while a new level loads. Browser smoke on a generated 1M-point cloud loaded levels 0 and 2 successfully.
  - Warm light-theme styles now load after the dark token sheet so application surfaces and text retain readable contrast.
  - Viewer shows FPS from completed WebGL render-loop frames in rolling one-second windows, so the target workstation can report its own navigation performance.
  - SCAN Studio now opens side-by-side RGB and height-Z views of the selected live cloud; changing projects reloads their cloud and candidate list and persists the project selection in the browser. Visual QA confirmed the registered FARO 1.rcs project and its 685 live candidates.
  - The user-provided SCAN Studio reference is integrated into the API-backed app: paired views are the primary workspace, review and annotation tools open on demand, and scene selectors expose only render modes supported by the viewer and source.
  - The graphite/orange toolbar actions are connected to project, import, view-save, measurement, recognition, DXF and IFC flows; the live 1.rcs cloud, candidate count, sampling status, and unknown RMSE/tolerance come from the API and are labelled truthfully.
  - Narrow-screen status and scene layout was checked at 375×812: scenes remain above the bottom dock, the full status fits without horizontal overflow, and unavailable layers report disabled rather than active.
- **Open**: Large-cloud level-of-detail and measured frame-time acceptance have not been demonstrated for the workshop pilot.
- **Criteria**: 60 FPS viewport navigation with 1M+ preview points, verified on the target workstation and representative cloud.
- **Status**: **IN PROGRESS**

### Stage 4 — Multi-Station Registration & Stitching
- **Goal**: Automated registration of overlapping point cloud stations without manual targets.
- **Completed**:
  - BEV structural feature extraction (density, height range, occupancy).
  - 2D FFT global angular search with 3D residual verification to break $180^\circ$ hall symmetry traps.
  - Point-to-plane ICP refinement with normal estimation and Kabsch fit for target pairs.
  - Pose-graph style error accumulation with loop-closure reporting in the stitched result.
- **Criteria**: Registration residual RMSE < 10.0 mm on industrial structures.
- **Not yet verified**: no independent multi-station ground truth was measured. The
  stitcher refuses incomplete FARO stations by design (that refusal is tested), so
  real registration accuracy — and therefore this criterion — is unconfirmed.
- **Status**: **TESTING**

### Stage 5 — Point Cloud Preparation & Filtering
- **Goal**: Non-destructive noise removal and slice extraction.
- **Completed**:
  - Adaptive 2D horizontal and vertical slice generation with user-defined thickness
    and resolution; slices are audit snapshots, the source cloud is never rewritten.
  - Statistical (SOR), radius (ROR) and voxel-downsample filters in
    `backend/scan2bim/processing/cleanup.py`; non-finite points are dropped first.
  - Derived cloud artefacts (`positions.npy`, optional `colors.npy`, `meta.json`)
    under `clouds/<id>/derived/<derived_id>/`; source positions are only read.
  - Optional local-PCA `normals.npy` and `curvature.npy` artefacts for derived clouds
    up to 500,000 points; unknown scanner viewpoint uses deterministic sign only.
  - `POST /clouds/{id}/cleanup` (background job), `GET /clouds/{id}/derived`,
    `GET /clouds/{id}/derived/{derived_id}/download?format=ply|xyz|npy`.
  - Cleanup panel in the export tab; PLY/XYZ downloads.
  - `test_cleanup.py`: 10 tests (filters, non-destructive source, PLY header, API).
- **Missing**: GPU acceleration; normal estimation is skipped above 500,000 derived
  points; cleanup is capped at 5 M points because the cKDTree would not fit a
  desktop's memory honestly.
- **Criteria**: Original point cloud coordinates remain byte-identical; slices stored as audit snapshots.
- **Acceptance verified**: The cleanup suite confirms the original `positions.npy` SHA-256 is identical after filtering; the API pipeline fetches the persisted section and confirms its result and point count match the original extraction. The same route continues through editable DXF export.
- **Verification**: `test_cleanup.py`, `test_geometry.py`, `test_api_pipeline.py` — 18 passed on October 23, 2026.
- **Status**: **DONE**

### Stage 6 — AI & Structural Element Recognition
- **Read-only crane-girder/column context audit (Oct 24, 2026)**: live `workshop_cloud` contains 376 column and 846 beam candidates; 99 have proposed role `crane_girder`, all 99 remain unreviewed. Each role proposal has `column_support_context=insufficient_context`; 75 have no detected column in the beam band, 14 have one, 7 have two, 2 have three and 1 has four. None has distinct detected columns near both beam endpoints. Of the 99, 38 have an ambiguous vertical profile and 61 have no profile evidence. The Studio shows these roles as hypotheses with context badges; this audit does not prove false positives because source occlusion and column-candidate misses are possible. Detail: [`CRANE_GIRDER_CONTEXT_AUDIT_2026-10-24.json`](validation/CRANE_GIRDER_CONTEXT_AUDIT_2026-10-24.json). Next acceptance evidence requires engineer-confirmed beam/column physical IDs, visibility-aware reference coverage and independent role metrics; Stage 6 remains open.
- **Crane-girder span-length audit (Oct 24, 2026)**: read-only review of those 99 proposals against the user-provided 6 m nominal longitudinal column step found 26 candidates longer than 6 m and 11 longer than a 9 m review threshold (1.5 × nominal step). The long-candidate maximum is 42.664 m; none of the 11 has detected columns at two distinct endpoints. This suggests possible merged or clipped candidates that need segmentation review, but length alone cannot prove a false merge or physical span. No element was split or changed. Detail: [`CRANE_GIRDER_SPAN_LENGTH_AUDIT_2026-10-24.json`](validation/CRANE_GIRDER_SPAN_LENGTH_AUDIT_2026-10-24.json). Do not turn the nominal pitch into an assumed grid or engineering limit.
- **Indexed live column-surface audit (Oct 24, 2026)**: verified the exact spatial-index provider on the current 40M-row derived FARO `1.rcs`: a sparse query returned identical sorted source row IDs to the linear reader (73,357 broad-phase rows, 10 exact slice rows; 0.015 s indexed vs 2.945 s linear in this run). Restarted the local API only after confirming there were no queued/running jobs; the live review-only surface endpoint then returned `spatial_index`, 379 crop points, `persisted=false`, and `source_geometry_modified=false` in 134 ms (previous service took 2.947 s for the same candidate). Read-only full audit of 267 oriented-box column candidates: all 267 used the index and completed, no API errors or mutation flags; 262 had no supported candidate face, 5 had partial faces, and all 267 vertical section-series states were `insufficient`. The per-candidate evidence is [`COLUMN_SURFACE_AUDIT_2026-10-24.json`](validation/COLUMN_SURFACE_AUDIT_2026-10-24.json). A targeted margin sweep on candidate `00933b157ee646c1831bacb5931050b7` found 0 points at margins 0.15/0.35 m, then 206 points but no supported faces at 0.60 m; association thresholds were not loosened. Studio annotation form and queue were verified in the browser and remained at 0/267; no physical labels were entered. This is a complete software/provenance/performance check, not evidence of field accuracy. Physical labels, independent holdout and tolerance remain open.
- **Fresh FARO `1.rcs` recognition (Oct 24, 2026)**: reran recognition on the registered 40M-point derived array after finding legacy candidates without frame/snapshot metadata. The job succeeded and produced 1,482 candidates (761 beams, 370 braces, 267 columns, 8 slabs, 24 trusses, 52 walls). It retained the three previously reviewed candidate statuses; 1,479 new/current candidates are explicitly `source_cloud_world` and bound to the current source snapshot. Live audit: 1,479 consistent, 0 mismatches, 3 legacy reviewed candidates unverifiable; a sampled beam query returned 100 points and consistent provenance. The original RCS remains 7,196,593,757 bytes. All 267 column annotations remain pending and physical accuracy is still `not_measured`; this improves evidence integrity, not Stage 6 acceptance.
- **Current live check (Oct 24, 2026)**: the latest `workshop_cloud` audit confirms 1,684/1,684 source-row bindings consistent with candidate geometry, zero mismatches and zero unverifiable records. All remain review-only and `accuracy_status=not_measured`; this verifies provenance, not physical detection accuracy. The cloud has 376 pending column references. The main Studio right panel displays the independent cross-section annotation form and now has a pending-column queue with a progress count. Row selection no longer opens the profile inspector; a separate button preserves that action. Browser verification selected a candidate, advanced to the next pending column, and confirmed the modal stays closed and no annotation is written. The separate 16-column pilot JSON has IDs that do not match any registered application cloud, so it is not presented as the same set. Frontend unit tests (98), TypeScript, and Vite production build (2,560 modules) pass. Stage 6 remains open pending real physical labels, holdout isolation and an agreed tolerance.
- **Live source-evidence pilot (Oct 24, 2026)**: the 43.5M-point `workshop_cloud` has 1,684 review-only candidates. A live read-only audit now reports 1,224 consistent row-ID-to-geometry bindings (846 beams, 378 braces), zero mismatches, and 460 unverifiable candidates without source IDs (376 columns, 58 walls, 4 slabs, 22 trusses); all 1,224 saved snapshots match the current point array. Member axes use a 0.55 m provenance corridor for the recognizer's section-slice support; this is explicitly not an engineering tolerance. Accuracy remains `not_measured`.
- **MEP safety and large-cloud limit (Oct 24, 2026)**: MEP recognition now samples at most 10,000 rows from stored positions and caps its review-only RANSAC pass at 3 segments × 30 iterations. On the actual stored 43.5M-row array, this bounded sample completed in 1.36 s and proposed no pipes; the synthetic geometry suite confirms the obsolete `CloudGeometry.positions` error is gone. A full repeat recognition reached 96% but was cancelled before persistence when worker memory reached 20.45 GB; the previous 1,684-candidate database remained unchanged. Large-cloud peak memory is still a release blocker for this phase and Stage 11.
- **Legacy evidence safety (Oct 24, 2026)**: aligned legacy point-row IDs are now reported as `unverifiable` when the candidate has no source-cloud snapshot; bbox overlap alone cannot prove row identity. Training-sample creation also rejects candidates without a snapshot, even when legacy rows happen to lie inside the bbox. Regressions first failed against the unsafe behavior and now pass. Combined provenance/learning/API suite: 47 passed; frontend tests and TypeScript passed. This closes the software safety check only; independent FARO labels, holdout isolation and an agreed tolerance remain open.
- **Cloud snapshot binding (Oct 24, 2026)**: new recognition candidates carry `source_cloud_snapshot` with cloud ID, exact stored-point-array SHA-256, row count, and coordinate origin. Recognition compares the snapshot before and after detection and refuses to persist candidates if source positions changed during the run. The point-evidence API detects a changed snapshot; the annotation panel tells the engineer to rerun recognition. SHA-256 is streamed from disk and cached by file size/mtime signature. Tests cover changed arrays, persistence, and full pipeline.
- **Provenance audit (Oct 24, 2026)**: a read-only audit of all 641 active `workshop_cloud_01` candidates found source-row/bbox mismatches in all 200 beam and 282 brace candidates (482 total); 159 candidates are unverifiable (87 columns, 58 walls, 4 slabs, and 10 trusses have no usable source-row evidence). These are candidate-evidence integrity failures, not element accuracy results. No geometry or source data was modified. The focused source-frame/beam-lineage suites passed (29 tests), and live GET returned explicit `mismatch`; the producer/serialization path for legacy IDs remains to be traced before these candidates can be used as point-level evidence.
- **Goal**: Automatic identification of structural building elements.
- **Completed**:
  - Review-only candidates for columns, crane beams, truss members, bracing, openings, and MEP pipe networks; observed geometry remains separate from inferred roles.
  - Source point-row provenance and evidence fields are retained for structural member proposals.
  - A generic 3D AABB IoU evaluator accepts an explicit reference set and performs one-to-one matching. Its synthetic tests verify the metric implementation only.
  - Default grid display now uses only the user-supplied 6 m longitudinal pitch. Rows, axes, and residuals remain unset until surveyed project control is provided; explicit topologies remain available for controlled tests.
  - The expert API and knowledge summary report only the confirmed 6 m nominal longitudinal pitch; hall dimensions, axes, transverse spans, elevations, and tolerances stay unknown unless separately supplied. Unsupported sample workshop dimensions and a default 87-column count were removed.
  - Crane-girder support context checks column height, beam-strip overlap, and distinct column footprints near both beam-axis endpoints. A pair of interior columns or a parallel row outside the strip is insufficient. The UI displays endpoint gaps and the heuristic search margin. This remains a review hypothesis and does not confirm a corbel, rail, or physical bearing.
  - The element table explicitly marks every recognizer-proposed structural role as `роль — гипотеза`, with a tooltip that says engineering review is pending. Multi-height beam/rail profiles and terminal connection plates remain ambiguous evidence; touching spans are preserved as separate proposals. A synthetic cylindrical duct lookalike remains review-only with no fitted profile or confirmed support.
  - The main Studio view now reads cloud coverage and processing state from API data. Unsupported scanner model, registration progress, RMSE charts, station positions and panorama claims were removed; the recognition action calls the real cloud API. Degenerate candidate bounds display as unknown or as an unmeasured centerline, never as a zero-sized section. Browser QA showed 641 review-only candidates, the live project point counts, and no console errors.
- The active candidate table now renders the existing uncertainty evidence per row: all 87 legacy grid-derived column axes show the known 6 m pitch without invented row/axis data, and every role with `role_status=proposed` carries a visible `роль — гипотеза` badge. Live browser inspection covered all 641 rows: 87 grid warnings, 176 proposed-role badges, no zero-sized bbox labels, and no console errors.
- Repeated column-section proposals use deterministic complete-link grouping: every pair in a type must agree within tolerance, preventing transitive chains from merging distinct sections. Proposal assignment also observes the configured section tolerance. A forward/reverse-order regression protects stable grouping.
- **Verification**: On October 24, the focused steel, frame detection, runway context, and beam-source suite passed (61 tests) using an external writable temp fixture (Windows sandbox ACL workaround). A broader column-type, beam/truss provenance, structural drawing/DXF/IFC, API pipeline, column type API, and model-contract suite also passed with code 0. Frontend `npm test` and TypeScript passed. A fresh six-setting type evaluation confirms 0 labeled/16 pending, with precision and recall `null` and engineering accuracy `not_assessed`. The latest production `npm run build` passed; these checks verify software behavior, not field accuracy.
- **Earlier unbounded MEP run (Oct 24, 2026)**: the first full-cloud repeat was cancelled at 96% after worker RSS reached 20.45 GB. This run predates bounded sampling and cooperative cancellation below; it wrote no candidates.
- **Latest verification (Oct 24, 2026)**: recognition completed on all 43,499,997 stored points and produced 1,684 review-only candidates. Truss envelopes now retain bounded, deterministic source-row evidence from the truss plane and final envelope bounds. Live audit reports 1,683 consistent bindings (846 beams, 378 braces, 375 columns, 22 trusses, 4 slabs, 58 walls), zero mismatches, and one unverifiable undersized column (136 × 47 mm) without point support inside its bbox; all candidates remain unreviewed and `accuracy_status=not_measured`. During periodic API RSS samples, the largest observed value was about 1.41 GB; this is not a continuous peak measurement. The new bounded-evidence unit test passed and `py_compile` passed. A broader five-file pytest attempt did not yield a valid suite result because the sandbox denied pytest temp-directory enumeration/cleanup; do not count it as passed. Stage 6 remains open pending physical FARO references, an independent holdout, an agreed engineering tolerance, and resolution of the undersized column evidence.
- The generic IoU evaluator now returns `null` for metrics with an empty denominator and for mean matched IoU when there are no matches. Synthetic regression tests cover empty references, empty detections, and the distinction between undefined recall and zero precision. This prevents unannotated pilot data from being presented as measured zero accuracy.
- Independent role labeling now covers all candidate classes, including beams, trusses, pipes and ducts. Labels are append-only, tied to the cloud and candidate geometry snapshot, require a reviewer and physical ID when labeled, and can be exported with the recognizer's geometry clearly marked as context. Regression coverage rejects duplicate physical IDs, stale geometry and invalidated synthetic rows.
- Latest annotation-module verification on October 24: focused backend annotation/API/OpenAPI/evaluation tests passed (50 tests); frontend unit tests and TypeScript passed. The annotation form is imported by the actual application entry tree (`main.tsx` → `StudioReferenceLayout.tsx`) and appears in the right drawer for a selected element. A fresh production build transformed 2,551 modules and includes the panel; main JS chunk is 524.86 kB after minification. Restarted API on port 8000 serves the new annotation route; live GET for `workshop_cloud_01` returned 641 pending candidates, zero reviewed labels, and undefined accuracy metrics as expected. Browser showed the panel with no JavaScript errors. No labels were submitted. The regression runner reported it could not remove its isolated temp directory after tests; the test results themselves passed. Stage 6 remains in progress pending physical FARO labels and independent accuracy acceptance.
- Latest UI review on October 24: the right-hand annotation panel now displays the selected candidate's recognizer class/role hypothesis, bbox dimensions, source, and score basis as read-only context while leaving all reference fields independent. A live browser check showed a 98% nominal-grid consensus explicitly labeled as not being a physical survey. The current cloud response contains 87 column candidates and 99 crane-girder role proposals among 641 candidates; these are proposal counts, not accuracy measurements. All frontend tests, TypeScript, and production build passed (2,552 modules; 527.78 kB app chunk), with no browser console errors. Stage 6 remains open pending independent FARO annotation and holdout evaluation.
- Independent detection-evaluation workflow added October 24: the annotation panel downloads a snapshot-bound JSON template and uploads or enters a manually assembled physical-reference set; the cloud API compares it with current candidates and counts unmatched physical references as false negatives. Volumetric candidates use 3D AABB IoU. A degenerate AABB with valid member centerline geometry is evaluated by minimum interval IoU across varying axes, with constant axes required inside the measured box; this separate score is never called volumetric IoU. Invalid candidates without evaluable geometry remain false positives. Reference coordinates are metres in cloud coordinates. Reports are not persisted or sent to training; API explicitly returns `holdout_status=not_verified`, because independence/leakage against model tuning is not yet enforced. Backend evaluator/API/OpenAPI suite: 24 passed; blank reviewer and physical IDs, duplicate IDs, invalid bounds and stale snapshots are rejected. Full frontend tests, TypeScript and production build passed (2,553 modules, 537.01 kB app chunk); live API OpenAPI exposes the route and browser displays the evaluation workflow without console errors. Stage 6 stays in progress until independently measured FARO references, holdout isolation, and accepted tolerances are verified.
- Direct physical-reference entry added October 24: reviewers can now add measured elements in the right panel, enter an independent class and physical ID, and type min/max X/Y/Z in metres; comma decimals are accepted. Client checks reject empty metadata, duplicate IDs, non-finite coordinates, and inverted/zero-size boxes. JSON upload remains available. Four reference-builder tests, full frontend test script and TypeScript passed; the production build passed (2,553 modules, 537.01 kB app chunk). Live browser showed and added/removed a blank measurement row with no console errors. This reduces reference-entry friction but adds no real labels; Stage 6 remains open pending FARO references, holdout isolation, and a user-approved tolerance.
- Candidate geometry audit and evaluator update, October 24: all 71/641 workshop candidates with zero-volume AABBs have finite non-zero `member` endpoints (67 braces, 4 beams). They are centerline proposals lacking cross-sectional thickness, not automatically false elements. The evaluator now compares their axis intervals with a physical reference box using a separate centerline extent IoU and exposes both score families distinctly; one-to-one assignment remains shared by class and prefers a volumetric match when both candidate representations map to the same physical element. RED/GREEN API/evaluator regression suite passed (25 tests), including matched/out-of-box lines and collision priority. No field references were submitted, so actual precision/recall remains unknown and Stage 6 remains open.
- Role evaluation added October 24: physical-reference rows may carry an independently measured role such as `crane_girder`, and the evaluator reports per-role precision/recall/F1 only after class-and-geometry matching. Unknown/unlabeled physical roles yield undefined role metrics; wrong and unassigned predictions remain visible in role counts. Synthetic unit and API cases cover correct and incorrect crane-girder predictions. No role references exist in the live workshop set, so live role accuracy remains unmeasured.
- Role/class compatibility added October 24: the backend rejects physically inconsistent pairs (for example `column` + `crane_girder`) for both independent annotations and uploaded recognition references. The UI filters choices to the selected physical class and clears a role if the class changes incompatibly. TDD: targeted API/schema/annotation tests 51 passed; full frontend tests, TypeScript and production build passed. This enforces annotation consistency but supplies no physical labels or accuracy evidence.
  - Invalidated synthetic ground-truth elements are now excluded by the shared live-element service, so normal candidate listings and downstream consumers cannot mistake archived fixture rows for real workshop detections. The audit rows remain in SQLite; the training selector continues to allow only engineer-reviewed examples.
- **Open**: The frozen column-type reference template has 16 candidates and all 16 remain `pending`; no independent physical role/type/section labels are present. Detection/classification recall, precision, and dimensional accuracy on the FARO pilot are not measured.
- **Coordinate-frame repair (October 24)**: Legacy `geometric` and `structural_grid` bboxes without frame metadata are read as cloud-local; new recognizer candidates carry `source_cloud_world` explicitly. The point endpoint now selects against the correct frame, returns points in world coordinates, and adds ±0.6 m context only on zero-width member axes. The 3D viewer places legacy local bboxes without subtracting cloud origin and translates explicitly world-framed geometry. API/unit regression and frame tests passed (56 related backend tests); frontend suite and TypeScript passed; production build passed. Independent FARO references, holdout and agreed tolerance are still absent.
- **Source-row integrity warning (October 24)**: `/elements/{id}/points` now compares bounded, declared `positions.npy` row IDs with the element's frame-aware bbox and reports `consistent`, `mismatch`, or `unverifiable`; it never trusts mismatched IDs to fabricate points. The right-hand annotation panel explains empty queries and mismatches while keeping the candidate unconfirmed. Live API check: a legacy column query returns 389 points; a beam candidate returns none and has 0/512 sampled source IDs inside its bbox (498 IDs are in the current array range), so the app flags its evidence for recheck. This is provenance health evidence, not a physical accuracy result. Related API/recognition suite: 41 passed; frontend suite and TypeScript passed; production build passed (2,556 modules, 543.22 kB app bundle, Vite >500 kB warning). Stage 6 remains open.
- **Verification update (October 24)**: A live audit found that `/elements` returned 747 rows although the independent review set had 641 candidates; the extra 106 were invalidated synthetic fixtures. A RED/GREEN API regression proves they are now excluded from ordinary element listings. Combined learning, annotation, API, steel, runway, and beam-lineage suite: 128 passed. No physical labels were added; the acceptance gap remains unchanged.
- **Legacy grid-claim repair (October 24)**: TDD migration keeps the 87 `structural_grid` element IDs but converts them from `approved`/`measured` into `unreviewed`, inferred, uncalibrated axis hypotheses. It removes unsupported marks, rows, axes, section sizes, estimated point counts, and fabricated confidence; only the nominal 6 m pitch remains, with control grid explicitly missing. A pre-migration SQLite backup passed `PRAGMA integrity_check`; the live API still returns 641 candidates and 0 such rows with an unsupported approval/measurement claim. Migration unit tests: 2 passed; focused API/evaluation/export suite: 81 passed; frontend tests and TypeScript passed; production build passed (2,553 modules, 540.07 kB app chunk). This repair does not supply independent FARO labels, holdout, or a project tolerance, so Stage 6 remains open.
- The generic IoU evaluator now returns `null` for metrics with an empty denominator and for mean matched IoU when there are no matches. Synthetic regression tests cover empty references, empty detections, and the distinction between undefined recall and zero precision. This prevents unannotated pilot data from being presented as measured zero accuracy.
- **Criteria**: Candidates carry confidence and provenance; class/geometry performance is measured against independently reviewed real workshop elements held out from tuning. When physical references include independently assigned roles, role precision/recall is reported separately after one-to-one geometry-and-class association. Acceptance still requires field labels, a leakage-safe holdout and an agreed engineering tolerance.
- **Status**: **IN PROGRESS — CURRENT FOCUS**
- **Bulk source evidence audit (Oct 24, 2026)**: a read-only cloud endpoint and annotation-panel action now summarize each candidate's source-row/bbox and snapshot alignment, grouped by detected class. Live-data evaluation through FastAPI TestClient returned HTTP 200 for 641 candidates: 0 consistent, 482 mismatches, 159 unverifiable; `accuracy_status` remains `not_measured`. This is an evidence-integrity report, not a detection-accuracy claim. Contract/API tests pass; the repository-owned API process was restarted with no active jobs; live HTTP returned 200 and the same 641-candidate breakdown, grouped by class: 200 beam mismatches, 282 brace mismatches, and 159 unverifiable (87 columns, 58 walls, 4 slabs, 10 trusses).

- **Column type evidence (Oct 24, 2026)**: the live Studio now displays a point-measured section summary for the registered FARO project. Of 266 active columns, 33 have point-supported sections; at the provisional 5 mm / 1% comparison threshold there are zero repeated type groups. The remaining sections are not confirmed by point data. A diagnostic grouping sweep on bbox side lengths varies from 202 groups at 5 mm to 44 at 100 mm, showing that looser thresholds can manufacture apparent repeats; these are hypotheses, not physical labels or accuracy evidence. Do not accept a 3–4-type claim from this sweep. Labels, representative side coverage, independent holdout and the engineering tolerance remain open. Frontend tests and production build pass; Vite still warns that the app chunk exceeds 500 kB.

- **Fresh column-section audit and Studio integration (Oct 24, 2026)**: a read-only center-slice recheck of all 33 active candidates carrying a stored point-measured section status returned 28 `insufficient_points`, 5 `unknown`, and 0 `proposed` at their oriented-box center (200 mm slice, 4 mm fit distance, 200 mm margin). This is one level per member and does not prove the full-height section is absent; it does show the stored status is not a verified result for a fresh center slice. The same API and browser result for candidate `9a95dcc75b7741df838529f662a6315b` was `unknown`, 48 points, no supported faces. The primary Studio right panel now includes the read-only point-section fitter for the selected column, with Z, slice thickness, optional two known sides, and vertical face coverage. On the tested live column, vertical analysis read 1,249 points, found 2 planes/2 tracks but 0 supported faces out of 4, and reported `insufficient`; all four sides were unknown across nine sampled elevations. At Z=6.55 m, a focused fit found four surface traces within 0.6° of one another, 251–388 mm observed spans and 1.3–2.0 mm RMS, but no closed-section proposal; a diagnostic 685×72 mm candidate-box constraint conflicts with the observed face spans. The Studio now explicitly warns that parallel traces do not prove a rectangular column section. Production build (2,566 modules) and frontend tests pass; the app chunk is 611.32 kB and still needs code splitting. No candidate or source FARO file was changed.
### Stage 7 — Supervised Learning & Annotation
- **Goal**: Active learning loop from engineering feedback.
- **Completed**:
  - UI/API for engineer confirmation, rejection, or relabeling of candidate elements, with undo history.
  - Sample isolation by stable physical element ID to avoid revision leakage between train and holdout.
  - Reuse of reviewed column types guarded by source-cloud fingerprints.
  - Training and similarity search now accept only explicit `engineer` samples; invalidated, generated, and undone examples are excluded. Model versions marked `invalidated` cannot be activated, including with `force`.
  - Invalidated synthetic elements cannot be confirmed, split, merged, or submitted as training samples through the review APIs.
  - Column-type proposal generation also excludes rejected and invalidated elements when called directly, outside those APIs.
  - Independent column-reference annotation GET/save/export/history endpoints exclude invalidated synthetic ground-truth rows; regression coverage confirms they cannot be annotated, restored from visible history, or exported as references.
  - Independent element-role annotations cover all recognized classes, with versioned snapshots, reviewer identity, physical IDs, unknown/excluded decisions, immutable history and JSON export. Backend tests prove crane-girder labels remain separate from recognizer output and reject duplicate physical IDs and stale snapshots.
  - A labeled physical ID from the current independent annotation is now carried into engineer training samples. The train/holdout splitter joins both candidate revisions and aliases across scans by physical ID, including transitive aliases, so one physical object cannot appear on both sides. Legacy SQLite databases gain the nullable field additively.
  - Engineer training samples now also retain the SHA-256 identity of the exact source `positions.npy`. Sample creation rejects stale cloud snapshots and source row IDs outside the candidate bounds; review confirmation can remain recorded, but reports a warning and creates no training sample when evidence is stale. Legacy SQLite databases gain this nullable identity field additively.
  - The former 106-row synthetic workshop catalog is explicitly marked invalidated, inferred, and unmeasured; its old seed-and-train entry point now refuses to write samples or activate a model. Synthetic catalog generation remains available only as a test fixture.
  - Invalidated synthetic samples remain in SQLite for audit but are omitted from the ordinary `/samples` response; only explicit engineer samples reach training and similarity search.
  - The false 106-row synthetic workshop dataset, its engineer-labelled samples, and all four derived model versions were retained for audit but invalidated in the runtime database. A SQLite backup was saved before the change.
  - Synthetic profile fixtures support regression tests; they are not physical measurements and are not training labels.
- **Missing**: Independently labeled real workshop elements and a leakage-safe holdout evaluation on those labels. Code-level leakage guards are covered by focused tests, but no field holdout has been constructed or measured. A tolerance sweep of the existing decimated 40M-point 1.rcs derivative found only 33 candidates with point-measured sections on two axes; group counts vary with threshold and do not identify true physical types. The preserved synthetic records remain visible for audit and must never be treated as training evidence.
- **Criteria**: Feedback is reversible and persisted, and any reported model score is measured on independently labeled physical elements excluded from training.
- **Status**: **IN PROGRESS**
### Stage 8 — Parametric 3D Geometry Reconstruction
- **Goal**: Fit accurate CAD/BIM parametric primitives to detected points.
- **Completed technically**:
  - Oriented-box candidates and section-series fitting preserve source-point provenance and keep inferred sides explicit.
  - Welded I-profile and section-catalogue matches are review-only candidates; a catalogue match does not confirm the physical steel grade.
  - Existing 86 focused tests cover synthetic section fitting, APIs, point lineage and catalogue behavior.
- **Open**: No independent real FARO cross-sections have verified profile fitting or dimensions. The workshop engineering tolerance is unspecified, and the cited catalogue excerpt has not been checked against all current corrections.
- **Criteria**: Parametric bounds and measured sides are evaluated against independent physical measurements with project-approved tolerances; unknown or occluded geometry remains explicitly unknown.
- **Status**: **IN PROGRESS**
### Stage 9 — Automated SPDS / CAD Drafting
- **Goal**: Production-ready vector working drawings according to Russian SPDS standards.
- **Completed**:
  - **Sheet 01**: Column Layout Plan at el. 0.000 (M 1:200).
  - **Sheet 02**: Crane Runway & Girder Layout at el. +6.800 (M 1:200).
  - **Sheet 03**: Transverse Cross-Section 1-1 (M 1:100).
  - **Sheet 04**: Roof Truss & Bracing Layout (M 1:200).
  - **Sheet 05**: Executive geodetic deviation scheme — draft residuals only, without
    SP 70 tolerance acceptance (that block was reverted).
  - Standard title blocks (GOST 21.101-2020 Form 3), dimension chains, and axis tags.
- **Criteria**: All five sheets contain editable vector geometry with no raster placeholders; DXF/PDF opens with correct Cyrillic text, dimensions and line weights and can be edited and printed in AutoCAD 2026.
- **Not yet verified**: the sheets were not opened and accepted in AutoCAD 2026;
  Cyrillic text, line weights and printing remain unconfirmed.
- **Status**: **TESTING**

### Stage 10 — Export & Interoperability
- **Goal**: Seamless exchange with Autodesk AutoCAD, Revit, and ReCap.
- **Completed**:
  - Automated binary DWG compilation (AutoCAD 2018 / AC1032) via ODAFileConverter
    or accoreconsole.exe; without a converter the API returns an honest 409.
  - IFC4 export with `Pset_ScanToBIM` (class, confidence, measured/inferred, review
    status, geometry, dimensions); stairs → `IfcStair`, openings → `IfcOpeningElement`.
  - Multi-page combined PDF drawing albums.
  - Point-cloud interchange exports: E57, LAS/LAZ, PLY and XYZ, each read back
    through SCAN's reader and checked against the source coordinates. The API
    lists and downloads generated exports by a stable export ID.
  - Native `.RCP` generation through the locally installed Autodesk DeCap adapter;
    package validation requires a non-empty RCP, Support folder and linked non-empty
    RCS files. A synthetic XYZ smoke test completed successfully on October 24, 2026.
- **Criteria**: DWG opens and prints in AutoCAD 2026; IFC4 or the supported Revit workflow opens, retains element identity and can be reviewed in Revit 2027; a ReCap `.RCP` project built from source station data opens and permits scan movement/registration review. Each output is checked against the verified SCAN model.
- **Not yet verified**: DWG header `AC10` and IFC entity content are tested, but a
  full open-and-print acceptance in AutoCAD/Revit has not been performed. The
  DeCap smoke test used a derived synthetic XYZ grid, not the user's FARO RCS or
  separate scan stations; the resulting RCP has not yet been opened in the ReCap
  GUI or checked for independent scan movement and registration review.
- **Status**: **TESTING**

### Stage 11 — Enterprise, GPU & Big Data
- **Goal**: Process hundred-million to billion-point clouds efficiently.
- **Tasks**:
  - [x] Chunked spatial indexing with cancel/resume tokens.
  - [x] Memory profiling and leak prevention on massive point sets.
    - The bounded 43.5M-point recognition run used about 1.5 GB maximum sampled API-process RSS; this is not acceptance for 100M/billion-point loads.
  - [x] Exact CPU voxel grouping and centroid/color averaging for bounded derived chunks (8 focused tests pass).
  - [ ] Verify CUDA voxel reduction and CUDA normal estimation on compatible hardware.
  - [ ] Benchmark bounded/chunked processing on representative large clouds; no 100M/billion-point acceptance has been run.
  - [ ] Distributed worker pipeline for corporate headless processing.
- **Status**: **IN PROGRESS**

### Stage 12 — Release Engineering & Packaging
- **Goal**: One-click local deployment on Windows 11 with full self-diagnostic test suite.
- **Tasks**:
  - [x] Full regression test harness (`pytest backend/tests/`, `npm test`).
  - [ ] Desktop launcher exists (`desktop_app.py`), but the installer-referenced batch launcher is missing and the installed runtime path is unverified.
  - [x] Launcher and installer source paths now match the repository; user data routes to `%LOCALAPPDATA%` and is excluded from the installation. Release preflight validates files and built UI assets.
  - [ ] Produce a relocatable Python runtime: the bundled `.venv` still depends on Python 3.13 at the developer’s absolute path. Compile the Inno Setup package and verify installation on a clean Windows 11 machine.
  - [x] Automated end-to-end acceptance certification suite (ackend/tests/test_end_to_end_acceptance.py).
- **Status**: **IN PROGRESS**

---

## Master Prompt §20 — приёмочные критерии

Статусы: ПОДТВЕРЖДЕНО — есть тест/прогон; ЧАСТИЧНО — часть пути работает;
НЕ ПРОВЕРЕНО — код есть, приёмки не было; НЕ ВЫПОЛНЕНО — нет функции.

| # | Критерий | Статус | Основание |
|---|---|---|---|
| 1 | Импорт реального набора FARO | ЧАСТИЧНО | `1.rcs` 297 873 927 точек прочитан; FLS-файлы не читаются, RCS даёт единое облако без станций |
| 2 | Метаданные и станции | НЕ ВЫПОЛНЕНО | станции RCS/E57 в БД не разбираются |
| 3 | Авторегистрация нескольких сканов | НЕ ПРОВЕРЕНО | BEV + ICP + pose graph есть, на реальных станциях не запускалась |
| 4 | Ошибки регистрации на контроле | НЕ ПРОВЕРЕНО | независимого эталона нет |
| 5 | Ручная корректировка | ЧАСТИЧНО | элементы и границы правятся; позы станций — нет |
| 6 | Сохранение и просмотр панорам | НЕ ВЫПОЛНЕНО | модуля панорам нет |
| 7 | Стабильная обработка большого облака | ПОДТВЕРЖДЕНО | 297.9 млн точек, ingest 4 млн, превью 2.5 млн, отмена/возобновление |
| 8 | Распознавание конструкций | ЧАСТИЧНО | 9 классов на синтетике и эвристика на цехе; точность по эталону не измерена |
| 9 | Геометрическая точность элементов | НЕ ПРОВЕРЕНО | допуск не согласован, разметки нет |
| 10 | Редактируемая модель | ПОДТВЕРЖДЕНО | правки, подтверждение/отклонение, oriented box, IFC/JSON |
| 11 | Планы и разрезы | ЧАСТИЧНО | 5 листов СПДС (планы + разрез 1-1); фасадов нет |
| 12 | Размеры и отметки | ЧАСТИЧНО | размерные цепи и отметки есть; приёмка в AutoCAD не пройдена |
| 13 | Открытие CAD в AutoCAD | НЕ ПРОВЕРЕНО | DWG AC10 создаётся, файл в редакторе не открывался |
| 14 | Обмен с ReCap | ЧАСТИЧНО | SCAN формирует и проверяет нативный RCP через DeCap на синтетическом XYZ; импорт отдельных FARO-станций и GUI round-trip в ReCap не приняты |
| 15 | Восстановление после сбоя | ЧАСТИЧНО | отмена и прогресс задач; очередь в памяти, после рестарта не восстанавливается |
| 16 | Работа без интернета | ПОДТВЕРЖДЕНО | все зависимости локальные, платных API нет |
| 17 | Воспроизводимость | ЧАСТИЧНО | Hough с фиксированным зерном, тесты; полный детерминизм не доказан |
| 18 | Windows-установщик | НЕ ВЫПОЛНЕНО | есть скрипты запуска, инсталлятора нет |
| 19 | Безопасность доступа | ЧАСТИЧНО | один пользователь, опциональный статический ключ; ролей нет |
| 20 | Документирование ограничений | ПОДТВЕРЖДЕНО | `docs/PLAN.md` раздел 3 и этот файл |

Этап 6/7 — снимок облака в обучающих примерах, 24 октября 2026

Подтверждённый инженером пример теперь сохраняет `source_snapshot_id`, связанный с SHA-256, числом строк и origin исходного `positions.npy`. Перед созданием примера сервис проверяет, что массив не изменился и что сохранённые row IDs попадают в bounds кандидата; перед фиксацией crop проверка повторяется. Кандидат со stale snapshot или несовпадающими строками не попадает в обучение. Ручное подтверждение такого кандидата сохраняет решение инженера, но возвращает предупреждение и не создаёт sample; прямой запрос создания примера отвечает HTTP 409. SQLite миграция добавляет nullable колонку, сохраняя старые записи; API-схема sample отдаёт идентификатор снимка.

RED/GREEN и downstream набор `test_sample_provenance.py`, `test_learning_split.py`, `test_feedback_undo.py`, `test_ground_truth_learning.py`, `test_recognition_reconcile_api.py`, `test_api_pipeline.py`, `test_openapi_schema.py`: 28 passed. В sandbox pytest для `tmp_path` пришлось запустить с временной fixture в рабочем каталоге, поскольку системная temp-директория запрещена. Live API после миграции отвечает health=`ok`; `training_samples.source_snapshot_id` присутствует. Ни один кандидат или исходный FARO-файл не изменён. Stage 6/7 остаются открытыми; принято 2/12, так как независимые полевые эталоны, holdout и согласованный инженерный допуск всё ещё отсутствуют.


Этап 6/7 — безопасная обработка legacy provenance, 24 октября 2026

Исправлена проверка старых кандидатов: совпадение сохранённых row IDs с bbox без `source_cloud_snapshot` теперь даёт `unverifiable`, а создание обучающего примера без снимка отклоняется. Совпадение координат bbox больше не считается доказательством идентичности строк массива. Live GET elements подтвердил: все 641 текущие записи (200 beam, 282 brace, 87 column, 58 wall, 4 slab, 10 truss) сохранены без snapshot и потому нуждаются в повторном распознавании для привязки к версии облака. Новые RED/GREEN regressions проверяют оба случая. После расширения аудита повторно запущен полный provenance/learning/API regression-набор: 47 passed; его три ключевых audit/frame/sample-файла отдельно дают 23 passed. Frontend `npm test`, `npx tsc -b --pretty false` и production build прошли (2 556 модулей; app chunk 546.24 kB, Vite предупредил о чанке >500 kB). Live API после контролируемого перезапуска вернул HTTP 200 и `source_snapshot_counts={current:0, missing:641, stale:0, unchecked:0}`; веб-приложение на 5173 отвечает HTTP 200. Данные FARO и записи кандидатов не изменялись. Точность не измерена; этапы 6–7 остаются открытыми до независимых FARO-эталонов, изолированного holdout и согласования допуска.

Этап 6 — пространственная принадлежность узлов ферм, 24 октября 2026

В `_section_node_evidence` узел мог включать строки из соседней плоскости: алгоритм сравнивал только медианы опорных точек двух стержней, поэтому смешанные слои могли давать совпадающие медианы; затем отображение назначало координату текущей плоскости фермы. Добавлена привязка к reference plane текущего кандидата и фильтрация исходных строк за пределами заданной полосы до повторной проверки минимальной опоры каждого стержня. RED/GREEN тесты воспроизводят crossing в неправильной плоскости и смешанные строки, скрытые одинаковыми медианами; валидный узел сохраняет только coplanar provenance.

Профильный backend-набор распознавания, связности, модели, API, DXF/IFC/СПДС: 187 passed, одно существующее предупреждение Starlette/httpx. Никакие данные FARO или записи кандидатов не изменялись. Это синтетическая проверка provenance/topology, не доказательство распознавания реального узла или точности. Этап 6 остаётся открыт; общий приём 2/12.

Этап 6 — live-аудит происхождения стержней ферм, 24 октября 2026

Read-only GET-аудит проекта `Proverka skvoznogo marshruta 1.rcs` (cloud `2621e5a320df49949d04aa1b7399539e`): в 40-миллионной производной выборке из RCS-источника на 297 873 927 точек обнаружены 24 фермы, все 24 `unreviewed` (5 software-кандидатов `candidate_complete`, 19 `partial`). Их сборки ссылаются на 969 дочерних предложений стержней; 0 ссылок отсутствует. У каждого дочернего стержня и каждого узла-кандидата не менее 5 точечных строк, все 407 841 ссылки в диапазоне сохранённой выборки; уникальных строк 327 518. Подробности: `docs/validation/TRUSS_PROVENANCE_AUDIT_2026-10-24.json`.

Ролевые гипотезы среди 969 стержней: 12 верхних и 34 нижних пояса, 923 `unknown`; причины unknown — 598 горизонтальных фрагментов короче минимального пролёта, 245 случаев без обеих измеренных хорд, 79 стержней, не достигающих обеих хорд, и 1 непланарная поддержка. Это не false-negative/precision подсчёт: без независимых физических меток неизвестно, какие строки являются реальными элементами. Сохранение `unknown` остаётся обязательным до проверки инженером.

В таблицу кандидатов Studio добавлен фильтр класса и поиск по ID, коду/русскому названию класса и роли. На live-проекте фильтр `Ферма` показал 24/1 482; запрос `ферма` вернул те же 24, неизвестный запрос показал корректное пустое состояние, очистка вернула список. Frontend tests и TypeScript прошли; production build — 1 979 модулей. Эти средства упрощают ручную разметку, но ни одной метки не внесли; физические эталоны и критерии Stage 6 остаются открытыми.

Проверена только целостность связей с исходными строками производной выборки. Полный RCS из 297,9 млн точек повторно не обрабатывался. Метки физических стержней, корректность ролей, совпадение узлов, полноразмерная точность, независимый holdout и допуск не проверены; `candidate_complete` не означает приёмку инженером. Исходный файл, кандидаты и аннотации не изменялись. Этап 6 остаётся активным; принято 2/12.
