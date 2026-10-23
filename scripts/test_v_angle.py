import numpy as np

pos = np.load('data/projects/workshop_project/clouds/workshop_cloud/positions.npy', mmap_mode='r')
# sample 1 in 20
sample = pos[::20]

# Try angles from 9.0 to 11.5 with step 0.1
for deg in [9.44, 9.8, 10.0, 10.23, 10.26, 10.3, 10.5]:
    rad = np.radians(deg)
    c, s = np.cos(rad), np.sin(rad)
    v = -sample[:, 0] * s + sample[:, 1] * c
    # Let's see histogram
    hist, edges = np.histogram(v, bins=1600, range=(-80, 80))
    # Count how concentrated the top 20 peaks are
    top20 = np.sort(hist)[-20:].sum()
    print(f"Deg {deg:5.2f}: top 20 bins sum = {top20:,}")
