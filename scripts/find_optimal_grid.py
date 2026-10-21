import sqlite3
import json
import math
import numpy as np

db_path = "data/scan2bim.sqlite3"
conn = sqlite3.connect(db_path)
c = conn.cursor()

project_id = "cf967dc89b8c46b899d428fbfa122d77"
c.execute("SELECT id, bbox_json FROM elements WHERE project_id = ? AND class_name = 'column'", (project_id,))
cols = c.fetchall()

col_centers = []
for cid, bbox_str in cols:
    bbox = json.loads(bbox_str)
    cx = (bbox["min"][0] + bbox["max"][0]) / 2.0
    cy = (bbox["min"][1] + bbox["max"][1]) / 2.0
    col_centers.append((cx, cy))

pts = np.array(col_centers)

# Test angles around 12.58 deg
max_peakiness = -1
best_angle = 12.58

for deg in np.linspace(5.0, 20.0, 1501):
    rad = math.radians(deg)
    # Rotate by -rad
    cos_a = math.cos(-rad)
    sin_a = math.sin(-rad)
    rot_y = pts[:, 0] * sin_a + pts[:, 1] * cos_a
    # Count how well Y coordinates cluster into distinct horizontal grid lines
    hist, _ = np.histogram(rot_y, bins=120)
    peakiness = float(np.sum(hist ** 2))
    if peakiness > max_peakiness:
        max_peakiness = peakiness
        best_angle = deg


print(f"Optimal rotation angle for horizontal grid lines: {best_angle:.3f} deg")

rad = math.radians(best_angle)
ca, sa = math.cos(-rad), math.sin(-rad)
rx = pts[:, 0] * ca - pts[:, 1] * sa
ry = pts[:, 0] * sa + pts[:, 1] * ca

# Let's shift so min_x = 0, min_y = 0
rx -= rx.min()
ry -= ry.min()

print(f"Building dimensions after alignment:")
print(f"  Length (X): {rx.max():.2f} m")
print(f"  Width (Y): {ry.max():.2f} m")

# Cluster Y into distinct row lines (axes A, B, C...)
y_sorted = np.sort(ry)
y_rows = []
for y in y_sorted:
    if not y_rows or abs(y - y_rows[-1]) > 2.5:
        y_rows.append(y)

print(f"Row lines (Y positions in m): {[round(y, 2) for y in y_rows]}")

# Cluster X into column bays (axes 1, 2, 3...)
x_sorted = np.sort(rx)
x_bays = []
for x in x_sorted:
    if not x_bays or abs(x - x_bays[-1]) > 4.5:
        x_bays.append(x)

print(f"Total bay lines (X positions): {len(x_bays)} bays")
print(f"Sample X bays: {[round(x, 1) for x in x_bays[:10]]}")
print(f"Bay steps (distances between consecutive axes in m): {[round(x_bays[i+1] - x_bays[i], 2) for i in range(min(10, len(x_bays)-1))]}")
