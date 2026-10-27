"""Verified point-count provenance for the workshop's second FARO source."""
from __future__ import annotations

from typing import Any, Mapping


WORKSHOP_2_SOURCE_POINT_COUNT = 574_367_742
WORKSHOP_2_LEGACY_UNVERIFIED_COUNT = 576_820_490
WORKSHOP_2_SOURCE_SHA256 = "784c2235541c89fbf78e02e28af8756a1040d46ff18111df3581b9b6b75b3792"
WORKSHOP_2_READER_VERSION = "24.0.0.240"


def apply_verified_workshop_2_count(
    metadata: Mapping[str, Any], *, source_sha256: str
) -> dict[str, Any]:
    """Return metadata with the repeated full DLL count and its audit trail.

    The stored sample count and unrelated scan metadata are preserved. The old
    hard-coded count remains visible as explicitly unverified history.
    """
    observed_sha256 = str(source_sha256).lower()
    if observed_sha256 != WORKSHOP_2_SOURCE_SHA256:
        raise ValueError("source SHA-256 does not match the audited Workshop 2 file")
    declared_identity = metadata.get("source_identity")
    declared_sha256 = (
        str(declared_identity.get("sha256", "")).lower()
        if isinstance(declared_identity, Mapping)
        else ""
    )
    if declared_sha256 and declared_sha256 != observed_sha256:
        raise ValueError("metadata source identity does not match the audited file")
    for key in ("source_sha256", "checksum_sha256"):
        value = str(metadata.get(key, "")).lower()
        if value and value != observed_sha256:
            raise ValueError(f"metadata {key} does not match the audited file")

    result = dict(metadata)
    result["reader"] = "recap-adskrcexport-dll"
    result["reader_version"] = WORKSHOP_2_READER_VERSION
    result["source_point_count"] = WORKSHOP_2_SOURCE_POINT_COUNT
    result["source_sha256"] = WORKSHOP_2_SOURCE_SHA256
    result["checksum_sha256"] = WORKSHOP_2_SOURCE_SHA256
    result["legacy_unverified_source_point_count"] = {
        "count": WORKSHOP_2_LEGACY_UNVERIFIED_COUNT,
        "label": "rcs_native_stream",
        "status": "unverified_hard_coded_value",
        "origin": (
            "scripts/prepare_both_workshop_clouds.py set this constant; "
            "no independent reader log was recorded"
        ),
    }
    result["count_reconciliation"] = {
        "status": "reconciled_to_repeated_full_dll_pass",
        "verified_source_point_count": WORKSHOP_2_SOURCE_POINT_COUNT,
        "legacy_unverified_source_point_count": WORKSHOP_2_LEGACY_UNVERIFIED_COUNT,
        "difference_points": (
            WORKSHOP_2_LEGACY_UNVERIFIED_COUNT - WORKSHOP_2_SOURCE_POINT_COUNT
        ),
        "source_sha256": WORKSHOP_2_SOURCE_SHA256,
        "reader": "scan2bim.formats.rcs_native via installed Autodesk ReCap DLL",
        "reader_version": WORKSHOP_2_READER_VERSION,
        "full_sequential_passes": 2,
        "recorded_at": "2026-10-24T22:52:44+00:00",
    }
    return result
