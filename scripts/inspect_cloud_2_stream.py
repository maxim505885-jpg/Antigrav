import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

import numpy as np
from scan2bim.formats.rcs_native import extract_rcs_native

p2 = Path(r"C:\Users\maxim\Desktop\ДЛЯ ИИ\облоко ТОЧЕК\2.rcs")
out_dir = Path("data/projects/cloud_2_rcs_stream")
out_dir.mkdir(parents=True, exist_ok=True)

print(f"Checking existing stream in {out_dir}...")
stream_json = out_dir / "stream.json"
if not stream_json.exists():
    # If test_2_rcs has cached points, copy them over so we don't start from scratch
    cached = Path("data/.tmp/test_2_rcs")
    if (cached / "stream.json").exists():
        import shutil
        for f in cached.glob("*"):
            shutil.copy2(f, out_dir / f.name)
        print("Copied cached stream progress!")

# Now check stream state
if (out_dir / "stream.json").exists():
    import json
    data = json.loads((out_dir / "stream.json").read_text(encoding="utf-8"))
    committed = data.get("committed_count", 0)
    print(f"Staged {committed:,} points in {out_dir}")
    
    # Read first 50,000 xyz points to inspect bounding box and coordinates
    xyz_file = out_dir / "xyz.f64"
    if xyz_file.exists() and xyz_file.stat().st_size >= 50000 * 24:
        pts = np.fromfile(xyz_file, dtype=np.float64, count=50000 * 3).reshape(-1, 3)
        print("Point sample count:", len(pts))
        print("X min/max:", pts[:, 0].min(), pts[:, 0].max())
        print("Y min/max:", pts[:, 1].min(), pts[:, 1].max())
        print("Z min/max:", pts[:, 2].min(), pts[:, 2].max())
