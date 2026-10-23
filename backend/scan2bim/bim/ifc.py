"""IFC4 export using IfcOpenShell.

Native IFC entities and SweptSolid representations are created. Each element
carries a Pset_ScanToBIM property set with confidence, measured/inferred flags
and review status, so the engineering provenance survives into Revit and other
BIM tools.
"""
from __future__ import annotations

import math
import json
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.guid

from .model import validate_bim_model


def _guid() -> str:
    return ifcopenshell.guid.new()


def _point(ifc, coords) -> Any:
    return ifc.create_entity("IfcCartesianPoint", Coordinates=[float(c) for c in coords])


def _axis_placement(ifc, location, ref_direction=None) -> Any:
    kwargs: dict[str, Any] = {"Location": _point(ifc, location)}
    if ref_direction is not None:
        kwargs["Axis"] = ifc.create_entity("IfcDirection", DirectionRatios=[0.0, 0.0, 1.0])
        kwargs["RefDirection"] = ifc.create_entity(
            "IfcDirection", DirectionRatios=[float(ref_direction[0]), float(ref_direction[1]), 0.0]
        )
    return ifc.create_entity("IfcAxis2Placement3D", **kwargs)


def _identity_placement(ifc) -> Any:
    return ifc.create_entity(
        "IfcLocalPlacement",
        RelativePlacement=_axis_placement(ifc, (0.0, 0.0, 0.0)),
    )


def _representation(ifc, context, solid) -> Any:
    shape = ifc.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=context,
        RepresentationIdentifier="Body",
        RepresentationType="SweptSolid",
        Items=[solid],
    )
    return ifc.create_entity("IfcProductDefinitionShape", Representations=[shape])


def _box_solid(ifc, center, length, thickness, height, rotation_z) -> Any:
    profile = ifc.create_entity(
        "IfcRectangleProfileDef",
        ProfileType="AREA",
        XDim=float(max(0.01, length)),
        YDim=float(max(0.01, thickness)),
        Position=ifc.create_entity(
            "IfcAxis2Placement2D", Location=_point(ifc, (0.0, 0.0))
        ),
    )
    position = _axis_placement(
        ifc,
        (float(center[0]), float(center[1]), float(center[2]) - float(height) / 2.0),
        ref_direction=(math.cos(rotation_z), math.sin(rotation_z)),
    )
    return ifc.create_entity(
        "IfcExtrudedAreaSolid",
        SweptArea=profile,
        Position=position,
        ExtrudedDirection=ifc.create_entity("IfcDirection", DirectionRatios=[0.0, 0.0, 1.0]),
        Depth=float(max(0.01, height)),
    )


def _member_solid(ifc, p0, p1, section) -> Any:
    """Rectangular section swept along the p0->p1 direction (brace/link)."""
    import numpy as _np

    start = _np.array([float(v) for v in p0], dtype=float)
    end = _np.array([float(v) for v in p1], dtype=float)
    direction = end - start
    length = float(_np.linalg.norm(direction))
    if length < 1e-6:
        direction = _np.array([0.0, 0.0, 1.0])
        length = max(0.01, float(section))
    else:
        direction = direction / length
    # Build an orthonormal frame with Z = member axis.
    z_axis = direction
    helper = _np.array([1.0, 0.0, 0.0])
    if abs(float(_np.dot(z_axis, helper))) > 0.9:
        helper = _np.array([0.0, 1.0, 0.0])
    x_axis = _np.cross(helper, z_axis)
    x_axis = x_axis / float(_np.linalg.norm(x_axis))
    y_axis = _np.cross(z_axis, x_axis)
    profile = ifc.create_entity(
        "IfcRectangleProfileDef",
        ProfileType="AREA",
        XDim=float(max(0.01, section)),
        YDim=float(max(0.01, section)),
        Position=ifc.create_entity(
            "IfcAxis2Placement2D", Location=_point(ifc, (0.0, 0.0))
        ),
    )
    position = ifc.create_entity(
        "IfcAxis2Placement3D",
        Location=_point(ifc, start),
        Axis=ifc.create_entity("IfcDirection", DirectionRatios=[float(v) for v in z_axis]),
        RefDirection=ifc.create_entity(
            "IfcDirection", DirectionRatios=[float(v) for v in x_axis]
        ),
    )
    del y_axis
    return ifc.create_entity(
        "IfcExtrudedAreaSolid",
        SweptArea=profile,
        Position=position,
        ExtrudedDirection=ifc.create_entity("IfcDirection", DirectionRatios=[0.0, 0.0, 1.0]),
        Depth=float(max(0.01, length)),
    )


def _slab_solid(ifc, polygon, z, thickness) -> Any:
    pts = [_point(ifc, (float(x), float(y), 0.0)) for x, y in polygon]
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    polyline = ifc.create_entity("IfcPolyline", Points=pts)
    profile = ifc.create_entity(
        "IfcArbitraryClosedProfileDef", ProfileType="AREA", OuterCurve=polyline
    )
    return ifc.create_entity(
        "IfcExtrudedAreaSolid",
        SweptArea=profile,
        Position=_axis_placement(ifc, (0.0, 0.0, float(z) - float(thickness) / 2.0)),
        ExtrudedDirection=ifc.create_entity("IfcDirection", DirectionRatios=[0.0, 0.0, 1.0]),
        Depth=float(max(0.02, thickness)),
    )


def _property_set(ifc, product, element: dict[str, Any]) -> None:
    props = [
        ("ElementId", "IfcText", str(element["id"])),
        ("ClassName", "IfcText", str(element["class_name"])),
        ("Role", "IfcText", str((element.get("dimensions") or {}).get("role", ""))),
        ("Confidence", "IfcReal", float(element.get("confidence", 0.0))),
        ("ConfidenceKind", "IfcText", str(element.get("confidence_kind", "heuristic"))),
        ("Measured", "IfcBoolean", bool(element.get("measured", True))),
        ("Inferred", "IfcBoolean", bool(element.get("inferred", False))),
        ("Source", "IfcText", str(element.get("source", "geometric"))),
        ("ReviewStatus", "IfcText", str(element.get("review_status", "unreviewed"))),
        ("GeometryStatus", "IfcText", str(element.get("ifc_geometry_status", "supported"))),
        ("GeometryJSON", "IfcText", json.dumps(element.get("geometry", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
        ("DimensionsJSON", "IfcText", json.dumps(element.get("dimensions", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
        ("MetadataJSON", "IfcText", json.dumps(element.get("metadata", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))),
    ]
    ifc_props = []
    for name, kind, value in props:
        nominal = ifc.create_entity(
            kind,
            **({"wrappedValue": value} if kind == "IfcReal" else {"wrappedValue": value}),
        )
        ifc_props.append(
            ifc.create_entity(
                "IfcPropertySingleValue", Name=name, NominalValue=nominal
            )
        )
    pset = ifc.create_entity(
        "IfcPropertySet",
        GlobalId=_guid(),
        Name="Pset_ScanToBIM",
        HasProperties=ifc_props,
    )
    ifc.create_entity(
        "IfcRelDefinesByProperties",
        GlobalId=_guid(),
        RelatedObjects=[product],
        RelatingPropertyDefinition=pset,
    )


def export_ifc(
    model: dict[str, Any],
    out_path: str | Path,
    project_name: str = "",
    author: str = "Intelligent Scan-to-BIM",
) -> Path:
    if "schema" in model:
        validate_bim_model(model)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ifc = ifcopenshell.file(schema="IFC4")

    context = ifc.create_entity(
        "IfcGeometricRepresentationContext",
        ContextType="Model",
        CoordinateSpaceDimension=3,
        Precision=1e-5,
        WorldCoordinateSystem=_axis_placement(ifc, (0.0, 0.0, 0.0)),
    )
    units = ifc.create_entity(
        "IfcUnitAssignment",
        Units=[
            ifc.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE"),
            ifc.create_entity("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE"),
            ifc.create_entity("IfcSIUnit", UnitType="VOLUMEUNIT", Name="CUBIC_METRE"),
            ifc.create_entity("IfcSIUnit", UnitType="PLANEANGLEUNIT", Name="RADIAN"),
        ],
    )
    project = ifc.create_entity(
        "IfcProject",
        GlobalId=_guid(),
        Name=project_name or model.get("project", {}).get("name") or "Scan-to-BIM project",
        RepresentationContexts=[context],
        UnitsInContext=units,
    )
    site = ifc.create_entity(
        "IfcSite", GlobalId=_guid(), Name="Site", CompositionType="ELEMENT"
    )
    building = ifc.create_entity(
        "IfcBuilding", GlobalId=_guid(), Name="Building", CompositionType="ELEMENT"
    )
    ifc.create_entity(
        "IfcRelAggregates",
        GlobalId=_guid(),
        RelatingObject=project,
        RelatedObjects=[site],
    )
    ifc.create_entity(
        "IfcRelAggregates",
        GlobalId=_guid(),
        RelatingObject=site,
        RelatedObjects=[building],
    )

    level_elevations = [
        float(lvl.get("elevation", lvl.get("z", 0.0))) for lvl in model.get("levels", [])
    ]
    if not level_elevations:
        zs = []
        for element in model.get("elements", []):
            try:
                zs.append(float(element["bbox"]["min"][2]))
            except Exception:
                pass
        level_elevations = [min(zs) if zs else 0.0]
    storeys = []
    for i, z in enumerate(level_elevations):
        storeys.append(
            ifc.create_entity(
                "IfcBuildingStorey",
                GlobalId=_guid(),
                Name=f"Level {i + 1} ({z:.2f} m)",
                Elevation=float(z),
                CompositionType="ELEMENT",
            )
        )
    ifc.create_entity(
        "IfcRelAggregates",
        GlobalId=_guid(),
        RelatingObject=building,
        RelatedObjects=storeys,
    )
    contained: dict[int, list[Any]] = {i: [] for i in range(len(storeys))}

    def storey_index(z: float) -> int:
        idx = 0
        for i, elevation in enumerate(level_elevations):
            if z >= elevation - 0.25:
                idx = i
        return idx

    for element in model.get("elements", []):
        geom = element.get("geometry", {})
        cls = element.get("class_name", "other")
        solid = None
        geometry_status = "supported"
        try:
            if geom.get("kind") == "oriented_box":
                center = geom["center"]
                sizes = geom["sizes"]
                solid = _box_solid(
                    ifc,
                    center,
                    float(sizes["length"]),
                    float(sizes["thickness"]),
                    float(sizes["height"]),
                    float(geom.get("rotation_z", 0.0)),
                )
                z_for_storey = float(center[2]) - float(sizes["height"]) / 2.0
            elif geom.get("kind") == "slab":
                polygon = geom.get("polygon") or []
                if len(polygon) < 3:
                    continue
                z = float(geom.get("z", 0.0))
                solid = _slab_solid(ifc, polygon, z, float(geom.get("assumed_thickness", 0.2)))
                z_for_storey = z
            elif geom.get("kind") == "member":
                p0 = geom.get("p0")
                p1 = geom.get("p1")
                if not p0 or not p1 or len(p0) != 3 or len(p1) != 3:
                    geometry_status = "unsupported_invalid_axis"
                    try:
                        z_for_storey = float(element["bbox"]["min"][2])
                    except (KeyError, TypeError, ValueError):
                        z_for_storey = 0.0
                else:
                    try:
                        section = float(geom.get("section_m"))
                    except (TypeError, ValueError):
                        section = 0.0
                    if not math.isfinite(section) or section <= 0.0:
                        geometry_status = "unsupported_missing_section"
                    else:
                        solid = _member_solid(ifc, p0, p1, section)
                        geometry_status = "square_envelope_approximation"
                    z_for_storey = min(float(p0[2]), float(p1[2]))
            elif geom.get("start_point") and geom.get("end_point") and (geom.get("radius_m") or cls == "pipe"):
                sp = geom["start_point"]
                ep = geom["end_point"]
                rad = float(geom.get("radius_m", 0.05))
                solid = _member_solid(ifc, sp, ep, rad * 2.0)
                geometry_status = "cylinder_envelope_approximation"
                z_for_storey = min(float(sp[2]), float(ep[2]))
            else:
                continue
        except Exception:
            continue

        representation = _representation(ifc, context, solid) if solid is not None else None
        placement = _identity_placement(ifc)

        if cls == "wall":
            product = ifc.create_entity(
                "IfcWall",
                GlobalId=_guid(),
                Name=f"Wall {element['id'][:8]}",
                ObjectPlacement=placement,
                Representation=representation,
                PredefinedType="STANDARD",
            )
        elif cls == "column":
            product = ifc.create_entity(
                "IfcColumn",
                GlobalId=_guid(),
                Name=f"Column {element['id'][:8]}",
                ObjectPlacement=placement,
                Representation=representation,
                PredefinedType="COLUMN",
            )
        elif cls == "slab":
            product = ifc.create_entity(
                "IfcSlab",
                GlobalId=_guid(),
                Name=f"Slab {element['id'][:8]}",
                ObjectPlacement=placement,
                Representation=representation,
                PredefinedType="FLOOR",
            )
        elif cls in ("beam", "girder"):
            product = ifc.create_entity(
                "IfcBeam",
                GlobalId=_guid(),
                Name=f"Beam {element['id'][:8]}",
                ObjectPlacement=placement,
                Representation=representation,
            )
        elif cls == "truss":
            product = ifc.create_entity(
                "IfcBuildingElementProxy",
                GlobalId=_guid(),
                Name=f"Truss {element['id'][:8]}",
                ObjectPlacement=placement,
                Representation=representation,
            )
        elif cls == "brace":
            product = ifc.create_entity(
                "IfcBuildingElementProxy",
                GlobalId=_guid(),
                Name=f"Brace {element['id'][:8]}",
                ObjectPlacement=placement,
                Representation=representation,
            )
        elif cls == "stair":
            # Detected flight; steps and railings are not modelled, so the
            # product is the inclined swept envelope of the measured run.
            if solid is not None:
                geometry_status = "inclined_member_approximation"
            product = ifc.create_entity(
                "IfcStair",
                GlobalId=_guid(),
                Name=f"Stair {element['id'][:8]}",
                ObjectPlacement=placement,
                Representation=representation,
                PredefinedType="STRAIGHT_RUN_STAIR",
            )
        elif cls == "pipe":
            product = ifc.create_entity(
                "IfcPipeSegment",
                GlobalId=_guid(),
                Name=f"Pipe {element['id'][:8]}",
                ObjectPlacement=placement,
                Representation=representation,
                PredefinedType="RIGIDSEGMENT",
            )
        elif cls == "opening":
            # IfcOpeningElement without a RelVoidsElement: the void is
            # exported on its own because no host relationship was verified.
            product = ifc.create_entity(
                "IfcOpeningElement",
                GlobalId=_guid(),
                Name=f"Opening {element['id'][:8]}",
                ObjectPlacement=placement,
                Representation=representation,
                PredefinedType="OPENING",
            )
        else:
            product = ifc.create_entity(
                "IfcBuildingElementProxy",
                GlobalId=_guid(),
                Name=f"{cls.title()} {element['id'][:8]}",
                ObjectPlacement=placement,
                Representation=representation,
            )
        product.Description = (
            f"Scan-to-BIM {cls}; confidence {element.get('confidence', 0):.3f} "
            f"({element.get('confidence_kind', 'heuristic')}); "
            f"measured={bool(element.get('measured', True))}; "
            f"inferred={bool(element.get('inferred', False))}; "
            f"review={element.get('review_status', 'unreviewed')}"
        )
        element_with_geometry_status = {**element, "ifc_geometry_status": geometry_status}
        _property_set(ifc, product, element_with_geometry_status)
        contained[storey_index(z_for_storey)].append(product)

    for i, storey in enumerate(storeys):
        if contained[i]:
            ifc.create_entity(
                "IfcRelContainedInSpatialStructure",
                GlobalId=_guid(),
                RelatingStructure=storey,
                RelatedElements=contained[i],
            )

    ifc.write(str(out_path))
    return out_path
