import pytest

from scan2bim.structure.proposals import (
    build_assembly_proposal,
    validate_assembly_proposal,
)


def test_assembly_proposal_links_unique_member_proposals_without_confirming_nodes():
    proposal = build_assembly_proposal(
        assembly_type="roof_truss",
        member_proposal_ids=["member-b", "member-a"],
    )

    assert proposal["assembly_type"] == {"value": "roof_truss", "status": "proposed"}
    assert proposal["member_proposal_ids"] == ["member-a", "member-b"]
    assert proposal["node_candidates"] == []
    assert proposal["review_state"] == "proposed"
    assert "member_connectivity" in proposal["unresolved_fields"]


def test_assembly_proposal_id_is_order_independent_and_deterministic():
    first = build_assembly_proposal(
        assembly_type="roof_truss", member_proposal_ids=["member-a", "member-b"],
    )
    second = build_assembly_proposal(
        assembly_type="roof_truss", member_proposal_ids=["member-b", "member-a"],
    )

    assert first["id"] == second["id"]


@pytest.mark.parametrize("member_ids", [[], ["member-a", "member-a"], [""]])
def test_assembly_proposal_rejects_missing_or_duplicate_members(member_ids):
    with pytest.raises(ValueError):
        build_assembly_proposal(assembly_type="roof_truss", member_proposal_ids=member_ids)


def test_assembly_proposal_cannot_be_marked_confirmed():
    proposal = build_assembly_proposal(
        assembly_type="roof_truss", member_proposal_ids=["member-a"],
    )
    proposal["review_state"] = "confirmed"

    with pytest.raises(ValueError, match="proposed"):
        validate_assembly_proposal(proposal)
