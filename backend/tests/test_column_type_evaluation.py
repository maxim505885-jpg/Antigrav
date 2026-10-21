"""Independent grouping references must not be replaced by predictions."""
from copy import deepcopy

import pytest

from scan2bim.structure.column_type_evaluation import evaluate_column_grouping


def columns(*ids):
    return [{"id": element_id, "class_name": "column", "measured": True, "inferred": False,
        "geometry": {"kind": "oriented_box", "sizes": {"length": 0.502, "thickness": 0.398, "height": 6}},
        "dimensions": {}} for element_id in ids]


def label(element_id, type_label=None, state=None, **kwargs):
    return {"element_id": element_id, "state": state or ("labeled" if type_label else "pending"),
        "type_label": type_label, "physical_instance_id": element_id if type_label else None,
        "note": "independent review", **kwargs}


def groups(*members):
    return [{"proposal_key": f"predicted-{i}", "member_element_ids": list(ids)} for i, ids in enumerate(members)]


def test_pairwise_metrics_ignore_arbitrary_prediction_label_names():
    result = evaluate_column_grouping(columns("a", "b", "c"),
        [label("a", "human-type-1"), label("b", "human-type-1"), label("c", "human-type-2")], groups(("a", "b"), ("c",)))
    assert result["pairwise"] == {"true_positive": 1, "false_merge_pairs": 0, "false_split_pairs": 0,
        "precision": 1.0, "recall": 1.0}
    assert result["engineering_accuracy_status"] == "not_assessed"


def test_false_merges_and_splits_are_counted_against_independent_labels():
    result = evaluate_column_grouping(columns("a", "b", "c", "d"),
        [label("a", "A"), label("b", "A"), label("c", "B"), label("d", "B")], groups(("a", "c"), ("b",), ("d",)))
    assert result["pairwise"]["false_merge_pairs"] == 1
    assert result["pairwise"]["false_split_pairs"] == 2
    assert result["pairwise"]["precision"] == result["pairwise"]["recall"] == 0.0


def test_abstaining_predictions_do_not_inflate_recall_or_join_unknowns():
    result = evaluate_column_grouping(columns("a", "b", "c"),
        [label("a", "A"), label("b", "A"), label("c", "A")], groups(("a", "b")))
    assert result["pairwise"]["recall"] == pytest.approx(1 / 3)
    assert result["unassigned_labeled_count"] == 1
    assert result["prediction_coverage_labeled"] == pytest.approx(2 / 3)
    missing = evaluate_column_grouping(columns("a", "b"), [label("a", "A"), label("b", "A")], [])
    assert missing["pairwise"]["precision"] is None
    assert missing["pairwise"]["recall"] == 0.0
    assert missing["pairwise"]["false_split_pairs"] == 1


def test_unknown_and_pending_references_are_reported_without_invented_labels():
    result = evaluate_column_grouping(columns("a", "b", "c", "d", "e"),
        [label("a", "A"), label("b", "A"), label("c", state="unknown"), label("d")], groups(("a", "b", "c", "d", "e")))
    assert result["pairwise"]["precision"] == 1.0
    assert result["reference_counts"] == {"labeled": 2, "unknown": 1, "pending": 1, "excluded": 0, "unannotated": 1}
    assert result["reference_coverage"] == 0.4


def test_unlabeled_template_has_no_accuracy_score():
    result = evaluate_column_grouping(columns("a", "b"), [label("a"), label("b")], groups(("a", "b")))
    assert result["evaluation_status"] == "awaiting_reference"
    assert result["pairwise"]["precision"] is None and result["pairwise"]["recall"] is None
    assert result["reference_coverage"] == 0.0


def test_dimension_errors_compare_independent_measurements_without_snapping():
    elements = columns("a"); before = deepcopy(elements)
    result = evaluate_column_grouping(elements, [label("a", "A", sides_m={"long": 0.5, "short": 0.4})], groups(("a",)))
    residual = result["dimension_residuals_mm"][0]
    assert residual["long_side_mm"] == pytest.approx(2)
    assert residual["short_side_mm"] == pytest.approx(-2)
    assert result["dimension_error_summary_mm"]["mae"] == pytest.approx(2)
    assert elements == before


@pytest.mark.parametrize("annotations,predictions", [
    ([label("a", "A"), label("a", "B")], []),
    ([label("missing", "A")], []),
    ([label("a", "A", state="pending")], []),
    ([label("a", "A")], groups(("a",), ("a",))),
    ([label("a", "A")], groups(("missing",))),
    ([label("a", "A", sides_m={"long": float("nan"), "short": 0.4})], []),
])
def test_malformed_or_conflicting_inputs_fail_explicitly(annotations, predictions):
    with pytest.raises(ValueError):
        evaluate_column_grouping(columns("a", "b"), annotations, predictions)


def test_annotation_template_never_copies_candidate_dimensions_or_type_guesses():
    from scan2bim.structure.column_type_evaluation import create_annotation_template
    result = create_annotation_template(columns("a", "b"), "a" * 64, "pilot-A")
    assert result["source_snapshot_sha256"] == "a" * 64
    assert result["annotator"] is None
    assert all(row["state"] == "pending" and row["type_label"] is None
        and row["sides_m"] is None for row in result["annotations"])


def test_tolerance_sweep_requires_matching_snapshot_and_explicit_reference_author():
    from scan2bim.structure.column_type_evaluation import create_annotation_template, evaluate_annotation_sweep
    elements = columns("a", "b")
    template = create_annotation_template(elements, "a" * 64, "pilot-A")
    kwargs = {"linear_tolerances_m": [0.002, 0.005], "relative_tolerances": [0.01]}
    with pytest.raises(ValueError, match="snapshot"):
        evaluate_annotation_sweep(elements, template, "b" * 64, **kwargs)
    pending = evaluate_annotation_sweep(elements, template, "a" * 64, **kwargs)
    assert len(pending["runs"]) == 2
    assert all(run["evaluation_status"] == "awaiting_reference" for run in pending["runs"])
    template["annotations"][0].update(state="labeled", type_label="A")
    template["annotations"][1].update(state="labeled", type_label="A")
    template["annotations"][0]["physical_instance_id"] = "physical-a"
    template["annotations"][1]["physical_instance_id"] = "physical-b"
    with pytest.raises(ValueError, match="annotator"):
        evaluate_annotation_sweep(elements, template, "a" * 64, **kwargs)
    template["annotator"] = "independent reviewer"
    result = evaluate_annotation_sweep(elements, template, "a" * 64, **kwargs)
    assert all(run["pairwise"]["recall"] == 1 for run in result["runs"])
    assert result["engineering_tolerance_m"] is None


def test_duplicate_detections_of_one_physical_column_cannot_inflate_grouping_scores():
    rows = [label("a", "A", physical_instance_id="same-physical-column"),
        label("b", "A", physical_instance_id="same-physical-column")]
    with pytest.raises(ValueError, match="physical"):
        evaluate_column_grouping(columns("a", "b"), rows, groups(("a", "b")))


def test_cli_creates_separate_references_and_refuses_overwrites_or_stale_snapshots(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    import runpy
    import sys
    script = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_column_types.py"
    source, annotations, report = (tmp_path / name for name in ("source.json", "references.json", "report.json"))
    source.write_text(json.dumps({"elements": columns("a", "b")}), encoding="utf-8")
    source_bytes = source.read_bytes()

    def run(*args):
        monkeypatch.setattr(sys, "argv", [str(script), *map(str, args)])
        runpy.run_path(str(script), run_name="__main__")

    run("template", "--source", source, "--out", annotations)
    original_annotations = annotations.read_bytes()
    run("evaluate", "--source", source, "--annotations", annotations, "--out", report)
    assert all(item["evaluation_status"] == "awaiting_reference" for item in json.loads(report.read_text())["runs"])
    with pytest.raises(SystemExit):
        run("template", "--source", source, "--out", annotations)
    assert annotations.read_bytes() == original_annotations and source.read_bytes() == source_bytes
    with pytest.raises(SystemExit):
        run("evaluate", "--source", source, "--annotations", tmp_path / "must-not-open.rcs", "--out", tmp_path / "forbidden.json")
    source.write_bytes(source_bytes + b"\n")
    stale_report = tmp_path / "stale.json"
    with pytest.raises(SystemExit):
        run("evaluate", "--source", source, "--annotations", annotations, "--out", stale_report)
    assert not stale_report.exists()


def test_mixed_manual_cloud_and_field_measurements_remain_explicit_in_evaluation():
    from scan2bim.structure.column_type_evaluation import evaluate_annotation_sweep

    elements = columns("a", "b")
    document = {
        "schema": "scan.column-type-reference/1", "dataset_id": "mixed",
        "source_snapshot_sha256": "a" * 64, "annotation_origin": "independent_manual",
        "reference_kind": "mixed", "annotator": "reviewer",
        "annotations": [
            {"element_id": "a", "state": "labeled", "type_label": "A",
             "physical_instance_id": "physical-a", "sides_m": {"long": .5, "short": .4},
             "measurement_source": "manual_cloud", "note": ""},
            {"element_id": "b", "state": "labeled", "type_label": "A",
             "physical_instance_id": "physical-b", "sides_m": {"long": .5, "short": .4},
             "measurement_source": "field_measurement", "note": ""},
        ],
    }

    result = evaluate_annotation_sweep(elements, document, "a" * 64,
        linear_tolerances_m=[.005], relative_tolerances=[.01])

    assert result["reference_kind"] == "mixed"
    assert result["runs"][0]["reference_counts"]["labeled"] == 2


def test_api_snapshot_annotations_evaluate_against_exported_bim_json_manifest(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    import runpy
    import sys
    from scan2bim.structure.column_annotations import (
        annotation_reference_document, column_snapshot_sha256,
    )

    elements = columns("a", "b")
    manifest = {
        "sha256": "d" * 64, "source_format": "e57", "size_bytes": 1000,
        "point_count": 200, "ingested_count": 200, "decimated": False,
        "origin_x": 0.0, "origin_y": 0.0, "origin_z": 0.0,
        "bbox_min_x": 0.0, "bbox_min_y": 0.0, "bbox_min_z": 0.0,
        "bbox_max_x": 10.0, "bbox_max_y": 10.0, "bbox_max_z": 10.0,
        "has_color": 0, "has_intensity": 0,
    }
    digest = column_snapshot_sha256(elements, manifest)
    annotations = annotation_reference_document("dataset", digest, elements, {}, manifest)
    source = tmp_path / "source.json"
    annotation_path = tmp_path / "annotations.json"
    report = tmp_path / "evaluation.json"
    source.write_text(json.dumps({"source": {"snapshot_manifest": manifest}, "elements": elements}), encoding="utf-8")
    annotation_path.write_text(json.dumps(annotations), encoding="utf-8")
    script = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_column_types.py"
    monkeypatch.setattr(sys, "argv", [str(script), "evaluate", "--source", str(source),
        "--annotations", str(annotation_path), "--out", str(report)])

    runpy.run_path(str(script), run_name="__main__")

    output = json.loads(report.read_text(encoding="utf-8"))
    assert output["source_snapshot_sha256"] == digest
    assert output["source_artifact_sha256"]
    assert output["runs"][0]["evaluation_status"] == "awaiting_reference"

    source_document = json.loads(source.read_text(encoding="utf-8"))
    source_document["source"]["snapshot_manifest"]["sha256"] = "e" * 64
    source.write_text(json.dumps(source_document), encoding="utf-8")
    stale_report = tmp_path / "stale-evaluation.json"
    monkeypatch.setattr(sys, "argv", [str(script), "evaluate", "--source", str(source),
        "--annotations", str(annotation_path), "--out", str(stale_report)])
    with pytest.raises(SystemExit):
        runpy.run_path(str(script), run_name="__main__")
    assert not stale_report.exists()
