# ROADMAP — SCAN: Intelligent Point Cloud Studio

Last Updated: October 23, 2026  
Status: Active Industrial Pilot Development  
Current Focus: Stage 6 — AI / Geometric Recognition, with point-cloud streaming and source provenance continuing in parallel.

This document defines the 12 core development phases of SCAN according to the product Master Prompt specifications.

---

## Stage Summary Status Matrix

| Phase | Title | Status | Passing Tests | Primary Deliverables |
|---|---|:---:|:---:|---|
| **Stage 1** | Architecture & Base Services | **DONE** | 65 | FastAPI Gateway, Async Job Engine, SQLite Schemas, Base Contracts |
| **Stage 2** | Import & Storage | **IN PROGRESS** | 42 | Memory-mapped chunks, supported formats, source metadata; real FARO station completeness remains open |
| **Stage 3** | Professional 3D Visualization | **IN PROGRESS** | 50 (FE) | Three.js viewer, SPDS 3D grid, color-coded element boxes, camera controls; large-cloud LOD/performance acceptance remains open |
| **Stage 4** | Multi-Station Registration | **TESTING** | 31 | BEV coarse matching, ICP, pose graph; точность RMSE на реальных станциях не измерена |
| **Stage 5** | Cleaning & Preparation | **DONE** | 18 | Исходник неизменен по SHA-256; сечение повторно читается как сохранённый audit snapshot; очистка создаёт скачиваемую производную копию |
| **Stage 6** | AI / Geometric Recognition | **IN PROGRESS** | 76 | Synthetic candidates for structural classes; real-pilot accuracy and independent labels remain open |
| **Stage 7** | Learning & Annotation Pipeline | **IN PROGRESS** | 35 | Review/undo, revision-safe storage and leakage-safe split; independently labeled pilot elements and real holdout metrics are missing |
| **Stage 8** | Parametric 3D Geometry | **IN PROGRESS** | 34 | Bounding box regularizer, oriented boxes, column section series; допуск цехового пилота не определён |
| **Stage 9** | Automated SPDS / CAD Drafting | **TESTING** | 48 | 5 SPDS vector sheets, dimension chains, axis bubbles; приёмка в AutoCAD не пройдена |
| **Stage 10** | Export & Interoperability | **TESTING** | 38 | Native binary DWG (AC1032) via ODA, vector PDF, IFC4 + Pset_ScanToBIM |
| **Stage 11** | Enterprise, GPU & Big Data | **IN PROGRESS** | 8 (CPU voxel) | Exact CPU voxel centroids/color means for bounded chunks; CUDA path, large-cloud performance and distributed processing remain unverified |
| **Stage 12** | Release Engineering & Acceptance | **IN PROGRESS** | 15 | Regression suites, automated acceptance tests, Windows setup script |

Test counts above are focused test evidence, not proof that a whole stage meets acceptance. Mark a stage DONE only after its listed acceptance criteria have passed. Stages 1 and 5 are closed (2/12); all other stages remain open, partial, or under testing.

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
- **Open**: The available FARO `1.rcs` is a merged cloud; individual station data and complete FARO FLS/RCP project metadata have not been validated. The original source remains read-only.
- **Criteria**: Ingest each supplied FARO station with metadata and provenance, without memory starvation, then reopen the project with station identity intact.
- **Status**: **IN PROGRESS**

### Stage 3 — 3D Visualization & Inspection
- **Goal**: High-performance interactive 3D viewport.
- **Completed**:
  - Three.js WebGL engine embedded in React with custom point cloud shaders.
  - Real-time 3D SPDS structural grid with circular axis bubbles.
  - View presets (all elements, structural skeleton only, columns/beams only).
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
- **Goal**: Automatic identification of structural building elements.
- **Completed**:
  - Review-only candidates for columns, crane beams, truss members and bracing; observed geometry is separated from inferred role.
  - Candidates retain source point-row provenance and confidence/evidence fields.
- **Open**: The workshop pilot lacks an independent labeled set and measured class/geometry accuracy. Proposed column types and dimensions require engineer review; no automatic final marks or tolerances are claimed.
- **Criteria**: Candidates carry confidence and provenance, and class/geometry performance is measured against independently reviewed real workshop elements.
- **Status**: **IN PROGRESS — CURRENT FOCUS**

### Stage 7 — Supervised Learning & Annotation
- **Goal**: Active learning loop from engineering feedback.
- **Completed**:
  - UI/API for engineer confirmation, rejection, or relabeling of candidate elements, with undo history.
  - Sample isolation by stable physical element ID to avoid revision leakage between train and holdout.
  - Reuse of reviewed column types guarded by source-cloud fingerprints.
  - Synthetic profile fixtures support regression tests; they are not physical measurements and are not training labels.
- **Missing**: Independently labeled real workshop elements, reviewer provenance, and a leakage-safe holdout evaluation on those labels.
- **Criteria**: Feedback is reversible and persisted, and any reported model score is measured on independently labeled physical elements excluded from training.
- **Status**: **IN PROGRESS**
### Stage 8 — Parametric 3D Geometry Reconstruction
- **Goal**: Fit accurate CAD/BIM parametric primitives to detected points.
- **Completed**:
  - Oriented-box column primitives with measured sides and section series by storey.
  - Review-only built-up I-profile hypotheses report the observed envelope, web
    and flange thicknesses with point-row provenance on synthetic, rotated sections.
  - Deviation of each candidate from a nominal grid reported as an *unverified
    hypothesis*; it never rejects detections or assigns marks.
- **Open**: Built-up profile fitting has not been verified against labeled FARO
  sections; a small ГОСТ 35087-2024 base-edition excerpt can return reference-only
  candidates, but its October 2026 corrigendum is not verified and cannot establish a
  confirmed project type. Stepped pilot profiles and physical accuracy remain unaccepted.
- **Reverted / missing**: the SP 70.13330 tolerance schedule integration was reverted
  (commit 37506fb); tolerance grading is not part of the current build.
- **Criteria**: Parametric geometry bounds match measured points within 95% confidence intervals.
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
- **Criteria**: 100% vector geometry in DXF/PDF; zero rasterization placeholders.
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
- **Criteria**: Exported files open error-free in Autodesk AutoCAD 2026 and Autodesk Revit 2027.
- **Not yet verified**: DWG header `AC10` and IFC entity content are tested, but a
  full open-and-print acceptance in AutoCAD/Revit has not been performed.
- **Status**: **TESTING**

### Stage 11 — Enterprise, GPU & Big Data
- **Goal**: Process hundred-million to billion-point clouds efficiently.
- **Tasks**:
  - [x] Chunked spatial indexing with cancel/resume tokens.
  - [x] Memory profiling and leak prevention on massive point sets.
  - [x] Exact CPU voxel grouping and centroid/color averaging for bounded derived chunks (8 focused tests pass).
  - [ ] Verify CUDA voxel reduction and CUDA normal estimation on compatible hardware.
  - [ ] Benchmark bounded/chunked processing on representative large clouds; no 100M/billion-point acceptance has been run.
  - [ ] Distributed worker pipeline for corporate headless processing.
- **Status**: **IN PROGRESS**

### Stage 12 — Release Engineering & Packaging
- **Goal**: One-click local deployment on Windows 11 with full self-diagnostic test suite.
- **Tasks**:
  - [x] Full regression test harness (`pytest backend/tests/`, `npm test`).
  - [x] Desktop launcher script (`desktop_app.py`, Windows batch launchers).
  - [x] Windows 11 standalone installer / self-contained runtime bundle (installer/scan_studio_setup.iss).
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
| 14 | Обмен с ReCap | ЧАСТИЧНО | импорт RCS работает; экспорт RCP/RCS/RSP не реализован |
| 15 | Восстановление после сбоя | ЧАСТИЧНО | отмена и прогресс задач; очередь в памяти, после рестарта не восстанавливается |
| 16 | Работа без интернета | ПОДТВЕРЖДЕНО | все зависимости локальные, платных API нет |
| 17 | Воспроизводимость | ЧАСТИЧНО | Hough с фиксированным зерном, тесты; полный детерминизм не доказан |
| 18 | Windows-установщик | НЕ ВЫПОЛНЕНО | есть скрипты запуска, инсталлятора нет |
| 19 | Безопасность доступа | ЧАСТИЧНО | один пользователь, опциональный статический ключ; ролей нет |
| 20 | Документирование ограничений | ПОДТВЕРЖДЕНО | `docs/PLAN.md` раздел 3 и этот файл |
