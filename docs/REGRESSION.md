# SCAN cross-module regression ledger

This ledger records downstream consumers and executable acceptance commands for the scan-to-BIM modules. It supplements the feature plan and the independent physical pilot protocol; passing a command is not evidence of physical accuracy or CAD/Revit host acceptance.

Run backend commands from the repository root through `scripts/run_pytest.ps1`. It uses the project `.venv`, creates short unique test-data and pytest temp paths under `data/.t/` to stay below Windows path-length limits, and does not reuse or delete prior runs. If only default `pytest` is available on PATH, it may use the wrong Python environment.

## Dependency evidence

- Python package import edges can be refreshed with `rg -n "^(from|import) " backend/scan2bim`.
- Frontend and Revit adapter source edges can be refreshed with `rg -n "^(import |using |namespace )" frontend/src integrations/revit/Scan.Plugin`.
- Cross-boundary data flow is verified by the named integration/contract tests below. Where an edge is inferred from API semantics rather than a static import, the consumer test is included in the required propagation set.
- Recheck these scans and this ledger when modules, test layout, or API boundaries change. Do not claim a downstream edge is absent just because a static scan cannot resolve it.

## Modules

### Point-cloud formats, ingest, and spatial access

- Downstream consumers: recognition, API cloud lifecycle, review-point queries, exports.
- Dependency evidence: imports/calls under `backend/scan2bim/formats`, `ingest`, `pointdata`, `geometry`; full-pipeline and point-query tests.
- Acceptance: `scripts/run_pytest.ps1 backend/tests/test_formats.py backend/tests/test_pointdata.py backend/tests/test_ingest_restart.py backend/tests/test_rcs_streaming_ingest.py`.
- Propagation: after changing normalized coordinates, units, row identity, colors, chunk boundaries, or resume semantics, also run `scripts/run_pytest.ps1 backend/tests/test_api_pipeline.py backend/tests/test_column_surface_assignment.py backend/tests/test_registration_api.py`.

### Recognition, geometry, and structural proposals

- Downstream consumers: review/annotation APIs, structural model contract, DXF/PDF/SPDS, IFC/Revit JSON, frontend viewer and tables.
- Dependency evidence: imports/calls under `backend/scan2bim/recognition`, `geometry`, and `structure`; cross-format assertions in `test_api_pipeline.py`.
- Acceptance: `scripts/run_pytest.ps1 backend/tests/test_steel.py backend/tests/test_frame_detection.py backend/tests/test_beam_source_lineage.py backend/tests/test_truss_source_lineage.py backend/tests/test_column_section_profile.py backend/tests/test_column_section_series.py backend/tests/test_column_surface_assignment.py backend/tests/test_structural_model_contract.py backend/tests/test_member_proposal.py`.
- Propagation: after changing candidate identity, class/role, axes, dimensions, provenance, or review state, also run API/review tests and all structural drawing/export suites: `scripts/run_pytest.ps1 backend/tests/test_api_pipeline.py backend/tests/test_feedback_undo.py backend/tests/test_recognition_reconcile_api.py backend/tests/test_structural_drawings.py backend/tests/test_structural_dxf.py backend/tests/test_structural_ifc.py backend/tests/test_spds_album_api.py backend/tests/test_spds_drawings.py backend/tests/test_spds_endpoints.py backend/tests/test_spds_full_set.py backend/tests/test_spds_full_set_safety.py`.

### API, persistence, and engineer review/learning

- Downstream consumers: frontend, desktop API client, structural export endpoints, project-scoped review history.
- Dependency evidence: routes/services/database imports plus OpenAPI, API-pipeline, persistence, and frontend request tests.
- Acceptance: `scripts/run_pytest.ps1 backend/tests/test_desktop_api.py backend/tests/test_openapi_schema.py backend/tests/test_api_pipeline.py backend/tests/test_column_type_api.py backend/tests/test_column_type_store.py backend/tests/test_feedback_undo.py backend/tests/test_recognition_reconcile_api.py`.
- Propagation: after changing request/response shapes, auth/project scoping, persisted review state, or error behavior, also run `cd frontend && npm test && npm run build`; for structural payload changes, run the recognition and export consumers above.

### CAD, drawing sets, and BIM interchange

- Downstream consumers: frontend download flow, AutoCAD DXF/PDF review, Revit JSON importer, schedules/manifests.
- Dependency evidence: export API routes and contract integration tests; full-pipeline element identity/provenance comparison.
- Acceptance: `scripts/run_pytest.ps1 backend/tests/test_structural_drawings.py backend/tests/test_structural_dxf.py backend/tests/test_structural_ifc.py backend/tests/test_spds_album_api.py backend/tests/test_spds_drawings.py backend/tests/test_spds_endpoints.py backend/tests/test_spds_full_set.py backend/tests/test_spds_full_set_safety.py backend/tests/test_api_pipeline.py`.
- Propagation: after changing the shared model, coordinate frame, units, IDs, or export schema, also run the frontend suite and build. Run the Revit adapter build when its payload contract changes. Actual AutoCAD/Revit GUI acceptance remains a separate release gate.

### Frontend application and review workflow

- Downstream consumers: API contracts, cloud/element identity, review and export actions.
- Dependency evidence: TypeScript imports under `frontend/src` and API contract tests.
- Acceptance: `cd frontend && npm test && npm run build`.
- Propagation: after changing API payloads or geometry semantics, also run `scripts/run_pytest.ps1 backend/tests/test_api_pipeline.py backend/tests/test_openapi_schema.py`.

### Revit 2027 adapter

- Downstream consumers: `scan2bim.bim/1.0` and the versioned structural model; emitted elements in a saved RVT.
- Dependency evidence: `integrations/revit/Scan.Plugin/ImportStructuralModelCommand.cs`, its project file, and the synthetic import-run contract fixtures in `integrations/revit/pilot/`.
- Acceptance: `dotnet build integrations/revit/Scan.Plugin/Scan.Plugin.csproj`; verify payload fixtures with `scripts/run_pytest.ps1 backend/tests/test_structural_model_contract.py backend/tests/test_structural_ifc.py`.
- Propagation: after changing importer behavior or the payload schema, rebuild and run `scripts/run_pytest.ps1 backend/tests/test_structural_model_contract.py backend/tests/test_structural_ifc.py backend/tests/test_api_pipeline.py`. Interactive import, reimport, save/reopen, rollback, sheets, and schedules require the later Revit 2027 host gate.

### FARO station registration and ReCap packaging

- Downstream consumers: aligned derived point clouds, registration manifest, ReCap package/API/UI.
- Dependency evidence: registration package imports and API tests; station-level physical acceptance requires individual station sources and independent controls.
- Acceptance: `scripts/run_pytest.ps1 backend/tests/test_registration_api.py backend/tests/test_stitching.py backend/tests/test_stitching_export.py`.
- Propagation: after changing transform, point identity, control-point, or package manifest semantics, also run `scripts/run_pytest.ps1 backend/tests/test_pointdata.py backend/tests/test_api_pipeline.py`. Do not read, modify, or upload the protected original `1.rcs` as part of regression checks.

## Audit report template

For each change, record the affected modules, acceptance commands, observed exit codes, downstream consumers run, any skipped command with its reason, and whether the evidence is synthetic, independently labeled, or an interactive host check. A missing independent label set or host gate is an open acceptance item, not a pass.
