from types import SimpleNamespace

from scan2bim.recognition.geometric import format_recognition_summary


def test_summary_reports_observed_classes_and_does_not_claim_missing_classes_absent():
    message = format_recognition_summary([
        SimpleNamespace(class_name="column"),
        SimpleNamespace(class_name="wall"),
        SimpleNamespace(class_name="wall"),
        SimpleNamespace(class_name="slab"),
    ])

    assert "колонны — 1" in message
    assert "стены — 2" in message
    assert "плиты — 1" in message
    assert "отсутствие класса в результате не доказывает его отсутствия в облаке" in message
    assert "балки" not in message
    assert "фермы" not in message


def test_summary_says_when_no_candidates_were_found():
    message = format_recognition_summary([])

    assert "кандидаты не найдены" in message
    assert "Покрытие и исходные точки проверьте вручную" in message
