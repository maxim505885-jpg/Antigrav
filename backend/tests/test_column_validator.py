import pytest
from scan2bim.recognition.column_validator import WorkshopColumnValidator


def test_geometry_filter_retains_column_candidate_without_confirming_role():
    validator = WorkshopColumnValidator()
    # Настоящая колонна цеха: 600х500 мм, высота 8.5 м, опирается на 0.000
    col = {
        "class_name": "column",
        "geometry": {
            "center": [12.0, 30.0, 4.25],
            "sizes": {"width": 0.60, "depth": 0.50, "height": 8.50}
        }
    }
    is_candidate, reason = validator.is_column_candidate(
        col, known_x_bays=[0.0, 6.0, 12.0], known_y_spans=[0.0, 30.0],
    )
    assert is_candidate is True
    assert "роль не подтверждена" in reason


def test_validator_rejects_thin_pipe():
    validator = WorkshopColumnValidator()
    # Тонкая труба/стойка: диаметр/ширина 150 мм
    pipe = {
        "class_name": "column",
        "geometry": {
            "center": [12.0, 30.0, 3.0],
            "sizes": {"width": 0.15, "depth": 0.15, "height": 6.0}
        }
    }
    is_candidate, reason = validator.is_column_candidate(pipe)
    assert is_candidate is False
    assert "слишком тонкий" in reason


def test_validator_rejects_short_equipment_post():
    validator = WorkshopColumnValidator()
    # Короткая стойка оборудования высотой 1.8 м
    post = {
        "class_name": "column",
        "geometry": {
            "center": [12.0, 30.0, 0.9],
            "sizes": {"width": 0.40, "depth": 0.40, "height": 1.8}
        }
    }
    is_candidate, reason = validator.is_column_candidate(post)
    assert is_candidate is False
    assert "роль неизвестна" in reason


def test_validator_rejects_out_of_grid_object():
    validator = WorkshopColumnValidator()
    # Элемент стоит посреди пролета (Y=14.5 м при пролетах 0 и 30 м)
    obstruction = {
        "class_name": "column",
        "geometry": {
            "center": [12.0, 14.5, 3.5],
            "sizes": {"width": 0.50, "depth": 0.50, "height": 7.0}
        }
    }
    is_candidate, reason = validator.is_column_candidate(
        obstruction,
        known_x_bays=[0.0, 6.0, 12.0],
        known_y_spans=[0.0, 30.0]
    )
    assert is_candidate is False
    assert "далеко от переданной сетки" in reason


def test_legacy_validator_method_remains_a_candidate_heuristic():
    candidate = {
        "class_name": "column",
        "geometry": {
            "center": [12.0, 30.0, 4.25],
            "sizes": {"width": 0.60, "depth": 0.50, "height": 8.50},
        },
    }

    retained, reason = WorkshopColumnValidator().is_true_column(candidate)

    assert retained is True
    assert "роль не подтверждена" in reason
