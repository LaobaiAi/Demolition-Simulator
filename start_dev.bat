@echo off
title XuanwuAI Dev
cd /d "%~dp0"

echo === XuanwuAI Gateway + Frontend ===
echo.

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
start "Frontend" cmd /c "cd /d "%~dp0frontend" && npm run dev"

REM Background Resource Monitor
start /MIN "ResourceMonitor" powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%~dp0_resource_guard.ps1' -mode monitor -checkIntervalSeconds 30"

echo.
echo Gateway:  http://localhost:8000
echo Frontend: http://localhost:3000
echo.
echo Close the terminal windows to stop, or press any key to quit this launcher.
pause >nul