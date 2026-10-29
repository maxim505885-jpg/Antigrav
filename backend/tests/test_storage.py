from __future__ import annotations

import errno
import json

import pytest

from scan2bim import storage


def test_write_json_atomic_retries_transient_permission_error(tmp_path, monkeypatch):
    target = tmp_path / "meta.json"
    target.write_text('{"state":"old"}', encoding="utf-8")
    real_replace = storage.os.replace
    attempts = 0
    delays: list[float] = []

    def replace_with_transient_denial(source, destination):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError(errno.EACCES, "simulated transient SMB sharing denial")
        real_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", replace_with_transient_denial)
    monkeypatch.setattr(storage.time, "sleep", delays.append)

    storage.write_json_atomic(target, {"state": "ready"})

    assert attempts == 3
    assert delays == [0.05, 0.1]
    assert json.loads(target.read_text(encoding="utf-8")) == {"state": "ready"}
    assert list(tmp_path.iterdir()) == [target]


def test_write_json_atomic_preserves_old_file_after_persistent_permission_error(
    tmp_path, monkeypatch
):
    target = tmp_path / "meta.json"
    target.write_text('{"state":"old"}', encoding="utf-8")
    attempts = 0

    def always_denied(_source, _destination):
        nonlocal attempts
        attempts += 1
        raise PermissionError(errno.EACCES, "simulated persistent SMB denial")

    monkeypatch.setattr(storage.os, "replace", always_denied)
    monkeypatch.setattr(storage.time, "sleep", lambda _delay: None)

    with pytest.raises(PermissionError, match="persistent SMB denial"):
        storage.write_json_atomic(target, {"state": "ready"})

    assert attempts == storage.JSON_REPLACE_MAX_ATTEMPTS
    assert json.loads(target.read_text(encoding="utf-8")) == {"state": "old"}
    assert list(tmp_path.iterdir()) == [target]
