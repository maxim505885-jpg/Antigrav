"""Report serialization preserves the frozen candidate identity."""

from scripts.fit_column_track_sections import _candidate_result


def test_candidate_result_does_not_let_measurement_report_erase_candidate_id():
    result = _candidate_result("column-17", {"candidate_id": None, "status": "unknown"})

    assert result["candidate_id"] == "column-17"
    assert result["status"] == "unknown"
