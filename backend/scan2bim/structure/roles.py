"""Shared semantic compatibility rules for independently reviewed object roles."""
from __future__ import annotations


ROLE_CLASSES: dict[str, frozenset[str]] = {
    "column": frozenset({"column"}),
    "crane_column": frozenset({"column"}),
    "beam": frozenset({"beam", "girder"}),
    "crane_girder": frozenset({"beam", "girder"}),
    "roof_beam": frozenset({"beam", "girder", "roof"}),
    "rail": frozenset({"beam", "girder"}),
    "floor_beam": frozenset({"beam", "girder", "slab"}),
    "purlin": frozenset({"beam", "girder", "roof"}),
    "truss_member": frozenset({"truss"}),
    "truss_top_chord": frozenset({"truss"}),
    "truss_bottom_chord": frozenset({"truss"}),
    "truss_post": frozenset({"truss"}),
    "truss_web": frozenset({"truss"}),
    "brace": frozenset({"brace", "truss"}),
    "pipe": frozenset({"pipe"}),
    "duct": frozenset({"duct"}),
    "cable_tray": frozenset({"duct"}),
    "other": frozenset({"wall", "column", "beam", "girder", "slab", "roof", "truss",
                         "brace", "stair", "opening", "pipe", "duct", "equipment", "other"}),
    "unknown": frozenset({"wall", "column", "beam", "girder", "slab", "roof", "truss",
                           "brace", "stair", "opening", "pipe", "duct", "equipment", "other"}),
}


def role_matches_class(class_name: str, role_label: str | None) -> bool:
    """Return whether the independently assigned role can describe the class."""
    return role_label is None or class_name in ROLE_CLASSES.get(role_label, frozenset())
