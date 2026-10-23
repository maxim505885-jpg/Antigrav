"""Training holdout must keep revisions of one physical element together."""

from scan2bim.learning.training import _split_samples_by_element


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
