import numpy as np

from scan2bim.ingest import _preview_indices


def test_preview_sampling_is_deterministic_unique_and_stratified():
    count, target = 100_003, 97

    first = _preview_indices(count, target)
    second = _preview_indices(count, target)

    assert first is not None
    assert np.array_equal(first, second)
    assert len(first) == target
    assert np.all(first >= 0)
    assert np.all(first < count)
    assert np.all(np.diff(first) > 0)

    starts = (np.arange(target, dtype=np.int64) * count) // target
    ends = ((np.arange(1, target + 1, dtype=np.int64)) * count) // target
    assert np.all(first >= starts)
    assert np.all(first < ends)


def test_preview_sampling_keeps_existing_no_sampling_cases():
    assert _preview_indices(5, 5) is None
    assert _preview_indices(5, 6) is None
    assert _preview_indices(5, 0) is None
