"""Preflight local SCAN Windows bundle inputs before compiling the Inno Setup."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
required = [
    ROOT / "Запустить_SCAN.bat",
    ROOT / "desktop_app.py",
    ROOT / "backend" / "scan2bim" / "api" / "app.py",
    ROOT / ".venv" / "Scripts" / "python.exe",
    ROOT / ".venv" / "pyvenv.cfg",
    Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python313" / "python.exe",
    ROOT / "frontend" / "dist" / "index.html",
    ROOT / "installer" / "scan_studio_setup.iss",
]
missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
if missing:
    print("Missing release inputs:", *missing, sep="\n- ", file=sys.stderr)
    raise SystemExit(1)

html = (ROOT / "frontend" / "dist" / "index.html").read_text(encoding="utf-8")
assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html)
missing_assets = [asset for asset in assets if not (ROOT / "frontend" / "dist" / asset.lstrip("/")).is_file()]
if not assets or missing_assets:
    print(f"Invalid frontend build assets: {missing_assets or 'none referenced'}", file=sys.stderr)
    raise SystemExit(1)

installer = (ROOT / "installer" / "scan_studio_setup.iss").read_text(encoding="utf-8")
for stale in ("..\\Запустить_ScanToBIM.bat", "..\\intelligent-scan-to-bim\\*"):
    if stale in installer:
        print(f"Stale installer source path: {stale}", file=sys.stderr)
        raise SystemExit(1)
if "..\\data\\" in installer or "..\\data\\*" in installer:
    print("The installer must not bundle scan/project data", file=sys.stderr)
    raise SystemExit(1)
if '..\\Programs\\Python\\' not in installer:
    print("Installer does not bundle the base Python runtime", file=sys.stderr)
    raise SystemExit(1)

print(f"Release bundle inputs OK; {len(assets)} frontend assets referenced.")
