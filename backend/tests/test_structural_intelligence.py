import pytest

from scan2bim.recognition.structural_intelligence import StructuralWorkshopClassifier


@pytest.fixture
def classifier():
    return StructuralWorkshopClassifier(
        bay_step_m=6.0, grid_tolerance_m=1.0, min_column_height_m=4.5,
    )


def test_grid_match_remains_a_review_proposal_and_does_not_invent_section(classifier):
    raw_candidates = [{
        "id": "column-candidate-1",
        "geometry": {
            "center": [-60.02, -4.78, 2.0],
            "sizes": {"height": 9.5},
        },
        "confidence": 0.42,
        "confidence_kind": "heuristic",
    }]

    proposals = classifier.classify_and_regularize(
        raw_candidates,
        known_x_bays=[-66.0, -60.0, -54.0],
        known_y_rows={"А": -17.5, "Б": -4.8, "В": 7.5, "Г": 20.5},
    )

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["review_state"] == "proposed"
    assert proposal["status"] == "unreviewed"
    assert proposal["grid_match"]["row_axis"] == "Б"
    assert proposal["grid_match"]["bay_axis"] == "2"
    assert proposal["grid_match"]["mark_candidate"] == "К-Б2"
    assert proposal["grid_match"]["status"] == "proposed"
    assert proposal["section_type"] == {"value": "unknown", "status": "unknown"}
    assert proposal["section_dimensions_m"] == {"width": None, "depth": None}
    assert proposal["measured_height_m"] == pytest.approx(9.5)
    assert proposal["confidence"] == pytest.approx(0.42)
    assert proposal["confidence_kind"] == "heuristic"


def test_tall_candidate_away_from_axes_is_not_labeled_as_structural_column(classifier):
    result = classifier.classify_and_regularize(
        [{
            "id": "pipe-candidate",
            "geometry": {"center": [-60.0, 0.5, 2.0], "sizes": {"height": 8.0}},
        }],
        known_x_bays=[-66.0, -60.0, -54.0],
        known_y_rows={"А": -17.5, "Б": -4.8, "В": 7.5, "Г": 20.5},
    )

    assert result == []
