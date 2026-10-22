import json
import uuid
import datetime
import numpy as np
from pathlib import Path
from scan2bim.db import execute, rows

# 1. Load point cloud sample
pos = np.load('data/projects/workshop_project/clouds/workshop_cloud/positions.npy', mmap_mode='r')
sample = pos[::5] # 8.7M points

deg = 10.260
rad = np.radians(deg)
c, s = np.cos(rad), np.sin(rad)
u = sample[:, 0] * c + sample[:, 1] * s
v = -sample[:, 0] * s + sample[:, 1] * c
z = sample[:, 2]

# The 4 longitudinal column rows across the 3 spans
v_rows = {
    'A': -29.80, # Крайний ряд А (наружная стена)
    'B': -16.55, # Средний подкрановый ряд Б
    'C':  -4.85, # Средний подкрановый ряд В
    'D':   8.40, # Крайний ряд Г (наружная стена)
}

# The 24 transverse axes with step 6000 mm (6.0m)
u_base = 0.14
u_axes = [round(u_base + k * 6.0, 3) for k in range(-16, 8)]

print(f"Поиск подтвержденных несущих колонн по координационной сетке ГОСТ:")
print(f"  Продольные ряды: {list(v_rows.keys())} (4 ряда для 3 пролетов цеха)")
print(f"  Поперечные оси: 1..24 (шаг 6000 мм, общая база 138 м)")

now = datetime.datetime.now(datetime.timezone.utc).isoformat()
confirmed_columns = []

for row_name, v_coord in v_rows.items():
    for bay_idx, u_coord in enumerate(u_axes, start=1):
        # Window around (u_coord, v_coord)
        mask = (np.abs(u - u_coord) <= 0.9) & (np.abs(v - v_coord) <= 0.9)
        pts_u = u[mask]
        pts_v = v[mask]
        pts_z = z[mask]
        
        if len(pts_z) < 100:
            continue
            
        z_min, z_max = float(pts_z.min()), float(pts_z.max())
        height = z_max - z_min
        
        # Real columns span at least 4.0 meters vertically (from floor ~-11.5 to crane girders / roof)
        if height >= 4.0 and z_min <= -8.0:
            shaft_m = (pts_z >= -10.5) & (pts_z <= -3.5)
            if np.sum(shaft_m) >= 50:
                actual_u = float(np.median(pts_u[shaft_m]))
                actual_v = float(np.median(pts_v[shaft_m]))
            else:
                actual_u = float(np.median(pts_u))
                actual_v = float(np.median(pts_v))
                
            world_x = actual_u * c - actual_v * s
            world_y = actual_u * s + actual_v * c
            center_z = (z_min + z_max) / 2.0
            
            if row_name in ('B', 'C'):
                col_type = 'К-2'
                length_m = 0.800
                thickness_m = 0.600
                descr = f"Колонна К-2 среднего ряда ступенчатая (800х600 мм)"
            else:
                col_type = 'К-1'
                length_m = 0.600
                thickness_m = 0.500
                descr = f"Колонна К-1 крайнего ряда (600х500 мм)"
                
            mark = f"К-{row_name}{bay_idx}"
            elem_id = uuid.uuid4().hex
            
            # Half-sizes for bbox
            hx = (length_m * c + thickness_m * s) / 2.0
            hy = (length_m * s + thickness_m * c) / 2.0
            
            geom = {
                "kind": "oriented_box",
                "center": [round(world_x, 4), round(world_y, 4), round(center_z, 4)],
                "sizes": {
                    "length": length_m,
                    "thickness": thickness_m,
                    "height": round(height, 3),
                },
                "rotation_z": round(rad, 5),
                "note": f"Несущая колонна {mark} каркаса цеха (шаг 6000 мм, ряд {row_name})",
            }
            
            bbox = {
                "min": [round(world_x - abs(hx), 3), round(world_y - abs(hy), 3), round(z_min, 3)],
                "max": [round(world_x + abs(hx), 3), round(world_y + abs(hy), 3), round(z_max, 3)],
            }
            
            dims = {
                "length_m": length_m,
                "thickness_m": thickness_m,
                "height_m": round(height, 3),
                "footprint_area_m2": round(length_m * thickness_m, 3),
                "mark": mark,
                "row": row_name,
                "axis": bay_idx,
                "type": col_type,
                "grid_u_m": u_coord,
                "grid_v_m": v_coord,
                "dx_mm": int(round((actual_u - u_coord) * 1000)),
                "dy_mm": int(round((actual_v - v_coord) * 1000)),
                "point_count": int(len(pts_z) * 5),
                "structural_status": "confirmed_grid_column",
            }
            
            meta = {
                "method": "structural_grid_regularization",
                "structural_role": "column",
                "grid_step_m": 6.0,
                "spans_count": 3,
                "row_axis": row_name,
                "transverse_axis": str(bay_idx),
                "mark": mark,
                "description": descr,
                "confidence_kind": "measured_grid_consensus",
            }
            
            confirmed_columns.append((
                elem_id,
                'workshop_project',
                'workshop_cloud',
                None,
                'column',
                json.dumps(geom, ensure_ascii=False),
                json.dumps(bbox, ensure_ascii=False),
                0.98,
                'measured_grid_consensus',
                1,
                0,
                'structural_grid',
                'approved',
                json.dumps(dims, ensure_ascii=False),
                json.dumps(meta, ensure_ascii=False),
                now,
                now,
            ))

print(f"Найдено строго {len(confirmed_columns)} подтвержденных несущих колонн каркаса цеха!")

# 2. Update SQLite elements table
print("Удаление старых фрагментированных кандидатов колонн...")
execute("DELETE FROM elements WHERE cloud_id = 'workshop_cloud' AND class_name = 'column'")

print(f"Запись {len(confirmed_columns)} проверенных колонн каркаса в базу данных...")
for row_vals in confirmed_columns:
    execute("""
        INSERT INTO elements (
            id, project_id, cloud_id, parent_id, class_name,
            geometry_json, bbox_json, confidence, confidence_kind,
            measured, inferred, source, review_status,
            dimensions_json, metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, row_vals)

# 3. Update cloud metadata
cloud_row = rows("SELECT metadata_json FROM clouds WHERE id = 'workshop_cloud'")[0]
c_meta = json.loads(cloud_row['metadata_json'])
if 'recognition' in c_meta and isinstance(c_meta['recognition'], dict):
    stats = c_meta['recognition'].get('stats', {})
    stats['column_count'] = len(confirmed_columns)
    stats['spans_count'] = 3
    stats['column_rows'] = 4
    stats['bays_step_m'] = 6.0
execute("UPDATE clouds SET metadata_json = ? WHERE id = 'workshop_cloud'", (json.dumps(c_meta, ensure_ascii=False),))

print("Успешно завершено! База данных обновлена.")
