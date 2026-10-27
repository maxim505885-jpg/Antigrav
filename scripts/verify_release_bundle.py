"""Preflight local SCAN Windows bundle inputs before compiling the Inno Setup."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
local_app_data = Path(
    os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
)
python_base = local_app_data / "Programs" / "Python" / "Python313"
required = [
    ROOT / "Запустить_SCAN.bat",
    ROOT / "desktop_app.py",
    ROOT / "backend" / "scan2bim" / "api" / "app.py",
    ROOT / "contracts" / "scan2bim.bim-1.0.schema.json",
    ROOT / "contracts" / "structural-model.schema.json",
    ROOT / ".venv" / "Scripts" / "python.exe",
    ROOT / ".venv" / "pyvenv.cfg",
    python_base / "python.exe",
    python_base / "python3.dll",
    python_base / "python313.dll",
    python_base / "Lib" / "os.py",
    ROOT / "frontend" / "dist" / "index.html",
    ROOT / "frontend" / "dist" / "templates" / "registration-controls-template.csv",
    ROOT / "installer" / "scan_studio_setup.iss",
    ROOT / "scripts" / "smoke_installed_bundle.ps1",
]
missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
if missing:
    print("Missing release inputs:", *missing, sep="\n- ", file=sys.stderr)
    raise SystemExit(1)

html = (ROOT / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")
control_template = (
    ROOT / "frontend" / "dist" / "templates" / "registration-controls-template.csv"
).read_text(encoding="utf-8-sig").splitlines()
expected_control_headers = "label,source_x,source_y,source_z,target_x,target_y,target_z"
if not control_template or control_template[0] != expected_control_headers:
    print("Invalid registration-control CSV template", file=sys.stderr)
    raise SystemExit(1)
assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
missing_assets = [asset for asset in assets if not (ROOT / "frontend" / "dist" / asset.lstrip("/")).is_file()]
if not assets or missing_assets:
    print(f"Invalid frontend build assets: {missing_assets or 'none referenced'}", file=sys.stderr)
    raise SystemExit(1)

installer = (ROOT / "installer" / "scan_studio_setup.iss").read_text(encoding="utf-8")
launcher = (ROOT / "Запустить_SCAN.bat").read_text(encoding="utf-8")
for stale in ("..\\Запустить_ScanToBIM.bat", "..\\intelligent-scan-to-bim\\*"):
    if stale in installer:
        print(f"Stale installer source path: {stale}", file=sys.stderr)
        raise SystemExit(1)
if "..\\data\\" in installer or "..\\data\\*" in installer:
    print("The installer must not bundle scan/project data", file=sys.stderr)
    raise SystemExit(1)
if '..\\backend\\*"' in installer or '..\\backend\\tests' in installer:
    print("The installer must include only the backend application package, not the whole development tree", file=sys.stderr)
    raise SystemExit(1)
if '..\\backend\\scan2bim\\*"' not in installer:
    print("The installer does not include the backend application package", file=sys.stderr)
    raise SystemExit(1)
if "..\\contracts\\*.json" not in installer:
    print("The installer does not include runtime model schemas", file=sys.stderr)
    raise SystemExit(1)
if "PrivilegesRequired=lowest" not in installer:
    print("The installer should install into the current user's profile without elevation", file=sys.stderr)
    raise SystemExit(1)
if "PYTHONDONTWRITEBYTECODE=1" not in launcher:
    print("The launcher should keep generated Python bytecode out of the installed application", file=sys.stderr)
    raise SystemExit(1)
if 'Excludes: "__pycache__\\*,*.pyc,*.pyo"' not in installer:
    print("The installer must use comma-separated cache exclusion patterns", file=sys.stderr)
    raise SystemExit(1)
if ";*.pyc" in installer or ";*.pyo" in installer:
    print("The installer has malformed semicolon-separated exclusion patterns", file=sys.stderr)
    raise SystemExit(1)
venv_cfg = (ROOT / ".venv" / "pyvenv.cfg").read_text(encoding="utf-8")
expected_python_config = (
    f"home = {python_base}",
    f"executable = {python_base / 'python.exe'}",
)
if any(line not in venv_cfg.splitlines() for line in expected_python_config) or "command = " not in venv_cfg:
    print("The source virtual environment configuration does not match the packaged Python base", file=sys.stderr)
    raise SystemExit(1)
if '#define PythonBase GetEnv("LOCALAPPDATA") + "\\Programs\\Python\\Python313"' not in installer:
    print("Installer does not bundle the base Python runtime", file=sys.stderr)
    raise SystemExit(1)

python_base_entry = next(
    (line for line in installer.splitlines() if 'Source: "{#PythonBase}\\*"' in line),
    "",
)
if "Lib\\site-packages\\*" not in python_base_entry:
    print("The base Python venv site-packages must not be duplicated in the installed runtime", file=sys.stderr)
    raise SystemExit(1)
venv_entry = next(
    (line for line in installer.splitlines() if 'Source: "..\\.venv\\*"' in line),
    "",
)
if "Lib\\site-packages\\jedi\\third_party\\typeshed\\*" not in venv_entry:
    print("Jedi's bundled typeshed database is not needed by the installed runtime", file=sys.stderr)
    raise SystemExit(1)
if "Lib\\test\\*" not in python_base_entry:
    print("The Python standard-library test suite must not be bundled", file=sys.stderr)
    raise SystemExit(1)
if "include-system-site-packages = false" not in venv_cfg:
    print("The source virtual environment unexpectedly depends on system site-packages", file=sys.stderr)
    raise SystemExit(1)

print(f"Release bundle inputs OK; {len(assets)} frontend assets referenced.")
