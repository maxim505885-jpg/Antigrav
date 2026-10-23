# SCAN Workshop Scan-to-BIM Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. The user has already asked to continue inline and without pauses; do not wait for a second execution-method choice. Ask one concrete question only when a release gate genuinely needs an engineering decision or a missing source file.

**Goal:** Turn the local FARO workshop scan into reviewable, dimensionally traceable column, crane-girder, truss, and bracing models; learn only from explicit engineer decisions; and issue accepted AutoCAD 2026 and Revit 2027 deliverables while preserving the original RCS.

**Architecture:** Keep source scans immutable and perform all work on versioned derived point data. Recognition emits candidates with point provenance and uncertainty; an engineer reviews geometry, role, and type; confirmed project knowledge feeds deterministic recommendations; a versioned structural model is the shared source for drawings and BIM. FARO station registration remains a separate branch until its individual stations are available.

**Tech Stack:** Existing Python 3.10+ / FastAPI / SQLite backend; React / TypeScript / Three.js UI; NumPy / SciPy and existing point-cloud adapters; ezdxf and current PDF renderer; IfcOpenShell; existing Revit 2027 add-in targeting .NET 10. Add a library only after a representative benchmark shows a measurable benefit and its license is recorded.

**Spec:** `docs/superpowers/specs/2026-10-21-column-typology-learning-design.md`; whole-program requirements and prior technical decisions: `docs/superpowers/plans/2026-10-21-scan-workshop-roadmap.md`; pilot evidence: `docs/STATUS.md`, `docs/validation/PROGRESS.md`, and `docs/validation/COLUMN_SECTIONS.md`.

## Global Constraints

- Never upload, overwrite, move, or commit the original local `1.rcs`; read it locally and read-only. All outputs go to versioned derived paths.
- Preserve every input SHA-256, point-row mapping, coordinate transform, unit, algorithm version, and parameter set needed to reproduce a measurement.
- Treat recognition output as a candidate until a human confirms it. Keep `unknown`, occluded, inferred, and rejected states explicit; never infer absence from missing returns.
- Keep measured geometry, fitted geometry, grid axes, and nominal dimensions separate. The known 6000 mm value is the longitudinal column pitch; it is not a column section size and must not snap measured geometry.
- Engineering tolerance is currently **undefined**. Report errors and coverage without saying the model meets accuracy requirements until an engineer/user supplies acceptance limits.
- Known-side completion is allowed only when the user explicitly enters both sides. Mark completed edges as inferred and require a separate engineer save/confirmation.
- Reuse confirmed project types as suggestions only. Never auto-assign a type, replace geometry, train/activate a statistical model, or overwrite annotations from a new recognition run.
- Exported DXF/PDF/IFC/JSON and Revit elements must preserve stable SCAN IDs, review state, units, transforms, source evidence, and unsupported/unknown state.
- No assumed DWG conversion: create DWG only by opening/saving through installed AutoCAD or another verified licensed tool.
- Do not call station registration or RCP/RCS generation complete from a single already-merged RCS. That branch requires original station files and independent control measurements.
- Keep generated reports immutable by version: never overwrite a pilot snapshot, annotation file, or accepted export; make a new version for each changed input or algorithm.

## Review Focus

- **Sparse or occluded column slices:** return insufficient/unknown and preserve missing faces; test in `backend/tests/test_section_fitting.py` and pilot review scripts.
- **Neighboring beams, walls, pipes, and scan bands inside an OBB:** do not attach their points to a column without spatial/height continuity and review; test in new `backend/tests/test_column_surface_assignment.py`.
- **Repeated or symmetric bays:** prevent 6000 mm pitch from shifting measured axes or causing false member joins; test in `backend/tests/test_grid_control.py` and new structural-model tests.
- **Coordinate origin, rotation, units, and long extents:** preserve world/local transforms, dimensions, and IDs through tiled processing and DXF/IFC/Revit; test in `backend/tests/test_structural_model.py`, `backend/tests/test_structural_dxf.py`, and `backend/tests/test_structural_ifc.py`.
- **Re-run, cancellation, rejection, undo, and stale sources:** keep engineer decisions durable and idempotent; test in `backend/tests/test_feedback_undo.py`, column-type store/API tests, and new batch-resume tests.

---

## Current Evidence and Release State

Working branch: `feature/workshop-pilot`, based on current HEAD `538cbe5`. The tree already contains extensive uncommitted work; preserve it and do not reset, clean, or replace existing files. The plan is based on actual project files and the latest recorded pilot runs, not on a claim that all previous checks have just been rerun.

| Work package | State | Evidence and remaining release gate |
|---|---|---|
| A0 baseline and data preservation | Done for the present pilot | Backup, pilot protocol, environment notes, immutable-source rule and derived-data reports are recorded. Re-run baseline before any release build. |
| A1 ground truth and accuracy | Open | 16 candidate rows have pending annotations; no independent physical dimensions and no agreed tolerance. 6000 mm pitch is known. |
| A2 full-resolution point access | Partial | Indexed/streaming path has been checked on a 4,004,372-row ROI and a 40-million-point derived set. Native RCS, E57 and LAS/LAZ full-resolution ingest use bounded blocks/memmaps on synthetic fixtures with checksummed output-block recovery; sequential source replay remains necessary. ICP and its API now use reproducible no-replacement sampling by seed and return exact source row IDs for selected points; the combined registration/stitching/API/export/pointdata/pipeline/OpenAPI suite passed 65 tests (one warning); unified-cloud cache reuse now checks output hash, station fingerprints, count and ICP matrix; centered coordinates are now computed in float64 before float32 storage; unified row ranges preserve each station input row interval in metadata and the registration manifest, and cache validation checks those ranges; ICP evidence now records both station-local and unified row IDs with each station range; the review pipeline validates unique station IDs and full contiguous coverage and copies portable source provenance into the SPDS album manifest; the draft release pipeline now rejects the current decimated 40M/297.9M first station and incomplete 3.5M second-station stream before ICP. The approximately 298-million-point source route has not been accepted end-to-end. |
| A3 shared structural model | Done for the synthetic interchange contract | Versioned `StructuralMember` schema covers axis/local frame, section variants including unknown and built-up, evidence, review state and reversible transforms. Additive SQLite storage has a pre-migration backup/restore regression. One synthetic element round-trips through API, BIM JSON, DXF XRECORD and IFC4 properties with ID, role, geometry, units, review and provenance intact. Native CAD/BIM application acceptance remains in A7/A8. |
| A4 columns and crane girders | In progress | Type grouping/catalog/reuse and a conservative section fitter exist. Full four-edge observed, point-linked rectangular sections can be copied into an editable annotation draft; when two adjacent faces are observed, explicitly entered side dimensions also produce a four-corner outer-envelope hypothesis with the two inferred edges marked and no fabricated source rows. Partial observed spans are treated as lower bounds; corner extrapolation is capped at 15% of the smaller entered side, an algorithm filter rather than an engineering tolerance. Equivalent corner-order hypotheses are deduplicated by matching all four corners and both side lengths within `max(3 mm, distance_tolerance_m)`; supporting source-face IDs are combined. Existing height rows stay intact and saving algorithm-derived rows requires explicit human verification. The focused backend API/surface/section suite passes (44 tests across five files); frontend 48 tests, TypeScript and production build pass. The pilot scan has 0 closed automatic section proposals; real type precision/recall is unknown. Supports, joints and fitted profiles remain unaccepted. |
| A5 trusses and bracing | In progress for synthetic contracts | Synthetic plane emits source-linked chords, internal bars, point-supported nodes and an assembly; partial envelope survives with two chords or one chord plus two traceable internal members, without inventing a missing elevation; short source-linked chord fragments split by occlusion remain separate with unknown roles instead of being bridged. A new severe-occlusion regression keeps a 4.2 m observed chord within a 14 m observed extent and leaves the missing bottom chord unknown; truss-lineage and topology suites pass 27 tests. Trusses separated by section plane keep their own source rows. Labeled bays, physical connectivity and held-out evaluation remain open. |
| A6 engineer review and project learning | Partial | Review queue, history, undo, groups, type memory, a column slice measurement panel and a point-linked suggestion-to-draft flow exist. Height rows preserve structured source index-space, row count/sample and analysis version into the independent JSON export; the API rejects point-linked rows unless the saved annotation records explicit human verification. Editing sourced rows and restoring archive drafts clears that verification. Annotation saves revalidate the candidate snapshot under a SQLite write lock; parallel saves receive unique revisions; delete/reimport recovery is tested for an identical snapshot. Browser/API regression proves an unreviewed candidate keeps its ID and `adjust_boundary`/`undo` history after an identical recognition rerun. All revisions of one stable candidate `element_id` stay in one deterministic train/holdout group; a single candidate produces no fake holdout. Synthetic scenarios are not real-pilot acceptance; physical labels and verified grids/levels remain. |
| A7 AutoCAD deliverables | Partial | DXF/PDF plans, dimensions, marks, schedules, scale and A3 pagination exist; explicit draft/final issue modes now stamp sheets and final mode filters to reviewed elements/types. Earlier Core Console conversion produced an AC1032 DWG header, including from a non-ASCII workspace path; the latest 492-test workspace regression saw the direct conversion exceed its 20-second timeout. GUI opening, visual review, edit/print and final drawing round-trip remain open. |
| A8 Revit 2027 | Partial | IFC4 export and JSON add-in compile/registration exist; the current release build succeeds with three Autodesk/.NET reference-version warnings. JSON 1.0 frame and duplicate-ID preflight are in place. Interactive RVT import, idempotent reimport, families, assemblies, sheets and round-trip acceptance remain. |
| A9 full workshop | Not started | Full scan processing, held-out validation, resource/resume behavior and reconciled issue set remain. |
| R1–R3 FARO registration/ReCap | Waiting for station sources | Individual FARO stations and control observations are not present in the current source set; the branch must stay conditional. |

Latest workspace-wide backend regression, 23 October: 492 tests collected, 490 passed. The two failures are an AutoCAD Core Console conversion exceeding its 20-second timeout and Windows denying cleanup of a temporary RCS cancellation directory (`WinError 5`); neither is an assertion failure in geometry or exchange data. The targeted API/export route passed 2 tests and the stairs/openings/IFC group passed 8. This run used pre-created isolated temp directories because Python cannot write to pytest-created nested folders in this Windows sandbox.

Known pilot diagnostics: the conservative section fitter evaluated 160 saved windows (103 insufficient points, 48 unknown, 9 open, 0 closed proposals). The latest immutable surface-track audit (`column-surface-tracks-v15.json`) contains 16 candidates, 153,909 point rows and 38 tracks; no track is attached to a candidate face, source rows remain traceable, and all five input hashes are unchanged. Earlier OBB-face audit v11 found 38 vertical surfaces: 30 have a normal mismatch, 7 lie outside the candidate boundary, and one geometrically matches a potential face but has only 45% continuous vertical support. These observations do not confirm or disprove the physical columns. The earlier v10 report is retained but superseded because its status ordering labeled unrelated short surfaces as insufficient support.

## Dependency Order

```text
A0 baseline/provenance
  └─ A1 independent pilot truth and acceptance limits
      ├─ A2 full-resolution derived point access
      ├─ A3 stable structural model and coordinate contract
      │   ├─ A4 columns + crane girders ──┐
      │   └─ A5 trusses + bracing ────────┤
      └─ A6 review/learning ──────────────┘
          ├─ A7 AutoCAD 2026 release
          └─ A8 Revit 2027 release
              └─ A9 full workshop / held-out acceptance

A0 ── R1 stations ── R2 registration ── R3 ReCap package (conditional)
```

The available user direction is to proceed without pauses. Therefore do all engineering and documentation work that does not require a missing human measurement. At a true acceptance gate, report the specific evidence and ask only the decision needed to unblock that gate; continue independent tasks meanwhile.

## Execution Tasks

### Task 0: Preserve baseline and make the project reproducible

**Files:** `scripts/baseline.py`, `scripts/rcs_probe.py`, `docs/validation/BASELINE.md`, `backend/scan2bim/config.py`, local ignored `data/validation/` artifacts.

**Interfaces:** Consumes the selected local project/cloud and installed Autodesk tools. Produces a versioned baseline manifest with input hashes, point counts, extents, units, source transforms, application/dependency versions, machine resources, command results, elapsed time, peak memory, and backup location. Do not put private local paths or source binaries in Git.

- [x] Existing project inventory, backup, RCS probe, and pilot baseline were recorded; preserve these results.
- [x] Re-run `.\.venv\Scripts\python.exe scripts/baseline.py --output data/validation` and record all current failures as well as successes. The script creates unique timestamped JSON and SQLite-backup names itself.
- [x] Run `.\.venv\Scripts\python.exe -m pytest backend/tests -q` against an isolated test data directory; record the exact command, exit code and warnings.
- [x] Run `npm test` and `npm run build` in `frontend/`; keep the current Vite chunk-size warning visible until resolved or explicitly accepted.
- [x] Record Revit 2027/.NET 10 and AutoCAD 2026/ReCap availability from installed applications, not old notes.
- [x] Verify the source RCS length and timestamp before/after the local run. If a full hash is needed, measure runtime first and write only the digest to the local manifest.
- [x] Make a new local DB backup before any migration or long-running reprocessing.

**Gate:** baseline gate passed for the current derived pilot: tool versions and database state are recorded, writes stayed in derived/test paths, original RCS metadata is unchanged, and backend/frontend checks pass. Full-resolution access and engineering accuracy remain separate open gates. Evidence: `docs/validation/BASELINE.md`.

### Task 1: Establish independent pilot ground truth and acceptance measurements

**Files:** `docs/validation/column-types-pilot.md`, `docs/validation/COLUMN_SECTIONS.md`, `scripts/evaluate_column_types.py`, local versioned annotations under `data/validation/pilot-A/column-type-evaluation/`.

**Interfaces:** Annotation rows identify one physical instance independently of model candidate IDs and contain measured side lengths only where visible, cross-section shape, height/occlusion coverage, structural role, reviewer/source, and confidence. Evaluation consumes a frozen model snapshot plus independent annotations and emits confusion/grouping measures, dimension residuals, unknown coverage, and per-element traceability.

- [x] Create a 16-row pending annotation template and snapshot SHA; keep it independent from candidate output.
- [x] Implement pairwise type-group precision/recall, false merges/splits, coverage and dimensional residual metrics; unset or unknown values remain null.
- [ ] Use the manual review UI and derived slice sheets to identify which candidates are physically observable and which are occluded/context-only. Do not infer a physical ID from candidate numbering.
- [ ] Prepare a new annotation version for selected observable members; never edit the existing SHA-pinned template in place.
- [ ] Compare at least the existing six tolerance sweeps (dimension thresholds 2/5/10 mm × relative thresholds 0.5/1%) against the annotations and retain all results, including null metrics.
- [x] Keep every revision of one stable candidate `element_id` in the same deterministic train/holdout group; when only one candidate exists, keep all of its samples in train instead of fabricating a test set. This does not establish a physical-member/bay holdout.
- [ ] Add a held-out set split by physical member/bay, not by multiple slices of the same member. Keep it untouched while thresholds are selected.
- [ ] At the engineering acceptance gate, ask for allowable position/level/section errors and recording convention. Until supplied, leave every pass/fail accuracy field “not assessed” and report raw residuals only.
- [ ] Record whether 3–4 recurring section types are actually observed; treat that count as a hypothesis, not an algorithm constraint.

**Gate:** a reviewer can trace every metric to independent physical IDs and source evidence, and the held-out split prevents leakage. Accuracy is not accepted until the tolerance decision exists.

### Task 2: Complete full-resolution, restartable derived point access

**Files:** `backend/scan2bim/pointdata/`, `backend/scan2bim/formats/`, `backend/scan2bim/api/`, `scripts/index_cloud.py`, `scripts/check_full_route.py`, new `backend/tests/test_pointdata*.py`, `docs/validation/POINTDATA.md`.

**Interfaces:** `PointQuery(bounds, resolution=None, cloud_id=...)` returns batches preserving XYZ, RGB/intensity where available, original derived-row ID, scan ID, coordinate frame, and units. Index is an accelerator only; results must match the canonical full-resolution source query.

- [x] Implement chunked local reads and an optional spatial index; record that 40-million-point indexing is not faster for every thin/large query.
- [x] Compare indexed and linear queries on boundary-touching, rotated thin-slice, empty and long-extent ROIs; assert equivalent source row IDs and coordinates on deterministic synthetic fixtures.
- [ ] Run a read-only, full-source route on the complete local scan; measure point count, omissions, quantization, wall time, peak RAM and index disk. Do not assume the previous approximately 298-million count without recounting.
- [ ] Compare one candidate persistent layout (current NPY plus index) with COPC/E57 only on the representative workload; select one canonical derived representation and document conversion loss.
- [x] Add cooperative cancellation for a running import through the job API and UI; terminate the isolated native RCS reader before its temporary output directory is removed.
- [x] Stage the complete derived output in `.ingest-stage`, persist a source-identity/file-SHA256 manifest, verify staged files, idempotently promote/finalize, and clean incomplete derived files without touching the source. After API restart, mark interrupted import jobs/clouds failed with an explicit resumable state; user-triggered resume reuses a valid complete checkpoint. Verified by `backend/tests/test_ingest_restart.py`.
- [x] Add a bounded-RAM full-resolution mode for the isolated ReCap RCS reader: `--all` streams every XYZ/RGB point to sequential raw files; import computes bounds by blocks and writes local positions/colors through NPY memmaps. A configurable free-disk reserve prevents the reader from consuming the final safety margin. Verified on multi-block synthetic native-reader and import tests; enable with `S2B_MAX_INGEST_POINTS=0`.
- [x] Add durable block checkpoints to the native RCS `--all` stream: flush XYZ/RGB blocks to disk before atomically committing point count and per-block SHA-256; on retry verify committed data, truncate any uncommitted tail and replay the committed prefix with `advancePoint` before continuing. Pause safely at the disk reserve and resume later; reuse a completed raw stream without launching the reader again. Verified with synthetic interruption, corruption, reserve exhaustion and restart tests.
- [x] Bind native RCS checkpoints to full source SHA-256, passing the precomputed hash to the isolated reader and rehashing after derived outputs finish. Reject a source changed during import even when path/size/mtime were restored; store the verified digest in cloud metadata.
- [x] Add a sequential E57 block reader and full-resolution two-pass ingest to NPY memmaps, with exact world bounds, source SHA-256 and checksummed output-block checkpoints. The pye57 reader cannot seek, so retry replays the source prefix and skips committed output blocks; bounds are recalculated. Verified with synthetic multi-scan and interrupted-write fixtures.
- [x] Add bounded-memory LAS/LAZ chunk readers and full-resolution memmap ingest; synthetic LAS and LAZ chunk fixtures check scaled coordinates, RGB, and intensity. Retry restarts both source passes from the beginning.
- [x] Add durable per-block output checkpoints/retry for E57, checking each committed XYZ/color/intensity block before resume; test interruption, committed-block corruption, and uncommitted-tail overwrite.
- [x] Add durable per-block output checkpoints/retry for LAS/LAZ, checking committed XYZ/color/intensity blocks; synthetic interruption/resume fixtures cover both `.las` and `.laz`. Readers replay the source prefix because they stream sequentially.
- [x] Add bounded-memory full-resolution text parsing for PTS/XYZ/TXT/CSV and resumable NPY-memmap writes with source SHA and per-block hashes. Synthetic tests cover CSV color detection, PTS intensity/color, interrupted resume and committed-block corruption.
- [x] Add bounded-memory PCD ASCII/binary readers (including separate and packed RGB plus intensity) and restartable full-resolution memmap ingest with source and block hashes. Synthetic tests cover bounded chunks and interrupted resume.
- [x] Add bounded-memory PLY ASCII and binary little/big-endian vertex readers plus restartable full-resolution memmap ingest with source and block hashes. Synthetic tests check XYZ/RGB/intensity and interruption/resume.
- [x] Finish baseline format fault injection and validate declared counts/truncation boundaries for PCD/PLY variants: PCD ASCII count mismatch and binary truncation; PLY ASCII count mismatch and binary truncation; both formats reject modified committed blocks on resume. Current explicit gaps: PCD `binary_compressed`; PLY vertex must be first and vertex list properties are unsupported. Sequential readers replay the source prefix during retry. Default 40M limit still decimates unless full mode is configured; the full real-source route remains unverified.
- [x] Confirm UI preview is decimated separately and never feeds exact section fitting, member geometry or QA measurements. Full-resolution ingest test caps the preview at two points while retaining all four stored XYZ/RGB points; section and structural recognition readers consume `positions.npy` via `CloudGeometry`/`NpyPointProvider`, while the API preview endpoint serves only `preview.bin`.
- [x] Verify durable checkpoint restore after interruption during partial atomic promotion, including finalization after the synthetic source is unavailable and source SHA remains recorded; see `test_finalize_recovers_after_partial_atomic_promotion`.

**Gate:** full-scan points can be queried and resumed without loading the whole scan in RAM; indexed query matches the canonical source; derived processing never changes the RCS.

**Progress note (22 Oct 2026):** full backend suite now has 284 passing tests (one existing Starlette/httpx deprecation warning). E57 and LAS/LAZ block reading and full-resolution ingest use two-pass sequential readers and NPY memmaps; `pye57 0.4.19` raises `ErrorNotImplemented` when seeking within a compressed vector, so mid-pass retry remains restart-from-source. Source SHA is verified before/after. The full FARO source, RCS DLL route, actual peak RAM/runtime/disk and real CAD/BIM acceptance remain unverified.

**Progress note (22 Oct 2026):** E57's second pass now flushes and fsyncs each XYZ/RGB/intensity output block before atomically saving a checkpoint with block checksums and the source SHA. Retry replays the sequential source prefix because pye57 seek is unavailable, verifies committed arrays, skips their output, and continues; bounds are recalculated. Fault injection detects modified committed data and confirms an uncommitted tail is overwritten. Full backend suite: 289 passed, one existing Starlette/httpx deprecation warning. LAS/LAZ block resume, PLY/PCD/text streaming, full FARO route and measured resource budget remain open.

**Progress note (22 Oct 2026):** `backend/tests/test_pointdata.py` compares indexed and linear selection for a rotated 27° thin footprint (including exact local-frame clipping), cell boundaries, a whole-tile extent and empty queries. Returned source row IDs and world coordinates match. Native RCS also has an opt-in all-points disk-stream path; synthetic reader/import tests verify all points, RGB, memmap output, cleanup, checksummed block recovery, reserve exhaustion, source-content replacement detection and retry. Full backend suite: 269 passed with one existing Starlette/httpx deprecation warning. The real 297M-point source route, measured peak RAM/runtime/disk, streaming readers for other formats and canonical layout remain acceptance gates; see `docs/validation/POINTDATA.md`.

**Progress note (23 Oct 2026):** the application API imported the available derived binary PLY at `data/output/unified_stitched_release/unified_stitched_cloud.ply` into a fresh isolated data directory with `S2B_MAX_INGEST_POINTS=0`: 43,500,000/43,500,000 points, zero non-finite rows dropped, no decimation, 20.2 s, sampled peak process RSS 921.8 MiB, minimum sampled free disk 9,326,764,032 bytes, and 690,218,523 output bytes. The source PLY SHA-256 stayed `cd912a991ef923295ec406b809e573feb9c3785755a631fe3999547431f8a5fa`; see `docs/validation/A2_FULL_PLY_PROFILE_2026-10-23.json`. This establishes the PLY API ingest/resource path for this derived file only. Its registration manifest is `metadata_only` and `registration_verified=false`, so this does not validate scan alignment, geometry, the protected original RCS route, or the complete workshop scan. Full-source acceptance, cancellation/restart at this scale, and index/query comparison remain open. The protected `1.rcs` was not read or modified.

### Task 3: Freeze a shared structural-member and provenance contract

**Files:** `backend/scan2bim/structure/models.py`, `backend/scan2bim/structure/coordinates.py`, `backend/scan2bim/structure/profiles.py`, `backend/scan2bim/schemas.py`, additive `backend/scan2bim/db.py` migration, `backend/scan2bim/bim/model.py`, `frontend/src/types.ts`, `contracts/structural-model.schema.json`, `backend/tests/test_structural_model.py`.

**Interfaces:** Versioned `StructuralMember` fields: stable ID; element and project/cloud IDs; role/class; measured or proposed axis start/end; local frame; cross-section representation (catalog profile, arbitrary polygon, built-up, circular, stepped, unknown); assemblies; measured dimensions; evidence/source rows; method/version/parameters; confidence and review state; source/local/world transforms. Existing v1 element APIs remain readable through an adapter.

- [x] Add contract tests for horizontal, rotated, sloped and vertical members; unknown and built-up sections; local/world transform round-trip; duplicate and stable IDs; old v1 payload compatibility.
- [x] Add versioned BIM JSON schema validation and explicit metre/source-cloud-world coordinate-frame fields; reject duplicate IDs, non-finite values and degenerate geometry. IFC export revalidates versioned models.
- [x] Preserve recognizer metadata as an optional additive BIM 1.0 field and serialize it into IFC `MetadataJSON`; older v1 payloads without metadata still validate.
- [x] Preserve member elements with missing sections in IFC without inventing geometry; retain stable ID and an explicit unsupported geometry status. Known single-width member envelopes are labeled as square approximations.
- [x] Add an additive DB migration and rollback/backup test; do not rewrite old records or IDs.
- [x] Keep nominal grid axes as annotations/reference geometry; alignment never snaps measured bays to the nominal 6000 mm step, and the original observations remain unchanged. `source_to_sheet_4x4` records an invertible presentation transform.
- [x] Round-trip the same fixture through API, JSON, DXF and IFC and assert ID, class/role, units, transform, review state and evidence match.

**Gate:** every downstream format can represent the same member and its uncertainty without silently dropping fields.

**Progress note (22 Oct 2026):** a regression test showed that BIM JSON dropped element recognition metadata even though the database retained it. `metadata` is now returned by `/elements`, emitted in BIM JSON, remains optional for older 1.0 payloads, and is preserved in IFC as compact `MetadataJSON`. Contract/IFC tests and the end-to-end API → BIM JSON → IFC provenance assertion pass. SPDS manifest now records an invertible source-cloud-world → sheet-local 4×4 transform; the observed geometry remains unchanged and nominal 6000 mm is not applied as a snap. Full geometric model, migration and cross-format identity/evidence round-trip remain open.

**Progress note (22 Oct 2026):** IFC export no longer substitutes a 150 mm member section when section data is absent. The IFC proxy keeps the original element ID and records `unsupported_missing_section` with no shape; supported one-width rectangular envelopes carry `square_envelope_approximation`. A versioned `StructuralMember` TypedDict/JSON Schema and validator now cover member axes, section variants, evidence, review and inverse transforms. The additive `structural_members` table is created idempotently without rewriting existing rows; SQLite backup/restore is tested. DXF entities carry an XRECORD with identity, geometry, units and review evidence; IFC Psets preserve geometry, role, dimensions and recognition provenance. The same API fixture was compared across BIM JSON, DXF and IFC; the targeted 16-test interchange/contract suite passes. Full backend rerun remains pending.

**Verification update (22 Oct 2026):** complete backend suite after A3 and the A4 two-known-sides API regression: 340 passed, exit code 0; only the existing Starlette/httpx deprecation warning remains.

### Task 4: Isolate and measure real column surfaces; establish repeatable types

**Files:** `backend/scan2bim/structure/section_fitting.py`, `backend/scan2bim/structure/column_section_series.py`, `backend/scan2bim/structure/vertical_surfaces.py`, `backend/scan2bim/structure/column_surface_assignment.py`, `backend/scan2bim/recognition/steel.py`, `backend/scan2bim/learning/`, `scripts/review_column_surface_tracks.py`, `scripts/fit_column_track_sections.py`, `scripts/fit_column_sections.py`, `scripts/evaluate_column_types.py`, and their section/track tests plus immutable pilot reports.

**Interfaces:** Implemented first association slice: `associate_surfaces_to_column(candidate_geometry, surface_result, *, max_normal_deviation_degrees=8.0, max_boundary_offset_m=0.10, min_edge_overlap_fraction=0.20, min_vertical_support_fraction=0.25, vertical_bin_m=0.25) -> dict`. It returns per-plane match/unknown states and edge evidence; these settings are algorithm filters, not engineering tolerances. Next slice: `fit_column_section_series(section_slices: Sequence[Mapping[str, Any]], *, known_sides_m: tuple[float, float] | None = None, distance_tolerance_m: float = 0.004) -> dict[str, Any]` in `structure/section_fitting.py`. Each slice is `{z_m: float, points_xy: finite N×2 array, source_point_ids?: Sequence[int]}`. It fits heights independently, returns them sorted by Z, maps local face indices to supplied source IDs, reports per-side min/max/range without pass/fail, and leaves sparse or unsupported slices `unknown`. Explicit known sides may create inferred edges at that slice only. `profile_variation_status` is `insufficient` with fewer than two complete sections, `incomplete` when any supplied height is unknown/ambiguous, otherwise `observed_variation` or `no_variation_observed` based on measured ranges. It must not interpolate across missing heights, assign a type, or confirm geometry. Later interface: `propose_column_type(section_series, confirmed_catalog) -> TypeProposal[]`; it may only produce reviewable suggestions.
**Track-to-section interface:** `fit_column_track_sections(candidate_geometry: Mapping[str, Any], surface_tracks: Sequence[Mapping[str, Any]], xyz_world_m: np.ndarray, source_point_ids: np.ndarray, *, vertical_bin_m: float = 0.25, known_sides_m: tuple[float, float] | None = None, distance_tolerance_m: float = 0.004) -> dict[str, Any]` in `structure/column_section_series.py`. `xyz_world_m` and `source_point_ids` are same-length candidate-ROI rows; track `source_point_indices` must resolve exactly through the source-row array. Only `candidate_track`/`weak_candidate_track` rows with a supported `candidate_edge_id` enter fitting; unassigned tracks stay explicitly excluded. Every candidate-height bin is returned, including empty bins as unknown. Each slice reports contributing track IDs/edges/statuses. Missing source IDs or duplicate input row IDs fail closed. No source cloud, candidate, or track is mutated.

- [x] Implement a conservative per-slice line/rectangle fitter with observed/inferred edges, point provenance and explicit unknown/open results.
- [x] Run slice, voxel-connectivity and vertical-plane diagnostics on all 16 current candidates; preserve their frozen reports.
- [x] Add manual section measurement to a selected column card, and transfer a proposed contour to edit fields without saving automatically.
- [x] Transfer only unambiguous four-observed-edge contours with source-row evidence to the annotation draft; preserve existing rows and require an explicit human verification checkbox before saving those suggestions.
- [x] Expose candidate-local vertical surface extraction, OBB face association, source-linked tracks and multi-height section fits through a review-only API and the selected-column panel; preserve unassigned surfaces and cap the source crop at 250,000 points.
- [x] Add a pure OBB-face association step using plane orientation, boundary offset, observed span overlap and continuous vertical support; output candidate edge evidence only. Test rotated world coordinates, nearby parallel context, short fragments, four candidate faces and invalid geometry.
- [x] Preserve the initial pilot run `column-surface-tracks-v10.json`; later review found its status ordering conflated short unrelated surfaces with weak candidate-face support. Do not use v10 status counts as the final diagnosis.
- [x] Correct status precedence, add a short-but-offset neighboring-plane regression, and rerun as `data/validation/pilot-A/column-surface-tracks-v11.json`. All five input hashes remained unchanged: 30/38 orientation mismatches, 7/38 outside the candidate boundary, 1/38 weak potential face at 45% vertical coverage, 0 accepted face associations.
- [x] Implement conservative face-track clustering by candidate-edge membership, normal and boundary agreement, finite footprint, shared vertical bins, along-face overlap or supported endpoint gap; preserve row provenance and link evidence. Surfaces with no candidate-height overlap or outside the stricter track boundary remain unassigned.
- [x] Add synthetic adversarial tests for a nearby wall, beam above the column head, disconnected height bands, unsupported/near endpoints, rotated geometry with large world coordinates, pipe-arc tangent planes, a partial L-corner, and one/four observed candidate faces.
- [x] Complete the conservative synthetic matrix: coplanar wall remains unowned/unconfirmed; scan-band stripes do not bridge; a neighboring 6000 mm bay stays outside the candidate; stepped profile remains height-offset invariant; rotated measured sections retain dimensions; missing middle bands remain separate at 0.25/0.5 m bins and 0.5/1/2 m gaps. Evidence: `test_coplanar_wall_match_remains_unowned_and_unconfirmed`, `test_scan_band_stripes_without_shared_height_bins_do_not_join`, `test_face_from_adjacent_six_metre_column_stays_outside_this_candidate`, `test_stepped_profile_is_invariant_to_height_offset`, `test_four_observed_faces_propose_a_measured_envelope_without_catalog_name`, and `test_missing_middle_band_never_bridges_surface_tracks`.
- [x] Run assignment on the frozen pilot snapshot as new immutable `data/validation/pilot-A/column-surface-tracks-v15.json`; all five input SHA-256 values stayed unchanged and every track retained source row IDs.
- [ ] Compare candidate surface tracks against independent engineer annotations before changing thresholds; the annotation set is still empty.
- [ ] Fit sections at multiple independent heights; detect constant, stepped, built-up, circular and unknown shapes without forcing rectangles.
- [x] Implement `fit_column_section_series` and tests: `test_section_series_preserves_steps_and_dimension_ranges`, `test_section_series_reports_repeatable_dimensions_without_assigning_a_type`, `test_section_series_keeps_sparse_heights_unknown_and_maps_source_ids`, `test_section_series_does_not_call_profile_constant_across_an_unknown_height`, `test_section_series_completes_only_explicit_known_dimensions`, and `test_section_series_rejects_duplicate_z_and_bad_source_mapping`. Verified per-height outputs, sorted Z, unmodified inputs, source-point mapping, incomplete-profile status, and `engineering_status=not_assessed`; this only reports measured ranges and does not name a column type.
- [x] Link tracks to source points with `fit_column_track_sections`; tests cover four-edge section reconstruction, explicit two-side completion, unassigned-track exclusion, missing height, source-row mismatch, and input immutability. Read-only run on frozen v15 produced `column-track-section-series-v2.json`: candidate IDs preserved, all 5 input hashes stayed unchanged, 16 candidates/38 excluded tracks/666 unknown height bins/0 proposals. v15 was not overwritten. v1 is retained as an immutable superseded report because its serialization lost candidate IDs.
- [x] Add a full-ring circular-section hypothesis with source-row evidence, radial residuals and angular coverage. Across independent Z slices, report diameter changes without assigning a type; partial arcs and I-shaped built-up profiles stay shape-unknown, while ambiguous rectangle envelopes remain review proposals. Synthetic verification covers complete rings, clutter, incomplete arcs, composite outlines and changing diameters.
- [x] Verify the selected-column API path with two explicit measured sides and two adjacent observed faces: returns four corners, labels two edges observed/two inferred, preserves source rows, and leaves candidate geometry/review untouched until the engineer applies it.
- [ ] Fit physically supported pilot sections at multiple independent heights; recognize/measure built-up and steel catalogue profiles without forcing their outer envelope into a structural type. Existing pilot evidence has no supported candidate-edge tracks.
- [ ] Propose repeated types from measured descriptors and the confirmed project catalog; keep a type unknown where visibility does not support comparison.
- [ ] Evaluate false merge/split and dimension residuals on train and held-out physical members; preserve null metrics where truth is absent.
- [ ] Record confirmed types only through explicit UI action; version catalog changes and keep undo/reject/recovery durable.

**Gate:** each published type/section has independent member truth, source-point trace, multi-height support and reviewed dimension errors; otherwise it stays an unconfirmed proposal. Current pilot evidence does not pass this gate.

### Task 5: Recover crane-girder members, profiles, supports, and joints

**Files:** `backend/scan2bim/recognition/steel.py`, `backend/scan2bim/structure/`, `backend/scan2bim/services.py`, new `backend/tests/test_crane_girders.py`, `scripts/validate_crane_girders.py`.

**Interfaces:** `propose_crane_girders(point_batches, column_supports, levels, grid) -> MemberProposal[]`; each proposal includes one physical span, axis endpoints, support evidence, observed profile attributes, joints/gaps, source rows and unresolved fields.

- [ ] Build independent labels for beam, rail, runway girder, roof beam, duct/tray and unrelated long objects.
- [ ] Infer member axes from full-resolution points and plane/surface evidence; do not merge separate spans across joints or a long row into one member.
- [ ] Detect each physical support at columns and preserve unsupported ends as unknown; keep rail and girder as distinct roles.
- [ ] Fit only supported profile properties; label hidden flange/web/seat attributes unknown.
- [x] Add a synthetic RED/GREEN safeguard: collinear Hough segments that only touch at a support remain separate unless their measured overlap exceeds 0.10 m; overlapping fragments still merge. This does not identify a physical joint or validate a real span.
- [x] Define and validate the review-only `MemberProposal` contract: one non-zero world-metre axis, unique source rows, endpoint support states, observed/unknown profile, joint/gap evidence, unresolved fields, and a forced `proposed` review state. Verified by `backend/tests/test_member_proposal.py`; horizontal beam candidates and brace/truss bars now emit this contract.
- [x] Preserve original point-row IDs through horizontal-member height-band sampling and selected-strip measurement; attach at most 512 deterministic source IDs plus explicit band/sample counts to each beam candidate.
- [x] Emit each horizontal beam candidate as a validated `MemberProposal` with a repeatable geometry/evidence ID, source-row index space, proposed role, and explicit unknown supports, profile, joint locations and physical span boundary. End-to-end synthetic 6 m crane-girder coverage is in `backend/tests/test_beam_source_lineage.py`; this does not confirm real beam roles or supports.
- [x] Add synthetic rotation and partial-occlusion cases; preserve the measured axis and selected source-row evidence through both.
- [x] Keep distinct close parallel spans separate: RED/GREEN test covers 6 m axes 0.30 m apart; merge lateral tolerance is limited to 0.20 m. This is an algorithm threshold, not an engineering tolerance.
- [ ] Test overlaid rail, connected end plates, repeated spans and non-structural lookalikes.
- [ ] Report span/level/support residuals and precision/recall against independent labels.

**Gate:** the engineer can review separate spans and supports, and held-out role/profile metrics meet agreed limits.

### Task 6: Model trusses and bracing as member networks

**Files:** `backend/scan2bim/structure/`, `backend/scan2bim/recognition/`, `backend/scan2bim/bim/`, new `backend/tests/test_truss_topology.py`, `backend/tests/test_bracing.py`, `scripts/validate_trusses.py`.

**Interfaces:** `MemberProposal` for each bar plus `AssemblyProposal` with stable assembly ID, member IDs, node coordinates, connectivity, bay/plane, evidence and review state. Model individual bars; assembly boundaries do not hide member-level provenance.

- [ ] Mark one representative roof truss, vertical bracing bay, and horizontal bracing plane from source points, including occlusion and non-structural diagonals.
- [x] Recover separate synthetic member centerlines and point-supported node candidates at intersecting Hough axes; merge duplicate candidate nodes only within 0.10 m. Each node retains source rows and member proposal references but does not claim a physical connection.
- [x] Require local source-point support and measurable along-axis extent on both intersecting members before emitting a node candidate; reject nearby clutter-only clusters and evidence from only one member. Direct adversarial regressions and truss source-lineage tests pass.
- [x] Classify truss posts/webs only when each member endpoint maps uniquely to a measured top and bottom chord within the review heuristic; preserve endpoint distances, assignment, and `unknown` for missing/ambiguous support. Role remains proposed, not a confirmed connection or engineering function. Synthetic integration and adversarial checks pass in `test_truss_source_lineage.py`.
- [x] Test crossed/close parallel braces, point gaps at projected nodes, non-planar member support, and crossing members in separate section planes; unsupported or plane-separated joints remain absent and ambiguous roles remain `unknown`.
- [x] Preserve a partial roof truss when both measured chords and at least one observed internal member exist but the full post count is absent; emit only observed member proposals and mark the envelope/assembly partial. Synthetic regression verifies row provenance and no fabricated posts.
- [x] Preserve a partial roof-truss candidate with one measured chord and at least two source-traceable internal members; publish the missing chord elevation as null, use only observed point extent for its envelope, and retain unknown role for members that cannot be mapped to both chords.
- [x] Add an overlapping-projection regression with two roof trusses at distinct section planes; each assembly keeps only its plane's source row IDs and is emitted separately.
- [ ] Test severe occlusion and overlapping bays against representative source-point labels; retain incomplete assembly members without fabricating missing bars or nodes. A synthetic 70% missing-chord-coverage case now proves conservative behavior, but representative FARO labels and overlapping bays are still required.
- [x] Preserve original `positions.npy` row IDs for detected vertical-brace members, select rows around each individual `(v,z)` axis, and emit a review-only `MemberProposal`; crossing-node points may be shared instead of being assigned falsely to one bar. Tests cover chunk row offsets, explicit downsampling, and a synthetic X-brace.
- [x] Preserve row IDs for horizontal plan braces by selecting 3D points near the individual plan axis and observed Z range; carry height-band downsampling state into the proposal. Synthetic clutter-at-offset case confirms neighboring points are excluded.
- [ ] Evaluate member detection, endpoint residuals, connectivity and assembly attribution on held-out bays.
- [x] Define and validate `AssemblyProposal`: stable identity over member-proposal IDs, optional point-supported node candidates, explicit unresolved connectivity/member-node membership, and forced proposed review state.
- [x] Emit separate top/bottom chord and post proposals from a synthetic roof-truss plane; preserve each member's source rows, link proposal IDs from the envelope, and attach point-supported node candidates while keeping connectivity unresolved. Verification: `test_truss_source_lineage.py`.

**Gate:** individual members and connectivity are reviewable and stable across repeat processing; no assembly is called confirmed from a visual silhouette alone.

### Task 7: Finish engineer review, annotation, and controlled project learning

**Files:** `frontend/src/App.tsx`, `frontend/src/components/ColumnSectionFitPanel.tsx`, `frontend/src/components/ColumnTypesPanel.tsx`, `frontend/src/components/ElementTable.tsx`, `frontend/src/api.ts`, `backend/scan2bim/api/app.py`, `backend/scan2bim/learning/`, type store/API/reconciliation tests.

**Interfaces:** Review decisions are append-only/versioned actions: confirm geometry, confirm role, confirm type, reject proposal with reason, clear type membership, undo/restore. Every decision references the user/project, source element revision and evidence snapshot. `unknown` remains a first-class decision.

- [x] Implement group/type catalog, explicit assign/confirm/reject actions, project-scoped reuse suggestions, history and undo; exercise core flows on synthetic projects.
- [x] Implement measurement panel and separate “transfer draft” from “save corrected geometry”.
- [x] Apply the user's light cream/terracotta visual reference to the existing SCAN workspace without replacing its functional controls.
- [x] Add a UI/API annotation flow for physical member ID, visible/hidden faces, dimensions by height, structural role, confidence and unknown/excluded reason. Store append-only revisions separately from recognition and bind each set to the cloud and candidate snapshot SHA-256.
- [x] Add user-visible evidence: source crop/rows, unique-point support fraction for detected faces, observed-vs-inferred edges, residuals, other candidate conflicts, algorithm version and prior decisions. The fraction is limited to selected-slice points assigned to one or more observed faces; it is not surface-area coverage.
- [x] Add a five-height perimeter observation map for the four oriented-box sides, preserving unknown/ambiguous slices and point-support fractions.
- [x] Add filtering by review status and independent column-reference state (unlabeled/labeled/unknown/excluded), show reference state per candidate, retain source-point return and per-member confirmation/undo.
- [ ] Add bay/level filtering after control grids and level assignments are independently checked; do not infer bays from nominal 6 m spacing.
- [x] Add API tests for append-only revisions, unknown reasons, duplicate physical IDs, malformed dimensions, source geometry/cloud hash changes, project isolation and old-snapshot history; add UI request tests.
- [x] Keep API schema generation operational for all route request models; the OpenAPI regression test covers the learning-sample request schema.
- [x] Add concurrency and stale-write race tests: snapshot changes during a save are rejected under the SQLite write lock, and parallel saves produce distinct revisions.
- [x] Gate training samples on explicit review and non-inferred geometry; require the sample label to match the reviewed class, make retries idempotent, and restore/supersede labels through undo.
- [x] Surface archived annotation history and allow loading one archived decision into an editable draft tied to the current snapshot; the user must review and save it explicitly.
- [x] Preserve structured source-row provenance on section measurements and enforce explicit human verification server-side before a sourced annotation can be saved; export the provenance and verification state in the independent reference JSON.
- [x] Add deletion/reimport lifecycle recovery tests and verify an annotation restored as a draft remains bound to the latest snapshot.
- [x] Export an independent annotation JSON compatible with the existing evaluator; bind it to the BIM source manifest and reject a mismatched source snapshot. Do not auto-train or auto-assign types.
- [ ] Export a reviewed learning manifest to the project catalog only after explicit confirmation; defer ML until independent labeled members and held-out evaluation exist.

**Gate:** a reviewer can independently label and revise real pilot members without editing JSON/SQLite manually; decisions survive reprocessing and are traceable. Synthetic-only acceptance is insufficient.

**Progress note (21 Oct 2026):** section-fit now exposes algorithm name/version, actual fitting parameters, derived-cloud row-index semantics and count, per-face source-row samples, support, observed-span kind, RMS/P95 residuals, open corners and dimension conflicts. The panel also lists recent review decisions and neighboring unreviewed elements whose axis-aligned bounding boxes overlap; overlap is explicitly only context, not duplicate proof. Each proposed boundary edge reports observed segment length/fraction and unobserved length; inferred edges with no colocated observed segment remain at zero. This is boundary-segment coverage only. Area/point-cloud coverage and explicit unobserved-surface evidence remain open. Unit tests for closed and partially observed contours pass; the full demo integration could not run in the latest attempt because the C: drive had only 2.3 MB free and failed while generating its PLY fixture.

**Progress note (22 Oct 2026):** the panel can request five evenly spaced section fits within an oriented column and show point-supported, partial, no-points, ambiguous, or unknown status for sides U±/V±. Side assignment uses world-space contour corners transformed by the column yaw. No-points means no segment was detected in that slice; current evidence cannot distinguish occlusion from an area not scanned, and the map is not surface-area visibility.

**Progress note (23 Oct 2026):** the five-height observation map now sends one `section-fit-batch` request, which returns the same independent source-linked slice-fit responses without persisting geometry or type. Targeted backend API regression passes; frontend unit tests, TypeScript and production build pass. The endpoint still queries each slice independently, so only the browser round-trip count is reduced; pilot accuracy remains unassessed.

**Progress note (22 Oct 2026):** manual column-annotation writes now recalculate the source snapshot after acquiring `BEGIN IMMEDIATE`, preventing a concurrent recognition/reimport update from accepting a stale revision into the current view. Two new regressions cover the reimport race and parallel append-only revisions; both fail/pass under TDD. Full backend suite: 286 passed with one existing Starlette/httpx deprecation warning. UI recovery of archived annotations and delete/reimport lifecycle coverage remain open.

**Progress note (22 Oct 2026):** deleting a recognized column candidate leaves its independent manual annotation in the cloud history; reimporting the exact same candidate geometry restores that annotation when the snapshot hash matches. A changed snapshot keeps the old annotation archived. The recovery action creates an editable draft bound to the current snapshot and still requires explicit review/save. Targeted lifecycle regression: 1 passed. Real labeled workshop members and independently validated grid/levels remain outstanding.

### Task 8: Deliver AutoCAD 2026 plans, schedules, and editable DWG

**Files:** `backend/scan2bim/cad/structural_drawings.py`, `backend/scan2bim/cad/dxf.py`, `backend/scan2bim/cad/pdf.py`, `backend/scan2bim/cad/sheets.py`, frontend export panels, `backend/tests/test_structural_dxf.py`, `backend/tests/test_structural_drawings.py`, `docs/validation/AUTOCAD_PILOT.md`.

**Interfaces:** Drawing export consumes one frozen structural-model version and an explicit sheet/template request. Outputs include editable DXF, PDF preview, drawing manifest, element-ID schedule, review/unknown flags, and QA report; DWG is a separately verified AutoCAD save operation.

- [x] Generate column and crane-girder plan DXF/PDF, A3 sheets, scale fragments, short marks, full-ID schedule and geometry dimensions; synthetic 120-column pagination/scale checks exist.
- [x] Add a per-fragment X/Y envelope for the physical geometry visible in the PDF window when an overall dimension cannot fit; label it as bounding-box extent, never as an axis chain or engineering acceptance dimension.
- [x] Add explicit draft/final issue selection to DXF/PDF export: user-facing default is final; draft is prominently marked “not for work”; final includes only confirmed/corrected elements and confirmed column types.
- [x] Prepare a source-hashed, immutable AutoCAD pilot package with DXF/PDF drafts and final-empty controls; short drawing marks map to full IDs in the schedule. See `docs/validation/AUTOCAD_PILOT.md`.
- [ ] Finish measured axis/grid lines, chain dimensions, level annotations, dimension styles, title block, layer names, fonts, north/orientation and agreed sheet template.
- [ ] Add plan/section views for trusses and bracing from the shared member model, with member/assembly schedules and unknown callouts.
- [x] Validate draft/final schedules against the synthetic full API model and frozen pilot package: no missing/duplicate exported IDs, candidates remain labeled, default final is empty until confirmation and then includes checked IDs only. Physical pilot IDs remain unverified.
- [x] Add a full four-sheet SPDS draft-album generator and local API/UI download. The ZIP contains four editable DXFs, individual PDFs, one combined PDF, and a manifest with source-element SHA-256, stable element IDs, grid-alignment version and draft-only release flag; public manifest paths are relative. Synthetic fixtures validate files and grid behavior. This prototype does not pass the AutoCAD acceptance gate.
- [ ] Open representative pilot DXFs in the user's installed AutoCAD 2026; verify units, coordinates, rotations, linetypes, dimensions, text, editability, print preview and PDF agreement.
- [ ] Save and reopen a DWG through AutoCAD; verify geometry and tables remain editable. If unavailable, release DXF/PDF only and keep DWG gate open.
- [ ] Record screenshots/checklist, AutoCAD build, template/hash and exact export hashes under `docs/validation/AUTOCAD_PILOT.md` plus local derived artifacts.

**Progress note (22 Oct 2026):** installed AutoCAD Core Console W.164.0.0 opened the pilot DXF read-only and audited 400 objects with 0 errors/0 fixes; SHA-256 still matches the immutable manifest. Core Console replaced Liberation fonts with `simplex.shx`. This is parser/schema evidence only; interactive AutoCAD review, font legibility, editing, plotting and DWG save/reopen remain unchecked.

**Progress note (22 Oct 2026):** the DXF/drawing regression modules pass together (25 tests). This closes automated regression only. The `acad` process currently has no visible main window; no interactive pilot review or DWG round-trip was claimed.

**Progress note (22 Oct 2026):** another AutoCAD 2026 launch was attempted with the frozen pilot DXF. Native window inspection remains unavailable in this computer session. A Core Console `SAVEAS` attempt stalled before command output, produced no DWG, and was terminated; input DXF hash and bytes still match the package manifest. GUI review and DWG save/reopen remain acceptance gates.

**Gate:** engineer accepts actual AutoCAD 2026 open/edit/print result; all element IDs reconcile to the frozen structural model; no false DWG claim.

**Progress note (22 Oct 2026):** empty-cloud integration testing found that duplicate legacy generators could shadow the evidence-based sheet builders. The public album route now resolves to the tested builders; empty classes are explicitly marked and no crane girders, trusses or braces are synthesized from a column grid. API/album and drawing tests pass. AutoCAD GUI/DWG acceptance remains open.

### Task 9: Deliver IFC and Revit 2027 model, schedules, views, and sheets

**Files:** `backend/scan2bim/bim/model.py`, `backend/scan2bim/bim/ifc.py`, versioned BIM JSON schema, `integrations/revit/Scan.Plugin/`, `backend/tests/test_structural_ifc.py`, contract/importer tests, `docs/validation/REVIT_PILOT.md`.

**Interfaces:** IFC and JSON serialize the same stable member IDs, units, transform, role/type/review status, measured dimensions, source evidence, assembly and unsupported shape status. Re-import is idempotent by SCAN ID and does not delete unrelated or absent prior objects.

- [x] Export IFC4 and preserve 33/33 IDs/classes/statuses in the latest recorded pilot check; add-in builds and registers locally.
- [x] Publish `scan2bim.bim/1.0` JSON schema; validate coordinate frame and unique element IDs before Revit import transaction. Existing 1.0 payloads without the additive frame field remain readable.
- [x] Prepare synthetic Revit 2027 import-run fixtures for create/update/absent-ID preservation/unsupported-truss behavior, plus a malformed geometry payload that fails after transaction start; validate the valid fixtures against BIM 1.0. See `docs/validation/REVIT_PILOT.md`.
- [ ] Add round-trip tests for rectangular, arbitrary-profile, stepped, sloped, circular, unknown and assembled members.
- [ ] Load the add-in inside Revit 2027 and import into a disposable RVT; test malformed element rollback and unsupported-element reporting.
- [ ] Import the same JSON twice and verify no duplicate elements; update a changed member and verify ID, type, parameters and geometry update without deleting absent elements.
- [ ] Map only supported confirmed profiles to reusable parametric families; retain explicitly marked editable DirectShape for unsupported/unknown built-ups.
- [ ] Build truss and bracing assemblies from individually identified members; create and verify plans, elevations, sections, tags, schedules and sheets in a project template.
- [ ] Save, close and reopen RVT; compare IDs, counts, dimensions, levels, grids, orientation and schedules with source JSON/IFC.
- [ ] Record Revit build, API/runtime, template hash, accepted/unsupported family coverage and evidence in `docs/validation/REVIT_PILOT.md`.

**Gate:** successful interactive Revit 2027 load/import/reimport/save/reopen plus manual review of model and sheets. A successful compile or IFC export alone does not pass.

### Task 10: Process and validate the entire workshop

**Files:** `backend/scan2bim/jobs.py`, `backend/scan2bim/structure/batch.py`, `scripts/validate_workshop.py`, `backend/tests/test_batch_resume.py`, `docs/validation/WORKSHOP_ACCEPTANCE.md`.

**Interfaces:** Each resumable job records source hashes, derived-data version, algorithm and parameter manifest, ROI/bay IDs, progress counters, cancellation state, output hashes and errors. Rerun of a finished tile is idempotent; a partial tile is never published as complete.

- [ ] Partition the scan by measured structural bays with overlap; reconcile seam members by evidence/ID, not by snapping geometry to the grid.
- [ ] Add cancel/resume/failed-tile recovery, bounded RAM, cache quotas, progress based on real counts, logs and disk-space checks.
- [ ] Process the full source at exact resolution with A2 index and canonical-query checks; measure runtime, peak RAM, disk and skipped/unknown regions.
- [ ] Run column, girder, truss and bracing evaluation on independent train/held-out bays and report per-class false merges, missed elements, dimensions, axes, levels, coverage and unknowns.
- [ ] Reconcile every CAD and BIM schedule to one frozen structural-model manifest; fail export on ID or count mismatch.
- [ ] Review unresolved/occluded regions and corrections per class; run independent selected measurements against accepted tolerances when supplied.
- [ ] Produce a versioned QA package containing manifests, hashes, metrics, unresolved items, export hashes and software versions; preserve previous release artifacts.

**Gate:** whole-shop results are reproducible after cancellation/restart, held-out metrics meet agreed tolerances, all IDs reconcile, and all unresolved regions are called out.

### Task 11: Register separate FARO stations and create a ReCap project (conditional)

**Files:** future `backend/scan2bim/registration/`, `backend/scan2bim/formats/recap_export.py` only if an official supported writer exists, `frontend/src/components/RegistrationWorkspace.tsx`, registration tests and `docs/validation/RECAP_REGISTRATION.md`.

**Interfaces:** Each station has immutable source hash, sensor metadata, units, initial pose, pairwise transform, pose-graph revision, residual/control evidence, reviewer and registration state. RCP/RCS output uses an official Autodesk or licensed SDK path; no proprietary codec is reverse engineered.

- [ ] Start only after user-provided separate station scans or a structured E57 with per-station poses are available. Confirm station IDs, units, overlap, target/control measurements and coordinate frame.
- [ ] Benchmark Open3D ICP/GICP and small_gicp on the actual overlap; add TEASER++ only if it demonstrably improves robust coarse alignment and licensing is suitable.
- [ ] Implement pose graph and reversible registration review; test known transforms, low overlap, symmetric bays, loop closure, bad control and drift.
- [ ] Validate registration against independent targets/control points and propagate residual/error into every station transform.
- [ ] Select an official ReCap/SCENE workflow or licensed SDK; verify current product capability/rights before implementation.
- [ ] Export or assemble the linked project, open it in ReCap, verify stations, orientation, controls and portability after copying the complete package.

**Gate:** actual multi-station registration and generated project open correctly in ReCap and pass independent control checks. Until then, report this work package as waiting for sources.

**Progress note (22 Oct 2026):** the current writer produces only a SCAN pose metadata JSON, not an Autodesk RCP/RCS project; it now reports `metadata_only` and `recap_project_generated=false`. The release script no longer invents a single station, identity pose, or residual. Separate station sources, control measurements, an official writer, ReCap open and acceptance remain pending.

## Release Sequence

| Release | Includes | Required evidence before user review |
|---|---|---|
| V0 — frozen pilot | Tasks 0–3 | Reproducible baseline, immutable inputs, physical pilot annotations started, point/query and structural contracts validated. |
| V1 — reviewed columns and crane girders | Tasks 4, 5, 7 plus column/girder subset of 8 | Measured sections and supports linked to points, independent review, errors reported, column/girder DXF/PDF opened in AutoCAD. |
| V2 — trusses and bracing | Tasks 6–8 | Member networks and assemblies reviewed, complete plans/sections/schedules accepted in AutoCAD. |
| V3 — Revit 2027 pilot | Task 9 | Interactive add-in import/reimport, saved/reopened RVT, families/DirectShape disposition, reviewed sheets and schedules. |
| V4 — full workshop | Task 10 | Restartable full scan, held-out acceptance, reconciled exports and unresolved-zone report. |
| VR — FARO/ReCap | Task 11 | Conditional on separate station sources; verified registration and portable ReCap package. |

## Immediate Next Actions

1. Continue Task 4 on column sections: keep unsupported pilot heights unknown; prepare the 16-row physical annotation set for later engineer review without inventing physical IDs or changing frozen v15 reports.
2. Continue Task 5 adversarial cases: separate rail from girder only when 3D evidence supports it; test end plates, support ends, repeated spans and ducts/trays while keeping ambiguous profile and physical role unknown.
3. Continue Task 6 topology: keep partial roof trusses with both observed chords and internal members in review; next cover a missing chord, stronger occlusion and overlapping bays while preserving source evidence and unresolved members.
4. Continue Task 2 on a separate derived full-resolution dataset: measure point count, omissions, resolution, wall time, peak RAM and disk; test cancellation/restart. Do not access the protected original RCS.
5. Keep AutoCAD 2026 and Revit 2027 host acceptance in their later release stages, after the structural proposals and review flow are stable. Their GUI launch/import tests are not the active work item.
6. When independent field measurements become available, record the engineering tolerance and control dimensions. Until then, preserve raw residuals and leave pass/fail accuracy unassessed. ReCap registration remains conditional on separate FARO stations and control observations.

## Progress Tracking Rules

- Change a checkbox to `[x]` only when its listed evidence exists and the stated verification has run successfully; link its report/test in the same commit.
- A test or compile result proves only the scope it exercises. A pilot screenshot, synthetic run, IFC export, or add-in build cannot substitute for an AutoCAD/Revit user acceptance gate.
- After each completed work package update `docs/status-panel.html`, `docs/STATUS.md`, `docs/validation/PROGRESS.md`, and this plan. Show only fully accepted milestones as green checks.
- Keep calendar estimates out until Task 0 measures full-run time and Task 1 measures engineer labeling/review throughput.
- Keep unresolved questions visible, but ask only when the next concrete release decision depends on them; do not use the undefined tolerance to stop unrelated engineering work.
