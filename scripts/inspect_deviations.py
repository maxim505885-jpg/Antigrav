import sqlite3, json

conn = sqlite3.connect('data/scan2bim.sqlite3')
rows = conn.execute("SELECT id, dimensions_json FROM elements WHERE cloud_id = 'workshop_cloud' AND class_name = 'column'").fetchall()
print(f"Total columns: {len(rows)}")

drs = []
for r in rows:
    dim = json.loads(r[1])
    dr = dim.get('delta_r_mm', 0)
    drs.append((dr, dim.get('mark'), dim.get('row'), dim.get('axis'), dim.get('delta_u_mm'), dim.get('delta_v_mm')))

drs.sort(key=lambda x: x[0])
print("\nSmallest 10 deviations:")
for dr, mark, row, axis, du, dv in drs[:10]:
    print(f"  {mark}: dr={dr} mm (du={du} mm, dv={dv} mm)")

print("\nLargest 10 deviations:")
for dr, mark, row, axis, du, dv in drs[-10:]:
    print(f"  {mark}: dr={dr} mm (du={du} mm, dv={dv} mm)")

avg_dr = sum(x[0] for x in drs) / len(drs)
print(f"\nAverage horizontal deviation: {avg_dr:.1f} mm")
