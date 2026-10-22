import os
import sys
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")
BACKEND = ROOT / "backend"

env = os.environ.copy()
env["PYTHONPATH"] = str(BACKEND)

cmd = [
    str(PYTHON),
    "-m", "uvicorn",
    "scan2bim.main:app",
    "--host", "127.0.0.1",
    "--port", "8000",
    "--app-dir", str(BACKEND)
]

print("Starting server process with Python:", PYTHON)
proc = subprocess.Popen(
    cmd,
    cwd=str(ROOT),
    env=env,
)

print(f"Server launched with PID {proc.pid}")
time.sleep(3)
