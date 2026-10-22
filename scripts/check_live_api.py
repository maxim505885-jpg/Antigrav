import urllib.request
import json

res2 = urllib.request.urlopen('http://127.0.0.1:8000/api/v1/clouds/workshop_cloud/elements')
elems = json.loads(res2.read().decode('utf-8'))
print(f"Total elements: {len(elems)}")

by_row = {}
for e in elems:
    if e['class_name'] == 'column':
        row = e.get('dimensions', {}).get('row')
        by_row.setdefault(row, []).append(e)

for r in ['А', 'Б', 'В', 'Г']:
    cols = by_row.get(r, [])
    axes = sorted([c.get('dimensions', {}).get('axis') for c in cols])
    print(f"  Ряд {r}: {len(cols)} колонн (оси {axes[0]}..{axes[-1]})")
