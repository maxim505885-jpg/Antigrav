"""Editable DXF export for a measured section.

Output is real CAD geometry (LWPOLYLINE / LINE / TEXT / DIMENSION) on named
layers, not a raster image of the point cloud. Coordinates are written in world
coordinates using the section frame offset.
"""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf.enums import TextEntityAlignment

LAYERS = {
    "S2B-CONTOURS": (7, 35),
    "S2B-HOLES": (8, 18),
    "S2B-AXES": (1, 13),
    "S2B-DIMS": (3, 13),
    "S2B-TEXT": (7, 18),
    "S2B-LEVELS": (4, 13),
    "S2B-FRAME": (8, 9),
}


def _setup_document() -> ezdxf.document.Drawing:
    doc = ezdxf.new("R2018", setup=True)
    doc.header["$INSUNITS"] = 6  # metres
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LUNITS"] = 2
    doc.header["$LUPREC"] = 3
    for name, (color, lineweight) in LAYERS.items():
        if name not in doc.layers:
            doc.layers.add(name, color=color, lineweight=lineweight)
    if "S2B-HOLES" in doc.layers:
        doc.layers.get("S2B-HOLES").dxf.linetype = "DASHED"
    dimstyle = doc.dimstyles.get("EZDXF")
    if dimstyle is not None:
        dimstyle.dxf.dimtxt = 0.30
        dimstyle.dxf.dimasz = 0.15
        dimstyle.dxf.dimexe = 0.10
        dimstyle.dxf.dimexo = 0.08
        dimstyle.dxf.dimgap = 0.06
        dimstyle.dxf.dimdec = 3
        dimstyle.dxf.dimlunit = 2
        dimstyle.dxf.dimscale = 1.0
        dimstyle.dxf.dimtad = 1
        dimstyle.dxf.dimtih = 0
        dimstyle.dxf.dimtoh = 0
    return doc


def _bounds(polygons: list[dict[str, Any]], offset: tuple[float, float]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for poly in polygons:
        if poly.get("is_hole"):
            continue
        for x, y in poly.get("points", []):
            xs.append(x + offset[0])
            ys.append(y + offset[1])
    if not xs:
        return 0.0, 0.0, 1.0, 1.0
    return min(xs), min(ys), max(xs), max(ys)


def _elevation_label(value: float) -> str:
    if abs(value) < 0.0005:
        return "±0.000"
    return f"{value:+.3f}"


def export_section_dxf(
    section: dict[str, Any],
    out_path: str | Path,
    cloud_name: str = "",
    project_name: str = "",
    scale: int = 50,
    draw_scan_points: bool = False,
    max_scan_points: int = 20000,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = _setup_document()
    msp = doc.modelspace()
    frame = section["frame"]
    offset = tuple(frame["world_offset"])
    polygons = section.get("polygons", [])
    minx, miny, maxx, maxy = _bounds(polygons, offset)
    width = max(1e-6, maxx - minx)
    height = max(1e-6, maxy - miny)

    doc.header["$PROJECTNAME"] = project_name or "Intelligent Scan-to-BIM"
    doc.header["$USERI1"] = int(scale)

    # Measured contours.
    for poly in polygons:
        layer = "S2B-HOLES" if poly.get("is_hole") else "S2B-CONTOURS"
        points = [(x + offset[0], y + offset[1]) for x, y in poly.get("points", [])]
        if len(points) < 3:
            continue
        msp.add_lwpolyline(
            points,
            close=True,
            dxfattribs={"layer": layer},
        )

    if draw_scan_points:
        preview = section.get("preview_points", [])[:max_scan_points]
        if preview:
            msp.add_point(
                [(x + offset[0], y + offset[1], 0.0) for x, y in preview],
                dxfattribs={"layer": "S2B-FRAME"},
            )

    # Axes: two horizontal and two vertical construction lines outside the model.
    ext = max(width, height) * 0.08 + 0.5
    if frame["kind"] == "horizontal":
        for x in (minx, maxx):
            msp.add_line(
                (x, miny - ext, 0),
                (x, maxy + ext, 0),
                dxfattribs={"layer": "S2B-AXES", "linetype": "CENTER"},
            )
        for y in (miny, maxy):
            msp.add_line(
                (minx - ext, y, 0),
                (maxx + ext, y, 0),
                dxfattribs={"layer": "S2B-AXES", "linetype": "CENTER"},
            )
        msp.add_circle(
            (minx - ext * 0.8, maxy + ext * 0.8),
            radius=max(0.15, ext * 0.08),
            dxfattribs={"layer": "S2B-AXES"},
        )
        msp.add_text(
            "1",
            height=0.25,
            dxfattribs={"layer": "S2B-TEXT"},
        ).set_placement((minx, miny - ext * 1.4), align=TextEntityAlignment.CENTER)
    else:
        for v in (miny, maxy):
            msp.add_line(
                (minx - ext, v, 0),
                (maxx + ext, v, 0),
                dxfattribs={"layer": "S2B-AXES", "linetype": "CENTER"},
            )
        msp.add_text(
            _elevation_label(frame["position_world"]),
            height=0.25,
            dxfattribs={"layer": "S2B-LEVELS"},
        ).set_placement((minx - ext * 1.6, maxy), align=TextEntityAlignment.MIDDLE_RIGHT)
        msp.add_line(
            (minx - ext * 1.2, miny, 0),
            (minx - ext * 1.2, maxy, 0),
            dxfattribs={"layer": "S2B-LEVELS"},
        )

    # Overall dimensions (editable DIMENSION entities).
    dim_offset = max(0.5, ext)
    try:
        msp.add_linear_dim(
            base=(minx, miny - dim_offset, 0),
            p1=(minx, miny, 0),
            p2=(maxx, miny, 0),
            angle=0,
            dimstyle="EZDXF",
            dxfattribs={"layer": "S2B-DIMS"},
        ).render()
        msp.add_linear_dim(
            base=(maxx + dim_offset, miny, 0),
            p1=(maxx, miny, 0),
            p2=(maxx, maxy, 0),
            angle=90,
            dimstyle="EZDXF",
            dxfattribs={"layer": "S2B-DIMS"},
        ).render()
    except Exception:
        # Dimension rendering must never break a drawing export.
        pass

    # Labels.
    msp.add_text(
        f"{'PLAN' if frame['kind'] == 'horizontal' else 'SECTION'} {frame['position_world']:.3f} m",
        height=0.35,
        dxfattribs={"layer": "S2B-TEXT"},
    ).set_placement((minx, maxy + ext * 0.5), align=TextEntityAlignment.LEFT)
    msp.add_text(
        f"Measured point-cloud section | thickness {frame['thickness']:.3f} m | scale 1:{scale}",
        height=0.18,
        dxfattribs={"layer": "S2B-TEXT"},
    ).set_placement((minx, miny - ext * 2.1), align=TextEntityAlignment.LEFT)

    # A3 sheet with a viewport; the model space stays fully editable.
    layout_name = f"S2B-{scale}"
    try:
        layout = doc.layouts.get(layout_name)
    except KeyError:
        layout = doc.layouts.new(layout_name)
    try:
        layout.page_setup(size=(420, 297), margins=(10, 10, 10, 10), units="mm")
    except Exception:
        layout.dxf.paper_width = 420
        layout.dxf.paper_height = 297
    try:
        layout.add_viewport(
            center=(210, 148),
            size=(380, 240),
            view_center_point=((minx + maxx) / 2, (miny + maxy) / 2),
            view_height=280 / scale,
        )
    except Exception:
        pass
    layout.add_text(
        f"{project_name or 'Intelligent Scan-to-BIM'} — {cloud_name or 'cloud'}",
        dxfattribs={"height": 5, "layer": "S2B-TEXT"},
    ).set_placement((20, 280))
    layout.add_text(
        f"Section at {frame['position_world']:.3f} m   scale 1:{scale}   {date.today().isoformat()}",
        dxfattribs={"height": 3, "layer": "S2B-TEXT"},
    ).set_placement((20, 270))
    layout.add_text(
        "Measured geometry. Orthogonal regularisation applied where reported. "
        "No material or structural function is inferred.",
        dxfattribs={"height": 2.2, "layer": "S2B-TEXT"},
    ).set_placement((20, 18))

    doc.saveas(out_path)
    return out_path


def export_elements_dxf(elements: list[dict[str, Any]], out_path: str | Path, project_name: str = "") -> Path:
    """Export recognised construction elements as editable 3D/2D CAD outlines."""
    out_path = Path(out_path)
    doc = _setup_document()
    msp = doc.modelspace()
    layer_map = {
        "wall": "S2B-WALLS",
        "column": "S2B-COLUMNS",
        "beam": "S2B-BEAMS",
        "slab": "S2B-SLABS",
    }
    for name, color in (("S2B-WALLS", 7), ("S2B-COLUMNS", 2), ("S2B-BEAMS", 5), ("S2B-SLABS", 4)):
        if name not in doc.layers:
            doc.layers.add(name, color=color)
    for el in elements:
        layer = layer_map.get(el.get("class_name", ""), "S2B-CONTOURS")
        geom = el.get("geometry", {})
        if geom.get("kind") == "slab" and geom.get("polygon"):
            msp.add_lwpolyline(
                [(float(x), float(y)) for x, y in geom["polygon"]],
                close=True,
                dxfattribs={"layer": layer, "elevation": float(geom.get("z", 0.0))},
            )
        elif geom.get("kind") == "oriented_box":
            cx, cy, cz = geom["center"]
            length = float(geom["sizes"]["length"])
            thickness = float(geom["sizes"]["thickness"])
            height = float(geom["sizes"]["height"])
            angle = float(geom.get("rotation_z", 0.0))
            ca, sa = math.cos(angle), math.sin(angle)
            pts = []
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                lx, ly = sx * length / 2, sy * thickness / 2
                pts.append((cx + lx * ca - ly * sa, cy + lx * sa + ly * ca, cz))
            msp.add_polyline3d(pts + [pts[0]], dxfattribs={"layer": layer})
            msp.add_polyline3d(
                [(x, y, z + height) for x, y, z in pts] + [(pts[0][0], pts[0][1], cz + height)],
                dxfattribs={"layer": layer},
            )
            for p in pts:
                msp.add_line(p, (p[0], p[1], p[2] + height), dxfattribs={"layer": layer})
    msp.add_text(project_name or "Intelligent Scan-to-BIM elements", height=0.4).set_placement((0, 0))
    doc.saveas(out_path)
    return out_path
