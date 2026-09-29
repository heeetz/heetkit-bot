@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Project virtual environment was not found.
    echo Expected: .venv\Scripts\python.exe
    echo Create the virtual environment and install the project dependencies first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m app.main %*
exit /b %errorlevel%
