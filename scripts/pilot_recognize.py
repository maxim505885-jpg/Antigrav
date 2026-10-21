"""Recognize an isolated candidate crop without altering the production DB."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from scan2bim.pointdata import NpyPointProvider, PointQuery
from scan2bim.pointdata.index import IndexedPointProvider
from scan2bim.geometry.section import CloudGeometry
from scan2bim.recognition import detect_structures


def main():
    data = ROOT / "data"
    definition = json.loads((data / "validation" / "pilot_candidates.json").read_text())
    candidate = definition["candidates"][0]
    with sqlite3.connect((data / "scan2bim.sqlite3").as_uri()+"?mode=ro",uri=True) as conn:
        conn.row_factory = sqlite3.Row
        cloud = dict(conn.execute("SELECT * FROM clouds WHERE id=?",(definition["cloud_id"],)).fetchone())
    folder = data / "projects" / cloud["project_id"] / "clouds" / cloud["id"]
    origin = np.array(definition["origin"])
    provider = NpyPointProvider(folder / "positions.npy",origin=origin,colors_path=folder / "colors.npy")
    reader = IndexedPointProvider(provider,folder / "spatial-index-v1")
    batches = list(reader.iter_points(PointQuery(tuple(candidate["bounds"]))))
    if not batches:
        raise ValueError("candidate contains no points")
    xyz = np.concatenate([b.xyz for b in batches])
    output = data / "validation" / "pilot-A"
    output.mkdir(parents=True,exist_ok=True)
    np.save(output / "positions.npy",(xyz-origin).astype(np.float32))
    np.save(output / "colors.npy",np.concatenate([b.rgb for b in batches]))
    np.save(output / "source_indices.npy",np.concatenate([b.source_indices for b in batches]))
    bounds_min, bounds_max = xyz.min(axis=0),xyz.max(axis=0)
    count = len(xyz)
    del xyz,batches
    geom = CloudGeometry(output / "positions.npy",origin,bounds_min,bounds_max,count)
    start = time.perf_counter()
    def progress(value,message):
        print(json.dumps({"progress":round(value,3),"message":message},ensure_ascii=True),flush=True)
    result = detect_structures(geom,progress=progress)
    payload = {"schema":"scan.pilot-recognition/1", "candidate":candidate,
               "source_cloud_id":cloud["id"], "stored_source_points":provider.count,
               "original_source_points":cloud["point_count"], "crop_points":count,
               "origin":origin.tolist(),"bbox_min":bounds_min.tolist(),"bbox_max":bounds_max.tolist(),
               "elapsed_s":round(time.perf_counter()-start,3), "result":asdict(result),
               "quality_status":"not validated against engineer ground truth",
               "production_database_modified":False}
    (output / "recognition.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"counts":dict(Counter(e.class_name for e in result.elements)),
                      "crop_points":count,"elapsed_s":payload["elapsed_s"],
                      "stats":result.stats},ensure_ascii=True),flush=True)


if __name__ == "__main__":
    main()
