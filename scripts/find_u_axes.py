import numpy as np
from scipy.signal import find_peaks

pos = np.load('data/projects/workshop_project/clouds/workshop_cloud/positions.npy', mmap_mode='r')
sample = pos[::10]

deg = 10.260
rad = np.radians(deg)
c, s = np.cos(rad), np.sin(rad)
u = sample[:, 0] * c + sample[:, 1] * s
v = -sample[:, 0] * s + sample[:, 1] * c
z = sample[:, 2]

# Filter points within the building envelope in V and Z
# V within [-32, 10], Z within column shaft heights (e.g. -11 to -2)
mask = (v >= -32.0) & (v <= 10.0) & (z >= -10.5) & (z <= -3.0) & (u >= -98.0) & (u <= 48.0)
u_bldg = u[mask]

print(f"Points in column height zone inside building: {len(u_bldg):,}")

# Histogram in U with 0.1m bins
bin_width = 0.1
bins = int((u_bldg.max() - u_bldg.min()) / bin_width)
hist, edges = np.histogram(u_bldg, bins=bins)
centers = (edges[:-1] + edges[1:]) / 2.0

# Find peaks separated by at least 4.5m
peaks, props = find_peaks(hist, height=1500, distance=int(4.5 / bin_width))

print(f"Found {len(peaks)} transverse axis peaks along U:")
u_axes = [centers[p] for p in peaks]
u_axes.sort()

for i, ua in enumerate(u_axes):
    diff = (ua - u_axes[i-1]) if i > 0 else 0.0
    print(f"  Axis {i+1:2d}: U = {ua:7.2f} m  (step from prev: {diff:5.2f} m)")
