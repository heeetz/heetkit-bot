@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Project virtual environment was not found.
    echo Expected: .venv\Scripts\python.exe
    echo Create the virtual environment and install the project dependencies first.
    pause
    exit /b 1
)

where npm.cmd >nul 2>nul
if errorlevel 1 (
    echo ERROR: npm was not found. Install Node.js to build the current frontend.
    pause
    exit /b 1
)

echo Building the frontend from the current source...
call npm.cmd --prefix "%~dp0frontend" run build
if errorlevel 1 (
    echo ERROR: Frontend build failed. HeetKit was not started.
    echo If dependencies are missing, run npm ci in the frontend folder first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m app.main %*
set "HEETKIT_EXIT_CODE=%errorlevel%"
if not "%HEETKIT_EXIT_CODE%"=="0" (
    echo ERROR: HeetKit stopped with exit code %HEETKIT_EXIT_CODE%. Review the startup error above.
    pause
)
exit /b %HEETKIT_EXIT_CODE%
