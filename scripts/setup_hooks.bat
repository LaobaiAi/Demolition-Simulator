@echo off
title Setup Git Hooks
cd /d "%~dp0.."

echo ============================================
echo  XuanwuAI — Install Git Pre-commit Hook
echo ============================================
echo.

REM Configure git to use .githooks/ directory instead of .git/hooks/
git config core.hooksPath .githooks

if %errorlevel% neq 0 (
    echo [ERROR] Failed to configure git hooks path.
    pause
    exit /b 1
)

echo [OK] Git hooks path set to: .githooks/
echo.
echo The pre-commit hook will run automatically on every "git commit":
echo   - Backend: pytest (gateway + relevant caiao_servers)
echo   - Frontend: tsc + ESLint + Vitest
echo.
echo Test it:  git commit -m "test"  (will be blocked if checks fail)
echo Skip it:  git commit --no-verify -m "..."
echo.
pause
