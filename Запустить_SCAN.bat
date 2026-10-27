@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  if not exist "python313\python.exe" (
    echo Не найден локальный Python runtime: .venv\Scripts\python.exe или python313\python.exe
    echo Переустановите SCAN или обратитесь к администратору.
    pause
    exit /b 1
  )
)
if exist "frontend\dist\index.html" (
  set "SERVE_FRONTEND=1"
)

if not defined LOCALAPPDATA set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONPATH=%~dp0backend;%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" desktop_app.py
) else (
  "python313\python.exe" desktop_app.py
)
exit /b %ERRORLEVEL%
