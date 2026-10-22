"""Review-only structural member proposals with explicit evidence and unknowns."""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal, Sequence, TypedDict


class Axis3(TypedDict):
    start: list[float]
    end: list[float]


class MemberProposal(TypedDict):
    """Unconfirmed, source-linked candidate for one proposed member span.

    Coordinates are metres in the source cloud's world frame. The proposal
    intentionally cannot carry a confirmed review state; the physical member
    identity and span boundary still require explicit review.
    """

    id: str
    role: dict[str, str]
    axis: Axis3
    source_point_ids: list[int]
    source_point_id_space: Literal["positions.npy row index"]
    source_point_ids_sampled: bool
    support_count_in_processing_sample: int
    support_evidence: dict[str, dict[str, Any]]
    observed_profile: dict[str, Any]
    joint_gaps: list[dict[str, Any]]
    unresolved_fields: list[str]
    review_state: Literal["proposed"]


class AssemblyProposal(TypedDict):
    """Review-only grouping of member proposals; connectivity stays explicit."""

    id: str
    assembly_type: dict[str, str]
    member_proposal_ids: list[str]
    node_candidates: list[dict[str, Any]]
    unresolved_fields: list[str]
    review_state: Literal["proposed"]


_PROFILE_KINDS = {
    "catalog_profile", "arbitrary_polygon", "built_up", "circular", "stepped", "unknown"
}


def _point3(value: Any, name: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must be a finite 3D point")
    if any(isinstance(component, bool) for component in value):
        raise ValueError(f"{name} must be a finite 3D point")
    try:
        point = [float(component) for component in value]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite 3D point") from exc
    if not all(math.isfinite(component) for component in point):
        raise ValueError(f"{name} must be a finite 3D point")
    return point


def _source_ids(value: Any, name: str, allowed: set[int] | None = None) -> list[int]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must contain source_point_ids")
    if any(isinstance(row, bool) or not isinstance(row, int) or row < 0 for row in value):
        raise ValueError(f"{name} must contain non-negative integer source_point_ids")
    if len(set(value)) != len(value):
        raise ValueError(f"{name} must contain unique source_point_ids")
    if allowed is not None and not set(value).issubset(allowed):
        raise ValueError(f"{name} refers to source_point_ids outside the proposal evidence")
    return value


def validate_member_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    """Validate a JSON-shaped single-span proposal without changing it.

    This contract checks provenance and evidence states, not physical accuracy.
    A proposal can describe unknown roles, supports, profiles and joints; it
    cannot be marked accepted or confirmed by the recognition pipeline.
    """
    required = {
        "id", "role", "axis", "source_point_ids", "support_evidence",
        "source_point_id_space", "source_point_ids_sampled",
        "support_count_in_processing_sample", "observed_profile", "joint_gaps",
        "unresolved_fields", "review_state",
    }
    if not isinstance(proposal, dict) or set(proposal) != required:
        raise ValueError("member proposal must contain exactly the documented fields")
    if not isinstance(proposal["id"], str) or not proposal["id"].strip():
        raise ValueError("member proposal id must be a non-empty stable identifier")

    role = proposal["role"]
    if (not isinstance(role, dict) or set(role) != {"value", "status"}
            or not isinstance(role["value"], str) or not role["value"].strip()
            or not isinstance(role["status"], str)
            or role["status"] not in {"proposed", "unknown"}):
        raise ValueError("role must have a non-empty value and proposed/unknown status")
    if role["status"] == "unknown" and role["value"] != "unknown":
        raise ValueError("unknown role status must use the unknown value")
    if role["status"] == "proposed" and role["value"] == "unknown":
        raise ValueError("unknown role value must use unknown status")

    axis = proposal["axis"]
    if not isinstance(axis, dict) or set(axis) != {"start", "end"}:
        raise ValueError("axis must contain start and end points")
    start = _point3(axis["start"], "axis.start")
    end = _point3(axis["end"], "axis.end")
    if math.dist(start, end) <= 1e-9:
        raise ValueError("axis must have non-zero length")

    source_ids = _source_ids(proposal["source_point_ids"], "proposal")
    source_set = set(source_ids)
    if proposal["source_point_id_space"] != "positions.npy row index":
        raise ValueError("source_point_id_space must name the derived positions.npy row index")
    if not isinstance(proposal["source_point_ids_sampled"], bool):
        raise ValueError("source_point_ids_sampled must be boolean")
    support_count = proposal["support_count_in_processing_sample"]
    if (isinstance(support_count, bool) or not isinstance(support_count, int)
            or support_count < len(source_ids)):
        raise ValueError("support_count_in_processing_sample must cover the source ID sample")

    supports = proposal["support_evidence"]
    if not isinstance(supports, dict) or set(supports) != {"start", "end"}:
        raise ValueError("support_evidence must describe start and end")
    for endpoint, evidence in supports.items():
        if not isinstance(evidence, dict) or set(evidence) != {"status", "source_point_ids"}:
            raise ValueError(f"support evidence at {endpoint} has an invalid shape")
        status = evidence["status"]
        rows = evidence["source_point_ids"]
        if status == "supported":
            _source_ids(rows, f"support evidence at {endpoint}", source_set)
        elif status == "unknown":
            if rows != []:
                raise ValueError(f"unknown support at {endpoint} cannot claim source points")
        else:
            raise ValueError(f"support evidence at {endpoint} must be supported or unknown")

    profile = proposal["observed_profile"]
    if (not isinstance(profile, dict) or not isinstance(profile.get("kind"), str)
            or profile["kind"] not in _PROFILE_KINDS):
        raise ValueError("observed_profile must declare a supported profile kind or unknown")
    if profile["kind"] == "unknown" and (
        not isinstance(profile.get("reason"), str) or not profile["reason"].strip()
    ):
        raise ValueError("unknown observed_profile requires a reason")

    joint_gaps = proposal["joint_gaps"]
    if not isinstance(joint_gaps, list):
        raise ValueError("joint_gaps must be a list")
    for index, item in enumerate(joint_gaps):
        if not isinstance(item, dict) or set(item) != {"kind", "position_m", "reason", "source_point_ids"}:
            raise ValueError(f"joint_gaps[{index}] has an invalid shape")
        if not isinstance(item["kind"], str) or item["kind"] not in {"joint", "gap"}:
            raise ValueError(f"joint_gaps[{index}].kind must be joint or gap")
        raw_position = item["position_m"]
        if isinstance(raw_position, bool) or not isinstance(raw_position, (int, float)):
            raise ValueError(f"joint_gaps[{index}].position_m must be finite")
        try:
            position = float(raw_position)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"joint_gaps[{index}].position_m must be finite") from exc
        if not math.isfinite(position):
            raise ValueError(f"joint_gaps[{index}].position_m must be finite")
        if position < 0 or position > math.dist(start, end):
            raise ValueError(f"joint_gaps[{index}].position_m must lie within the member axis")
        if not isinstance(item["reason"], str) or not item["reason"].strip():
            raise ValueError(f"joint_gaps[{index}].reason must be explicit")
        _source_ids(item["source_point_ids"], f"joint_gaps[{index}]", source_set)

    unresolved = proposal["unresolved_fields"]
    if (not isinstance(unresolved, list)
            or any(not isinstance(field, str) or not field.strip() for field in unresolved)
            or len(set(unresolved)) != len(unresolved)):
        raise ValueError("unresolved_fields must contain unique non-empty strings")
    if proposal["review_state"] != "proposed":
        raise ValueError("recognition proposals must remain proposed until explicit review")
    return proposal


def build_member_proposal(
    *,
    role: str,
    axis_start_m: Sequence[float],
    axis_end_m: Sequence[float],
    source_point_ids: Sequence[int],
    source_point_ids_sampled: bool,
    support_count_in_processing_sample: int,
    source_point_id_space: str = "positions.npy row index",
    joint_gaps: Sequence[dict[str, Any]] = (),
) -> MemberProposal:
    """Build a review-only member candidate with unsupported fields explicit."""
    start = [round(component, 4) for component in _point3(axis_start_m, "axis_start_m")]
    end = [round(component, 4) for component in _point3(axis_end_m, "axis_end_m")]
    rows = list(source_point_ids)
    canonical_endpoints = sorted((start, end))
    identity_document = json.dumps(
        {"axis_endpoints": canonical_endpoints, "source_point_ids": sorted(rows),
         "source_point_id_space": source_point_id_space},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    proposal_id = "member-proposal-" + hashlib.sha256(identity_document).hexdigest()[:24]
    known_role = isinstance(role, str) and bool(role.strip()) and role.strip() != "unknown"
    proposal: MemberProposal = {
        "id": proposal_id,
        "role": {
            "value": role if known_role else "unknown",
            "status": "proposed" if known_role else "unknown",
        },
        "axis": {"start": start, "end": end},
        "source_point_ids": rows,
        "source_point_id_space": source_point_id_space,  # type: ignore[typeddict-item]
        "source_point_ids_sampled": source_point_ids_sampled,
        "support_count_in_processing_sample": support_count_in_processing_sample,
        "support_evidence": {
            "start": {"status": "unknown", "source_point_ids": []},
            "end": {"status": "unknown", "source_point_ids": []},
        },
        "observed_profile": {
            "kind": "unknown",
            "reason": "full cross-section is not fitted from the horizontal band",
        },
        "joint_gaps": [dict(item) for item in joint_gaps],
        "unresolved_fields": [
            "physical_role_review", "physical_span_boundary", "start_support",
            "end_support", "cross_section", "joint_locations",
        ],
        "review_state": "proposed",
    }
    validate_member_proposal(proposal)
    return proposal


def validate_assembly_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    """Validate a review-only assembly without inferring member connectivity."""
    required = {
        "id", "assembly_type", "member_proposal_ids", "node_candidates",
        "unresolved_fields", "review_state",
    }
    if not isinstance(proposal, dict) or set(proposal) != required:
        raise ValueError("assembly proposal must contain exactly the documented fields")
    if not isinstance(proposal["id"], str) or not proposal["id"].strip():
        raise ValueError("assembly proposal id must be a non-empty stable identifier")
    assembly_type = proposal["assembly_type"]
    if (not isinstance(assembly_type, dict) or set(assembly_type) != {"value", "status"}
            or not isinstance(assembly_type["value"], str) or not assembly_type["value"].strip()
            or not isinstance(assembly_type["status"], str)
            or assembly_type["status"] not in {"proposed", "unknown"}):
        raise ValueError("assembly_type must have a non-empty value and proposed/unknown status")
    if (assembly_type["status"] == "unknown") != (assembly_type["value"] == "unknown"):
        raise ValueError("unknown assembly type value and status must agree")
    member_ids = proposal["member_proposal_ids"]
    if (not isinstance(member_ids, list) or not member_ids
            or any(not isinstance(item, str) or not item.strip() for item in member_ids)
            or len(set(member_ids)) != len(member_ids)):
        raise ValueError("assembly proposal requires unique member proposal IDs")
    nodes = proposal["node_candidates"]
    if not isinstance(nodes, list):
        raise ValueError("node_candidates must be a list")
    node_ids: set[str] = set()
    assembly_member_ids = set(member_ids)
    for index, node in enumerate(nodes):
        if (not isinstance(node, dict)
                or set(node) != {
                    "id", "position_m", "candidate_member_proposal_ids",
                    "source_point_ids", "status",
                }):
            raise ValueError(f"node_candidates[{index}] has an invalid shape")
        if not isinstance(node["id"], str) or not node["id"].strip() or node["id"] in node_ids:
            raise ValueError(f"node_candidates[{index}].id must be unique and non-empty")
        node_ids.add(node["id"])
        _point3(node["position_m"], f"node_candidates[{index}].position_m")
        node_members = node["candidate_member_proposal_ids"]
        if (not isinstance(node_members, list) or len(node_members) < 2
                or any(not isinstance(item, str) or not item.strip() for item in node_members)
                or len(set(node_members)) != len(node_members)):
            raise ValueError(f"node_candidates[{index}] requires unique candidate member IDs")
        if not set(node_members).issubset(assembly_member_ids):
            raise ValueError(f"node_candidates[{index}] references a member outside the assembly proposal")
        _source_ids(node["source_point_ids"], f"node_candidates[{index}]")
        if node["status"] != "proposed":
            raise ValueError("node candidates must remain proposed until explicit review")
    unresolved = proposal["unresolved_fields"]
    if (not isinstance(unresolved, list)
            or any(not isinstance(item, str) or not item.strip() for item in unresolved)
            or len(set(unresolved)) != len(unresolved)):
        raise ValueError("unresolved_fields must contain unique non-empty strings")
    if proposal["review_state"] != "proposed":
        raise ValueError("assembly proposals must remain proposed until explicit review")
    return proposal


def build_assembly_proposal(
    *,
    assembly_type: str,
    member_proposal_ids: Sequence[str],
    node_candidates: Sequence[dict[str, Any]] = (),
) -> AssemblyProposal:
    """Build a stable proposal for an assembly without claiming connectivity."""
    if isinstance(member_proposal_ids, (str, bytes)):
        raise ValueError("assembly proposal requires a sequence of member proposal IDs")
    raw_members = list(member_proposal_ids)
    if (not raw_members
            or any(not isinstance(item, str) or not item.strip() for item in raw_members)
            or len(set(raw_members)) != len(raw_members)):
        raise ValueError("assembly proposal requires unique member proposal IDs")
    members = sorted(raw_members)
    nodes = list(node_candidates)
    known_type = isinstance(assembly_type, str) and bool(assembly_type.strip()) and assembly_type.strip() != "unknown"
    type_value = assembly_type.strip() if known_type else "unknown"
    identity_document = json.dumps(
        {"assembly_type": type_value, "member_proposal_ids": members},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    assembly_id = "assembly-proposal-" + hashlib.sha256(identity_document).hexdigest()[:24]
    proposal: AssemblyProposal = {
        "id": assembly_id,
        "assembly_type": {
            "value": type_value,
            "status": "proposed" if known_type else "unknown",
        },
        "member_proposal_ids": members,
        "node_candidates": nodes,
        "unresolved_fields": ["member_connectivity", "node_membership", "assembly_boundary"],
        "review_state": "proposed",
    }
    validate_assembly_proposal(proposal)
    return proposal
