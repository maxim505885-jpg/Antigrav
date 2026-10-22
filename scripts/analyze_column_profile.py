import numpy as np
import json
from pathlib import Path

cloud_dir = Path("data/projects/3f6321f10c9145db909ec27b1c2ba044/clouds/2621e5a320df49949d04aa1b7399539e")
pos = np.load(cloud_dir / "positions.npy", mmap_mode="r")
theta = np.radians(-10.23)
cos_t, sin_t = np.cos(theta), np.sin(theta)
R = np.array([[cos_t, -sin_t], [sin_t, cos_t]])

data = json.loads(Path("data/output/workshop_release/clean_grid_columns.json").read_text(encoding="utf-8"))
cols = data["columns"]

col = [c for c in cols if c["row"] == "Б" and c["bay"] == 10][0]
gx, gy = col["x_grid"], col["y_grid"]
mark = col["mark"]
print(f"Analyzing column {mark} at grid ({gx}, {gy}):")

# Points along column shaft
x_rot = pos[:, 0] * cos_t - pos[:, 1] * sin_t
y_rot = pos[:, 0] * sin_t + pos[:, 1] * cos_t
mask = (np.abs(x_rot - gx) <= 0.8) & (np.abs(y_rot - gy) <= 0.8)
col_pts = pos[mask]
print(f"Total points in column vertical shaft: {len(col_pts):,}")
print(f"Z range: min={col_pts[:, 2].min():.2f}m, max={col_pts[:, 2].max():.2f}m")

# Analyze cross sections at 3 elevations
for z0, z1, name in [(-2.2, -1.0, "Основание (цоколь)"), (1.0, 2.5, "Подкрановая ветвь"), (4.5, 6.0, "Надкрановая часть")]:
    band_m = (col_pts[:, 2] >= z0) & (col_pts[:, 2] <= z1)
    pts_b = col_pts[band_m]
    if len(pts_b) > 0:
        xy_b = pts_b[:, :2] @ R.T
        dx = float(np.ptp(xy_b[:, 0]))
        dy = float(np.ptp(xy_b[:, 1]))
        print(f"  {name} Z[{z0}..{z1}]: {len(pts_b):,} pts, measured bounds: {dx*1000:.0f} x {dy*1000:.0f} мм")
