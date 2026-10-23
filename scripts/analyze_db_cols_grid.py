import json
import numpy as np
from scan2bim.db import rows

cols = rows('SELECT id, geometry_json, bbox_json, dimensions_json FROM elements WHERE cloud_id = ? AND class_name = ?', ('workshop_cloud', 'column'))

deg = 10.260
rad = np.radians(deg)
c, s = np.cos(rad), np.sin(rad)

# 4 rows in V
known_v_rows = [-29.80, -16.55, -4.85, 8.40]
row_names = ['A', 'B', 'C', 'D']

col_data = []
for c_row in cols:
    g = json.loads(c_row['geometry_json'])
    cx, cy, cz = g['center']
    u = cx * c + cy * s
    v = -cx * s + cy * c
    dim = json.loads(c_row['dimensions_json'])
    h = dim.get('height_m', 0.0)
    col_data.append({'id': c_row['id'], 'cx': cx, 'cy': cy, 'cz': cz, 'u': u, 'v': v, 'height': h})

print(f"Total columns in DB: {len(col_data)}")

# For each column, find closest V row
for r_name, target_v in zip(row_names, known_v_rows):
    matches = [c for c in col_data if abs(c['v'] - target_v) <= 1.8]
    print(f"Row {r_name} (V={target_v:6.2f}m): {len(matches)} column candidates within 1.8m")

# Check how many columns are far from any of the 4 rows
outside = [c for c in col_data if not any(abs(c['v'] - tv) <= 1.8 for tv in known_v_rows)]
print(f"Candidates NOT matching the 4 rows (|V - row| > 1.8m): {len(outside)}")
for o in outside[:10]:
    print(f"  Outside candidate: u={o['u']:6.2f}, v={o['v']:6.2f}, z={o['cz']:6.2f}, h={o['height']:.2f}")
