import json
import numpy as np
from scan2bim.db import rows

cols = rows("SELECT id, geometry_json, bbox_json, dimensions_json FROM elements WHERE cloud_id = 'workshop_cloud' AND class_name = 'column'")
print(f"Total columns in DB: {len(cols)}")

centers = []
for c in cols:
    g = json.loads(c['geometry_json'])
    b = json.loads(c['bbox_json'])
    if g.get('center'):
        centers.append(g['center'])
    else:
        centers.append([(b['min'][0]+b['max'][0])/2, (b['min'][1]+b['max'][1])/2, (b['min'][2]+b['max'][2])/2])

centers = np.array(centers)
print(f"X span: {centers[:, 0].min():.2f} to {centers[:, 0].max():.2f} (dx = {centers[:, 0].max() - centers[:, 0].min():.2f} m)")
print(f"Y span: {centers[:, 1].min():.2f} to {centers[:, 1].max():.2f} (dy = {centers[:, 1].max() - centers[:, 1].min():.2f} m)")
print(f"Z span: {centers[:, 2].min():.2f} to {centers[:, 2].max():.2f} (dz = {centers[:, 2].max() - centers[:, 2].min():.2f} m)")

# Hall axis angle
# In steel stats: hall_axis_deg was ~9.44 deg.
angle_rad = np.radians(9.4426)
c, s = np.cos(angle_rad), np.sin(angle_rad)

# Project columns onto longitudinal (U) and transverse (V) axes
u = centers[:, 0] * c + centers[:, 1] * s
v = -centers[:, 0] * s + centers[:, 1] * c

print(f"\nLongitudinal U span: {u.min():.2f} to {u.max():.2f} (length = {u.max() - u.min():.2f} m)")
print(f"Transverse V span: {v.min():.2f} to {v.max():.2f} (width = {v.max() - v.min():.2f} m)")

# Let's inspect V clusters (the rows of columns across the width of the hall)
v_hist, v_edges = np.histogram(v, bins=50)
print("\nTransverse V histogram (finding the 4 rows of columns):")
for i in range(len(v_hist)):
    if v_hist[i] > 2:
        print(f"  V in [{v_edges[i]:.2f}, {v_edges[i+1]:.2f}]: {v_hist[i]} column candidates")
