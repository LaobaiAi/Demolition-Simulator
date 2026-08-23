@echo off
title XuanwuAI Demolition Simulator
cd /d "%~dp0"

echo ============================================
echo   XuanwuAI Demolition Simulator
echo ============================================
echo.
echo [1] Start Gateway + Frontend
echo [2] Start Gateway + Frontend + Unity
echo [3] Exit
echo.
choice /c 123 /n /m "Select (1-3): "
if errorlevel 3 exit /b
if errorlevel 2 goto with_unity
if errorlevel 1 goto standard

:with_unity
echo Launching with Unity 3D...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_services.ps1" -Unity
goto done

:standard
echo Launching Gateway + Frontend...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_services.ps1"
goto done

:done
echo.
echo ============================================
echo   Gateway:  http://localhost:8000
echo   Frontend: http://localhost:3000
echo ============================================
echo.
echo To stop all services later, run:  _cleanup.ps1
pause
exit /b
