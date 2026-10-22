import sqlite3
from pathlib import Path

db = sqlite3.connect("data/scan2bim.sqlite3")
cursor = db.cursor()

print("--- PROJECTS ---")
for row in cursor.execute("SELECT id, name, created_at FROM projects"):
    print(row)

print("\n--- CLOUDS ---")
for row in cursor.execute("SELECT id, project_id, name, source_path, source_format, point_count, status FROM clouds"):
    print(row)
