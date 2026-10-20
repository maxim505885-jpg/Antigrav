"""Small, auditable kNN classifier used as a learned class prior.

The model is a JSON artifact with feature normalisation and the reviewed
examples. It is intentionally lightweight: it runs on CPU, trains in
milliseconds and can be rolled back by activating an older version.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .features import FEATURE_NAMES, vector_from_features


@dataclass
class KNNModel:
    artifact: dict[str, Any]

    @classmethod
    def fit(
        cls,
        samples: list[dict[str, Any]],
        k: int = 5,
        version: int = 1,
        name: str = "geometric-knn",
        notes: str = "",
    ) -> "KNNModel":
        if not samples:
            raise ValueError("cannot train without samples")
        names = list(FEATURE_NAMES)
        X = np.vstack([vector_from_features(s["features"], names) for s in samples])
        y = [str(s["class_name"]) for s in samples]
        mean = X.mean(axis=0)
        std = X.std(axis=0)
        std[std < 1e-9] = 1.0
        artifact = {
            "kind": "knn-prior",
            "name": name,
            "version": version,
            "k": int(max(1, min(k, len(samples)))),
            "feature_names": names,
            "mean": mean.tolist(),
            "std": std.tolist(),
            "X": ((X - mean) / std).round(6).tolist(),
            "y": y,
            "sample_ids": [s.get("id") for s in samples],
            "notes": notes,
        }
        return cls(artifact)

    @property
    def version(self) -> int:
        return int(self.artifact.get("version", 1))

    def _transform(self, features: dict[str, float]) -> np.ndarray:
        names = self.artifact.get("feature_names", FEATURE_NAMES)
        vec = vector_from_features(features, names)
        mean = np.asarray(self.artifact["mean"], dtype=np.float64)
        std = np.asarray(self.artifact["std"], dtype=np.float64)
        return (vec - mean) / std

    def predict(self, features: dict[str, float]) -> dict[str, Any]:
        X = np.asarray(self.artifact["X"], dtype=np.float64)
        y = self.artifact["y"]
        if X.size == 0:
            return {"predicted_class": None, "probabilities": {}, "neighbors": []}
        v = self._transform(features)
        distances = np.linalg.norm(X - v, axis=1)
        order = np.argsort(distances)[: int(self.artifact.get("k", 5))]
        weights: dict[str, float] = {}
        neighbors = []
        for idx in order:
            dist = float(distances[idx])
            weight = 1.0 / (dist + 1e-6)
            label = str(y[idx])
            weights[label] = weights.get(label, 0.0) + weight
            neighbors.append(
                {
                    "sample_id": self.artifact.get("sample_ids", [])[idx]
                    if idx < len(self.artifact.get("sample_ids", []))
                    else None,
                    "class_name": label,
                    "distance": round(dist, 5),
                }
            )
        total = sum(weights.values())
        probabilities = {
            label: round(value / total, 4) for label, value in sorted(weights.items(), key=lambda kv: -kv[1])
        }
        predicted = max(probabilities, key=probabilities.get) if probabilities else None
        return {
            "predicted_class": predicted,
            "probabilities": probabilities,
            "neighbors": neighbors,
        }
