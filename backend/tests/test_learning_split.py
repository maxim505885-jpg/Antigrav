"""Training holdout must keep revisions of one physical element together."""

import sqlite3

from scan2bim import db as database
from scan2bim.learning.training import _split_samples_by_element, _validate_physical_instance_labels
from scan2bim.learning import store


def test_training_and_test_splits_never_separate_samples_for_same_element():
    samples = [
        {"id": "revision-a", "element_id": "column-1"},
        {"id": "revision-b", "element_id": "column-1"},
        {"id": "revision-c", "element_id": "column-2"},
        {"id": "revision-d", "element_id": "column-3"},
        {"id": "revision-e", "element_id": "column-4"},
    ]

    train, test = _split_samples_by_element(samples, test_fraction=0.5)

    train_elements = {sample["element_id"] for sample in train}
    test_elements = {sample["element_id"] for sample in test}
    assert train_elements.isdisjoint(test_elements)
    assert len(train) + len(test) == len(samples)


def test_single_physical_element_does_not_create_a_fake_holdout():
    samples = [
        {"id": "revision-a", "element_id": "column-1"},
        {"id": "revision-b", "element_id": "column-1"},
    ]

    train, test = _split_samples_by_element(samples, test_fraction=0.25)

    assert train == samples
    assert test == []


def test_different_candidate_ids_for_one_physical_instance_stay_in_one_split():
    samples = [
        {"id": "sample-a", "element_id": "element-a", "physical_instance_id": "C-17"},
        {"id": "sample-b", "element_id": "element-c", "physical_instance_id": "C-17"},
        {"id": "sample-c", "element_id": "element-b", "physical_instance_id": "C-18"},
        {"id": "sample-d", "element_id": "element-d", "physical_instance_id": "C-19"},
    ]

    train, test = _split_samples_by_element(samples, test_fraction=0.5)

    physical_train = {sample["physical_instance_id"] for sample in train}
    physical_test = {sample["physical_instance_id"] for sample in test}
    assert physical_train.isdisjoint(physical_test)
    assert {sample["id"] for sample in train + test} == {sample["id"] for sample in samples}


def test_training_rejects_conflicting_classes_for_one_physical_instance():
    samples = [
        {"id": "sample-a", "element_id": "candidate-a", "physical_instance_id": "C-17", "class_name": "column"},
        {"id": "sample-b", "element_id": "candidate-b", "physical_instance_id": " C-17 ", "class_name": "beam"},
    ]

    try:
        _validate_physical_instance_labels(samples)
    except ValueError as exc:
        assert "C-17" in str(exc)
        assert "column" in str(exc)
        assert "beam" in str(exc)
    else:
        raise AssertionError("one physical element must not carry conflicting training classes")


def test_training_sample_identity_migration_preserves_legacy_rows():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE training_samples (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, cloud_id TEXT NOT NULL,
            element_id TEXT, class_name TEXT NOT NULL, features_json TEXT NOT NULL,
            points_path TEXT, split TEXT NOT NULL DEFAULT 'train',
            source TEXT NOT NULL DEFAULT 'engineer', created_at TEXT NOT NULL
        )
    """)
    connection.execute(
        "INSERT INTO training_samples (id,project_id,cloud_id,element_id,class_name,features_json,created_at) "
        "VALUES ('old','p','c','e','column','{}','now')"
    )

    database._ensure_training_sample_identity(connection)

    columns = {row["name"] for row in connection.execute("PRAGMA table_info(training_samples)")}
    existing = connection.execute(
        "SELECT element_id,class_name,source_snapshot_id FROM training_samples WHERE id='old'"
    ).fetchone()
    assert "physical_instance_id" in columns
    assert "source_snapshot_id" in columns
    assert tuple(existing) == ("e", "column", None)


def test_only_engineer_reviewed_samples_are_trainable(monkeypatch):
    samples = [
        {"id": "approved", "source": "engineer", "class_name": "column", "features": {}},
        {"id": "invalidated", "source": "invalidated_synthetic_ground_truth", "class_name": "column", "features": {}},
        {"id": "undone", "source": "undone", "class_name": "column", "features": {}},
        {"id": "generated", "source": "demo", "class_name": "column", "features": {}},
    ]
    monkeypatch.setattr(store, "list_samples", lambda project_id: samples)

    assert [sample["id"] for sample in store.samples_for_training("p")] == ["approved"]
    assert [sample["id"] for sample in store.similar_samples("p", {}, k=4)] == ["approved"]
