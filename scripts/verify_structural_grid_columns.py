import json
import numpy as np
from pathlib import Path

pos = np.load('data/projects/workshop_project/clouds/workshop_cloud/positions.npy', mmap_mode='r')
# sample 1 in 5 for high precision check
sample = pos[::5]

deg = 10.260
rad = np.radians(deg)
c, s = np.cos(rad), np.sin(rad)
u = sample[:, 0] * c + sample[:, 1] * s
v = -sample[:, 0] * s + sample[:, 1] * c
z = sample[:, 2]

# The 4 rows across the 3 spans
v_rows = {
    'A': -29.80,
    'B': -16.55,
    'C': -4.85,
    'D':  8.40,
}

# The 24 axes with 6000 mm step (k from -16 to 7)
u_base = 0.14
u_axes = [round(u_base + k * 6.0, 3) for k in range(-16, 8)]

print(f"Grid: 4 rows ({list(v_rows.keys())}), 24 transverse axes (1..24)")
print(f"Total grid nodes: {len(v_rows) * len(u_axes)}")

confirmed_columns = []

for row_name, v_coord in v_rows.items():
    for bay_idx, u_coord in enumerate(u_axes, start=1):
        # Look for point cloud density in a cylinder around (u_coord, v_coord)
        # Tolerance radius 0.9 m
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
            # Measure actual centroid in rotated frame
            # Use points in column shaft (between -10.0 and -4.0)
            shaft_m = (pts_z >= -10.5) & (pts_z <= -3.5)
            if np.sum(shaft_m) >= 50:
                actual_u = float(np.median(pts_u[shaft_m]))
                actual_v = float(np.median(pts_v[shaft_m]))
            else:
                actual_u = float(np.median(pts_u))
                actual_v = float(np.median(pts_v))
                
            # Convert (actual_u, actual_v) back to world coordinates (X, Y)
            # [x] = [ c  -s] [u]
            # [y] = [ s   c] [v]
            world_x = actual_u * c - actual_v * s
            world_y = actual_u * s + actual_v * c
            
            # Determine column section dimensions
            # Row B and C are middle crane rows (typically 800x600 mm or similar)
            # Row A and D are outer rows (typically 600x500 mm or similar)
            if row_name in ('B', 'C'):
                col_type = 'K-2'
                length_m = 0.8
                thickness_m = 0.6
                descr = f"Колонна К-2 среднего ряда (800x600 мм)"
            else:
                col_type = 'K-1'
                length_m = 0.6
                thickness_m = 0.5
                descr = f"Колонна К-1 крайнего ряда (600x500 мм)"
                
            mark = f"К-{row_name}{bay_idx}"
            
            confirmed_columns.append({
                "mark": mark,
                "row": row_name,
                "axis": bay_idx,
                "type": col_type,
                "description": descr,
                "grid_u": u_coord,
                "grid_v": v_coord,
                "actual_u": actual_u,
                "actual_v": actual_v,
                "world_x": round(world_x, 4),
                "world_y": round(world_y, 4),
                "z_bottom": round(z_min, 3),
                "z_top": round(z_max, 3),
                "height_m": round(height, 3),
                "length_m": length_m,
                "thickness_m": thickness_m,
                "rotation_deg": deg,
                "point_count": int(len(pts_z) * 5),
                "dev_u_mm": int(round((actual_u - u_coord) * 1000)),
                "dev_v_mm": int(round((actual_v - v_coord) * 1000)),
            })

print(f"Total physically confirmed columns on grid: {len(confirmed_columns)}")

cols_by_row = {}
for c in confirmed_columns:
    cols_by_row.setdefault(c['row'], []).append(c)

for r in ['A', 'B', 'C', 'D']:
    cols = cols_by_row.get(r, [])
    print(f"  Row {r} (V={v_rows[r]:.2f}m): {len(cols)} columns confirmed (axes: {[c['axis'] for c in cols]})")
