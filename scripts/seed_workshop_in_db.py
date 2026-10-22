import json
import os
import shutil
from pathlib import Path
import sys

sys.path.insert(0, str(Path("backend").resolve()))

from scan2bim.db import execute, one, dumps, utcnow
from scan2bim.storage import cloud_paths, project_dir

def seed():
    print("Seeding Unified Workshop project and cloud into database...")
    
    project_id = "workshop_project"
    project_name = "Производственный цех (1.rcs + 2.rcs)"
    project_desc = "Промышленное здание цеха по ГОСТ 21.501-2018 (РД КР/КМ). Сводный массив 43.5 млн точек, 84 несущие колонны, подкрановые балки, стропильные фермы."
    
    cloud_id = "workshop_cloud"
    cloud_name = "Сводное облако цеха (43.5 млн точек)"
    
    now = utcnow()
    
    # 1. Upsert Project
    existing_proj = one("SELECT id FROM projects WHERE id = ?", (project_id,))
    if existing_proj:
        execute(
            "UPDATE projects SET name = ?, description = ?, updated_at = ? WHERE id = ?",
            (project_name, project_desc, now, project_id),
        )
    else:
        execute(
            "INSERT INTO projects (id, name, description, units, created_at, updated_at) VALUES (?, ?, ?, 'm', ?, ?)",
            (project_id, project_name, project_desc, now, now),
        )
    print("  Project ready.")
    
    # 2. Setup Cloud Storage Directory
    paths = cloud_paths(project_id, cloud_id)
    c_dir = paths["dir"]
    c_dir.mkdir(parents=True, exist_ok=True)
    
    unified_src_dir = Path("data/output/unified_stitched_release")
    unified_pos = unified_src_dir / "unified_cloud" / "positions.npy"
    unified_lod = unified_src_dir / "lod"
    
    # Copy / link positions.npy
    dest_pos = paths["positions"]
    if not dest_pos.is_file() and unified_pos.is_file():
        print("  Linking positions.npy...")
        try:
            os.link(str(unified_pos), str(dest_pos))
        except Exception:
            shutil.copy2(unified_pos, dest_pos)
            
    # Copy preview.bin from lod/lod_0.bin (50k points in 15-byte format)
    dest_prev = paths["preview"]
    src_lod0 = unified_lod / "lod_0.bin"
    if src_lod0.is_file():
        shutil.copy2(src_lod0, dest_prev)
        print("  Copied preview.bin from lod_0.bin.")
        
    # Copy lod directory
    dest_lod_dir = c_dir / "lod"
    dest_lod_dir.mkdir(parents=True, exist_ok=True)
    if unified_lod.is_dir():
        for f in unified_lod.glob("*"):
            dest_f = dest_lod_dir / f.name
            if not dest_f.is_file():
                shutil.copy2(f, dest_f)
        print("  Copied LOD pyramid files into cloud storage.")
        
    # Write meta.json
    dest_meta = paths["meta"]
    meta_content = {
        "source_file": "unified_stitched_cloud.ply",
        "point_count": 43500000,
        "format": "ply",
        "origin": [0.0, 0.0, 0.0],
        "bbox_min": [-158.426, -60.441, -26.878],
        "bbox_max": [158.426, 60.441, 26.878],
        "has_color": True,
        "coordinate_frame": "source_cloud_world",
        "units": "m",
    }
    dest_meta.write_text(json.dumps(meta_content, indent=2, ensure_ascii=False), encoding="utf-8")

    # 3. Upsert Cloud in DB
    existing_cloud = one("SELECT id FROM clouds WHERE id = ?", (cloud_id,))
    if existing_cloud:
        execute(
            """UPDATE clouds SET 
                name = ?, source_path = ?, source_format = ?, size_bytes = ?, 
                point_count = ?, ingested_count = ?, decimated = 0,
                origin_x = 0, origin_y = 0, origin_z = 0,
                bbox_min_x = -158.426, bbox_min_y = -60.441, bbox_min_z = -26.878,
                bbox_max_x = 158.426, bbox_max_y = 60.441, bbox_max_z = 26.878,
                has_color = 1, has_intensity = 1, status = 'ready',
                metadata_json = ?, updated_at = ?
            WHERE id = ?""",
            (
                cloud_name, "unified_stitched_cloud.ply", "ply", 652500182,
                43500000, 43500000, json.dumps(meta_content), now, cloud_id
            ),
        )
    else:
        execute(
            """INSERT INTO clouds (
                id, project_id, name, source_path, source_format, size_bytes,
                point_count, ingested_count, decimated,
                origin_x, origin_y, origin_z,
                bbox_min_x, bbox_min_y, bbox_min_z,
                bbox_max_x, bbox_max_y, bbox_max_z,
                has_color, has_intensity, status,
                metadata_json, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, 0,
                0, 0, 0,
                -158.426, -60.441, -26.878,
                158.426, 60.441, 26.878,
                1, 1, 'ready',
                ?, ?, ?
            )""",
            (
                cloud_id, project_id, cloud_name, "unified_stitched_cloud.ply", "ply", 652500182,
                43500000, 43500000, json.dumps(meta_content), now, now
            ),
        )
    print("  Cloud ready in database.")

    # 4. Insert 808 elements from revit_bim_model.json
    bim_json_path = unified_src_dir / "revit_bim_model.json"
    if bim_json_path.is_file():
        bim_data = json.loads(bim_json_path.read_text(encoding="utf-8"))
        elements = bim_data.get("elements", [])
        print(f"  Loading {len(elements)} structural elements into DB...")
        
        # Clear existing elements for this cloud
        execute("DELETE FROM elements WHERE cloud_id = ?", (cloud_id,))
        
        for el in elements:
            el_id = el.get("id")
            cname = el.get("class_name", "column")
            geom = el.get("geometry", {})
            bbox = el.get("bbox", {})
            conf = float(el.get("confidence", 0.9))
            conf_kind = el.get("confidence_kind", "heuristic")
            measured = 1 if el.get("measured", True) else 0
            inferred = 1 if el.get("inferred", False) else 0
            dims = el.get("dimensions", {})
            meta = el.get("metadata", {})
            
            execute(
                """INSERT INTO elements (
                    id, project_id, cloud_id, class_name,
                    geometry_json, bbox_json, confidence, confidence_kind,
                    measured, inferred, source, review_status,
                    dimensions_json, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'geometric', 'unreviewed', ?, ?, ?, ?)""",
                (
                    el_id, project_id, cloud_id, cname,
                    json.dumps(geom, ensure_ascii=False), json.dumps(bbox),
                    conf, conf_kind, measured, inferred,
                    json.dumps(dims, ensure_ascii=False), json.dumps(meta, ensure_ascii=False),
                    now, now
                ),
            )
        print(f"  Successfully inserted {len(elements)} elements into database.")

    # 5. Insert key horizontal level section for plan preview
    execute("DELETE FROM sections WHERE cloud_id = ?", (cloud_id,))
    section_id = "section_plan_000"
    execute(
        """INSERT INTO sections (
            id, project_id, cloud_id, kind, axis, position,
            thickness, grid_res, params_json, result_json,
            point_count, created_at
        ) VALUES (
            ?, ?, ?, 'horizontal', 'z', 0.0,
            0.5, 0.05, '{}', '{}',
            50000, ?
        )""",
        (section_id, project_id, cloud_id, now),
    )
    print("  Created key horizontal section at 0.000m.")

    print("\n[SUCCESS] Workshop project seeded! ID='workshop_project', Cloud='workshop_cloud'.")

if __name__ == "__main__":
    seed()
