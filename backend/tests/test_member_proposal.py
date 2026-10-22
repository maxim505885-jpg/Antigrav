import copy

import pytest

from scan2bim.structure.proposals import validate_member_proposal


def _proposal():
    return {
        "id": "proposal-1",
        "role": {"value": "crane_girder", "status": "proposed"},
        "axis": {"start": [0.0, 0.0, 5.0], "end": [6.0, 0.0, 5.0]},
        "source_point_ids": [10, 12, 14],
        "source_point_id_space": "positions.npy row index",
        "source_point_ids_sampled": False,
        "support_count_in_processing_sample": 3,
        "support_evidence": {
            "start": {"status": "unknown", "source_point_ids": []},
            "end": {"status": "supported", "source_point_ids": [14]},
        },
        "observed_profile": {"kind": "unknown", "reason": "web and flanges occluded"},
        "joint_gaps": [],
        "unresolved_fields": ["start_support", "cross_section"],
        "review_state": "proposed",
    }


def test_member_proposal_keeps_axis_provenance_and_unknown_support_and_profile():
    proposal = _proposal()

    assert validate_member_proposal(proposal) is proposal
    assert proposal["support_evidence"]["start"]["status"] == "unknown"
    assert proposal["observed_profile"]["kind"] == "unknown"
    assert proposal["review_state"] == "proposed"


@pytest.mark.parametrize("axis", [
    {"start": [0.0, 0.0, 0.0], "end": [0.0, 0.0, 0.0]},
    {"start": [0.0, 0.0], "end": [1.0, 0.0, 0.0]},
    {"start": [0.0, 0.0, float("nan")], "end": [1.0, 0.0, 0.0]},
])
def test_member_proposal_rejects_degenerate_or_invalid_axes(axis):
    proposal = _proposal()
    proposal["axis"] = axis

    with pytest.raises(ValueError, match="axis"):
        validate_member_proposal(proposal)


def test_member_proposal_rejects_duplicate_or_untraceable_source_rows():
    duplicate = _proposal()
    duplicate["source_point_ids"] = [10, 10]
    with pytest.raises(ValueError, match="source_point_ids"):
        validate_member_proposal(duplicate)

    missing = _proposal()
    missing["source_point_ids"] = []
    with pytest.raises(ValueError, match="source_point_ids"):
        validate_member_proposal(missing)


def test_member_proposal_requires_consistent_role_status_and_row_namespace():
    unknown_role = _proposal()
    unknown_role["role"]["status"] = "unknown"
    with pytest.raises(ValueError, match="unknown role"):
        validate_member_proposal(unknown_role)

    wrong_namespace = _proposal()
    wrong_namespace["source_point_id_space"] = "scanner raw row index"
    with pytest.raises(ValueError, match="source_point_id_space"):
        validate_member_proposal(wrong_namespace)


def test_member_proposal_cannot_be_confirmed_or_claim_unobserved_support():
    confirmed = _proposal()
    confirmed["review_state"] = "confirmed"
    with pytest.raises(ValueError, match="proposed"):
        validate_member_proposal(confirmed)

    false_support = copy.deepcopy(_proposal())
    false_support["support_evidence"]["start"] = {"status": "supported", "source_point_ids": []}
    with pytest.raises(ValueError, match="support"):
        validate_member_proposal(false_support)


def test_member_proposal_rejects_unresolved_fields_with_invalid_shape():
    proposal = _proposal()
    proposal["unresolved_fields"] = ["cross_section", "cross_section"]

    with pytest.raises(ValueError, match="unresolved_fields"):
        validate_member_proposal(proposal)


@pytest.mark.parametrize("field,value", [
    ("role_status", []),
    ("profile_kind", {}),
    ("joint_kind", []),
    ("boolean_coordinate", True),
])
def test_member_proposal_malformed_json_values_fail_with_contract_error(field, value):
    proposal = _proposal()
    if field == "role_status":
        proposal["role"]["status"] = value
    elif field == "profile_kind":
        proposal["observed_profile"]["kind"] = value
    elif field == "joint_kind":
        proposal["joint_gaps"] = [{
            "kind": value, "position_m": 1.0, "reason": "observed break",
            "source_point_ids": [10],
        }]
    else:
        proposal["axis"]["start"][0] = value

    with pytest.raises(ValueError):
        validate_member_proposal(proposal)


def test_builder_creates_stable_unconfirmed_beam_candidate_with_unknown_supports():
    from scan2bim.structure.proposals import build_member_proposal

    proposal = build_member_proposal(
        role="crane_girder",
        axis_start_m=[100.0, 200.0, 5.0],
        axis_end_m=[106.0, 200.0, 5.0],
        source_point_ids=[10, 12, 14],
        source_point_ids_sampled=False,
        support_count_in_processing_sample=3,
    )

    assert validate_member_proposal(proposal) is proposal
    assert proposal["id"].startswith("member-proposal-")
    assert proposal["role"] == {"value": "crane_girder", "status": "proposed"}
    assert proposal["support_evidence"]["start"]["status"] == "unknown"
    assert proposal["support_evidence"]["end"]["status"] == "unknown"
    assert proposal["observed_profile"] == {
        "kind": "unknown", "reason": "full cross-section is not fitted from the horizontal band",
    }
    assert proposal["review_state"] == "proposed"

    reversed_proposal = build_member_proposal(
        role="unknown",
        axis_start_m=[106.0, 200.0, 5.0],
        axis_end_m=[100.0, 200.0, 5.0],
        source_point_ids=[14, 12, 10],
        source_point_ids_sampled=False,
        support_count_in_processing_sample=3,
    )
    assert reversed_proposal["id"] == proposal["id"]


def test_builder_preserves_point_linked_internal_gap_candidates():
    from scan2bim.structure.proposals import build_member_proposal

    gap = {
        "kind": "gap",
        "position_m": 3.0,
        "reason": "No core-line points; this may be occlusion or a physical joint.",
        "source_point_ids": [11, 12, 19, 20],
    }
    proposal = build_member_proposal(
        role="crane_girder",
        axis_start_m=[0.0, 0.0, 5.0],
        axis_end_m=[6.0, 0.0, 5.0],
        source_point_ids=[11, 12, 13, 19, 20],
        source_point_ids_sampled=False,
        support_count_in_processing_sample=5,
        joint_gaps=[gap],
    )

    assert validate_member_proposal(proposal) is proposal
    assert proposal["joint_gaps"] == [gap]
    assert proposal["review_state"] == "proposed"


def test_member_gap_position_must_lie_on_the_proposed_axis():
    proposal = _proposal()
    proposal["joint_gaps"] = [{
        "kind": "gap", "position_m": 6.1,
        "reason": "No core-line points; physical cause unknown.",
        "source_point_ids": [10, 12],
    }]

    with pytest.raises(ValueError, match="within the member axis"):
        validate_member_proposal(proposal)


@pytest.mark.parametrize("position_m", [True, "3.0"])
def test_member_gap_position_requires_a_json_number(position_m):
    proposal = _proposal()
    proposal["joint_gaps"] = [{
        "kind": "gap", "position_m": position_m,
        "reason": "No core-line points; physical cause unknown.",
        "source_point_ids": [10, 12],
    }]

    with pytest.raises(ValueError, match="position_m must be finite"):
        validate_member_proposal(proposal)
