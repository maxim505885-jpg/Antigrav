import json
import numpy as np
from scan2bim.db import rows

cols = rows('SELECT id, geometry_json, bbox_json, dimensions_json FROM elements WHERE cloud_id = ? AND class_name = ?', ('workshop_cloud', 'column'))

centers = []
for c in cols:
    g = json.loads(c['geometry_json'])
    centers.append(g['center'])
centers = np.array(centers)

print(f"Total columns in DB: {len(centers)}")

# Try angles from 9.0 to 11.0 to find sharpest alignment in transverse direction (V)
best_deg = None
max_peakiness = 0

for deg in np.linspace(9.0, 11.5, 51):
    rad = np.radians(deg)
    c, s = np.cos(rad), np.sin(rad)
    u = centers[:, 0] * c + centers[:, 1] * s
    v = -centers[:, 0] * s + centers[:, 1] * c
    # Histogram of V with 0.5m bins
    hist, _ = np.histogram(v, bins=100, range=(-50, 50))
    # Peakiness: sum of top 4 peaks
    top4 = np.sort(hist)[-4:].sum()
    if top4 > max_peakiness:
        max_peakiness = top4
        best_deg = deg

print(f"Best rotation angle for columns: {best_deg:.3f} deg (top 4 peaks contain {max_peakiness} columns)")

# Rotate with best_deg
rad = np.radians(best_deg)
c, s = np.cos(rad), np.sin(rad)
u = centers[:, 0] * c + centers[:, 1] * s
v = -centers[:, 0] * s + centers[:, 1] * c

# Analyze V (transverse rows)
hist_v, bin_edges_v = np.histogram(v, bins=200, range=(-40, 40))
bin_centers_v = (bin_edges_v[:-1] + bin_edges_v[1:]) / 2.0

# Print significant peaks in V
peaks_v = []
for i in range(1, len(hist_v) - 1):
    if hist_v[i] > hist_v[i-1] and hist_v[i] > hist_v[i+1] and hist_v[i] >= 10:
        peaks_v.append((bin_centers_v[i], hist_v[i]))

print("Significant transverse rows (V peaks):")
for pv, cnt in sorted(peaks_v, key=lambda x: -x[1]):
    print(f"  V = {pv:6.2f} m: {cnt} columns")
