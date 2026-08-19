@echo off
title XuanwuAI Dev
cd /d "%~dp0"

echo [CLEANUP] Removing leftovers from previous runs...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_cleanup.ps1"

echo === XuanwuAI Gateway + Frontend ===
echo.

REM Auto-setup Git pre-commit hook (runs pytest/tsc/eslint on git commit)
for /f "usebackq delims=" %%p in (`git config core.hooksPath 2^>nul`) do set "HOOKS_PATH=%%p"
if not "%HOOKS_PATH%"==".githooks" (
    echo [SETUP] Activating pre-commit hook...
    git config core.hooksPath .githooks
    echo [OK] Pre-commit hook ready.
    echo.
)

REM Resource Pre-check
echo [CHECK] Checking system resources...
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%~dp0_resource_guard.ps1' -mode precheck"
if %errorlevel% == 2 (
    echo [ABORT] Cancelled.
    pause
    exit /b
)
if %errorlevel% == 1 (
    echo [PAUSE] Resources critical. Close some applications and try again.
    pause
    exit /b
)
echo [OK] Proceeding with launch.
echo.

echo Starting Gateway (with watchdog)...
start "Gateway-Watchdog" cmd /c "cd /d "%~dp0gateway" && "venv\Scripts\python.exe" watchdog.py"

echo Waiting for Gateway (port 8000)...
:wait_gateway
timeout /t 1 /nobreak >nul
curl -s http://localhost:8000/health >nul 2>&1
if errorlevel 1 goto wait_gateway
echo Gateway ready.

REM ---- Auto-detect Node.js ----
set "NODE_DIR=%USERPROFILE%\.workbuddy\binaries\node\versions\22.22.2"
if not exist "%NODE_DIR%\npm.cmd" (
    for %%n in (npm) do (
        where %%n >nul 2>&1 && goto :have_npm
    )
    echo [ERROR] Node.js / npm not found.
    pause
    exit /b 1
)
:have_npm
if exist "%NODE_DIR%\npm.cmd" set "PATH=%NODE_DIR%;%PATH%"

echo Starting Frontend...
if not exist "%~dp0frontend\node_modules\next" (
    echo [INSTALL] Installing frontend dependencies...
    call npm install --prefix "%~dp0frontend"
    if %errorlevel% neq 0 (
        echo [ERROR] Frontend npm install failed.
        pause
        exit /b
    )
)
set "NODE_OPTIONS=--max-old-space-size=2048"
start "Frontend" /MIN cmd /c "set PATH=%NODE_DIR%;%%PATH%% && set NODE_OPTIONS=--max-old-space-size=2048 && cd /d "%~dp0frontend" && npx next dev -p 3000"

REM Background Resource Monitor
start /MIN "ResourceMonitor" powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%~dp0_resource_guard.ps1' -mode monitor -checkIntervalSeconds 30"

echo.
echo Gateway:  http://localhost:8000
echo Frontend: http://localhost:3000
echo.
echo Close the terminal windows to stop, or press any key to quit this launcher.
pause >nul

echo Stopping services...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_cleanup.ps1"
echo All stopped. Goodbye!