import sqlite3
import os

for root, dirs, files in os.walk("data"):
    for f in files:
        if f.endswith(".db"):
            p = os.path.join(root, f)
            conn = sqlite3.connect(p)
            try:
                cur = conn.cursor()
                cur.execute("SELECT id, positions_path FROM clouds WHERE id LIKE '2621%'")
                r = cur.fetchone()
                if r:
                    print("DB:", p)
                    print("Row:", r)
            except Exception:
                pass
