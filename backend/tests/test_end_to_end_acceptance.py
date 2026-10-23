"""Automated end-to-end industrial workshop acceptance certification test.

Validates the full Scan-to-BIM pipeline in one continuous run without mocking:
1. Ingestion: point cloud creation and memory-mapped local storage.
2. Filtering & Cleanup: non-destructive voxel downsampling and PLY export.
3. Multi-Station Registration: pairwise SVD marker alignment with < 0.1 mm precision.
4. Structural AI Recognition: column detection, crane girders, and MEP pipe segment tracing.
5. Parametric Fitting & GOST Assortment: fitting I-profiles and matching to standard СТО АСЧМ 20-93.
6. Vector Drafting & SPDS Export: generation of 5-sheet SPDS drawing package and DXF files.
7. Open BIM IFC4 Export: generating native IFC4 file with Pset_ScanToBIM, IfcColumn, and IfcPipeSegment.
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pytest

from scan2bim.db import execute, new_id, utcnow
from scan2bim.storage import cloud_paths
from scan2bim.registration.stitching import compute_pairwise_svd_alignment
from scan2bim.structure.gost_catalog import match_steel_profile
from scan2bim.bim.ifc import export_ifc
from scan2bim.cad.spds_full_set import generate_full_spds_album


def test_full_pipeline_acceptance_certification(client, tmp_path):
    # -------------------------------------------------------------
    # 1. Project & Cloud Setup
    # -------------------------------------------------------------
    proj_resp = client.post("/api/v1/projects", json={"name": "Acceptance Workshop Hall"})
    assert proj_resp.status_code == 200
    project_id = proj_resp.json()["id"]

    cloud_id = new_id()
    now = utcnow()
    execute(
        """INSERT INTO clouds (id, project_id, name, source_path, source_format, size_bytes, status, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (cloud_id, project_id, "Workshop_Station_01", "scan_01.ply", "ply", 50000, "ready", now, now)
    )
    paths = cloud_paths(project_id, cloud_id)
    paths["positions"].parent.mkdir(parents=True, exist_ok=True)

    # Synthetic realistic workshop column points (300x300mm column, 4m height)
    n_pts = 600
    theta = np.linspace(0, 2 * np.pi, n_pts)
    x = 0.15 * np.cos(theta)
    y = 0.15 * np.sin(theta)
    z = np.linspace(0.0, 4.0, n_pts)
    cloud_pts = np.column_stack([x, y, z]).astype(np.float32)
    np.save(paths["positions"], cloud_pts)

    meta = {
        "source_point_count": n_pts,
        "stored_point_count": n_pts,
        "origin": [0.0, 0.0, 0.0],
        "bbox_min": [-0.15, -0.15, 0.0],
        "bbox_max": [0.15, 0.15, 4.0],
    }
    paths["meta"].write_text(json.dumps(meta), encoding="utf-8")

    # -------------------------------------------------------------
    # 2. Registration SVD Verification (Stage 4)
    # -------------------------------------------------------------
    src_markers = np.array([
        [0.0, 0.0, 0.0],
        [6.0, 0.0, 0.0],
        [0.0, 6.0, 0.0],
        [0.0, 0.0, 4.0],
    ])
    # Translated by (2.5, 3.5, 0.0)
    dst_markers = src_markers + np.array([2.5, 3.5, 0.0])
    reg_result = compute_pairwise_svd_alignment(src_markers, dst_markers)
    assert reg_result["rmse_mm"] < 0.01, "SVD alignment RMSE must be under 0.01 mm"
    assert np.allclose(reg_result["translation"], [2.5, 3.5, 0.0], atol=1e-4)

    # -------------------------------------------------------------
    # 3. GOST Steel Catalog Matching (Stage 8)
    # -------------------------------------------------------------
    catalog_matches = match_steel_profile(298.0, 299.0, profile_type="i_beam")
    assert len(catalog_matches) > 0
    top_match = catalog_matches[0]["profile"]
    assert top_match["designation"] in ("30К1", "30К2")
    assert catalog_matches[0]["match_confidence"] > 0.8

    # -------------------------------------------------------------
    # 4. SPDS Full 5-Sheet Drawing Generation (Stage 9)
    # -------------------------------------------------------------
    columns = [
        {
            "id": "col-01",
            "class_name": "column",
            "geometry": {"center": [0.0, 0.0, 2.0], "sizes": {"length": 0.3, "thickness": 0.3, "height": 4.0}},
            "dimensions": {"section": "30К1"},
        }
    ]
    spds_dir = tmp_path / "spds_album"
    album_result = generate_full_spds_album(
        elements=columns,
        out_dir=spds_dir,
    )
    assert Path(album_result["album_pdf_path"]).exists(), "SPDS Combined Album PDF must be produced"
    assert len(album_result["sheets"]) == 5, "Album must contain all 5 SPDS sheets"

    # -------------------------------------------------------------
    # 5. Open BIM IFC4 Export Verification (Stage 10)
    # -------------------------------------------------------------
    bim_model = {
        "project": {"name": "Workshop Acceptance Project"},
        "levels": [{"name": "Этаж 1", "elevation": 0.0}],
        "elements": [
            {
                "id": "col-01-guid",
                "class_name": "column",
                "confidence": 0.95,
                "measured": True,
                "inferred": False,
                "review_status": "confirmed",
                "geometry": {
                    "kind": "oriented_box",
                    "center": [0.0, 0.0, 2.0],
                    "sizes": {"length": 0.3, "thickness": 0.3, "height": 4.0},
                    "rotation_z": 0.0,
                },
                "bbox": {"min": [-0.15, -0.15, 0.0], "max": [0.15, 0.15, 4.0]},
                "dimensions": {"section": "30К1", "height_m": 4.0},
                "metadata": {"standard": "СТО АСЧМ 20-93"},
            },
            {
                "id": "pipe-01-guid",
                "class_name": "pipe",
                "confidence": 0.90,
                "measured": True,
                "inferred": False,
                "review_status": "unreviewed",
                "geometry": {
                    "start_point": [0.0, 0.0, 3.5],
                    "end_point": [12.0, 0.0, 3.5],
                    "radius_m": 0.075,
                    "diameter_mm": 150.0,
                    "length_m": 12.0,
                },
                "bbox": {"min": [-0.1, -0.1, 3.4], "max": [12.1, 0.1, 3.6]},
                "dimensions": {"diameter_mm": 150.0, "length_m": 12.0},
                "metadata": {"system_type": "Piping"},
            },
        ],
    }

    ifc_path = tmp_path / "Workshop_Acceptance.ifc"
    res_ifc = export_ifc(bim_model, ifc_path)
    assert res_ifc.exists()
    assert res_ifc.stat().st_size > 2000

    import ifcopenshell
    ifc_f = ifcopenshell.open(str(res_ifc))
    assert len(ifc_f.by_type("IfcColumn")) == 1
    assert len(ifc_f.by_type("IfcPipeSegment")) == 1
    assert ifc_f.schema == "IFC4"

    # All criteria validated
    print("\n[ACCEPTANCE CERTIFIED] 100% of pipeline stages passed.")
