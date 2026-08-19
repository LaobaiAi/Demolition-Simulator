@echo off
title XuanwuAI Demolition Simulator
cd /d "%~dp0"

echo [CLEANUP] Removing leftovers from previous runs...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_cleanup.ps1"

setlocal enabledelayedexpansion

echo ============================================
echo   XuanwuAI Demolition Simulator
echo ============================================
echo.

REM Resource Pre-check
echo [CHECK] Checking system resources before launch...
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%~dp0_resource_guard.ps1' -mode precheck"
set GUARD_EXIT=%errorlevel%

if %GUARD_EXIT% == 2 (
    echo.
    echo [ABORT] User cancelled. Exiting.
    pause
    exit /b
)
if %GUARD_EXIT% == 1 (
    echo.
    echo [PAUSE] Resources critical, skipping launch.
    echo         Close some applications and try again.
    pause
    exit /b
)

echo [OK] Resources OK - proceeding with launch.
echo.

echo [1] Start Gateway + Frontend
echo [2] Start Gateway + Frontend + Unity
echo [3] Start Unity only
echo [4] Exit
echo.
choice /c 1234 /n /m "Select (1-4): "
if errorlevel 4 exit /b
if errorlevel 3 goto unity_only
if errorlevel 2 goto all
if errorlevel 1 goto gateway_frontend

:all
call :launch_unity
call :sleep 5
goto gateway_frontend

:unity_only
call :launch_unity
pause
echo Stopping services...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_cleanup.ps1"
exit /b

:gateway_frontend
echo Starting Gateway Backend (with watchdog, minimized)...
start "Gateway-Watchdog" /MIN cmd /k "cd /d "%~dp0gateway" && "venv\Scripts\python.exe" watchdog.py"

echo Waiting for Gateway to initialize...
timeout /t 8 /nobreak >nul

echo Starting Frontend (minimized)...
start "Frontend" /MIN cmd /k "cd /d "%~dp0frontend" && npm run dev"

REM Wait before resource monitor
timeout /t 15 /nobreak >nul

REM Background Resource Monitor
echo Starting background resource monitor (checks every 60s)...
start /MIN "ResourceMonitor" powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%~dp0_resource_guard.ps1' -mode monitor -checkIntervalSeconds 60"
echo.

echo ============================================
echo   Gateway:  http://localhost:8000
echo   Frontend: http://localhost:3000
echo   Monitor:  running in background
echo ============================================
echo.
echo [TIP] All windows launched minimized to reduce system load.
echo.
pause
echo Stopping services...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_cleanup.ps1"
exit /b

:launch_unity
echo Looking for Unity Editor...
set UNITY_EXE=

for /d %%d in ("C:\Program Files\Unity\Hub\Editor\*") do (
    if exist "%%d\Editor\Unity.exe" (
        set UNITY_EXE=%%d\Editor\Unity.exe
        goto found_unity
    )
)

for /d %%d in ("C:\Program Files\Unity\*") do (
    if exist "%%d\Editor\Unity.exe" (
        set UNITY_EXE=%%d\Editor\Unity.exe
        goto found_unity
    )
)

echo Unity Editor not found.
goto :eof

:found_unity
echo Unity found: %UNITY_EXE%
echo Launching Unity project...

if not exist "unity_project\Temp" mkdir "unity_project\Temp"
echo 1 > "unity_project\Temp\auto_play.flag"

start "XuanwuAI Unity" /MIN "%UNITY_EXE%" -projectPath "%~dp0unity_project"
echo Unity Editor launched (minimized).
goto :eof

:sleep
ping 127.0.0.1 -n %1 >nul
goto :eof
