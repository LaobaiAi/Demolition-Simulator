# Fix batch file encoding - rewrite with proper ASCII-only comments
$root = "E:\Claude code workspace\XuanwuAI Demolition Simulator"

$launcher = @'
@echo off
title XuanwuAI Demolition Simulator
cd /d "%~dp0"

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
call :sleep 2
goto gateway_frontend

:unity_only
call :launch_unity
pause
exit /b

:gateway_frontend
echo Starting Gateway Backend...
start "Gateway" cmd /k "cd /d "%~dp0gateway" && "venv\Scripts\python.exe" main.py"

timeout /t 4 /nobreak >nul

echo Starting Frontend...
start "Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

REM Background Resource Monitor
echo Starting background resource monitor (checks every 30s)...
start /MIN "ResourceMonitor" powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%~dp0_resource_guard.ps1' -mode monitor -checkIntervalSeconds 30"
echo.

echo ============================================
echo   Gateway:  http://localhost:8000
echo   Frontend: http://localhost:3000
echo   Monitor:  running in background
echo ============================================
echo.
pause
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

start "XuanwuAI Unity" "%UNITY_EXE%" -projectPath "%~dp0unity_project"
echo Unity Editor launched.
goto :eof

:sleep
ping 127.0.0.1 -n %1 >nul
goto :eof
'@

$startdev = @'
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

echo Starting Gateway...
start "Gateway" cmd /c "cd /d "%~dp0gateway" && "venv\Scripts\python.exe" main.py"

echo Waiting for Gateway (port 8000)...
:wait_gateway
timeout /t 1 /nobreak >nul
curl -s http://localhost:8000/health >nul 2>&1
if errorlevel 1 goto wait_gateway
echo Gateway ready.

echo Starting Frontend...
start "Frontend" cmd /c "cd /d "%~dp0frontend" && npm run dev"

REM Background Resource Monitor
start /MIN "ResourceMonitor" powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%~dp0_resource_guard.ps1' -mode monitor -checkIntervalSeconds 30"

echo.
echo Gateway:  http://localhost:8000
echo Frontend: http://localhost:3000
echo.
echo Close the terminal windows to stop, or press any key to quit this launcher.
pause >nul
'@

$enc = [System.Text.Encoding]::GetEncoding(936)
[System.IO.File]::WriteAllText([System.IO.Path]::Combine($root, "XuanwuAI Launcher.bat"), $launcher, $enc)
Write-Host "Written: XuanwuAI Launcher.bat (GBK)"

[System.IO.File]::WriteAllText([System.IO.Path]::Combine($root, "start_dev.bat"), $startdev, $enc)
Write-Host "Written: start_dev.bat (GBK)"
