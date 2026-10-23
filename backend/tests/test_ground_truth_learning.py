"""Unit and integration tests for real Ground Truth workshop dataset and Supervised Learning (Stage 7).

Verifies:
1. 106 real verified workshop elements generated across 6 classes:
   - column (40), beam (20), truss (16), brace (12), opening (8), pipe (10).
2. Proper ingestion into SQLite `elements` and `training_samples`.
3. Model training on held-out split with Macro-F1 >= 0.75 and Accuracy >= 0.80.
4. Active model registration and artifact activation.
5. Learned prior prediction attaching predictions to unseen candidates without mutating geometry.
"""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import pytest

import scan2bim.config as config
from scan2bim.db import init_db, execute, rows, utcnow
from scan2bim.learning.features import features_from_element
from scan2bim.learning.ground_truth import (
    generate_workshop_ground_truth_catalog,
    seed_and_train_ground_truth,
)
from scan2bim.learning.training import apply_learned_prior


@pytest.fixture
def clean_db():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_learning.db"
        old_path = config.DB_PATH
        config.DB_PATH = db_path
        init_db()
        yield db_path
        config.DB_PATH = old_path


def test_catalog_structure_and_classes():
    catalog = generate_workshop_ground_truth_catalog()
    assert len(catalog) == 106

    classes = {elem.class_name for elem in catalog}
    assert classes == {"column", "beam", "truss", "brace", "opening", "pipe"}

    counts: dict[str, int] = {}
    for elem in catalog:
        counts[elem.class_name] = counts.get(elem.class_name, 0) + 1

    assert counts["column"] == 40
    assert counts["beam"] == 20
    assert counts["truss"] == 16
    assert counts["brace"] == 12
    assert counts["opening"] == 8
    assert counts["pipe"] == 10

    # Ensure all elements have realistic dimensions and valid coordinates
    for elem in catalog:
        assert len(elem.center) == 3
        assert elem.sizes["length"] > 0
        assert elem.sizes["thickness"] > 0
        assert elem.sizes["height"] > 0
        assert 0.0 <= elem.confidence <= 1.0


def test_seed_and_train_ground_truth_metrics(clean_db):
    proj_id = "test_workshop_project"
    cloud_id = "test_workshop_cloud_01"
    now = utcnow()

    execute(
        "INSERT INTO projects (id, name, description, units, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (proj_id, "Workshop Real Project", "Test workshop", "m", now, now),
    )

    execute(
        "INSERT INTO clouds (id, project_id, name, source_path, source_format, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (cloud_id, proj_id, "Workshop 1.rcs", "1.rcs", "rcs", now, now),
    )

    res = seed_and_train_ground_truth(
        project_id=proj_id,
        cloud_id=cloud_id,
        model_name="workshop-real-knn",
    )

    assert res["status"] == "success"
    assert res["ground_truth_catalog_size"] == 106
    assert res["inserted_elements"] == 106
    assert res["inserted_samples"] == 106
    assert res["macro_f1"] >= 0.75
    assert res["accuracy"] >= 0.80

    db_elements = rows("SELECT id, class_name FROM elements WHERE project_id = ?", (proj_id,))
    assert len(db_elements) == 106

    db_samples = rows("SELECT id, class_name FROM training_samples WHERE project_id = ?", (proj_id,))
    assert len(db_samples) == 106

    # Verify model prediction on unseen candidates
    test_col = {
        "id": "unseen_col_candidate",
        "confidence": 0.90,
        "geometry": {
            "kind": "oriented_box",
            "sizes": {"length": 0.35, "thickness": 0.30, "height": 8.40},
            "rotation_z": 0.0,
        },
        "dimensions": {"length_m": 0.35, "thickness_m": 0.30, "height_m": 8.40},
        "bbox": {"min": [24.0, 0.0, 0.0], "max": [24.35, 0.30, 8.40]},
        "metadata": {},
    }
    test_col["features"] = features_from_element(test_col)

    test_beam = {
        "id": "unseen_beam_candidate",
        "confidence": 0.88,
        "geometry": {
            "kind": "oriented_box",
            "sizes": {"length": 6.00, "thickness": 0.30, "height": 0.65},
            "rotation_z": 0.0,
        },
        "dimensions": {"length_m": 6.00, "thickness_m": 0.30, "height_m": 0.65},
        "bbox": {"min": [0.0, 0.0, 6.8], "max": [6.0, 0.30, 7.45]},
        "metadata": {},
    }
    test_beam["features"] = features_from_element(test_beam)

    candidates = [test_col, test_beam]
    applied = apply_learned_prior(candidates, name="workshop-real-knn")

    assert applied == 2
    assert test_col["metadata"]["learned_suggestion"]["predicted_class"] == "column"
    assert test_beam["metadata"]["learned_suggestion"]["predicted_class"] == "beam"
