@echo off
chcp 65001 >nul
title XuanwuAI Demo Simulator
cd /d "%~dp0"

echo ============================================
echo   XuanwuAI Demolition Simulator
echo ============================================
echo.

REM ---- Detect .workbuddy runtimes ----
set "PYTHON=%USERPROFILE%\.workbuddy\binaries\python\versions\3.14.3\python.exe"
set "NODE_DIR=%USERPROFILE%\.workbuddy\binaries\node\versions\22.22.2"

if exist "%PYTHON%" (echo [OK] Found Python ) else (
    echo [WARN] .workbuddy Python not found, trying system python...
    for %%p in (python python3 py) do (
        where %%p >nul 2>&1 && set "PYTHON=%%p" && goto :found_python
    )
    echo [ERROR] Python not found! Install Python 3.11+ first.
    pause & exit /b 1
    :found_python
)

if exist "%NODE_DIR%\npm.cmd" (echo [OK] Found Node) else (
    echo [ERROR] Node.js not found at %NODE_DIR%
    echo Please install Node.js 22+ or adjust NODE_DIR in this script.
    pause & exit /b 1
)
echo.

echo [CLEANUP] Removing leftovers from previous runs...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_cleanup.ps1"

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

REM ---- Start Gateway ----
echo [1/2] Starting Gateway (port 8000)...
start "Gateway" /MIN cmd /c "cd /d "%~dp0gateway" && "%PYTHON%" main.py"

echo    Waiting for Gateway...
:wait_gw
timeout /t 2 /nobreak >nul
curl.exe -s http://localhost:8000/health >nul 2>&1
if errorlevel 1 goto wait_gw
echo    Gateway READY.
echo.

REM ---- Start Frontend (with memory limit) ----
echo [2/2] Starting Frontend (port 3000)...
set "PATH=%NODE_DIR%;%PATH%"
set "NODE_OPTIONS=--max-old-space-size=2048"
start "Frontend" /MIN cmd /c "set PATH=%NODE_DIR%;^%PATH^% && set NODE_OPTIONS=--max-old-space-size=2048 && cd /d "%~dp0frontend" && npx next dev -p 3000"

echo    Waiting for Frontend to compile...
:wait_fe
timeout /t 3 /nobreak >nul
curl.exe -s -o NUL http://localhost:3000 >nul 2>&1
if errorlevel 1 goto wait_fe
echo    Frontend READY.
echo.

REM ---- Open Browser ----
echo ============================================
echo   Gateway  : http://localhost:8000
echo   Frontend : http://localhost:3000
echo ============================================
echo.
echo Opening browser...
start http://localhost:3000
echo.
echo Press any key to stop all services...
pause >nul

REM ---- Cleanup ----
echo.
echo Stopping services...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_cleanup.ps1"
echo All stopped. Goodbye!
