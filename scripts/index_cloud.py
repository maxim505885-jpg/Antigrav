"""Build a local stored-cloud index and compare its query with a full scan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from scan2bim.pointdata import NpyPointProvider, PointQuery
from scan2bim.pointdata.index import build_index, IndexedPointProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud-id", default="2621e5a320df49949d04aa1b7399539e")
    parser.add_argument("--bounds", type=float, nargs=6, default=(-65,35,-5.27,-45,55,10.69))
    args = parser.parse_args()
    query = PointQuery(tuple(args.bounds))
    data = ROOT / "data"
    with sqlite3.connect((data / "scan2bim.sqlite3").as_uri()+"?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM clouds WHERE id=?", (args.cloud_id,)).fetchone()
        if row is None:
            raise ValueError("cloud not found")
        cloud = dict(row)
    folder = data / "projects" / cloud["project_id"] / "clouds" / cloud["id"]
    origin = [cloud[f"origin_{axis}"] for axis in "xyz"]
    source = NpyPointProvider(folder / "positions.npy",origin=origin,colors_path=folder / "colors.npy")
    directory = folder / "spatial-index-v1"
    if not directory.exists():
        if shutil.disk_usage(folder).free < source.count*8 + 1024**3:
            raise ValueError("insufficient disk budget for index plus 1 GiB reserve")
        build_index(source, directory)
    indexed = IndexedPointProvider(source, directory)
    times = {}
    all_ids = []
    for label, reader in (("linear",source),("indexed",indexed)):
        start = time.perf_counter()
        ids = [b.source_indices for b in reader.iter_points(query)]
        ids = np.sort(np.concatenate(ids)) if ids else np.empty(0,dtype=np.int64)
        times[label] = round(time.perf_counter()-start,4)
        all_ids.append(ids)
    np.testing.assert_array_equal(all_ids[0],all_ids[1])
    result = {"cloud_id":cloud["id"], "stored_point_count":source.count,
              "original_point_count":cloud["point_count"], "query_world_bounds":query.bounds,
              "selected_points":len(all_ids[0]),"same_source_rows":True,
              "timings_s_including_id_sort":times,"index":indexed.metadata,
              "note":"Stored 40M sample only; not an index of every original RCS point."}
    output = data / "validation" / "index_validation.json"
    output.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
