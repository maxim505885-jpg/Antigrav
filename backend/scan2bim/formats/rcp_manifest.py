"""Read the lightweight XML manifest stored inside Autodesk ReCap RCP files.

This module does not decode point data or modify the project. RCP is a ZIP
container whose scan nodes refer to separate RCS files; those linked RCS files
remain the responsibility of the licensed local ReCap reader.
"""
from __future__ import annotations

import math
import os
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path, PureWindowsPath
from typing import Any


MAX_RCP_XML_BYTES = 32 * 1024 * 1024
ASSET_BOUNDS_CONSISTENCY_EPSILON = 0.001


class RcpManifestError(ValueError):
    """The RCP manifest cannot be safely or unambiguously interpreted."""


def compare_axis_aligned_asset_bounds(
    actual_min: list[float],
    actual_max: list[float],
    asset_bounds: dict[str, Any],
    unit_type_raw: str | None = None,
) -> dict[str, Any]:
    """Compare full RCS extents to an axis-aligned RCP asset box.

    The small epsilon detects metadata/coordinate consistency only. It is not
    a survey or engineering tolerance and this function never applies a
    transform to point coordinates.
    """
    expected_min = asset_bounds.get("min")
    expected_max = asset_bounds.get("max")
    if not asset_bounds.get("axis_aligned_interpretation_supported"):
        raise RcpManifestError("RCP asset bounds are not axis-aligned")
    if not isinstance(expected_min, list) or not isinstance(expected_max, list):
        raise RcpManifestError("RCP asset bounds are missing min/max coordinates")
    if len(actual_min) != 3 or len(actual_max) != 3 or len(expected_min) != 3 or len(expected_max) != 3:
        raise RcpManifestError("RCP asset bounds comparison requires three coordinates per extent")
    try:
        actual_min_values = [float(value) for value in actual_min]
        actual_max_values = [float(value) for value in actual_max]
        expected_min_values = [float(value) for value in expected_min]
        expected_max_values = [float(value) for value in expected_max]
    except (TypeError, ValueError) as exc:
        raise RcpManifestError("RCP asset bounds comparison contains invalid coordinates") from exc
    values = (*actual_min_values, *actual_max_values, *expected_min_values, *expected_max_values)
    if not all(math.isfinite(value) for value in values):
        raise RcpManifestError("RCP asset bounds comparison contains non-finite coordinates")
    min_delta = [abs(actual_min_values[i] - expected_min_values[i]) for i in range(3)]
    max_delta = [abs(actual_max_values[i] - expected_max_values[i]) for i in range(3)]
    max_abs_delta = max((*min_delta, *max_delta))
    bounds_match = max_abs_delta <= ASSET_BOUNDS_CONSISTENCY_EPSILON
    return {
        "status": "rcs_bounds_match_rcp_asset_bounds" if bounds_match else "rcs_bounds_differ_from_rcp_asset_bounds",
        "method": "axis-aligned RCP AssetBoundingBox min/size compared with full ingested RCS extents",
        "rcp_asset_min": expected_min_values,
        "rcp_asset_max": expected_max_values,
        "rcs_min": actual_min_values,
        "rcs_max": actual_max_values,
        "absolute_min_delta": min_delta,
        "absolute_max_delta": max_delta,
        "max_absolute_delta_in_coordinate_units": max_abs_delta,
        "consistency_epsilon_in_coordinate_units": ASSET_BOUNDS_CONSISTENCY_EPSILON,
        "unit_type_raw": unit_type_raw,
        "epsilon_is_engineering_tolerance": False,
        "translation_reapplication": "do_not_apply_for_this_node" if bounds_match else "unresolved; do not auto-apply",
    }


def _value(parent: ET.Element, tag: str, default: str = "") -> str:
    node = parent.find(tag)
    return str(node.get("Value", default)) if node is not None else default


def _number(parent: ET.Element, tag: str, attr: str, default: float = 0.0) -> float:
    node = parent.find(tag)
    raw = node.get(attr) if node is not None else None
    if raw is None:
        return default
    try:
        result = float(raw)
    except ValueError as exc:
        raise RcpManifestError(f"RCP contains invalid {tag}.{attr}") from exc
    if not math.isfinite(result):
        raise RcpManifestError(f"RCP contains non-finite {tag}.{attr}")
    return result


def _index_support_scans(support_root: Path) -> dict[str, list[Path]]:
    """Index RCS filenames once instead of recursively walking Support per node."""
    index: dict[str, list[Path]] = {}
    if not support_root.is_dir():
        return index
    for directory, _subdirs, filenames in os.walk(support_root):
        for filename in filenames:
            if filename.lower().endswith(".rcs"):
                index.setdefault(filename.casefold(), []).append(Path(directory) / filename)
    return index


def _resolve_scan_path(
    rcp_path: Path,
    stored_path: str,
    relative_path: str,
    support_index: dict[str, list[Path]] | None = None,
) -> Path | None:
    candidates: list[Path] = []
    for raw in (stored_path, relative_path):
        if not raw.strip():
            continue
        # RCP files can be moved between platforms; accept both path syntaxes.
        native = Path(raw)
        windows = PureWindowsPath(raw)
        if native.is_absolute():
            candidates.append(native)
        elif windows.is_absolute():
            candidates.append(Path(windows.as_posix()))
        else:
            candidates.append(rcp_path.parent / Path(raw.replace("\\", "/")))

    for candidate in candidates:
        if candidate.is_file() and candidate.suffix.lower() == ".rcs":
            return candidate.resolve()

    # A moved RCP may retain an unusable absolute path. Resolve only by the
    # exact RCS basename inside conventional sibling support folders. If the
    # old absolute path names that conventional support folder, prefer its
    # matching copy over unrelated same-basename files beside the RCP.
    basenames = {PureWindowsPath(value).name for value in (stored_path, relative_path) if value}
    old_parent_names = {
        PureWindowsPath(value).parent.name.casefold()
        for value in (stored_path, relative_path)
        if value and PureWindowsPath(value).parent.name
    }
    named_support_root = rcp_path.parent / f"{rcp_path.stem} Support"
    if named_support_root.name.casefold() in old_parent_names and named_support_root.is_dir():
        for basename in basenames:
            if support_index is not None:
                support_matches = {
                    candidate.resolve()
                    for candidate in support_index.get(basename.casefold(), [])
                }
            else:
                support_matches = {
                    candidate.resolve()
                    for candidate in named_support_root.rglob(basename)
                    if candidate.is_file() and candidate.suffix.lower() == ".rcs"
                }
            if len(support_matches) == 1:
                return next(iter(support_matches))
            if len(support_matches) > 1:
                raise RcpManifestError(
                    f"linked scan '{basename}' resolves to multiple files in "
                    f"'{named_support_root.name}'"
                )

    for basename in basenames:
        roots = [named_support_root, rcp_path.parent]
        matches: set[Path] = set()
        for root in roots:
            if not root.exists():
                continue
            if root.is_file() and root.name.casefold() == basename.casefold():
                matches.add(root.resolve())
            elif root.is_dir():
                # Do not recursively search the user's entire workspace.
                for candidate in root.glob(basename):
                    if candidate.is_file() and candidate.suffix.lower() == ".rcs":
                        matches.add(candidate.resolve())
                if root.name.casefold().endswith(" support"):
                    if support_index is not None and root == named_support_root:
                        matches.update(
                            candidate.resolve()
                            for candidate in support_index.get(basename.casefold(), [])
                        )
                    else:
                        for candidate in root.rglob(basename):
                            if candidate.is_file() and candidate.suffix.lower() == ".rcs":
                                matches.add(candidate.resolve())
        if len(matches) == 1:
            return next(iter(matches))
        if len(matches) > 1:
            raise RcpManifestError(f"linked scan '{basename}' resolves to multiple RCS files")
    return None


def read_rcp_manifest(path: str | Path) -> dict[str, Any]:
    """Read RCP project and scan-node metadata without extracting the ZIP."""
    rcp_path = Path(path).expanduser().resolve()
    if not rcp_path.is_file() or rcp_path.suffix.lower() != ".rcp":
        raise RcpManifestError(f"not an RCP file: {rcp_path}")
    try:
        with zipfile.ZipFile(rcp_path) as archive:
            xml_members = [
                info for info in archive.infolist()
                if not info.is_dir() and info.filename.lower().endswith(".xml")
            ]
            if len(xml_members) != 1:
                raise RcpManifestError("RCP must contain exactly one XML project manifest")
            info = xml_members[0]
            if info.file_size > MAX_RCP_XML_BYTES:
                raise RcpManifestError("RCP XML manifest exceeds the 32 MiB safety limit")
            xml_bytes = archive.read(info)
            if len(xml_bytes) > MAX_RCP_XML_BYTES:
                raise RcpManifestError("RCP XML manifest exceeds the 32 MiB safety limit")
            if b"<!DOCTYPE" in xml_bytes.upper() or b"<!ENTITY" in xml_bytes.upper():
                raise RcpManifestError("RCP XML DTD/entity declarations are not accepted")
            root = ET.fromstring(xml_bytes)
            # Some ReCap projects declare UTF-8 while retaining legacy
            # Windows-1251 bytes in the linked absolute path. ElementTree
            # replaces those bytes when reading the byte stream, so retry only
            # when that corruption marker is actually present.
            path_values = [element.get("Value", "") for element in root.findall(".//Path")]
            if any("\ufffd" in value for value in path_values):
                root = ET.fromstring(xml_bytes.decode("cp1251"))
    except (OSError, zipfile.BadZipFile, ET.ParseError, UnicodeDecodeError) as exc:
        raise RcpManifestError(f"cannot read RCP project manifest: {exc}") from exc

    project = root.find("ProjectId")
    nodes_parent = root.find("Nodes")
    unit_node = root.find("UnitType")
    asset_infos = {
        item.get("AssetName", ""): item
        for item in root.findall("./AssetCollection/AssetInfo")
    }
    if nodes_parent is None:
        raise RcpManifestError("RCP has no Nodes section")
    nodes: list[dict[str, Any]] = []
    support_index = _index_support_scans(rcp_path.parent / f"{rcp_path.stem} Support")
    for node in list(nodes_parent):
        stored_path = _value(node, "Path")
        relative_path = _value(node, "RelativePath")
        translation = node.find("Translation")
        rotation = node.find("Rotation")
        scale = node.find("Scale")
        node_name = _value(node, "NodeName", node.get("Id", "scan"))
        asset_bounds: dict[str, Any] | None = None
        asset_info = asset_infos.get(node_name)
        asset_box = asset_info.find("AssetBoundingBox") if asset_info is not None else None
        if asset_box is not None:
            tform = asset_box.find("tform")
            tform_translation = tform.find("T") if tform is not None else None
            size_attrs = ("sizeX", "sizeY", "sizeZ")
            if tform_translation is not None and all(asset_box.get(k) is not None for k in size_attrs):
                translation_values = [
                    _number(tform, "T", axis) for axis in ("x", "y", "z")
                ]
                try:
                    size_values = [float(asset_box.get(k)) for k in size_attrs]
                except (TypeError, ValueError) as exc:
                    raise RcpManifestError(f"RCP asset bounds for node '{node_name}' are invalid") from exc
                if not all(math.isfinite(value) and value >= 0 for value in size_values):
                    raise RcpManifestError(f"RCP asset bounds for node '{node_name}' are invalid")
                # Preserve the raw transform and size. The derived axis-aligned
                # bounds are useful only when the node itself is unrotated and
                # the asset transform contains translation alone.
                node_rotation = [
                    _number(node, "Rotation", axis) for axis in ("x", "y", "z")
                ]
                asset_transform_children = [child.tag for child in list(tform)]
                axis_aligned = (
                    all(abs(value) <= 1e-12 for value in node_rotation)
                    and asset_transform_children == ["T"]
                )
                asset_bounds = {
                    "tform_translation": translation_values,
                    "size": size_values,
                    "axis_aligned_interpretation_supported": axis_aligned,
                    "min": translation_values if axis_aligned else None,
                    "max": [translation_values[i] + size_values[i] for i in range(3)] if axis_aligned else None,
                }
        try:
            declared_point_count = int(_value(node, "NumPoints", "0") or 0)
        except ValueError as exc:
            raise RcpManifestError(f"RCP scan node '{node_name}' has invalid NumPoints") from exc
        if declared_point_count < 0:
            raise RcpManifestError("RCP NumPoints cannot be negative")
        nodes.append({
            "node_id": node.get("Id"),
            "name": node_name,
            "stored_path": stored_path,
            "relative_path": relative_path,
            "resolved_rcs_path": str(
                _resolve_scan_path(rcp_path, stored_path, relative_path, support_index) or ""
            ),
            "declared_point_count": declared_point_count,
            "has_rgb": _value(node, "HasRGB", "0") == "1",
            "has_intensity": _value(node, "HasIntensity", "0") == "1",
            "has_normals": _value(node, "HasNormals", "0") == "1",
            "registered": _value(node, "Registered", "0") == "1",
            "translation": [
                _number(node, "Translation", "x"),
                _number(node, "Translation", "y"),
                _number(node, "Translation", "z"),
            ],
            "rotation": [
                _number(node, "Rotation", "x"),
                _number(node, "Rotation", "y"),
                _number(node, "Rotation", "z"),
            ],
            "scale": [
                _number(node, "Scale", "x", 1.0),
                _number(node, "Scale", "y", 1.0),
                _number(node, "Scale", "z", 1.0),
            ],
            "asset_bounds": asset_bounds,
        })
    if not nodes:
        raise RcpManifestError("RCP contains no scan nodes")
    return {
        "project_id": project.get("UUID") if project is not None else None,
        "project_file": str(rcp_path),
        "manifest_member": info.filename,
        "unit_type_raw": unit_node.get("Value") if unit_node is not None else None,
        "node_count": len(nodes),
        "nodes": nodes,
    }
