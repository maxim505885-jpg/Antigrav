# SCAN Column Typology and Learning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Each task follows TDD and ends with verification.

**Goal:** Find repeated column section types from measured point-cloud geometry, learn confirmed project types, and produce dimensioned, editable plans without altering measured geometry.

**Architecture:** Add an explainable geometry descriptor and grouping proposal layer beside the existing steel recognizer. Store confirmed project type prototypes and instance assignments through reversible review actions. Generate drawing marks and schedules from this shared type catalog while retaining a unique ID and measured geometry for each column.

**Tech Stack:** Python, FastAPI, SQLite, NumPy/SciPy, React/TypeScript, ezdxf, existing PDF renderer, pytest, frontend tests.

**Spec:** `docs/superpowers/specs/2026-10-21-column-typology-learning-design.md`

## Global Constraints

- Keep the local source `1.rcs` unchanged, offline and out of Git; use derived validation data only.
- Store geometry in metres and preserve the existing world/local coordinate transforms.
- Treat the 6000 mm pitch as a review hint; never snap or rewrite measured locations or dimensions.
- Every physical column keeps its own stable element ID and measured dimensions even when assigned to a shared type mark.
- Grouping output starts as a proposal; only engineer confirmation creates/updates a confirmed project type.
- Do not infer a steel catalogue designation from two outer dimensions alone.
- Preserve review history and undo behavior; repeated recognition/export must not create duplicate type assignments or drawing elements.
- Report confidence as a heuristic with its evidence, not as calibrated probability.

## Review Focus

- Similar boxes with dimensions just inside/outside the configured threshold: prove stable grouping and no measurement snapping.
- Rectangles rotated by 0°, 90°, 180° and 270°: prove equivalent footprints group consistently while each instance orientation remains intact.
- Stepped or built-up columns: prove coarse bounding boxes do not silently merge them into solid uniform columns.
- Partially scanned columns: prove sparse evidence lowers confidence and does not become a confirmed type.
- Rerun, split, merge, reject and undo: prove confirmed human decisions and stable IDs remain consistent.

## File Map

- Create `backend/scan2bim/structure/column_types.py`: canonical descriptors, similarity and deterministic proposal grouping.
- Create `backend/tests/test_column_types.py`: unit tests for dimensions, orientation, morphology, uncertainty and grouping.
- Modify `backend/scan2bim/db.py`: additive migration for the project type catalog and type assignment history.
- Create `backend/scan2bim/structure/column_type_store.py`: catalog CRUD, assignment, review and undo persistence.
- Modify `backend/scan2bim/api/app.py`: project/cloud type proposal and review endpoints.
- Modify `backend/tests/test_recognition_reconcile_api.py` or create `backend/tests/test_column_type_api.py`: API contract and rerun safety.
- Modify `backend/scan2bim/cad/dxf.py`: type marks, per-instance IDs and type schedule rows.
- Modify `backend/tests/test_structural_drawings.py`: four-corner geometry and type mark/schedule assertions.
- Modify `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/components/ElementTable.tsx`, and `frontend/src/styles.css`: review proposed groups and show type membership/evidence.
- Create or extend frontend tests for group confirmation, reassignment, and undo behavior.
- Add `docs/validation/column-types-pilot.md` after the evaluation slice is selected and manually labeled.

## Implementation Tasks

### Task 1: Canonical measured column descriptors

**Files:** Create `backend/scan2bim/structure/column_types.py`; test `backend/tests/test_column_types.py`.

**Interfaces:** `column_descriptor(element: dict[str, Any]) -> dict[str, Any]` returns `element_id`, canonical `long_side_m`, `short_side_m`, `area_m2`, the measured `long_axis_angle_rad` normalized to the rectangle's 180-degree symmetry (or null if absent), `morphology`, `morphology_evidence`, `evidence_coverage`, and `measurement_sources`. Missing or malformed measurements return an explicit `eligible=False` descriptor with reasons; they are never replaced by a catalog nominal size.

- [x] Write tests for exact two-side extraction, long/short normalization, each right-angle rotation, missing dimensions, invalid values, and stepped/build-up evidence preservation.
- [x] Run `pytest backend/tests/test_column_types.py -q` and confirm the new descriptor tests fail because the function is absent.
- [x] Implement `column_descriptor` using measured dimensions first and section-profile metadata only as morphology/evidence.
- [x] Re-run the focused tests: 9 passed. Full backend suite remains part of cross-task verification with `S2B_DATA_DIR` and pytest temp paths inside `data/validation/`.

### Task 2: Explainable repeated-type proposals

**Files:** `backend/scan2bim/structure/column_types.py`; `backend/tests/test_column_types.py`.

**Interfaces:** `propose_column_types(elements: list[dict[str, Any]], *, linear_tolerance_m: float, relative_tolerance: float = 0.01) -> list[dict[str, Any]]`. Each proposal contains a deterministic proposal key, member element IDs, representative measured sides, per-member residuals, morphology agreement, evidence summary, heuristic confidence, and `status="proposed"`.

- [x] Add failing tests for repeated equal sections, one-off types, small dimension noise, threshold boundaries, rotation-equivalent rectangles, and incompatible stepped/solid morphology.
- [x] Run the focused tests and verify failure on the absent grouping function.
- [x] Implement deterministic clustering with both tolerances supplied by project settings; never alter member geometry.
- [x] Verify repeatability under input reordering and test that a single column remains a valid one-member type proposal.
- [x] Run focused tests: 16 descriptor/grouping tests and the long-path PDF regression pass. The full backend suite subsequently passed with an isolated test data directory and approved access to Windows temporary directories.

### Task 3: Project catalog and reversible assignments

**Files:** Modify `backend/scan2bim/db.py`; create `backend/scan2bim/structure/column_type_store.py`; create `backend/tests/test_column_type_store.py`.

**Interfaces:** `list_column_types(project_id: str) -> list[dict]`, `confirm_column_type(project_id: str, proposal: dict, mark: str | None = None, engineer: str = "engineer", note: str = "") -> dict`, `assign_column_type(element_id: str, type_id: str, ...) -> dict`, and `undo_column_type_action(action_id: str, ...) -> dict`.

- [x] Add failing store tests for migration on an empty DB, creating a confirmed type, adding members without replacing IDs/dimensions, rejecting cross-project assignments, duplicate confirmation idempotency, and undo restoring prior assignments.
- [x] Run focused tests against an isolated writable test DB and confirm behavior is absent.
- [x] Add additive tables for project-scoped type prototypes and an append-only action history; do not rewrite existing element IDs.
- [x] Implement catalog operations and idempotent assignment/undo, including stale-action guards and idempotent undo.
- [x] Focused store/API regression tests and the full backend suite pass. The full run used an isolated test data directory and approved execution to permit Windows temporary-directory traversal/cleanup.

### Task 4: API for proposals and engineer decisions

**Files:** Modify `backend/scan2bim/api/app.py`; create `backend/tests/test_column_type_api.py`.

**Interfaces:** `GET /api/v1/clouds/{cloud_id}/column-types` returns proposals plus confirmed catalog entries; `POST /api/v1/column-types/{proposal_key}/confirm` confirms a proposal with optional mark/note; `POST /api/v1/elements/{element_id}/column-type` assigns or clears membership; `POST /api/v1/column-types/actions/{action_id}/undo` reverses a type action.

Review-contract extension: `POST /api/v1/column-types/{proposal_key}/reject` records a project-scoped rejection with cloud context, matching tolerances and review note. GET also returns `rejected_proposals`; these stay out of active proposals until their rejection action is undone. Rejecting a group does not reject any physical column.

- [x] Add failing API tests for proposed status, evidence details, confirmation, assignment validation, unknown IDs, undo and repeated calls.
- [x] Run focused tests and verify the routes do not exist.
- [x] Implement routes using the descriptor/grouping and store interfaces; derive project ownership from the element/cloud records rather than trusting request IDs.
- [x] Re-run API tests and existing feedback/undo tests: 35 focused tests passed across typology, persistence, API, feedback undo, and recognition reconciliation.

### Task 5: Review repeated groups in the SCAN interface

Progress: review panel, durable decisions, measured group outlines, narrow-viewport camera fit, split by clearing a member then confirming a new type, and undo are implemented and interactively checked on isolated synthetic data. 13 frontend tests, TypeScript and build pass. Automated React control/state coverage and real-pilot acceptance remain open; do not equate browser synthetic checks with engineering acceptance.

**Files:** Modify `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/components/ElementTable.tsx`, `frontend/src/styles.css`; create frontend tests beside the relevant modules.

- [ ] Add failing UI/state tests for listing a proposal, seeing dimensions and residuals, confirming as `К1`, creating another type, assigning a member, rejecting a proposal, and undoing the last action.
- [ ] Run the focused frontend test command and confirm the expected controls/state are missing.
- [x] Add a compact review panel that selects all instances in a type group and displays per-instance measured dimensions, confidence/evidence, and exceptions.
- [x] Keep proposal, confirmed, corrected and rejected states visually distinct; do not show proposed types as approved facts.
- [x] Run `npm test`, `npx tsc -b`, and `npm run build`.

### Task 6: Type-aware column plan and schedule

Progress: measured corners, type marks, residuals and DXF-derived schedule are implemented; 17 structural drawing tests pass. Fixed-scale fragments and 25-row schedule pages preserve all 120 IDs in synthetic 1:100 and 1:500 bundles. Partial dimensions are excluded from details while complete global measurements remain on overview and are repeated numerically. Printed geometry scale and 2.5 mm annotation height tested at 1:50/100/200/500. Axis dimension chains, edge-page review and AutoCAD acceptance remain open.

**Files:** Modify `backend/scan2bim/cad/dxf.py`, `backend/tests/test_structural_drawings.py`, and existing PDF/API export tests.

- [x] Add failing DXF tests for exactly four footprint vertices from the measured sides and rotation; equivalent rotations; type marks shared by confirmed members; unique element IDs retained in the schedule; proposed/unreviewed labels; and measured-dimension residuals.
- [x] Run focused tests and confirm current per-element C-marks do not meet the type schedule assertions.
- [x] Extend the export input contract with the confirmed/proposed type catalog. Draw each physical rectangle from that element's own measured dimensions, and print the shared mark plus member ID in the schedule.
- [x] Keep the PDF export derived from the same DXF modelspace geometry/schedule; add page-layout tests if the schedule grows beyond one sheet.
- [x] Run `pytest backend/tests/test_structural_drawings.py backend/tests/test_api_pipeline.py -q`, audit generated DXF, and render a PDF preview for visual review.

### Task 7: Pilot annotation and grouping evaluation

Progress: independent annotation template and JSON-bound evaluation tooling implemented. 16 evaluation/CLI tests pass. Pilot snapshot sweep (6 settings) produces 16 singleton proposals; 16 pending references mean precision/recall remain null. Protocol: `docs/validation/column-types-pilot.md`. Actual annotation and acceptance remain open.

**Files:** `docs/validation/column-types-pilot.md`; a derived-data-only annotation fixture under `data/validation/pilot-A/` (ignored by Git); tests under `backend/tests/`.

- [ ] Select a manageable set of visible pilot columns and annotate physical instance ID, measured short/long sides where visible, morphology, confidence/occlusion, and human-assigned type.
- [x] Add tests that calculate pairwise grouping precision/recall, false merges, false splits, unknown coverage, and per-member dimension residuals from the annotation fixture.
- [ ] Run evaluation over more than one tolerance setting and record which settings produce a useful proposal/unknown balance; do not choose a production setting without engineering review.
- [x] Keep the control annotation separate from recognition output; document where the scan cannot support a definite label.
- [x] Update the status panel and progress log with measured outcomes and open limits.

### Task 8: Controlled project learning and reuse

Progress: deterministic catalog reuse is connected to API and UI. Cross-cloud matching, ambiguity, incomplete visibility, stale sources, project isolation, explicit assignment and undo checked on synthetic data. Report: `docs/validation/COLUMN_TYPE_REUSE.md`. Real-pilot evaluation and production acceptance remain pending. Task 7 is not bypassed by this infrastructure.

**Files:** `backend/scan2bim/structure/column_type_store.py`, `backend/scan2bim/recognition/steel.py`, `backend/scan2bim/api/app.py`, `backend/tests/test_column_type_store.py`.

- [x] Add failing tests showing that a confirmed type from one cloud in a project can be proposed for a geometrically matching column in another cloud, while a different project remains isolated.
- [x] Implement project-catalog matching as a proposal source and include source type ID, descriptor residuals and evidence coverage.
- [x] Add tests for profile changes, incomplete visibility, conflicting user labels and deleted/rejected elements; conflicts remain review items.
- [x] Keep deterministic prototypes active by explicit review only. If a statistical model is later introduced, require a held-out evaluation and explicit activation using the existing model-version controls.
- [ ] Run backend tests and record catalog behavior in the pilot report.

### Task 9: AutoCAD 2026 acceptance

**Files:** `docs/validation/column-types-pilot.md`; generated local DXF/PDF only.

- [ ] Open the type-aware DXF in AutoCAD 2026 and verify units, four-corner footprints, rotations, marks, layer visibility and editable schedule.
- [ ] Verify A3 PDF output against the same plan and record text size, clipping, dimension readability and print preview.
- [ ] Save a DWG copy through AutoCAD and reopen it; verify dimensions and polylines remain editable.
- [ ] Record the AutoCAD version, drawing settings and result. Keep this acceptance pending until tested in the user's interactive session.

### Task 10: Revit 2027 handoff

**Files:** `integrations/revit/Scan.Plugin/ImportStructuralModelCommand.cs`, plugin tests or a testable contract library, `docs/validation/column-types-pilot.md`.

- [ ] Extend the neutral BIM JSON with project type ID/mark, measured per-instance dimensions, review state and evidence metadata; add schema tests before importer changes.
- [ ] Map confirmed type prototypes to reusable Revit families only where the section is supported; keep unknown/built-up/stepped elements as explicit editable DirectShape until a validated family mapping exists.
- [ ] Add importer tests for reimport idempotency, duplicate IDs, type consistency and unsupported profiles.
- [ ] Build against the installed Revit 2027 API/.NET 10 SDK; test in a disposable RVT and verify repeated import creates no duplicate elements.
- [ ] Save/reopen the test RVT, verify schedules and views, and document family coverage. Do not mark A8 complete before interactive acceptance.

### Task 11: Expand from columns to the whole workshop

**Files:** Existing `backend/scan2bim/recognition/steel.py`, `backend/scan2bim/structure/`, drawing exporters, review UI, and `docs/superpowers/plans/2026-10-21-scan-workshop-roadmap.md`.

- [ ] Reuse the same candidate → evidence → review → confirmed catalog pattern for crane girders, truss members/assemblies and bracing, preserving each geometry's uncertainty.
- [ ] Build control slices per structure class; measure false joins, missed members, axis/level residuals and profile mismatches.
- [ ] Produce complete column, crane-girder, truss and bracing plans/sections, editable DXF/DWG and Revit 2027 views/schedules only after their class-specific acceptance tests pass.
- [ ] Scale point ingestion/indexing to the full local cloud in isolated processing and benchmark time/memory before full-shop export.
- [ ] Run the end-to-end pilot, record unresolved occlusions/unknowns, and issue a reproducible QA package. Keep FARO registration R1–R3 separate until individual source stations are supplied.

## Execution Order

Tasks 1–2 are the first implementation slice. Tasks 3–4 form the persistent review layer. Tasks 5–6 deliver the first visible benefit: repeat type marks and measured four-sided column outlines in the plan. Task 7 gates threshold tuning. Tasks 8–10 reuse confirmed knowledge and validate CAD/BIM integrations. Task 11 expands validated behavior to the whole workshop. Do not start by training a deep network on the current small, unreviewed candidate set.
