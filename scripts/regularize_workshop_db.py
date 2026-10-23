"""Apply comprehensive structural regularization to workshop_cloud in data/scan2bim.sqlite3."""
import sqlite3
import json
from pathlib import Path
from scan2bim.structure.workshop_topology import regularize_workshop_model, WorkshopGridTopology

db_path = Path("data/scan2bim.sqlite3")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

rows = conn.execute("SELECT * FROM elements WHERE cloud_id = 'workshop_cloud'").fetchall()
print(f"Total elements loaded from DB: {len(rows)}")

elements = []
for r in rows:
    el = dict(r)
    el["geometry"] = json.loads(r["geometry_json"]) if r["geometry_json"] else {}
    el["bbox"] = json.loads(r["bbox_json"]) if r["bbox_json"] else None
    el["dimensions"] = json.loads(r["dimensions_json"]) if r["dimensions_json"] else {}
    el["metadata"] = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
    elements.append(el)

regularized, summary = regularize_workshop_model(elements)
print("Regularization Summary:")
print(json.dumps(summary, indent=2, ensure_ascii=False))

# Update DB
with conn:
    for el in regularized:
        dim_json = json.dumps(el.get("dimensions", {}), ensure_ascii=False)
        meta_json = json.dumps(el.get("metadata", {}), ensure_ascii=False)
        cls_name = el.get("class_name")
        conn.execute(
            """
            UPDATE elements 
            SET class_name = ?, dimensions_json = ?, metadata_json = ?
            WHERE id = ?
            """,
            (cls_name, dim_json, meta_json, el["id"])
        )

print("Database updated successfully!")
conn.close()
