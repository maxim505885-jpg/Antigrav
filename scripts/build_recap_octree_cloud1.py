import sys
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))

import json
from scan2bim.pointdata.octree import ReCapOctreeBuilder

# Point to cloud 1
cloud_dir = Path("data/projects/3f6321f10c9145db909ec27b1c2ba044/clouds/2621e5a320df49949d04aa1b7399539e")
positions_p = cloud_dir / "positions.npy"
out_octree = Path("data/output/workshop_release/recap_octree")

builder = ReCapOctreeBuilder()
manifest = builder.build_lod_pyramid(positions_p, out_octree)

assert (out_octree / "lod_0.npy").exists()
assert (out_octree / "lod_1.npy").exists()
assert (out_octree / "octree_manifest.json").exists()
print("ReCap Octree Pyramid generation verified!")
