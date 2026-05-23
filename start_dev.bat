@echo off
title XuanwuAI Dev
cd /d "%~dp0"

echo === XuanwuAI Gateway + Frontend ===
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

echo.
echo Gateway:  http://localhost:8000
echo Frontend: http://localhost:3000
echo.
echo Close the terminal windows to stop, or press any key to quit this launcher.
pause >nul
