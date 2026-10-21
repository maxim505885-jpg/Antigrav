"""Create a fresh isolated synthetic project for browser acceptance checks."""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
data_dir = Path(os.environ.get("S2B_DATA_DIR", "")).resolve()
if not os.environ.get("S2B_DATA_DIR") or not data_dir.is_relative_to(ROOT / "data" / "validation"):
    raise SystemExit("S2B_DATA_DIR must point to a fresh directory under data/validation")
sys.path.insert(0, str(ROOT / "backend"))

import numpy as np
from scan2bim import db
from scan2bim.config import DB_PATH
from scan2bim.ingest import ingest_cloud

if DB_PATH.exists():
    raise SystemExit("Refusing to seed an existing database")
db.init_db()
project_id, cloud_id = "qa-types-project", "qa-types-cloud"
now = db.utcnow()
elements, points = [], []
for index in range(6):
    length, thickness = (0.5 + index * 0.001, 0.4) if index < 4 else (0.8, 0.6)
    cx, cy = index % 3 * 6, index // 3 * 12
    angle = index % 2 * math.pi / 2
    c, s = math.cos(angle), math.sin(angle)
    corners = []
    for x, y in ((-length / 2, -thickness / 2), (length / 2, -thickness / 2),
                 (length / 2, thickness / 2), (-length / 2, thickness / 2)):
        corners.append((cx + x * c - y * s, cy + x * s + y * c))
    for z in np.linspace(0, 8, 70):
        for edge in range(4):
            start, end = np.array(corners[edge]), np.array(corners[(edge + 1) % 4])
            for t in np.linspace(0, 1, 10):
                xy = start * (1 - t) + end * t
                points.append([*xy, z])
    elements.append({"id": f"synthetic-column-{index + 1:02d}",
        "geometry": {"kind": "oriented_box", "center": [cx, cy, 4], "rotation_z": angle,
            "sizes": {"length": length, "thickness": thickness, "height": 8}},
        "bbox": {"min": [min(p[0] for p in corners), min(p[1] for p in corners), 0],
            "max": [max(p[0] for p in corners), max(p[1] for p in corners), 8]}})
source = data_dir / "synthetic-columns.xyz"
np.savetxt(source, np.array(points), fmt="%.6f")
with db.db() as con:
    con.execute("INSERT INTO projects (id,name,description,created_at,updated_at) VALUES (?,?,?,?,?)",
        (project_id, "QA - synthetic column types", "Browser acceptance only; not a workshop survey", now, now))
    con.execute("INSERT INTO clouds (id,project_id,name,source_path,source_format,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
        (cloud_id, project_id, "Six synthetic columns", str(source), "xyz", now, now))
ingest_cloud(project_id, cloud_id, source)
with db.db() as con:
    for element in elements:
        con.execute("INSERT INTO elements (id,project_id,cloud_id,class_name,geometry_json,bbox_json,"
            "dimensions_json,confidence,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (element["id"], project_id, cloud_id, "column", db.dumps(element["geometry"]), db.dumps(element["bbox"]),
             db.dumps({"column_type": "solid", "section_coverage": 0.9}), 0.8, now, now))
print(json.dumps({"data_dir": str(data_dir), "project_id": project_id, "cloud_id": cloud_id,
    "elements": len(elements), "points": len(points)}))
