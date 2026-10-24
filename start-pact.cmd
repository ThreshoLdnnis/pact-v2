@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\bootstrap.py
) else if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
  "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\bootstrap.py
) else (
  py -3.12 scripts\bootstrap.py
)
if errorlevel 1 (
  echo Setup failed. See README.md for manual installation.
  pause
  exit /b 1
)
:run
echo PACT Sandbox: http://127.0.0.1:8000
echo Demo PIN: 246810 unless PACT_DEMO_PIN was changed.
echo Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m uvicorn pact.app:create_app --factory --host 127.0.0.1 --port 8000
pause
