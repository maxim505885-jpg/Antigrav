import sqlite3
import json

db_path = "data/scan2bim.sqlite3"
conn = sqlite3.connect(db_path)
c = conn.cursor()

project_id = "cf967dc89b8c46b899d428fbfa122d77"

print("=== PROJECT INFO ===")
for r in c.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchall():
    print(r)

print("\n=== SAMPLE BEAMS ===")
for r in c.execute("SELECT id, class_name, bbox_json, dimensions_json, metadata_json FROM elements WHERE project_id = ? AND class_name = 'beam' LIMIT 3", (project_id,)).fetchall():
    print(r[0], r[1])
    print("  bbox:", r[2])
    print("  dims:", r[3])
    print("  meta:", r[4])

print("\n=== SAMPLE TRUSSES ===")
for r in c.execute("SELECT id, class_name, bbox_json, dimensions_json, metadata_json FROM elements WHERE project_id = ? AND class_name = 'truss' LIMIT 3", (project_id,)).fetchall():
    print(r[0], r[1])
    print("  bbox:", r[2])
    print("  dims:", r[3])
    print("  meta:", r[4])

print("\n=== SAMPLE BRACES ===")
for r in c.execute("SELECT id, class_name, bbox_json, dimensions_json, metadata_json FROM elements WHERE project_id = ? AND class_name = 'brace' LIMIT 3", (project_id,)).fetchall():
    print(r[0], r[1])
    print("  bbox:", r[2])
    print("  dims:", r[3])
    print("  meta:", r[4])
