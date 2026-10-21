from scan2bim.recognition.reconcile import protect_reviewed_candidates


def _candidate(center=(1.0, 2.0, 3.0), class_name="column"):
    return {
        "class_name": class_name,
        "geometry": {"kind": "oriented_box", "center": list(center), "sizes": {"length": 1.0, "thickness": 1.0, "height": 4.0}},
        "bbox": {"min": [center[0] - 0.5, center[1] - 0.5, center[2] - 2.0], "max": [center[0] + 0.5, center[1] + 0.5, center[2] + 2.0]},
        "dimensions": {},
        "metadata": {},
    }


def _reviewed(element_id, candidate, status="confirmed"):
    return {
        "id": element_id,
        "class_name": candidate["class_name"],
        "geometry_json": __import__("json").dumps(candidate["geometry"], separators=(",", ":")),
        "bbox_json": __import__("json").dumps(candidate["bbox"], separators=(",", ":")),
        "review_status": status,
    }


def test_exact_reviewed_geometry_is_reused_without_a_new_candidate():
    candidate = _candidate()

    result = protect_reviewed_candidates([candidate], [_reviewed("manual-1", candidate)])

    assert result.candidates == []
    assert result.preserved_ids == ["manual-1"]
    assert result.conflicts == []


def test_nearby_changed_candidate_is_flagged_and_manual_correction_is_kept():
    reviewed_candidate = _candidate()
    updated_candidate = _candidate(center=(1.1, 2.0, 3.0))

    result = protect_reviewed_candidates([updated_candidate], [_reviewed("corrected-1", reviewed_candidate, "corrected")])

    assert len(result.candidates) == 1
    assert result.candidates[0]["dimensions"]["review_conflict_with"] == ["corrected-1"]
    assert result.conflicts == [{"candidate_index": 0, "protected_ids": ["corrected-1"]}]


def test_far_candidate_is_kept_without_false_review_conflict():
    candidate = _candidate(center=(20.0, 20.0, 3.0))

    result = protect_reviewed_candidates([candidate], [_reviewed("manual-1", _candidate())])

    assert len(result.candidates) == 1
    assert "review_conflict_with" not in result.candidates[0]["dimensions"]
    assert result.conflicts == []
