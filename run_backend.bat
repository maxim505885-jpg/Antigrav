@echo off
cd /d "%~dp0"
set PYTHONPATH=backend
.venv\Scripts\python.exe -m uvicorn scan2bim.api.app:app --host 127.0.0.1 --port 8000
