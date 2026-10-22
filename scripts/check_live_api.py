import urllib.request
import json

res = urllib.request.urlopen('http://127.0.0.1:8000/api/v1/projects/workshop_project/clouds')
clouds = json.loads(res.read().decode('utf-8'))
for c in clouds:
    print(f"Cloud {c['id']}: name={c['name']} status={c['status']}")

res2 = urllib.request.urlopen('http://127.0.0.1:8000/api/v1/clouds/workshop_cloud/elements')
elems = json.loads(res2.read().decode('utf-8'))
print(f"Total elements: {len(elems)}")
col_marks = [e.get('dimensions', {}).get('mark') for e in elems if e['class_name'] == 'column']
print(f"Columns count: {len(col_marks)}")
print("Sample column marks:", col_marks[:16])

# Group by row
by_row = {}
for e in elems:
    if e['class_name'] == 'column':
        row = e.get('dimensions', {}).get('row')
        by_row.setdefault(row, []).append(e)

for r in ['A', 'B', 'C', 'D']:
    print(f"  Row {r}: {len(by_row.get(r, []))} columns")
