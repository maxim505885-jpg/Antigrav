import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

import json
import numpy as np

# Load cloud 1
cloud_dir = Path("data/projects/3f6321f10c9145db909ec27b1c2ba044/clouds/2621e5a320df49949d04aa1b7399539e")
pos = np.load(cloud_dir / "positions.npy", mmap_mode="r")

# Поворот на -10.23 градуса для ориентации вдоль цеха
theta = np.radians(-10.23)
cos_t, sin_t = np.cos(theta), np.sin(theta)
R = np.array([[cos_t, -sin_t], [sin_t, cos_t]])

# Фильтруем точки уровня подкрановых путей Z [3.7 .. 4.5]
mask_crane = (pos[:, 2] >= 3.7) & (pos[:, 2] <= 4.5)
pts_crane = pos[mask_crane]
xy_rot = (pts_crane[:, :2] @ R.T)

print(f"Точек в диапазоне подкрановых путей: {len(pts_crane):,}")
print(f"X вдоль цеха: min={xy_rot[:, 0].min():.2f}m, max={xy_rot[:, 0].max():.2f}m")
print(f"Y поперек цеха: min={xy_rot[:, 1].min():.2f}m, max={xy_rot[:, 1].max():.2f}m")

# Гистограмма по Y поперек пролетов (3 пролета по 30 метров)
hist_y, edges_y = np.histogram(xy_rot[:, 1], bins=100)
print("\n--- Выраженные линии подкрановых путей по оси Y ---")
for i in range(len(hist_y)):
    if hist_y[i] > 100000:
        print(f"Y = {edges_y[i]:.2f} .. {edges_y[i+1]:.2f} м: {hist_y[i]:,} точек")
