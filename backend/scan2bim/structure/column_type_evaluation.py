"""Evaluate proposed partitions against separately authored instance labels."""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

from .column_types import _finite_positive, column_descriptor, propose_column_types


def create_annotation_template(elements, source_snapshot_sha256: str, dataset_id: str) -> dict[str, Any]:
    """Create empty reference fields; prediction values are not ground truth."""
    evaluate_column_grouping(elements, [], [])  # Validate physical instance IDs.
    return {"schema": "scan.column-type-reference/1", "dataset_id": dataset_id,
        "source_snapshot_sha256": source_snapshot_sha256, "annotation_origin": "independent_manual",
        "reference_kind": "manual_cloud", "annotator": None, "engineering_tolerance_m": None,
        "annotations": [{"element_id": item["id"], "physical_instance_id": None, "state": "pending", "type_label": None,
            "sides_m": None, "measurement_source": None, "note": ""}
            for item in sorted(elements, key=lambda item: item["id"]) if item.get("class_name") == "column"]}


def evaluate_annotation_sweep(elements, document, source_snapshot_sha256: str, *,
    linear_tolerances_m: list[float], relative_tolerances: list[float]) -> dict[str, Any]:
    """Compare exploratory grouping thresholds without selecting a production setting."""
    if document.get("schema") != "scan.column-type-reference/1":
        raise ValueError("unsupported annotation schema")
    if document.get("source_snapshot_sha256") != source_snapshot_sha256:
        raise ValueError("reference snapshot checksum differs from source snapshot")
    if document.get("annotation_origin") != "independent_manual":
        raise ValueError("reference must declare independent manual annotation")
    reference_kind = document.get("reference_kind")
    if reference_kind not in {"manual_cloud", "field_measurement", "mixed"}:
        raise ValueError("reference_kind must distinguish cloud, field or mixed measurements")
    annotations = document.get("annotations")
    if not isinstance(annotations, list):
        raise ValueError("annotations must be a list")
    if any(row.get("state") != "pending" for row in annotations) and not str(document.get("annotator") or "").strip():
        raise ValueError("reviewed references require a named annotator")
    for row in annotations:
        if row.get("sides_m") is not None and row.get("measurement_source") not in {"manual_cloud", "field_measurement"}:
            raise ValueError("reference side measurements require their independent measurement source")
        if (row.get("sides_m") is not None and reference_kind != "mixed"
                and row.get("measurement_source") != reference_kind):
            raise ValueError("reference_kind conflicts with a row measurement_source")
        if row.get("state") in {"unknown", "excluded"} and not str(row.get("note") or "").strip():
            raise ValueError("unknown/excluded references require a review note")
    evaluate_column_grouping(elements, annotations, [])
    if not linear_tolerances_m or not relative_tolerances:
        raise ValueError("at least one setting is required for each tolerance")
    for value in [*linear_tolerances_m, *relative_tolerances]:
        if isinstance(value, bool) or not math.isfinite(value) or value < 0:
            raise ValueError("exploratory tolerances must be finite and non-negative")
    runs = []
    for linear in sorted(set(linear_tolerances_m)):
        for relative in sorted(set(relative_tolerances)):
            proposals = propose_column_types([item for item in elements if item.get("review_status") != "rejected"],
                linear_tolerance_m=linear, relative_tolerance=relative)
            runs.append({"linear_tolerance_m": linear, "relative_tolerance": relative,
                "proposal_count": len(proposals), "singleton_count": sum(len(p["member_element_ids"]) == 1 for p in proposals),
                "proposals": proposals, **evaluate_column_grouping(elements, annotations, proposals)})
    return {"schema": "scan.column-type-evaluation/1", "dataset_id": document.get("dataset_id"),
        "source_snapshot_sha256": source_snapshot_sha256, "reference_kind": document["reference_kind"],
        "annotator": document.get("annotator"), "parameter_status": "exploratory_not_production",
        "engineering_tolerance_m": None, "runs": runs}


def evaluate_column_grouping(
    elements: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score known reference pairs; missing predictions remain false splits.

    Unknown/pending reference labels are never filled from predictions. These
    are grouping metrics on candidate instances, not detection recall or proof
    of engineering accuracy. Pair counts use contingency tables, not O(n²) pairs.
    """
    population = [item for item in elements if item.get("class_name") == "column"]
    by_id = {item["id"]: item for item in population}
    if len(by_id) != len(population) or any(not key for key in by_id):
        raise ValueError("column instance IDs must be non-empty and unique")
    references, counts, physical_ids = {}, Counter(), set()
    for row in annotations:
        element_id = row.get("element_id")
        if element_id not in by_id or element_id in references:
            raise ValueError("annotation IDs must be unique and belong to the source snapshot")
        state = row.get("state")
        if state not in {"labeled", "pending", "unknown", "excluded"}:
            raise ValueError("invalid annotation state")
        label = row.get("type_label")
        if state == "labeled":
            if not isinstance(label, str) or not label.strip():
                raise ValueError("labeled references require an independent type label")
            physical_id = row.get("physical_instance_id")
            if not isinstance(physical_id, str) or not physical_id.strip() or physical_id.strip() in physical_ids:
                raise ValueError("labeled references need unique physical instance IDs; reconcile duplicate detections first")
            physical_ids.add(physical_id.strip())
        elif label is not None:
            raise ValueError("unknown/pending/excluded references must not contain type labels")
        sides = row.get("sides_m")
        if sides is not None:
            if not isinstance(sides, dict) or any(_finite_positive(sides.get(side)) is None for side in ("long", "short")):
                raise ValueError("reference sides must be positive finite measurements")
            if float(sides["long"]) < float(sides["short"]):
                raise ValueError("reference sides must use long/short order")
        references[element_id] = row
        counts[state] += 1
    counts["unannotated"] = len(by_id) - len(references)
    predicted, keys = {}, set()
    for proposal in proposals:
        key = proposal.get("proposal_key")
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError("prediction group keys must be non-empty and unique")
        keys.add(key)
        for element_id in proposal.get("member_element_ids", []):
            if element_id not in by_id or element_id in predicted:
                raise ValueError("each predicted instance must occur in exactly one known group")
            predicted[element_id] = key

    known = {key: row["type_label"].strip() for key, row in references.items() if row["state"] == "labeled"}
    choose_two = lambda n: n * (n - 1) // 2
    true_pairs = sum(choose_two(n) for n in Counter(known.values()).values())
    assigned = {key: predicted[key] for key in known if key in predicted}
    predicted_pairs = sum(choose_two(n) for n in Counter(assigned.values()).values())
    contingency = Counter((known[key], group) for key, group in assigned.items())
    tp = sum(choose_two(n) for n in contingency.values())
    residuals = []
    missing_dimensions = 0
    for key in sorted(known):
        sides = references[key].get("sides_m")
        if sides is None:
            continue
        descriptor = column_descriptor(by_id[key])
        if not descriptor["eligible"]:
            missing_dimensions += 1
            continue
        residuals.append({"element_id": key,
            **{f"{side}_side_mm": (descriptor[f"{side}_side_m"] - float(sides[side])) * 1000
                for side in ("long", "short")}})
    errors = [row[side] for row in residuals for side in ("long_side_mm", "short_side_mm")]
    available = len(by_id) - counts["excluded"]
    return {
        "evaluation_status": "evaluated" if len(known) >= 2 else "awaiting_reference",
        "engineering_accuracy_status": "not_assessed",
        "metric_scope": "grouping_on_candidate_instances_only",
        "target_column_count": len(by_id),
        "reference_counts": {state: counts[state] for state in ("labeled", "unknown", "pending", "excluded", "unannotated")},
        "reference_coverage": len(known) / available if available else None,
        "unassigned_labeled_count": len(known) - len(assigned),
        "prediction_coverage_labeled": len(assigned) / len(known) if known else None,
        "pairwise": {"true_positive": tp, "false_merge_pairs": predicted_pairs - tp,
            "false_split_pairs": true_pairs - tp,
            "precision": tp / predicted_pairs if predicted_pairs else None,
            "recall": tp / true_pairs if true_pairs else None},
        "dimension_residuals_mm": residuals,
        "unmeasurable_reference_count": missing_dimensions,
        "dimension_error_summary_mm": {"side_count": len(errors),
            "mae": sum(abs(e) for e in errors) / len(errors) if errors else None,
            "bias": sum(errors) / len(errors) if errors else None,
            "rmse": math.sqrt(sum(e * e for e in errors) / len(errors)) if errors else None,
            "max_absolute": max(map(abs, errors)) if errors else None},
    }
