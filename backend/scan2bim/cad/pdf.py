"""A3 PDF sheet for a measured section (matplotlib, vector output)."""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Polygon as MplPolygon  # noqa: E402


def export_section_pdf(
    section: dict[str, Any],
    out_path: str | Path,
    cloud_name: str = "",
    project_name: str = "",
    scale: int = 50,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame = section["frame"]
    offset = frame["world_offset"]
    polygons = section["polygons"]
    if not polygons:
        raise ValueError("section contains no polygons to draw")

    xs_all: list[float] = []
    ys_all: list[float] = []
    for poly in polygons:
        for x, y in poly["points"]:
            xs_all.append(x + offset[0])
            ys_all.append(y + offset[1])
    minx, maxx = min(xs_all), max(xs_all)
    miny, maxy = min(ys_all), max(ys_all)
    width = max(1e-3, maxx - minx)
    height = max(1e-3, maxy - miny)

    fig = plt.figure(figsize=(16.54, 11.69))  # A3 landscape
    ax = fig.add_axes([0.08, 0.10, 0.86, 0.78])
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")

    for poly in polygons:
        pts = [(x + offset[0], y + offset[1]) for x, y in poly["points"]]
        patch = MplPolygon(
            pts,
            closed=True,
            fill=not poly.get("is_hole", False),
            facecolor=(0.86, 0.88, 0.91) if not poly.get("is_hole") else "white",
            edgecolor="#1a1a1a" if not poly.get("is_hole") else "#777777",
            linewidth=0.9,
            linestyle="--" if poly.get("is_hole") else "-",
            zorder=2,
        )
        ax.add_patch(patch)

    margin = max(width, height) * 0.15 + 1.0
    ax.set_xlim(minx - margin, maxx + margin)
    ax.set_ylim(miny - margin, maxy + margin)

    # Axis lines outside the footprint.
    ext = max(width, height) * 0.08 + 0.5
    ax.plot([minx, minx], [miny - ext, maxy + ext], color="#b03030", lw=0.7, ls="-.")
    ax.plot([maxx, maxx], [miny - ext, maxy + ext], color="#b03030", lw=0.7, ls="-.")
    ax.plot([minx - ext, maxx + ext], [miny, miny], color="#b03030", lw=0.7, ls="-.")
    ax.plot([minx - ext, maxx + ext], [maxy, maxy], color="#b03030", lw=0.7, ls="-.")

    # Overall dimensions.
    ax.annotate(
        "",
        xy=(minx, miny - ext * 0.6),
        xytext=(maxx, miny - ext * 0.6),
        arrowprops={"arrowstyle": "<->", "color": "#2060a0", "lw": 0.9},
    )
    ax.text(
        (minx + maxx) / 2,
        miny - ext * 0.95,
        f"{width:.3f} m",
        ha="center",
        va="top",
        fontsize=9,
        color="#2060a0",
    )
    ax.annotate(
        "",
        xy=(maxx + ext * 0.6, miny),
        xytext=(maxx + ext * 0.6, maxy),
        arrowprops={"arrowstyle": "<->", "color": "#2060a0", "lw": 0.9},
    )
    ax.text(
        maxx + ext * 0.8,
        (miny + maxy) / 2,
        f"{height:.3f} m",
        ha="left",
        va="center",
        rotation=90,
        fontsize=9,
        color="#2060a0",
    )

    title = "PLAN" if frame["kind"] == "horizontal" else "SECTION"
    fig.text(0.08, 0.93, f"{title} at {frame['position_world']:.3f} m", fontsize=18, weight="bold")
    fig.text(
        0.08,
        0.90,
        f"{project_name or 'Intelligent Scan-to-BIM'} — {cloud_name or 'point cloud'}"
        f"   |   scale 1:{scale} (A3)   |   {date.today().isoformat()}",
        fontsize=9,
        color="#444444",
    )
    fig.text(
        0.08,
        0.04,
        "Measured geometry from point cloud. Orthogonal regularisation applied where reported. "
        "Material and structural function are not inferred. Confidence and review status are "
        "stored per element in the project database.",
        fontsize=7,
        color="#666666",
    )
    fig.text(0.88, 0.04, f"slab thickness {frame['thickness']:.3f} m", fontsize=7, color="#666666")

    # Scale bar (10% of sheet width, rounded to a sensible engineering length).
    target = width * 0.2
    candidates = [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100]
    bar = min(candidates, key=lambda c: abs(c - target))
    x0 = maxx - bar
    y0 = miny - ext * 1.5
    ax.plot([x0, maxx], [y0, y0], color="black", lw=2)
    ax.text((x0 + maxx) / 2, y0 - ext * 0.15, f"{bar:g} m", ha="center", va="top", fontsize=7)

    fig.savefig(out_path, format="pdf", metadata={"Title": f"{title} {frame['position_world']:.3f} m"})
    plt.close(fig)
    return out_path
