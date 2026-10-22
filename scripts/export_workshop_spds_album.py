import sqlite3
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from scan2bim.cad.spds_full_set import generate_full_spds_album

db_path = Path("data/scan2bim.sqlite3")
conn = sqlite3.connect(db_path)
c = conn.cursor()

# Get all elements for the workshop project (cf967dc89b8c46b899d428fbfa122d77)
project_id = "cf967dc89b8c46b899d428fbfa122d77"
rows = c.execute(
    "SELECT id, class_name, geometry_json, bbox_json, dimensions_json FROM elements WHERE project_id = ?",
    (project_id,)
).fetchall()

elements = []
for r in rows:
    el_id, class_name, geom_json, bbox_json, dims_json = r
    geom = json.loads(geom_json) if geom_json else {}
    bbox = json.loads(bbox_json) if bbox_json else {}
    dims = json.loads(dims_json) if dims_json else {}

    # If center not in geom, derive from bbox
    if "center" not in geom and "min" in bbox and "max" in bbox:
        geom["center"] = [
            (bbox["min"][0] + bbox["max"][0]) / 2.0,
            (bbox["min"][1] + bbox["max"][1]) / 2.0,
            (bbox["min"][2] + bbox["max"][2]) / 2.0,
        ]

    elements.append({
        "id": el_id,
        "class_name": class_name,
        "geometry": geom,
        "bbox": bbox,
        "dimensions": dims,
    })

print(f"Loaded {len(elements)} structural elements for real workshop 1.rcs.")

out_dir = Path("data/output/workshop_release/spds_album")
manifest = generate_full_spds_album(
    elements=elements,
    output_dir=out_dir,
    project_title="Производственный корпус (облако 1.rcs)",
)

print("\n=== GENERATION COMPLETE ===")
print("Album PDF:", manifest["album_pdf_path"])
for s in manifest["sheets"]:
    print(f"Sheet {s['num']}: {s['title']}")
    print(f"  DXF: {s['dxf_path']} (size: {Path(s['dxf_path']).stat().st_size} bytes)")
    print(f"  PDF: {s['pdf_path']} (size: {Path(s['pdf_path']).stat().st_size} bytes)")
