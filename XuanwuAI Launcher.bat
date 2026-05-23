@echo off
title XuanwuAI Demolition Simulator
cd /d "%~dp0"

echo ============================================
echo   XuanwuAI Demolition Simulator
echo ============================================
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

echo.
echo Gateway:  http://localhost:8000
echo Frontend: http://localhost:3000
echo.
echo Close the terminal windows to stop.
pause
exit /b

:launch_unity
echo Looking for Unity Editor...
set UNITY_EXE=

REM Check Unity Hub (most common for 2021.3 LTS)
for /d %%d in ("C:\Program Files\Unity\Hub\Editor\*") do (
    if exist "%%d\Editor\Unity.exe" (
        set UNITY_EXE=%%d\Editor\Unity.exe
        goto found_unity
    )
)

REM Check standalone install
for /d %%d in ("C:\Program Files\Unity\*") do (
    if exist "%%d\Editor\Unity.exe" (
        set UNITY_EXE=%%d\Editor\Unity.exe
        goto found_unity
    )
)

echo Unity Editor not found. Install Unity 2021.3 LTS or set UNITY_PATH.
goto :eof

:found_unity
echo Unity found: %UNITY_EXE%
echo Launching Unity project...

REM Create auto-play flag
if not exist "unity_project\Temp" mkdir "unity_project\Temp"
echo 1 > "unity_project\Temp\auto_play.flag"

start "XuanwuAI Unity" "%UNITY_EXE%" -projectPath "%~dp0unity_project"
echo Unity Editor launched. Scene will auto-setup and enter Play mode.
goto :eof

:sleep
ping 127.0.0.1 -n %1 >nul
goto :eof
