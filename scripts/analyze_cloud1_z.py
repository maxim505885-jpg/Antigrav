import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

import json
import numpy as np

# Load cloud 1
cloud_dir = Path("data/projects/3f6321f10c9145db909ec27b1c2ba044/clouds/2621e5a320df49949d04aa1b7399539e")
meta = json.loads((cloud_dir / "meta.json").read_text(encoding="utf-8"))
pos = np.load(cloud_dir / "positions.npy", mmap_mode="r")

print(f"Total points in cloud 1 positions.npy: {len(pos):,}")
z_vals = pos[:, 2]
print(f"Z min: {z_vals.min():.2f}m, Z max: {z_vals.max():.2f}m")

# Histogram of Z
hist, edges = np.histogram(z_vals, bins=50)
print("\n--- Высотные скопления точек по Z (уровни пола, балок, ферм) ---")
for i in range(len(hist)):
    if hist[i] > 100000:
        print(f"Z [{edges[i]:.2f} .. {edges[i+1]:.2f}] : {hist[i]:,} точек")
