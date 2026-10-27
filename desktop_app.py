"""Desktop Application Launcher for Intelligent Scan-to-BIM.

Starts local FastAPI/Uvicorn server and opens an application-mode native desktop window.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = sys.executable or (ROOT / ".venv" / "Scripts" / "python.exe")
BACKEND_DIR = ROOT / "backend"
URL = "http://127.0.0.1:8000"


def configure_data_directory() -> Path:
    """Resolve the persistent SCAN data root before starting the API process.

    S2B_DATA_DIR takes precedence. Otherwise, an optional data-root.txt under
    %LOCALAPPDATA%\\ScanStudio may contain an absolute local, removable, or
    network path. Existing data is never moved automatically.
    """
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    app_config_dir = local_app_data / "ScanStudio"
    configured = os.environ.get("S2B_DATA_DIR", "").strip()
    if not configured:
        config_file = app_config_dir / "data-root.txt"
        if config_file.is_file():
            try:
                configured = config_file.read_text(encoding="utf-8-sig").strip().strip('"')
            except OSError as exc:
                raise OSError(f"Cannot read SCAN data directory setting at {config_file}: {exc}") from exc

    raw_path = configured or str(app_config_dir / "data")
    raw_path = os.path.expandvars(raw_path).strip()
    data_dir = Path(raw_path).expanduser()
    if not data_dir.is_absolute():
        raise ValueError("SCAN data directory must be an absolute path")
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        if not data_dir.is_dir():
            raise NotADirectoryError(str(data_dir))
        data_dir = data_dir.resolve()
    except OSError as exc:
        raise OSError(f"Cannot create or access SCAN data directory '{data_dir}': {exc}") from exc

    os.environ["S2B_DATA_DIR"] = str(data_dir)
    return data_dir


def browser_profile_dir(browser: str | None = None) -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    browser_name = Path(browser).stem.lower() if browser else "chromium"
    return base / "ScanStudio" / "BrowserProfile" / browser_name


def native_window_command(browser: str, profile_dir: Path | None = None) -> list[str]:
    profile = profile_dir or browser_profile_dir(browser)
    return [
        browser,
        f"--user-data-dir={profile}",
        f"--app={URL}",
        "--window-size=1600,980",
        "--window-position=50,50",
        "--disable-extensions",
        "--disable-plugins",
        "--no-first-run",
    ]


def _has_visible_window(process_id: int) -> bool:
    """Return whether a Windows top-level visible window belongs to this process."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        found = False

        def visit(hwnd, _lparam):
            nonlocal found
            if not user32.IsWindowVisible(hwnd):
                return True
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == process_id:
                found = True
                return False
            return True

        callback = callback_type(visit)
        user32.EnumWindows(callback, 0)
        return found
    except (AttributeError, OSError, TypeError, ValueError):
        # If visibility cannot be queried, preserve the previous process-based behavior.
        return True


def wait_for_native_window(
    process: subprocess.Popen,
    *,
    timeout_seconds: float = 8.0,
    poll_interval_seconds: float = 0.2,
) -> bool:
    """Wait briefly for an actual browser window, not just a surviving Edge process."""
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        if process.poll() is not None:
            return False
        if _has_visible_window(process.pid):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(max(0.01, poll_interval_seconds), remaining))


def is_server_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}/api/v1/health", timeout=1.0) as res:
            return res.status == 200
    except Exception:
        return False


def start_server_process() -> subprocess.Popen | None:
    if is_server_ready():
        print("[Scan-to-BIM] Сервер уже запущен на порту 8000.")
        return None

    print("[Scan-to-BIM] Запуск локального сервера...")
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{BACKEND_DIR};{ROOT}"
    env.setdefault("S2B_INGEST_MODE", "worker")

    cmd = [
        str(PYTHON),
        "-m", "uvicorn",
        "scan2bim.main:app",
        "--host", "127.0.0.1",
        "--port", "8000",
        "--app-dir", str(BACKEND_DIR),
    ]

    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )

    # Wait up to 10 seconds for server to start
    for _ in range(20):
        if is_server_ready():
            print("[Scan-to-BIM] Сервер успешно запущен.")
            return proc
        time.sleep(0.5)

    print("[Scan-to-BIM] Внимание: сервер запускается дольше обычного, продолжаем...")
    return proc


def start_worker_process() -> subprocess.Popen:
    """Start the durable local worker beside the desktop app's owned API."""
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{BACKEND_DIR};{ROOT}"
    env["S2B_INGEST_MODE"] = "worker"
    cmd = [str(PYTHON), "-m", "scan2bim.worker"]
    return subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def launch_native_window() -> subprocess.Popen | None:
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    browser = next((p for p in edge_paths if Path(p).is_file()), None)

    if browser:
        print(f"[Scan-to-BIM] Открытие нативного окна приложения: {browser}")
        profile_dir = browser_profile_dir(browser)
        try:
            profile_dir.mkdir(parents=True, exist_ok=True)
            process = subprocess.Popen(native_window_command(browser, profile_dir))
            if wait_for_native_window(process):
                return process
            print(
                "[Scan-to-BIM] Окно приложения не появилось за отведённое время; "
                "открываем SCAN в стандартном браузере."
            )
            import webbrowser
            webbrowser.open(URL)
            return None
        except OSError as exc:
            print(f"[Scan-to-BIM] Не удалось создать профиль приложения: {exc}")
            print("[Scan-to-BIM] Открытие в стандартном браузере...")
            import webbrowser
            webbrowser.open(URL)
            return None
    else:
        print("[Scan-to-BIM] Открытие в стандартном браузере...")
        import webbrowser
        webbrowser.open(URL)
        return None


def stop_server_process(server_proc: subprocess.Popen | None) -> None:
    if server_proc is None or server_proc.poll() is not None:
        return
    server_proc.terminate()
    try:
        server_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server_proc.kill()
        server_proc.wait()


def main() -> None:
    print("=" * 60)
    print("  Intelligent Scan-to-BIM · Настольное приложение")
    print("=" * 60)
    try:
        data_dir = configure_data_directory()
    except (OSError, ValueError) as exc:
        print(f"[Scan-to-BIM] Не удалось настроить папку данных: {exc}", file=sys.stderr)
        return
    print(f"[Scan-to-BIM] Данные проекта: {data_dir}")
    server_proc = start_server_process()
    worker_proc = None
    worker_mode = os.environ.get("S2B_INGEST_MODE", "worker").strip().lower() == "worker"
    if server_proc is not None and worker_mode:
        try:
            worker_proc = start_worker_process()
            time.sleep(0.5)
            if worker_proc.poll() is not None:
                raise RuntimeError("Headless worker exited during startup")
            print("[Scan-to-BIM] Локальный headless worker запущен.")
        except Exception as exc:
            print(f"[Scan-to-BIM] Не удалось запустить headless worker: {exc}", file=sys.stderr)
            stop_server_process(server_proc)
            return
    window_proc = launch_native_window()
    if window_proc is not None:
        print("[Scan-to-BIM] Приложение работает. Для завершения закройте окно программы.")
        try:
            window_proc.wait()
        finally:
            stop_server_process(worker_proc)
            stop_server_process(server_proc)
    else:
        print("[Scan-to-BIM] Приложение открыто в стандартном браузере.")


if __name__ == "__main__":
    main()
