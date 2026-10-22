import numpy as np
from scipy.signal import find_peaks

pos = np.load('data/projects/workshop_project/clouds/workshop_cloud/positions.npy', mmap_mode='r')
sample = pos[::10]

deg = 10.260
rad = np.radians(deg)
c, s = np.cos(rad), np.sin(rad)
v = -sample[:, 0] * s + sample[:, 1] * c
u = sample[:, 0] * c + sample[:, 1] * s

print(f"U bounds: min={u.min():.2f}, max={u.max():.2f}")
print(f"V bounds: min={v.min():.2f}, max={v.max():.2f}")

# Histogram in V with 0.1m bins
bin_width = 0.05
bins = int((v.max() - v.min()) / bin_width)
hist, edges = np.histogram(v, bins=bins)
centers = (edges[:-1] + edges[1:]) / 2.0

peaks, props = find_peaks(hist, height=10000, distance=int(3.0 / bin_width))

print(f"Found {len(peaks)} major peaks in V:")
for p in sorted(peaks, key=lambda idx: centers[idx]):
    print(f"  V = {centers[p]:6.2f} m, count = {hist[p]:,}")
