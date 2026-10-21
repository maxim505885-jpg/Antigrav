import sqlite3
import json

db_path = "data/scan2bim.sqlite3"
conn = sqlite3.connect(db_path)
c = conn.cursor()

print("=== TABLES ===")
for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
    print(r[0])

print("\n=== CLOUDS SCHEMA ===")
for r in c.execute("PRAGMA table_info(clouds)").fetchall():
    print(r)

print("\n=== ELEMENTS SCHEMA ===")
for r in c.execute("PRAGMA table_info(elements)").fetchall():
    print(r)

print("\n=== CLOUDS DATA ===")
for r in c.execute("SELECT * FROM clouds").fetchall():
    print(r)

import sqlite3
import json

db_path = "data/scan2bim.sqlite3"
conn = sqlite3.connect(db_path)
c = conn.cursor()

print("=== ELEMENTS SUMMARY BY CLASS_NAME ===")
for r in c.execute("SELECT class_name, count(*), round(min(confidence), 2), round(max(confidence), 2) FROM elements GROUP BY class_name").fetchall():
    print(f"Class: {r[0]:15} Count: {r[1]:4} Conf: [{r[2]}..{r[3]}]")

real_cloud_id = "2621e5a320df49949d04aa1b7399539e"
print(f"\n=== REAL CLOUD 1.rcs ELEMENTS BY CLASS_NAME ===")
for r in c.execute("SELECT class_name, count(*) FROM elements WHERE cloud_id = ? GROUP BY class_name", (real_cloud_id,)).fetchall():
    print(f"Class: {r[0]:15} Count: {r[1]:4}")

print("\n=== SAMPLE COLUMNS (first 3) ===")
for r in c.execute("SELECT id, class_name, bbox_json, dimensions_json, metadata_json FROM elements WHERE cloud_id = ? AND class_name = 'column' LIMIT 3", (real_cloud_id,)).fetchall():
    print("ID:", r[0], "Class:", r[1])
    print("  bbox:", r[2])
    print("  dimensions:", r[3])
    print("  metadata:", r[4][:120] if r[4] else None)

print("\n=== ELEMENTS BY PROJECT AND CLASS ===")
for r in c.execute("SELECT project_id, cloud_id, class_name, count(*) FROM elements GROUP BY project_id, cloud_id, class_name").fetchall():
    print(r)



