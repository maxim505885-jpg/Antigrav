import numpy as np

# Load positions
pos = np.load('data/output/unified_stitched_release/unified_cloud/positions.npy', mmap_mode='r')
print(f"Total points: {len(pos):,}")

# Take a 1-in-10 sample of points around column heights
# In raw Z coordinates, let's see what Z range has columns:
# Columns run from ground up to crane girders / roof
sample = pos[::10]
print(f"Sampled points: {len(sample):,}")

# Find dominant axis of the building
# We know angle is ~9.44 degrees
for deg in [9.0, 9.44, 9.5, 9.97, 10.0]:
    rad = np.radians(deg)
    c, s = np.cos(rad), np.sin(rad)
    u = sample[:, 0] * c + sample[:, 1] * s
    v = -sample[:, 0] * s + sample[:, 1] * c
    # Check peakiness of histogram in V (transverse)
    v_hist, _ = np.histogram(v, bins=600, range=(-65, 65))
    peak_sum = np.sort(v_hist)[-10:].sum()
    print(f"Angle {deg:.2f} deg: top 10 V-peaks sum = {peak_sum}")

