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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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


def launch_native_window() -> None:
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    browser = next((p for p in edge_paths if Path(p).is_file()), None)

    if browser:
        print(f"[Scan-to-BIM] Открытие нативного окна приложения: {browser}")
        subprocess.Popen([
            browser,
            f"--app={URL}",
            "--window-size=1600,980",
            "--window-position=50,50",
            "--disable-extensions",
            "--disable-plugins",
        ])
    else:
        print("[Scan-to-BIM] Открытие в стандартном браузере...")
        import webbrowser
        webbrowser.open(URL)


def main() -> None:
    print("=" * 60)
    print("  Intelligent Scan-to-BIM · Настольное приложение")
    print("=" * 60)
    server_proc = start_server_process()
    launch_native_window()
    print("[Scan-to-BIM] Приложение работает. Для завершения закройте окно программы.")


if __name__ == "__main__":
    main()
