import desktop_app
import pytest


def test_native_window_uses_dedicated_scan_profile(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    command = desktop_app.native_window_command(
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    )

    assert command[0].endswith("msedge.exe")
    assert f"--user-data-dir={tmp_path / 'ScanStudio' / 'BrowserProfile' / 'msedge'}" in command
    assert "--app=http://127.0.0.1:8000" in command
    assert "--no-first-run" in command


def test_native_window_uses_separate_profiles_for_edge_and_chrome(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    edge = desktop_app.browser_profile_dir(
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    )
    chrome = desktop_app.browser_profile_dir(
        r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    )

    assert edge == tmp_path / "ScanStudio" / "BrowserProfile" / "msedge"
    assert chrome == tmp_path / "ScanStudio" / "BrowserProfile" / "chrome"


def test_wait_for_native_window_checks_visibility_instead_of_process_liveness(monkeypatch):
    class FakeProcess:
        pid = 123

        def poll(self):
            return None

    monkeypatch.setattr(desktop_app, "_has_visible_window", lambda process_id: process_id == 123)

    assert desktop_app.wait_for_native_window(FakeProcess(), timeout_seconds=0)


def test_native_window_falls_back_when_browser_stays_alive_without_a_window(
    monkeypatch, tmp_path
):
    import webbrowser

    opened = []

    class FakeProcess:
        pass

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(desktop_app.Path, "is_file", lambda path: "msedge.exe" in str(path))
    monkeypatch.setattr(desktop_app.subprocess, "Popen", lambda _command: FakeProcess())
    monkeypatch.setattr(desktop_app, "wait_for_native_window", lambda _process: False)
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)

    assert desktop_app.launch_native_window() is None
    assert opened == [desktop_app.URL]


def test_configure_data_directory_uses_default_and_persists_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("S2B_DATA_DIR", raising=False)

    data_dir = desktop_app.configure_data_directory()

    assert data_dir == tmp_path / "ScanStudio" / "data"
    assert data_dir.is_dir()
    assert desktop_app.os.environ["S2B_DATA_DIR"] == str(data_dir)


def test_configure_data_directory_reads_custom_root_file(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("S2B_DATA_DIR", raising=False)
    app_config = tmp_path / "ScanStudio"
    app_config.mkdir()
    custom_root = tmp_path / "large-drive" / "SCAN Data"
    (app_config / "data-root.txt").write_text(str(custom_root), encoding="utf-8")

    data_dir = desktop_app.configure_data_directory()

    assert data_dir == custom_root
    assert data_dir.is_dir()
    assert desktop_app.os.environ["S2B_DATA_DIR"] == str(data_dir)


def test_configure_data_directory_environment_overrides_config_file(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app_config = tmp_path / "ScanStudio"
    app_config.mkdir()
    (app_config / "data-root.txt").write_text(str(tmp_path / "from-file"), encoding="utf-8")
    env_root = tmp_path / "from-environment"
    monkeypatch.setenv("S2B_DATA_DIR", str(env_root))

    data_dir = desktop_app.configure_data_directory()

    assert data_dir == env_root
    assert data_dir.is_dir()
    assert not (tmp_path / "from-file").exists()


def test_configure_data_directory_reports_invalid_target(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    invalid_root = tmp_path / "a-file"
    invalid_root.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("S2B_DATA_DIR", str(invalid_root))

    try:
        desktop_app.configure_data_directory()
    except OSError as exc:
        assert "SCAN data directory" in str(exc)
    else:
        raise AssertionError("A file cannot be used as the SCAN data directory")


def test_main_defaults_to_owned_worker_and_stops_both_processes(monkeypatch):
    events = []

    class FakeProcess:
        def __init__(self, name):
            self.name = name
            self.running = True

        def wait(self, timeout=None):
            events.append((self.name, "wait", timeout))
            self.running = False
            return 0

        def poll(self):
            return None if self.running else 0

        def terminate(self):
            events.append((self.name, "terminate", None))
            self.running = False

    server = FakeProcess("server")
    worker = FakeProcess("worker")
    window = FakeProcess("window")
    monkeypatch.delenv("S2B_INGEST_MODE", raising=False)
    monkeypatch.setattr(desktop_app, "configure_data_directory", lambda: None)
    monkeypatch.setattr(desktop_app, "start_server_process", lambda: server)
    monkeypatch.setattr(desktop_app, "start_worker_process", lambda: worker)
    monkeypatch.setattr(desktop_app.time, "sleep", lambda _: None)
    monkeypatch.setattr(desktop_app, "launch_native_window", lambda: window)

    desktop_app.main()

    assert events == [
        ("window", "wait", None),
        ("worker", "terminate", None),
        ("worker", "wait", 5),
        ("server", "terminate", None),
        ("server", "wait", 5),
    ]


def test_desktop_starts_and_stops_worker_for_owned_worker_mode(monkeypatch):
    events = []

    class FakeProcess:
        def __init__(self, name):
            self.name = name
            self.running = True

        def wait(self, timeout=None):
            events.append((self.name, "wait", timeout))
            self.running = False
            return 0

        def poll(self):
            return None if self.running else 0

        def terminate(self):
            events.append((self.name, "terminate", None))
            self.running = False

    server = FakeProcess("server")
    worker = FakeProcess("worker")
    window = FakeProcess("window")
    monkeypatch.setenv("S2B_INGEST_MODE", "worker")
    monkeypatch.setattr(desktop_app, "configure_data_directory", lambda: None)
    monkeypatch.setattr(desktop_app, "start_server_process", lambda: server)
    monkeypatch.setattr(desktop_app, "start_worker_process", lambda: worker)
    monkeypatch.setattr(desktop_app.time, "sleep", lambda _: None)
    monkeypatch.setattr(desktop_app, "launch_native_window", lambda: window)

    desktop_app.main()

    assert events == [
        ("window", "wait", None),
        ("worker", "terminate", None),
        ("worker", "wait", 5),
        ("server", "terminate", None),
        ("server", "wait", 5),
    ]


def test_desktop_does_not_start_worker_for_existing_api(monkeypatch):
    events = []
    monkeypatch.setenv("S2B_INGEST_MODE", "worker")
    monkeypatch.setattr(desktop_app, "configure_data_directory", lambda: None)
    monkeypatch.setattr(desktop_app, "start_server_process", lambda: None)
    monkeypatch.setattr(desktop_app, "start_worker_process", lambda: events.append("worker"))
    monkeypatch.setattr(desktop_app, "launch_native_window", lambda: None)

    desktop_app.main()

    assert events == []


def test_desktop_local_mode_remains_an_explicit_override(monkeypatch):
    events = []

    class FakeProcess:
        def wait(self, timeout=None):
            events.append(("server", "wait", timeout))
            return 0

        def poll(self):
            return None

        def terminate(self):
            events.append(("server", "terminate", None))

    monkeypatch.setenv("S2B_INGEST_MODE", "local")
    monkeypatch.setattr(desktop_app, "configure_data_directory", lambda: None)
    monkeypatch.setattr(desktop_app, "start_server_process", lambda: FakeProcess())
    monkeypatch.setattr(desktop_app, "start_worker_process", lambda: events.append("worker"))
    monkeypatch.setattr(desktop_app, "launch_native_window", lambda: FakeProcess())

    desktop_app.main()

    assert events == [("server", "wait", None), ("server", "terminate", None), ("server", "wait", 5)]


@pytest.mark.parametrize(("configured_mode", "expected_mode"), [(None, "worker"), ("local", "local")])
def test_owned_server_inherits_default_or_explicit_job_mode(monkeypatch, configured_mode, expected_mode):
    captured = {}
    readiness = iter([False, True])

    class FakeProcess:
        pass

    if configured_mode is None:
        monkeypatch.delenv("S2B_INGEST_MODE", raising=False)
    else:
        monkeypatch.setenv("S2B_INGEST_MODE", configured_mode)
    monkeypatch.setattr(desktop_app, "is_server_ready", lambda: next(readiness))
    monkeypatch.setattr(desktop_app.time, "sleep", lambda _: None)

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(desktop_app.subprocess, "Popen", fake_popen)

    assert isinstance(desktop_app.start_server_process(), FakeProcess)
    assert captured["env"]["S2B_INGEST_MODE"] == expected_mode


def test_worker_process_inherits_resolved_data_root_and_mode(monkeypatch):
    captured = {}

    class FakeProcess:
        pass

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setenv("S2B_DATA_DIR", r"D:\SCAN\Data")
    monkeypatch.setattr(desktop_app.subprocess, "Popen", fake_popen)

    process = desktop_app.start_worker_process()

    assert isinstance(process, FakeProcess)
    assert captured["command"] == [str(desktop_app.PYTHON), "-m", "scan2bim.worker"]
    assert captured["env"]["S2B_DATA_DIR"] == r"D:\SCAN\Data"
    assert captured["env"]["S2B_INGEST_MODE"] == "worker"
    assert captured["env"]["PYTHONPATH"] == f"{desktop_app.BACKEND_DIR};{desktop_app.ROOT}"
