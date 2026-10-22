"""Run geometry-based recognition and produce a review-only draft package."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from scan2bim.pipeline_single_pass import WorkshopPipeline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("positions", type=Path, help="path to a derived positions.npy cloud")
    parser.add_argument("--output", type=Path, default=Path("data/output/workshop_draft"))
    parser.add_argument("--title", default="Производственный корпус")
    args = parser.parse_args()
    result = WorkshopPipeline(args.output).execute_pipeline(args.positions, project_title=args.title)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
