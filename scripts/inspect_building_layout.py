import numpy as np

pos = np.load('data/projects/workshop_project/clouds/workshop_cloud/positions.npy', mmap_mode='r')
sample = pos[::50] # ~870,000 points

deg = 10.260
rad = np.radians(deg)
c, s = np.cos(rad), np.sin(rad)
u = sample[:, 0] * c + sample[:, 1] * s
v = -sample[:, 0] * s + sample[:, 1] * c
z = sample[:, 2]

print("U percentiles (1, 5, 25, 50, 75, 95, 99):", np.percentile(u, [1, 5, 25, 50, 75, 95, 99]))
print("V percentiles (1, 5, 25, 50, 75, 95, 99):", np.percentile(v, [1, 5, 25, 50, 75, 95, 99]))
print("Z percentiles (1, 5, 25, 50, 75, 95, 99):", np.percentile(z, [1, 5, 25, 50, 75, 95, 99]))

# Check if there are distinct buildings/sections along U
hist_u, edges_u = np.histogram(u, bins=60)
for left, right, cnt in zip(edges_u[:-1], edges_u[1:], hist_u):
    if cnt > 1000:
        bar = '#' * int(cnt / 5000)
        print(f"U [{left:6.1f} .. {right:6.1f}]: {cnt:6d} {bar}")
