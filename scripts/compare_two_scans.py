import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

import json
import numpy as np

# Load cloud 1 metadata and points sample
cloud1_meta_file = Path("data/projects/3f6321f10c9145db909ec27b1c2ba044/clouds/2621e5a320df49949d04aa1b7399539e/meta.json")
cloud1_meta = json.loads(cloud1_meta_file.read_text(encoding="utf-8"))

cloud1_pos_file = Path("data/projects/3f6321f10c9145db909ec27b1c2ba044/clouds/2621e5a320df49949d04aa1b7399539e/positions.npy")
# Sample 100k points from cloud 1
pts1 = np.load(cloud1_pos_file, mmap_mode="r")[:100000]

# Sample 100k points from cloud 2
pts2_file = Path("data/projects/cloud_2_rcs_stream/xyz.f64")
pts2 = np.fromfile(pts2_file, dtype=np.float64, count=100000 * 3).reshape(-1, 3)

print("=== СРАВНЕНИЕ ДВУХ СКАНОВ ===")
print("Скан 1 (1.rcs):")
print(f"  Точек в файле: {cloud1_meta['source_point_count']:,}")
print(f"  Габариты BBox: X[{cloud1_meta['bbox_min'][0]:.2f}, {cloud1_meta['bbox_max'][0]:.2f}], Y[{cloud1_meta['bbox_min'][1]:.2f}, {cloud1_meta['bbox_max'][1]:.2f}], Z[{cloud1_meta['bbox_min'][2]:.2f}, {cloud1_meta['bbox_max'][2]:.2f}]")
print(f"  Центр/Origin: {cloud1_meta['origin']}")

print("\nСкан 2 (2.rcs):")
print(f"  Размер файла: 13.9 GB (~580+ млн точек)")
print(f"  Выборка X min/max: [{pts2[:, 0].min():.2f}, {pts2[:, 0].max():.2f}]")
print(f"  Выборка Y min/max: [{pts2[:, 1].min():.2f}, {pts2[:, 1].max():.2f}]")
print(f"  Выборка Z min/max: [{pts2[:, 2].min():.2f}, {pts2[:, 2].max():.2f}]")

# Расстояние между центроидами выборок
c1 = pts1.mean(axis=0)
c2 = pts2.mean(axis=0)
dist = np.linalg.norm(c1 - c2)
print(f"\nЦентроид выборки Скан 1: {c1}")
print(f"Центроид выборки Скан 2: {c2}")
print(f"Смещение между центроидами: dx={c2[0]-c1[0]:.2f}m, dy={c2[1]-c1[1]:.2f}m, dz={c2[2]-c1[2]:.2f}m (общая дистанция: {dist:.2f} м)")
