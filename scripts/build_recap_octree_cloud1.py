"""Legacy filename: create a sampled web preview, not a ReCap project."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from scan2bim.pointdata.octree import PreviewLodBuilder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("positions", type=Path, help="path to a derived positions.npy file")
    parser.add_argument("--output", type=Path, default=Path("data/output/web_preview"))
    args = parser.parse_args()
    manifest = PreviewLodBuilder().build_lod_pyramid(args.positions, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
