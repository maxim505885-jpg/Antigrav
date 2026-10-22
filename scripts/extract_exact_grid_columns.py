import numpy as np
import json
from pathlib import Path

cloud_dir = Path("data/projects/3f6321f10c9145db909ec27b1c2ba044/clouds/2621e5a320df49949d04aa1b7399539e")
pos = np.load(cloud_dir / "positions.npy", mmap_mode="r")

# Columns floor slice
mask = (pos[:, 2] >= -2.2) & (pos[:, 2] <= -1.5)
pts = pos[mask]

# Building rotation
theta = np.radians(-10.23)
cos_t, sin_t = np.cos(theta), np.sin(theta)
R = np.array([[cos_t, -sin_t], [sin_t, cos_t]])
xy = pts[:, :2] @ R.T

# Exact 4 longitudinal rows of columns:
# Row A: Outer wall row
# Row B: Middle crane row 1
# Row C: Middle crane row 2
# Row D: Outer wall row 2
row_defs = [
    ("А", -17.5, 1.2),
    ("Б", -4.8, 1.2),
    ("В", 7.5, 1.2),
    ("Г", 20.5, 1.2),
]

# 23 bays from -66m to +66m with 6.000m step (ГОСТ)
x_bays = [float(round(x, 3)) for x in np.arange(-66.0, 67.0, 6.0)]

confirmed_columns = []

for row_name, y_c, y_tol in row_defs:
    mask_r = (xy[:, 1] >= y_c - y_tol) & (xy[:, 1] <= y_c + y_tol)
    xy_r = xy[mask_r]
    
    for bay_idx, x_theory in enumerate(x_bays, start=1):
        mask_col = (np.abs(xy_r[:, 0] - x_theory) <= 1.0) & (np.abs(xy_r[:, 1] - y_c) <= 1.0)
        pts_col = xy_r[mask_col]
        
        # Real physical column returns at least 80 points in a 0.7m slice
        if len(pts_col) >= 80:
            cx, cy = float(pts_col[:, 0].mean()), float(pts_col[:, 1].mean())
            dx_mm = int(round((cx - x_theory) * 1000))
            dy_mm = int(round((cy - y_c) * 1000))
            confirmed_columns.append({
                "row": row_name,
                "bay": bay_idx,
                "mark": f"К-{row_name}{bay_idx}",
                "type": "К-2" if row_name in ("Б", "В") else "К-1",
                "x_grid": x_theory,
                "y_grid": y_c,
                "x_actual": cx,
                "y_actual": cy,
                "dx_mm": dx_mm,
                "dy_mm": dy_mm,
                "point_count": int(len(pts_col)),
                "dimensions": {
                    "length_m": 0.8 if row_name in ("Б", "В") else 0.6,
                    "thickness_m": 0.6 if row_name in ("Б", "В") else 0.5,
                    "height_m": 10.2,
                }
            })

out_json = Path("data/output/workshop_release/clean_grid_columns.json")
out_json.write_text(json.dumps({
    "x_bays": x_bays,
    "y_spans": [-17.5, -4.8, 7.5, 20.5],
    "rows": ["А", "Б", "В", "Г"],
    "columns": confirmed_columns,
    "total_columns": len(confirmed_columns),
}, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"Extracted {len(confirmed_columns)} confirmed structural columns on grid!")
for r in ["А", "Б", "В", "Г"]:
    count = sum(1 for c in confirmed_columns if c["row"] == r)
    print(f"Ряд {r}: {count} подтвержденных несущих колонн")
