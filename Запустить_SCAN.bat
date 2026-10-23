@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Не найден локальный Python runtime: .venv\Scripts\python.exe
  echo Переустановите SCAN или обратитесь к администратору.
  pause
  exit /b 1
)
if not exist "python313\python.exe" (
  echo Не найден встроенный Python runtime.
  echo Переустановите SCAN или обратитесь к администратору.
  pause
  exit /b 1
)
if not exist "frontend\dist\index.html" (
  echo Не найдена production-сборка интерфейса frontend\dist.
  echo Пакет SCAN установлен неполностью.
  pause
  exit /b 1
)

if not defined LOCALAPPDATA set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "S2B_DATA_DIR=%LOCALAPPDATA%\ScanStudio\data"
if not exist "%S2B_DATA_DIR%" mkdir "%S2B_DATA_DIR%"
set "PYTHONPATH=%~dp0backend;%~dp0"
".venv\Scripts\python.exe" desktop_app.py
exit /b %ERRORLEVEL%
