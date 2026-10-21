import sqlite3
import json
import math
import numpy as np

db_path = "data/scan2bim.sqlite3"
conn = sqlite3.connect(db_path)
c = conn.cursor()

project_id = "cf967dc89b8c46b899d428fbfa122d77"

# Fetch columns
c.execute("SELECT id, bbox_json, dimensions_json, metadata_json FROM elements WHERE project_id = ? AND class_name = 'column'", (project_id,))
cols = c.fetchall()
print(f"Total columns in project: {len(cols)}")

col_centers = []
for cid, bbox_str, dims_str, meta_str in cols:
    bbox = json.loads(bbox_str)
    cx = (bbox["min"][0] + bbox["max"][0]) / 2.0
    cy = (bbox["min"][1] + bbox["max"][1]) / 2.0
    cz = (bbox["min"][2] + bbox["max"][2]) / 2.0
    col_centers.append((cx, cy, cz))

col_centers = np.array(col_centers)
print(f"Columns bounding box in cloud coordinates:")
print(f"  X: [{col_centers[:,0].min():.2f} .. {col_centers[:,0].max():.2f}] span={col_centers[:,0].max() - col_centers[:,0].min():.2f} m")
print(f"  Y: [{col_centers[:,1].min():.2f} .. {col_centers[:,1].max():.2f}] span={col_centers[:,1].max() - col_centers[:,1].min():.2f} m")
print(f"  Z: [{col_centers[:,2].min():.2f} .. {col_centers[:,2].max():.2f}] span={col_centers[:,2].max() - col_centers[:,2].min():.2f} m")

# Estimate main axis angle via PCA on (X, Y)
pts_xy = col_centers[:, :2] - col_centers[:, :2].mean(axis=0)
cov = np.cov(pts_xy, rowvar=False)
evals, evecs = np.linalg.eigh(cov)
main_vec = evecs[:, np.argmax(evals)]
angle_rad = math.atan2(main_vec[1], main_vec[0])
angle_deg = math.degrees(angle_rad)
print(f"PCA Main Axis Angle: {angle_deg:.3f} deg ({angle_rad:.4f} rad)")

# Rotate columns into building coordinate system
rot_angle = -angle_rad
cos_a = math.cos(rot_angle)
sin_a = math.sin(rot_angle)
R = np.array([[cos_a, -sin_a], [sin_a, cos_a]])
rot_xy = (pts_xy @ R.T)

print(f"Rotated coordinates span:")
print(f"  Along building (U): [{rot_xy[:,0].min():.2f} .. {rot_xy[:,0].max():.2f}] length={rot_xy[:,0].max() - rot_xy[:,0].min():.2f} m")
print(f"  Across building (V): [{rot_xy[:,1].min():.2f} .. {rot_xy[:,1].max():.2f}] width={rot_xy[:,1].max() - rot_xy[:,1].min():.2f} m")

# Inspect trusses
c.execute("SELECT id, bbox_json, dimensions_json FROM elements WHERE project_id = ? AND class_name = 'truss'", (project_id,))
trusses = c.fetchall()
print(f"\nTotal trusses: {len(trusses)}")
for tid, bbox_str, dims_str in trusses[:5]:
    b = json.loads(bbox_str)
    d = json.loads(dims_str)
    print(f"  Truss: span={d.get('span_m')} h={d.get('height_m')} top_z={d.get('top_chord_z')} bot_z={d.get('bottom_chord_z')} bbox_x=[{b['min'][0]:.1f}..{b['max'][0]:.1f}]")

# Inspect crane beams
c.execute("SELECT id, bbox_json, dimensions_json FROM elements WHERE project_id = ? AND class_name = 'beam' AND json_extract(dimensions_json, '$.role') = 'crane_girder'", (project_id,))
crane_beams = c.fetchall()
print(f"\nCrane girders: {len(crane_beams)}")
for bid, bbox_str, dims_str in crane_beams[:5]:
    b = json.loads(bbox_str)
    d = json.loads(dims_str)
    print(f"  Crane Girder: len={d.get('length_m')} h={d.get('height_m')} z=[{b['min'][2]:.2f}..{b['max'][2]:.2f}]")
