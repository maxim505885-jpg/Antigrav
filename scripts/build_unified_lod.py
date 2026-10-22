import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path("backend").resolve()))

from scan2bim.pointdata.octree import StreamingLodBuilder

def main():
    base_dir = Path("data/output/unified_stitched_release")
    pos_path = base_dir / "unified_cloud" / "positions.npy"
    lod_dir = base_dir / "lod"
    
    print(f"Building Streaming LOD pyramid for unified cloud: {pos_path}")
    t0 = time.time()
    builder = StreamingLodBuilder()
    manifest = builder.build_lod_pyramid(pos_path, lod_dir, cloud_id="unified")
    elapsed = time.time() - t0
    
    print(f"LOD pyramid generated in {elapsed:.2f} s:")
    print(f"  Total points: {manifest['total_points']:,}")
    print(f"  Bounds center: {manifest['bounds']['center']}")
    for lvl in manifest["levels"]:
        print(f"  - Level {lvl['level']}: {lvl['name']} | {lvl['points_count']:,} pts | {lvl['byte_size'] / 1024:.1f} KB | dist > {lvl['distance_min']}m")

if __name__ == "__main__":
    main()
