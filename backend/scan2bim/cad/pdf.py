"""A3 PDF sheet for a measured section (matplotlib, vector output)."""
from __future__ import annotations

import math
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Polygon as MplPolygon  # noqa: E402


def structural_schedule_from_dxf(doc) -> dict[str, Any]:
    """Read the actual editable DXF cells, not a second measurement model."""
    cells, widths, summaries = {}, {}, []
    for entity in doc.modelspace().query('TEXT[layer=="S2B-SCHEDULE"]'):
        if not entity.has_xdata("S2B-SCHEDULE"):
            continue
        tags = entity.get_xdata("S2B-SCHEDULE")
        if tags[0].code == 1000:
            if tags[0].value == "summary":
                summaries.append(entity.dxf.text)
            continue
        row, column = int(tags[0].value), int(tags[1].value)
        cells[row, column] = entity.dxf.text
        if row == 0:
            widths[column] = float(tags[2].value)
    if not cells:
        return {"headers": [], "rows": [], "widths": [], "summaries": summaries}
    column_count = max(column for row, column in cells) + 1
    row_count = max(row for row, column in cells) + 1
    if len(cells) != column_count * row_count or len(widths) != column_count:
        raise ValueError("DXF schedule contains incomplete cells")
    rows = [[cells[row, column] for column in range(column_count)] for row in range(row_count)]
    return {"headers": rows[0], "rows": rows[1:],
        "widths": [widths[column] for column in range(column_count)], "summaries": summaries}


def plan_entity_in_window(entity, bound, window) -> bool:
    """Clip physical geometry, but never present a partial dimension as complete."""
    if bound is None or not bound.has_data:
        return False
    if window is None:
        return True
    x0, x1, y0, y1 = window
    if entity.dxftype() == "DIMENSION":
        return (x0 <= bound.extmin.x and bound.extmax.x <= x1
            and y0 <= bound.extmin.y and bound.extmax.y <= y1)
    return not (bound.extmax.x < x0 or bound.extmin.x > x1
        or bound.extmax.y < y0 or bound.extmin.y > y1)


def _fragment_geometry_extent(entities, entity_bounds, window) -> str:
    """Describe the axis-aligned extent of physical plan geometry visible in a tile.

    Values are clipped entity bounding boxes, not grid-chain dimensions or a
    substitute for measured member coordinates. The label makes that scope
    explicit so a tile boundary is never presented as a structural axis.
    """
    x0, x1, y0, y1 = window
    visible = []
    for entity in entities:
        bound = entity_bounds.get(entity.dxf.handle)
        if bound is None or not bound.has_data:
            continue
        low_x, high_x = max(x0, bound.extmin.x), min(x1, bound.extmax.x)
        low_y, high_y = max(y0, bound.extmin.y), min(y1, bound.extmax.y)
        if low_x <= high_x and low_y <= high_y:
            visible.append((low_x, high_x, low_y, high_y))
    label = "Охват геометрии в окне (по габаритным коробкам, не цепочка осей): "
    if not visible:
        return label + "объектов нет."
    min_x = min(item[0] for item in visible)
    max_x = max(item[1] for item in visible)
    min_y = min(item[2] for item in visible)
    max_y = max(item[3] for item in visible)
    return (f"{label}X {min_x:.3f}..{max_x:.3f} м (ΔX={max_x-min_x:.3f} м); "
            f"Y {min_y:.3f}..{max_y:.3f} м (ΔY={max_y-min_y:.3f} м).")


def _export_paginated_plan(doc, out_path: Path, drawing_type: str, project_name: str, scale: int, issue_mode: str) -> None:
    from ezdxf import bbox
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    from matplotlib.backends.backend_pdf import PdfPages

    if scale < 10 or scale > 1000:
        raise ValueError("PDF plan scale must be between 10 and 1000")
    schedule = structural_schedule_from_dxf(doc)
    plan_layers = {"S2B-COLUMNS", "S2B-CRANE-GIRDERS", "S2B-MARKS", "S2B-DIMS"}
    plan = [entity for entity in doc.modelspace() if entity.dxf.layer in plan_layers]
    cache = bbox.Cache()
    bounds = bbox.extents(plan, cache=cache)
    if bounds.has_data:
        min_x, min_y = bounds.extmin.x - 0.5, bounds.extmin.y - 0.5
        max_x, max_y = bounds.extmax.x + 0.5, bounds.extmax.y + 0.5
    else:
        min_x = min_y = 0.0
        max_x = max_y = 1.0
    # The physical axes rectangle and model limits have the same aspect ratio.
    axes_rect = [0.04, 0.10, 0.92, 0.80]
    tile_width = 16.54 * 25.4 * axes_rect[2] * scale / 1000
    tile_height = 11.69 * 25.4 * axes_rect[3] * scale / 1000
    overlap = min(2.0, tile_width * 0.1, tile_height * 0.1)
    nx = max(1, math.ceil((max_x - min_x - overlap) / (tile_width - overlap)))
    ny = max(1, math.ceil((max_y - min_y - overlap) / (tile_height - overlap)))
    if nx * ny > 200:
        raise ValueError("PDF plan exceeds 200 fragments; choose a smaller area or a larger scale denominator")
    entity_bounds = {entity.dxf.handle: bbox.extents([entity], cache=cache) for entity in plan}
    physical_plan = [entity for entity in plan
        if entity.dxf.layer in {"S2B-COLUMNS", "S2B-CRANE-GIRDERS"}]
    config = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.BLACK)
    title = "План колонн" if drawing_type == "columns" else "План подкрановых балок"
    issue_stamp = "ЧЕРНОВИК · НЕ ДЛЯ РАБОТЫ" if issue_mode == "draft" else "ФИНАЛЬНЫЙ ВЫПУСК · ТОЛЬКО ПРОВЕРЕННЫЕ ОБЪЕКТЫ"
    page_number = 0

    def new_page(subtitle: str):
        nonlocal page_number
        page_number += 1
        fig = plt.figure(figsize=(16.54, 11.69))
        fig.text(0.035, 0.96, project_name or "Intelligent Scan-to-BIM", fontsize=12, weight="bold")
        fig.text(0.965, 0.96, title, fontsize=12, ha="right")
        fig.text(0.50, 0.96, issue_stamp, fontsize=10, color="#b00020" if issue_mode == "draft" else "#176b32", ha="center", weight="bold")
        fig.text(0.035, 0.925, subtitle, fontsize=10)
        fig.text(0.965, 0.035, f"Лист {page_number}", fontsize=8, ha="right")
        return fig

    def render_plan(fig, window=None):
        ax = fig.add_axes(axes_rect)
        def include(entity):
            bound = entity_bounds.get(entity.dxf.handle)
            return plan_entity_in_window(entity, bound, window)
        Frontend(RenderContext(doc), MatplotlibBackend(ax), config=config).draw_layout(
            doc.modelspace(), finalize=True, filter_func=include)
        if window:
            ax.set_xlim(window[0], window[1])
            ax.set_ylim(window[2], window[3])
            ax.set_aspect("equal", adjustable="box")
        else:
            ax.set_aspect("equal", adjustable="datalim")
        ax.axis("off")
        fig.set_size_inches(16.54, 11.69, forward=True)

    with PdfPages(out_path, metadata={"Title": f"{title} - {project_name}"}) as pdf:
        if nx * ny > 1:
            fig = new_page(f"Обзорная схема; не в масштабе. Фрагменты: {nx} × {ny}; рабочий масштаб 1:{scale}.")
            try:
                render_plan(fig)
                pdf.savefig(fig)
            finally:
                plt.close(fig)
        for iy in range(ny):
            for ix in range(nx):
                x = min_x + ix * (tile_width - overlap)
                y = min_y + iy * (tile_height - overlap)
                if nx == 1:
                    x = (min_x + max_x - tile_width) / 2
                if ny == 1:
                    y = (min_y + max_y - tile_height) / 2
                fig = new_page(f"Фрагмент {ix + 1}/{nx}, {iy + 1}/{ny}; М 1:{scale}; печатать 100%, без подгонки.")
                try:
                    render_plan(fig, (x, x + tile_width, y, y + tile_height))
                    if nx * ny > 1:
                        sizes = "; ".join(f"{'X' if abs(entity.dxf.get('angle', 0)) < 1e-6 else 'Y'} "
                            f"{entity.get_measurement():.3f} м" for entity in plan if entity.dxftype() == "DIMENSION")
                        fig.text(0.035, 0.905, f"Габариты комплекта: {sizes}. Полные размерные линии — на обзорной схеме.", fontsize=8)
                    fig.text(0.035, 0.072, f"Окно листа: X {x:.3f}..{x + tile_width:.3f} м; "
                        f"Y {y:.3f}..{y + tile_height:.3f} м.", fontsize=8)
                    fig.text(0.035, 0.052,
                        _fragment_geometry_extent(physical_plan, entity_bounds, (x, x + tile_width, y, y + tile_height)),
                        fontsize=7)
                    pdf.savefig(fig)
                finally:
                    plt.close(fig)
        rows_per_page = 25
        summary_pending = list(schedule["summaries"])
        widths = schedule["widths"]
        for start in range(0, len(schedule["rows"]), rows_per_page):
            chunk = schedule["rows"][start:start + rows_per_page]
            fig = new_page(f"Ведомость экземпляров - строки {start + 1}..{start + len(chunk)} из {len(schedule['rows'])}.")
            try:
                ax = fig.add_axes([0.035, 0.10, 0.93, 0.80])
                ax.axis("off")
                height = (len(chunk) + 1) * 0.032
                table = ax.table(cellText=chunk, colLabels=schedule["headers"],
                    colWidths=[value / sum(widths) for value in widths], cellLoc="left",
                    bbox=[0, 1 - height, 1, height])
                table.auto_set_font_size(False)
                table.set_fontsize(9)
                for (row, column), cell in table.get_celld().items():
                    cell.set_linewidth(0.5)
                    cell.PAD = 0.03
                    if row == 0:
                        cell.set_text_props(weight="bold")
                        cell.set_facecolor("#eef2f6")
                if start + len(chunk) == len(schedule["rows"]) and summary_pending:
                    top = 1 - height - 0.05
                    if top - len(summary_pending) * 0.035 > 0.02:
                        for index, line in enumerate(summary_pending):
                            ax.text(0, top - index * 0.035, line, fontsize=9, transform=ax.transAxes)
                        summary_pending.clear()
                fig.text(0.035, 0.055, "Значения взяты из редактируемой ведомости DXF. Подтверждение типа не заменяет проверку геометрии.", fontsize=8)
                pdf.savefig(fig)
            finally:
                plt.close(fig)
        for start in range(0, len(summary_pending), 35):
            fig = new_page("Количество по типам в данном комплекте")
            try:
                for index, line in enumerate(summary_pending[start:start + 35]):
                    fig.text(0.04, 0.88 - index * 0.021, line, fontsize=10)
                pdf.savefig(fig)
            finally:
                plt.close(fig)


def export_structural_plan_pdf(
    elements: list[dict[str, Any]],
    out_path: str | Path,
    drawing_type: str,
    project_name: str = "",
    *,
    column_types: list[dict[str, Any]] | None = None,
    scale: int = 100,
    issue_mode: str = "draft",
) -> Path:
    """Render the editable structural-plan DXF as a vector A3 PDF sheet."""
    import ezdxf
    from .dxf import export_structural_plan_dxf

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Do not inherit the (possibly very long) PDF stem: Windows may reject the
    # temporary sibling path even when the requested PDF path itself is valid.
    dxf_path = out_path.with_name(f".s2b_{uuid.uuid4().hex[:12]}.dxf")
    try:
        export_structural_plan_dxf(elements, dxf_path, drawing_type, project_name,
            column_types=column_types, annotation_scale=scale, issue_mode=issue_mode)
        doc = ezdxf.readfile(dxf_path)
    finally:
        dxf_path.unlink(missing_ok=True)

    _export_paginated_plan(doc, out_path, drawing_type, project_name, scale, issue_mode)
    return out_path


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
