"""Create local-only survey density views; candidates are NOT verified truth."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from scan2bim.pointdata import NpyPointProvider, PointQuery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud-id", default="2621e5a320df49949d04aa1b7399539e")
    args = parser.parse_args()
    data = ROOT / "data"
    with sqlite3.connect((data / "scan2bim.sqlite3").as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM clouds WHERE id=?", (args.cloud_id,)).fetchone()
        if row is None:
            raise ValueError("cloud not found")
        cloud = dict(row)
    folder = data / "projects" / cloud["project_id"] / "clouds" / cloud["id"]
    origin = [cloud[f"origin_{axis}"] for axis in "xyz"]
    bounds = tuple(cloud[f"bbox_{side}_{axis}"] for side in ("min", "max") for axis in "xyz")
    provider = NpyPointProvider(folder / "positions.npy", origin=origin,
                                colors_path=folder / "colors.npy")
    lo, hi = np.array(bounds[:3]), np.array(bounds[3:])
    # Pad metadata bounds: their rounding must not cut away original points.
    extent = (lo[0] - .01, hi[0] + .01, lo[1] - .01, hi[1] + .01)
    edges_x = np.linspace(extent[0], extent[1], 1001)
    edges_y = np.linspace(extent[2], extent[3], 701)
    layers = [np.zeros((1000, 700), dtype=np.int64) for _ in range(3)]
    z_ranges = [(lo[2]-.01, hi[2]+.01), (4.8, 5.7), (6.5, 9.9)]
    seen = 0
    start = time.perf_counter()
    for batch in provider.iter_points(PointQuery(tuple(lo-.01) + tuple(hi+.01))):
        seen += len(batch.xyz)
        for histogram, (zmin, zmax) in zip(layers, z_ranges):
            selected = batch.xyz[(batch.xyz[:, 2] >= zmin) & (batch.xyz[:, 2] <= zmax)]
            histogram += np.histogram2d(selected[:, 0], selected[:, 1], bins=(edges_x, edges_y))[0].astype(np.int64)
    candidates = []
    for label, x in zip("ABC", (-65., -30., 5.)):
        candidates.append({"label": label, "bounds": [x, 35., float(lo[2]), x+20, 55., float(hi[2])],
                           "status": "candidate_unverified", "ground_truth": [], "tolerances": None})
    fig, axes = plt.subplots(3, 1, figsize=(15, 20), constrained_layout=True)
    for ax, hist, title in zip(axes, layers, ["All stored points", "Band Z = 4.8 .. 5.7 m", "Roof band Z = 6.5 .. 9.9 m"]):
        ax.imshow(np.log1p(hist.T), origin="lower", extent=extent, cmap="magma", aspect="equal")
        for candidate in candidates:
            x,y,_,xmax,ymax,_ = candidate["bounds"]
            ax.add_patch(Rectangle((x,y),xmax-x,ymax-y,fill=False,edgecolor="cyan",lw=1.5))
            ax.text(x+1,ymax-3,candidate["label"],color="cyan",fontsize=17,weight="bold")
        ax.set(title=title, xlabel="World X (m)", ylabel="World Y (m)")
    fig.suptitle("Local survey overview — A/B/C are candidate areas, not verified structural bays", fontsize=15)
    output = data / "validation"
    output.mkdir(exist_ok=True, parents=True)
    fig.savefig(output / "pilot_candidates.png", dpi=120)
    plt.close(fig)
    result = {"schema":"scan.pilot-candidates/1", "cloud_id":cloud["id"], "origin":origin,
              "source_point_count":cloud["point_count"], "stored_points":provider.count,
              "points_visited":seen,"elapsed_s":round(time.perf_counter()-start,3),
              "resolution":"stored sample, NOT full RCS", "candidates":candidates}
    (output / "pilot_candidates.json").write_text(json.dumps(result,indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
