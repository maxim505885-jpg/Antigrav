from scan2bim.formats.workshop_count_metadata import (
    WORKSHOP_2_LEGACY_UNVERIFIED_COUNT,
    WORKSHOP_2_SOURCE_SHA256,
    WORKSHOP_2_SOURCE_POINT_COUNT,
    apply_verified_workshop_2_count,
)


def test_workshop_2_verified_count_preserves_sample_and_records_legacy_value():
    original = {
        "source_point_count": WORKSHOP_2_LEGACY_UNVERIFIED_COUNT,
        "stored_point_count": 3_500_000,
        "decimated": True,
        "origin": [1.0, 2.0, 3.0],
    }

    updated = apply_verified_workshop_2_count(
        original, source_sha256=WORKSHOP_2_SOURCE_SHA256
    )

    assert updated["source_point_count"] == WORKSHOP_2_SOURCE_POINT_COUNT
    assert updated["stored_point_count"] == 3_500_000
    assert updated["decimated"] is True
    assert updated["origin"] == [1.0, 2.0, 3.0]
    assert updated["legacy_unverified_source_point_count"]["count"] == WORKSHOP_2_LEGACY_UNVERIFIED_COUNT
    assert updated["legacy_unverified_source_point_count"]["status"] == "unverified_hard_coded_value"
    assert updated["count_reconciliation"]["difference_points"] == 2_452_748


def test_workshop_2_verified_count_normalization_is_idempotent():
    first = apply_verified_workshop_2_count(
        {"stored_point_count": 10}, source_sha256=WORKSHOP_2_SOURCE_SHA256
    )
    second = apply_verified_workshop_2_count(first, source_sha256=WORKSHOP_2_SOURCE_SHA256)

    assert second == first


def test_workshop_2_count_rejects_unknown_or_mismatched_source():
    import pytest

    with pytest.raises(ValueError, match="source SHA-256"):
        apply_verified_workshop_2_count(
            {"stored_point_count": 10}, source_sha256="0" * 64
        )

    with pytest.raises(ValueError, match="metadata source identity"):
        apply_verified_workshop_2_count(
            {
                "stored_point_count": 10,
                "source_identity": {"sha256": "0" * 64},
            },
            source_sha256=WORKSHOP_2_SOURCE_SHA256,
        )

    with pytest.raises(ValueError, match="metadata source_sha256"):
        apply_verified_workshop_2_count(
            {"source_sha256": "0" * 64},
            source_sha256=WORKSHOP_2_SOURCE_SHA256,
        )
