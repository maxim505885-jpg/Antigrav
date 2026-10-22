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

# Фильтруем точки уровня стропильных ферм кровли Z [6.2 .. 7.5]
mask_roof = (pos[:, 2] >= 6.2) & (pos[:, 2] <= 7.5)
pts_roof = pos[mask_roof]
xy_rot = (pts_roof[:, :2] @ R.T)

print(f"Точек в диапазоне стропильных ферм кровли: {len(pts_roof):,}")
print(f"X вдоль цеха: min={xy_rot[:, 0].min():.2f}m, max={xy_rot[:, 0].max():.2f}m")
print(f"Y поперек цеха: min={xy_rot[:, 1].min():.2f}m, max={xy_rot[:, 1].max():.2f}m")

# Фермы стоят поперек цеха (вдоль Y) с шагом 6 метров вдоль цеха (по оси X)
# Посмотрим пики по оси X
hist_x, edges_x = np.histogram(xy_rot[:, 0], bins=140)
print("\n--- Выраженные плоскости ферм по оси X (шаг 6000 мм) ---")
for i in range(len(hist_x)):
    if hist_x[i] > 50000:
        print(f"X = {edges_x[i]:.2f} .. {edges_x[i+1]:.2f} м: {hist_x[i]:,} точек")
