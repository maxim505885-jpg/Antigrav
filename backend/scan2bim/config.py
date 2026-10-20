"""Runtime configuration for Intelligent Scan-to-BIM.

All paths can be overridden with environment variables so the core can later run
as a server without code changes.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("S2B_DATA_DIR", REPO_ROOT / "data")).resolve()
DB_PATH = Path(os.environ.get("S2B_DB_PATH", DATA_DIR / "scan2bim.sqlite3"))
PROJECTS_DIR = DATA_DIR / "projects"
EXPORTS_DIR = DATA_DIR / "exports"
MODELS_DIR = DATA_DIR / "models"

# Viewer preview is decimated to this many points; the full cloud is retained.
MAX_PREVIEW_POINTS = int(os.environ.get("S2B_MAX_PREVIEW_POINTS", "2500000"))
# Safety limit for ingestion. 0 = read every point. Large scans are uniformly
# sampled and the decimation is reported in the cloud metadata.
MAX_INGEST_POINTS = int(os.environ.get("S2B_MAX_INGEST_POINTS", "40000000"))
# Points retained for the 2D section overlay (the geometry is computed on all points).
MAX_SECTION_PREVIEW_POINTS = int(os.environ.get("S2B_MAX_SECTION_POINTS", "150000"))

DEFAULT_SECTION_THICKNESS = 0.05  # metres
DEFAULT_GRID_RES = 0.02          # metres
# Absolute raster ceiling (hard guard for pathological input).
MAX_RASTER_CELLS = 80_000_000
# Interactive section budget. A 145 x 86 m site sliced at 0.02 m needs 24 M cells
# and took 147 s to vectorise, which feels broken in the UI. Sections therefore
# coarsen the grid (and say so) beyond this budget instead of hanging.
MAX_SECTION_RASTER_CELLS = int(
    os.environ.get("S2B_MAX_SECTION_RASTER_CELLS", "6000000")
)
MIN_COMPONENT_AREA = 0.03        # m^2, filters scan noise blobs

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "S2B_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173",
    ).split(",")
    if o.strip()
]

API_KEY = os.environ.get("S2B_API_KEY", "").strip()
API_VERSION = "v1"

# Autodesk ReCap / RCS conversion. RCS is proprietary: we never parse it and
# never claim native support. A converter command may be supplied explicitly.
RECAP_EXE = Path(
    os.environ.get(
        "S2B_RECAP_EXE", r"C:\Program Files\Autodesk\Autodesk ReCap\ReCap.exe"
    )
)
RCS_CONVERTER_CMD = os.environ.get("S2B_RCS_CONVERTER", "").strip()

# External ML inference environment (Pointcept / Open3D-ML). Kept separate from
# the core environment because PyTorch + CUDA are heavy and version-sensitive.
ML_PYTHON = os.environ.get("S2B_ML_PYTHON", "").strip()
ML_MODEL_DIR = os.environ.get("S2B_ML_MODELS", str(MODELS_DIR / "pointcept"))

WEBHOOK_TIMEOUT = 10

for _d in (DATA_DIR, PROJECTS_DIR, EXPORTS_DIR, MODELS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
