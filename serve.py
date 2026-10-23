import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(backend_dir))

import uvicorn
from scan2bim.api.app import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
