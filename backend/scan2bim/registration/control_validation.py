"""Independent control-point evaluation for a proposed station transform."""
from __future__ import annotations

import numpy as np


def evaluate_control_points(
    matrix_4x4: list[list[float]],
    source_points: list[list[float]],
    target_points: list[list[float]],
    *,
    acceptance_rmse_mm: float = 10.0,
) -> dict[str, object]:
    """Measure a transform against a separately supplied control-point set.

    The caller is responsible for keeping controls out of the fitting set; the
    API records an explicit independence attestation and never infers it.
    """
    matrix = np.asarray(matrix_4x4, dtype=np.float64)
    source = np.asarray(source_points, dtype=np.float64)
    target = np.asarray(target_points, dtype=np.float64)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError("Преобразование должно быть конечной матрицей 4×4")
    if not np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0], atol=1e-8):
        raise ValueError("Последняя строка матрицы должна быть [0, 0, 0, 1]")
    rotation = matrix[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6) or not np.isclose(
        np.linalg.det(rotation), 1.0, atol=1e-6
    ):
        raise ValueError("Матрица должна содержать правильное жёсткое вращение без масштаба и отражения")
    if source.ndim != 2 or source.shape[1:] != (3,) or target.shape != source.shape:
        raise ValueError("Нужны одинаковые списки трёхмерных контрольных координат")
    if len(source) < 3:
        raise ValueError("Для независимой оценки укажите не менее трёх контрольных точек")
    if not np.isfinite(source).all() or not np.isfinite(target).all():
        raise ValueError("Координаты контрольных точек должны быть конечными числами")
    if len(np.unique(source, axis=0)) != len(source):
        raise ValueError("Исходные контрольные точки должны быть уникальными")
    if len(np.unique(target, axis=0)) != len(target):
        raise ValueError("Целевые контрольные точки должны быть уникальными")

    # Three points on one line cannot independently constrain rotation around
    # that line.  Reject nearly-collinear control layouts rather than reporting
    # a deceptively strong accuracy result from an under-constrained sample.
    for points, label in ((source, "исходные"), (target, "целевые")):
        singular_values = np.linalg.svd(points - points.mean(axis=0), compute_uv=False)
        if singular_values[0] == 0 or singular_values[1] <= max(
            singular_values[0] * 1e-8, np.finfo(np.float64).eps
        ):
            raise ValueError(
                f"{label.capitalize()} контрольные точки почти коллинеарны; "
                "расположите их минимум в двух независимых направлениях"
            )
    if not np.isfinite(acceptance_rmse_mm) or acceptance_rmse_mm <= 0:
        raise ValueError("Допуск RMSE должен быть положительным конечным числом")

    transformed = (matrix[:3, :3] @ source.T).T + matrix[:3, 3]
    residuals_mm = np.linalg.norm(transformed - target, axis=1) * 1000.0
    rmse_mm = float(np.sqrt(np.mean(np.square(residuals_mm))))
    return {
        "status": "controls_evaluated",
        "accuracy_status": "independent_controls_measured",
        "independent_control_count": int(len(source)),
        "independence_attested_by_user": True,
        "fit_residuals_are_independent": True,
        "acceptance_rmse_mm": float(acceptance_rmse_mm),
        "rmse_mm": rmse_mm,
        "max_error_mm": float(np.max(residuals_mm)),
        "p95_error_mm": float(np.percentile(residuals_mm, 95)),
        "criterion_passed": rmse_mm < acceptance_rmse_mm,
        "residuals_mm": [float(value) for value in residuals_mm],
    }
