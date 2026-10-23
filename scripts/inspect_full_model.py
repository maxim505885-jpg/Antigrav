import json
import numpy as np
from scan2bim.db import rows

elems = rows("SELECT class_name, geometry_json, dimensions_json, bbox_json FROM elements WHERE cloud_id = 'workshop_cloud'")
print(f"Total elements: {len(elems)}")

counts = {}
for e in elems:
    cls = e['class_name']
    counts[cls] = counts.get(cls, 0) + 1

print("Class counts:")
for k, v in sorted(counts.items()):
    print(f"  {k:10s}: {v}")

# Inspect each class sample
for cls in sorted(counts.keys()):
    sample = [e for e in elems if e['class_name'] == cls][0]
    g = json.loads(sample['geometry_json'])
    d = json.loads(sample['dimensions_json'])
    b = json.loads(sample['bbox_json'])
    print(f"\nSample {cls}:")
    print(f"  kind: {g.get('kind')}")
    print(f"  center: {g.get('center')}")
    print(f"  sizes: {g.get('sizes')}")
    print(f"  dims: {d}")
    print(f"  bbox: {b}")
