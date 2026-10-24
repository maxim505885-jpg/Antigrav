"""Synthetic workshop fixtures must never masquerade as physical ground truth."""
import pytest

from scan2bim import db as database
from scan2bim.learning.ground_truth import (
    generate_synthetic_workshop_fixture_catalog,
    seed_and_train_ground_truth,
)


def test_workshop_catalog_is_explicitly_synthetic_and_unreviewed():
    catalog = generate_synthetic_workshop_fixture_catalog()

    assert len(catalog) == 106
    assert {element.class_name for element in catalog} == {
        "column", "beam", "truss", "brace", "opening", "pipe",
    }
    row = catalog[0].to_dict("fixture-project", "fixture-cloud")
    assert row["source"] == "invalidated_synthetic_ground_truth"
    assert row["review_status"] == "invalidated"
    assert row["inferred"] is True
    assert row["measured"] is False
    assert row["confidence_kind"] == "synthetic_fixture"
    assert "verified_by" not in row["metadata"]


def test_synthetic_workshop_catalog_cannot_seed_or_train(monkeypatch):
    monkeypatch.setattr(database, "execute", lambda *_args, **_kwargs: pytest.fail("must not seed fixtures"))
    monkeypatch.setattr(database, "one", lambda *_args, **_kwargs: pytest.fail("must not query training data"))

    with pytest.raises(ValueError, match="synthetic.*cannot be seeded or used for training"):
        seed_and_train_ground_truth("p", "c")
