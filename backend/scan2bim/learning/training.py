"""Controlled training of the learned class prior.

A newly trained model is always a *candidate*. It only becomes active through
an explicit activation call, and only if held-out metrics pass the configured
threshold. This prevents silent accuracy regressions.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from ..config import MODELS_DIR
from ..db import dumps, execute, new_id, one, rows, utcnow
from .features import FEATURE_NAMES
from .knn import KNNModel
from .store import samples_for_training


def _bucket(sample_id: str) -> int:
    return int(hashlib.sha256(sample_id.encode("utf-8")).hexdigest()[:8], 16) % 10000


def _split_samples_by_element(
    samples: list[dict[str, Any]], test_fraction: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split by physical element so repeated revisions cannot leak across holdout."""
    threshold = int(round(test_fraction * 10000))
    groups: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        element_id = str(sample.get("element_id") or sample["id"])
        groups.setdefault(element_id, []).append(sample)

    test_elements = {element_id for element_id in groups if _bucket(element_id) < threshold}
    if len(groups) <= 1:
        test_elements.clear()
    elif not test_elements:
        test_elements.add(min(groups, key=lambda element_id: (_bucket(element_id), element_id)))
    train_elements = set(groups) - test_elements
    if len(groups) > 1 and not train_elements:
        element_id = max(test_elements, key=lambda value: (_bucket(value), value))
        test_elements.remove(element_id)
        train_elements.add(element_id)

    train = [sample for sample in samples
        if str(sample.get("element_id") or sample["id"]) in train_elements]
    test = [sample for sample in samples
        if str(sample.get("element_id") or sample["id"]) in test_elements]
    return train, test


def _metrics(y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
    labels = sorted(set(y_true) | set(y_pred))
    per_class: dict[str, Any] = {}
    f1s = []
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        if label in y_true:
            f1s.append(f1)
        per_class[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": y_true.count(label),
        }
    accuracy = sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true) if y_true else 0.0
    return {
        "accuracy": round(accuracy, 4),
        "macro_f1": round(float(np.mean(f1s)) if f1s else 0.0, 4),
        "per_class": per_class,
        "test_support": len(y_true),
        "classes_in_test": sorted(set(y_true)),
    }


def train_candidate(
    project_id: str,
    name: str = "geometric-knn",
    test_fraction: float = 0.25,
    min_test_samples: int = 6,
    min_macro_f1: float = 0.6,
    notes: str = "",
) -> dict[str, Any]:
    samples = samples_for_training(project_id)
    if len(samples) < 4:
        raise ValueError(
            "at least 4 engineer-reviewed samples are required for a train/test split"
        )
    train, test = _split_samples_by_element(samples, test_fraction)

    model = KNNModel.fit(train, version=1, name=name, notes=notes)
    y_true = [str(s["class_name"]) for s in test]
    y_pred = [str(model.predict(s["features"])["predicted_class"]) for s in test]
    metrics = _metrics(y_true, y_pred)
    metrics["train_support"] = len(train)
    metrics["thresholds"] = {
        "min_test_samples": min_test_samples,
        "min_macro_f1": min_macro_f1,
    }
    eligible = (
        metrics["test_support"] >= min_test_samples
        and metrics["macro_f1"] >= min_macro_f1
        and len(set(y_true)) >= 2
    )
    metrics["eligible_for_activation"] = bool(eligible)
    if metrics["test_support"] < min_test_samples:
        metrics["blocking_reason"] = (
            f"held-out set has {metrics['test_support']} samples, "
            f"minimum is {min_test_samples}; collect more reviewed examples"
        )
    elif len(set(y_true)) < 2:
        metrics["blocking_reason"] = "held-out set contains a single class"
    elif metrics["macro_f1"] < min_macro_f1:
        metrics["blocking_reason"] = (
            f"macro F1 {metrics['macro_f1']} is below threshold {min_macro_f1}"
        )

    existing = one(
        "SELECT MAX(version) AS v FROM model_versions WHERE name = ? AND kind = 'knn-prior'",
        (name,),
    )
    version = int(existing["v"] or 0) + 1
    model.artifact["version"] = version
    model.artifact["metrics"] = metrics
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    path = MODELS_DIR / f"knn_{name}_v{version}.json"
    path.write_text(json.dumps(model.artifact, ensure_ascii=False, indent=2), encoding="utf-8")

    model_id = new_id()
    now = utcnow()
    execute(
        """
        INSERT INTO model_versions (id, name, version, kind, path, metrics_json, status, notes, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (model_id, name, version, "knn-prior", str(path), dumps(metrics), "candidate", notes, now),
    )
    return {
        "id": model_id,
        "name": name,
        "version": version,
        "kind": "knn-prior",
        "path": str(path),
        "metrics": metrics,
        "status": "candidate",
        "notes": notes,
        "created_at": now,
        "activated_at": None,
    }


def active_artifact(name: str = "geometric-knn") -> dict[str, Any] | None:
    record = one(
        "SELECT * FROM model_versions WHERE name = ? AND kind = 'knn-prior' AND status = 'active' "
        "ORDER BY version DESC LIMIT 1",
        (name,),
    )
    if not record:
        return None
    try:
        return json.loads(Path(record["path"]).read_text(encoding="utf-8"))
    except Exception:
        return None


def apply_learned_prior(elements: list[dict[str, Any]], name: str = "geometric-knn") -> int:
    """Attach suggestions from the active model without overriding geometry."""
    artifact = active_artifact(name)
    if not artifact:
        return 0
    model = KNNModel(artifact)
    applied = 0
    for element in elements:
        try:
            prediction = model.predict(element.get("features") or {})
        except Exception:
            continue
        if prediction.get("predicted_class"):
            meta = element.setdefault("metadata", {})
            meta["learned_suggestion"] = prediction
            applied += 1
    return applied
