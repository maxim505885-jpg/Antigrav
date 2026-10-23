import pytest

from scan2bim.learning import registry


def test_invalidated_model_cannot_be_force_activated(monkeypatch):
    record = {
        "id": "invalid-model",
        "name": "workshop-real-knn",
        "version": 4,
        "kind": "knn-prior",
        "status": "invalidated",
        "metrics_json": '{"eligible_for_activation":true}',
    }
    monkeypatch.setattr(registry, "one", lambda *_args: record)
    monkeypatch.setattr(
        registry,
        "execute",
        lambda *_args: pytest.fail("invalidated model activation must stop before database writes"),
    )

    with pytest.raises(ValueError, match="invalidated model versions"):
        registry.activate("invalid-model", force=True)
