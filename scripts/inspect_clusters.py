import json
import numpy as np
from scan2bim.db import rows
from scipy.spatial.distance import cdist

cols = rows("SELECT id, geometry_json, bbox_json FROM elements WHERE cloud_id = 'workshop_cloud' AND class_name = 'column'")
centers = []
for c in cols:
    g = json.loads(c['geometry_json'])
    b = json.loads(c['bbox_json'])
    pt = g.get('center') or [(b['min'][0]+b['max'][0])/2, (b['min'][1]+b['max'][1])/2, (b['min'][2]+b['max'][2])/2]
    centers.append(pt)
centers = np.array(centers)

dists = cdist(centers[:, :2], centers[:, :2])
np.fill_diagonal(dists, np.inf)

close_pairs = dists < 2.0
num_close = np.sum(close_pairs, axis=1)
print(f"Total columns: {len(centers)}")
print(f"Columns with another column closer than 2.0m: {np.sum(num_close > 0)} out of {len(centers)}")
print(f"Max neighbors within 2.0m of a single column: {np.max(num_close)}")

for k in range(1, 8):
    print(f"  Columns with {k} neighbors within 2.0m: {np.sum(num_close == k)}")

# Let's inspect an example of a cluster of columns that are standing right next to each other
cluster_centers = []
visited = set()
clusters = []
for i in range(len(centers)):
    if i in visited:
        continue
    # find all within 2.0m
    cluster = [i]
    queue = [i]
    visited.add(i)
    while queue:
        curr = queue.pop(0)
        neighbors = np.where(dists[curr] < 2.0)[0]
        for n in neighbors:
            if n not in visited:
                visited.add(n)
                queue.append(n)
                cluster.append(n)
    clusters.append(cluster)

clusters_by_size = {}
for cl in clusters:
    s = len(cl)
    clusters_by_size[s] = clusters_by_size.get(s, 0) + 1

print(f"\nCluster sizes (distance < 2.0m):")
for s in sorted(clusters_by_size.keys()):
    print(f"  Clusters of size {s}: {clusters_by_size[s]}")

# Print an example cluster with size >= 4
for cl in clusters:
    if len(cl) >= 4:
        print(f"\nExample cluster of {len(cl)} columns standing together:")
        for idx in cl:
            pt = centers[idx]
            print(f"  Column idx {idx}: X={pt[0]:.3f}, Y={pt[1]:.3f}, Z={pt[2]:.3f}")
        break
