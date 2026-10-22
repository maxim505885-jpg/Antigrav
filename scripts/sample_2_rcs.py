import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

from scan2bim.formats.rcs_native import read_rcs_native

p2 = Path(r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\2.rcs")
print(f"Reading sample from {p2} (max 50,000 points)...")
cloud = read_rcs_native(p2, max_points=50000)
print(f"Points read: {len(cloud.positions)}")
print(f"BBox min: {cloud.positions.min(axis=0)}")
print(f"BBox max: {cloud.positions.max(axis=0)}")
print(f"Has colors: {cloud.colors is not None}")
