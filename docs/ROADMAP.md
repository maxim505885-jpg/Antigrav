# ROADMAP — SCAN: Intelligent Point Cloud Studio

Last Updated: October 23, 2026  
Status: Active Industrial Pilot Development  

This document defines the 12 core development phases of SCAN according to the product Master Prompt specifications.

---

## Stage Summary Status Matrix

| Phase | Title | Status | Passing Tests | Primary Deliverables |
|---|---|:---:|:---:|---|
| **Stage 1** | Architecture & Base Services | **DONE** | 65 | FastAPI Gateway, Async Job Engine, SQLite Schemas, Base Contracts |
| **Stage 2** | Import & Storage | **DONE** | 42 | Memory-mapped chunks, E57, LAS, RCS/RCP, PTS, PLY, spatial octree index |
| **Stage 3** | Professional 3D Visualization | **DONE** | 50 (FE) | Three.js viewer, SPDS 3D grid, color-coded element boxes, camera controls |
| **Stage 4** | Multi-Station Registration | **DONE** | 31 | BEV neural coarse matching, Point-to-Plane ICP, Pose Graph Optimizer |
| **Stage 5** | Cleaning & Preparation | **DONE** | 28 | Non-destructive outlier filtering, horizontal & vertical slice rasterization |
| **Stage 6** | AI / Geometric Recognition | **DONE** | 76 | Walls, columns, crane beams, trusses, bracing, stairs, wall openings |
| **Stage 7** | Learning & Annotation Pipeline | **DONE** | 35 | KNN prior, element feedback undo/redo, holdout splitting without data leakage |
| **Stage 8** | Parametric 3D Geometry | **DONE** | 34 | Bounding box regularizer, oriented boxes, column section series, deviations |
| **Stage 9** | Automated SPDS / CAD Drafting | **DONE** | 48 | 5 full SPDS vector sheets, dimension chains, axis bubbles, tolerance tables |
| **Stage 10** | Export & Interoperability | **DONE** | 38 | Native binary DWG (AC1032) via ODA, pure vector PDF, IFC4 with Pset_ScanToBIM |
| **Stage 11** | Enterprise, GPU & Big Data | **IN PROGRESS** | 22 | Multi-core chunking, cancel/resume streaming, large dataset profiling |
| **Stage 12** | Release Engineering & Acceptance | **IN PROGRESS** | 15 | Regression suites, automated acceptance tests, Windows setup script |

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
  - Support for PTS, PLY, LAS/LAZ, E57, and Autodesk ReCap RCS/RCP.
- **Criteria**: Streaming ingestion without memory starvation or heap allocation spikes.
- **Status**: **DONE**

### Stage 3 — 3D Visualization & Inspection
- **Goal**: High-performance interactive 3D viewport.
- **Completed**:
  - Three.js WebGL engine embedded in React with custom point cloud shaders.
  - Real-time 3D SPDS structural grid with circular axis bubbles.
  - View presets (all elements, structural skeleton only, columns/beams only).
- **Criteria**: 60 FPS viewport navigation with 1M+ preview points.
- **Status**: **DONE**

### Stage 4 — Multi-Station Registration & Stitching
- **Goal**: Automated registration of overlapping point cloud stations without manual targets.
- **Completed**:
  - BEV structural feature extraction (density, height range, occupancy).
  - 2D FFT global angular search with 3D residual verification to break $180^\circ$ hall symmetry traps.
  - Sub-millimeter Point-to-Plane ICP refinement with surface normal estimation.
  - Multi-station pose graph network optimization with loop closure error distribution.
- **Criteria**: Registration residual $\text{RMSE} < 10.0\text{ mm}$ on industrial structures.
- **Status**: **DONE**

### Stage 5 — Point Cloud Preparation & Filtering
- **Goal**: Non-destructive noise removal and slice extraction.
- **Completed**:
  - Statistical and radius outlier filtering pipelines.
  - Adaptive 2D horizontal and vertical slice generation with user-defined thickness and resolution.
- **Criteria**: Original point cloud coordinates remain byte-identical; slices stored as audit snapshots.
- **Status**: **DONE**

### Stage 6 — AI & Structural Element Recognition
- **Goal**: Automatic identification of structural building elements.
- **Completed**:
  - Vertical columns with multi-height section verification.
  - Crane runways and runway beams.
  - Roof trusses, chords, and diagonal braces.
  - Stair runs (sloped planes between storeys) and wall openings (doors/windows with lintels).
- **Criteria**: Detected candidates carry explicit confidence metrics and distinction between observed geometry and functional role hypothesis.
- **Status**: **DONE**

### Stage 7 — Supervised Learning & Annotation
- **Goal**: Active learning loop from engineering feedback.
- **Completed**:
  - UI for engineer confirmation, rejection, or relabeling of candidate elements.
  - Strict sample isolation by physical element ID to avoid train/test leakage.
  - KNN feature priors and incremental model refinement.
- **Criteria**: Complete undo/redo history for every feedback operation.
- **Status**: **DONE**

### Stage 8 — Parametric 3D Geometry Reconstruction
- **Goal**: Fit accurate CAD/BIM parametric primitives to detected points.
- **Completed**:
  - Stepped industrial column modeling (Series 1.424.1 / 1.423.1).
  - Deviation calculation relative to nominal 3-span 4-row building grid ($\Delta U, \Delta V, \Delta R$).
  - Tolerance grading based on SP 70.13330.2012 (Table 4.9).
- **Criteria**: Parametric geometry bounds match measured points within 95% confidence intervals.
- **Status**: **DONE**

### Stage 9 — Automated SPDS / CAD Drafting
- **Goal**: Production-ready vector working drawings according to Russian SPDS standards.
- **Completed**:
  - **Sheet 01**: Column Layout Plan at el. 0.000 (M 1:200).
  - **Sheet 02**: Crane Runway & Girder Layout at el. +6.800 (M 1:200).
  - **Sheet 03**: Transverse Cross-Section 1-1 (M 1:100).
  - **Sheet 04**: Roof Truss & Bracing Layout (M 1:200).
  - **Sheet 05**: Executive Geodetic Deviation Scheme with SP 70 compliance schedule.
  - Standard title blocks (GOST 21.101-2020 Form 3), dimension chains, and axis tags.
- **Criteria**: 100% vector geometry in DXF/PDF; zero rasterization placeholders.
- **Status**: **DONE**

### Stage 10 — Export & Interoperability
- **Goal**: Seamless exchange with Autodesk AutoCAD, Revit, and ReCap.
- **Completed**:
  - Automated binary DWG compilation (AutoCAD 2018 format / AC1032) via ODAFileConverter / accoreconsole.exe.
  - IFC4 export with comprehensive `Pset_ScanToBIM` property sets (deviations, review status, grid axes).
  - Multi-page combined PDF drawing albums.
- **Criteria**: Exported files open error-free in Autodesk AutoCAD 2026 and Autodesk Revit 2027.
- **Status**: **DONE**

### Stage 11 — Enterprise, GPU & Big Data (Current Focus)
- **Goal**: Process hundred-million to billion-point clouds efficiently.
- **Tasks**:
  - [x] Chunked spatial indexing with cancel/resume tokens.
  - [x] Memory profiling and leak prevention on massive point sets.
  - [ ] Implement CUDA-accelerated normal estimation and voxel grid downsampling.
  - [ ] Distributed worker pipeline for corporate headless processing.
- **Status**: **IN PROGRESS**

### Stage 12 — Release Engineering & Packaging
- **Goal**: One-click local deployment on Windows 11 with full self-diagnostic test suite.
- **Tasks**:
  - [x] Full regression test harness (`pytest backend/tests/`, `npm test`).
  - [x] Desktop launcher script (`desktop_app.py`, Windows batch launchers).
  - [ ] Windows 11 standalone installer / self-contained runtime bundle.
  - [ ] Automated end-to-end acceptance certification suite.
- **Status**: **IN PROGRESS**
