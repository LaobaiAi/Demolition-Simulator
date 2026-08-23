# start_services.ps1 - Unified launcher for Gateway (venv + watchdog) and Frontend (Next.js)
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_services.ps1           # Gateway + Frontend
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_services.ps1 -Unity    # + Unity 3D
# This script is safe to run from any shell; no interactive prompts.

param([switch]$Unity)

$ErrorActionPreference = 'Continue'

$root   = Split-Path -Parent $PSScriptRoot
$gwDir  = Join-Path $root 'gateway'
$feDir  = Join-Path $root 'frontend'
$gwPy   = Join-Path $gwDir 'venv\Scripts\python.exe'
$nodeDir = Join-Path $env:USERPROFILE '.workbuddy\binaries\node\versions\22.22.2'
$npm     = Join-Path $nodeDir 'npm.cmd'

if (-not (Test-Path $gwPy)) { Write-Error "venv python not found: $gwPy"; exit 1 }
if (-not (Test-Path $npm))  { Write-Error "npm not found: $npm"; exit 1 }

# --- Clean up leftover processes from previous runs ---
Write-Host '[*] Cleaning up leftover processes...'
& (Join-Path $root '_cleanup.ps1') -Quiet

# --- Clean stale run logs ---
Remove-Item (Join-Path $gwDir 'gw_run_out.log'), (Join-Path $gwDir 'gw_run_err.log') -ErrorAction SilentlyContinue
Remove-Item (Join-Path $feDir 'fe_run_out.log'), (Join-Path $feDir 'fe_run_err.log') -ErrorAction SilentlyContinue

# --- Start Gateway (venv + watchdog) ---
Write-Host '[*] Starting Gateway (venv + watchdog)...'
$gw = Start-Process -FilePath $gwPy -ArgumentList 'watchdog.py' -WorkingDirectory $gwDir -WindowStyle Minimized -PassThru `
      -RedirectStandardOutput (Join-Path $gwDir 'gw_run_out.log') `
      -RedirectStandardError  (Join-Path $gwDir 'gw_run_err.log')
Write-Host "    watchdog PID: $($gw.Id)"

Start-Sleep -Seconds 5
if (Get-Process -Id $gw.Id -ErrorAction SilentlyContinue) {
    Write-Host '    watchdog alive.'
} else {
    Write-Host '    WARNING: watchdog exited early - check gateway\gw_run_err.log'
}

# --- Start Frontend (Next.js with hard memory cap) ---
if (-not (Test-Path (Join-Path $feDir 'node_modules\next'))) {
    Write-Host '[*] node_modules missing, installing frontend deps (first run only)...'
    $env:PATH = "$nodeDir;$env:PATH"
    Push-Location $feDir
    & $npm install
    Pop-Location
}

Write-Host '[*] Starting Frontend (Next.js, memory cap 1GB per worker)...'
$env:PATH = "$nodeDir;$env:PATH"
$fe = Start-Process -FilePath 'cmd.exe' `
      -ArgumentList '/c','set NODE_OPTIONS=--max-old-space-size=1024&&set NEXT_TELEMETRY_DISABLED=1&&npm run dev' `
      -WorkingDirectory $feDir -WindowStyle Minimized -PassThru `
      -RedirectStandardOutput (Join-Path $feDir 'fe_run_out.log') `
      -RedirectStandardError  (Join-Path $feDir 'fe_run_err.log')
Write-Host "    npm PID: $($fe.Id)"

# --- Optionally launch Unity 3D (loads in parallel) ---
if ($Unity) {
    $unityExe = $null
    Get-ChildItem 'C:\Program Files\Unity\Hub\Editor\*' -Directory -ErrorAction SilentlyContinue | ForEach-Object {
        if (-not $unityExe) {
            $cand = Join-Path $_.FullName 'Editor\Unity.exe'
            if (Test-Path $cand) { $unityExe = $cand }
        }
    }
    if (-not $unityExe) {
        Get-ChildItem 'C:\Program Files\Unity\*' -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            if (-not $unityExe) {
                $cand = Join-Path $_.FullName 'Editor\Unity.exe'
                if (Test-Path $cand) { $unityExe = $cand }
            }
        }
    }
    if ($unityExe) {
        $projDir = Join-Path $root 'unity_project'
        New-Item (Join-Path $projDir 'Temp') -ItemType Directory -Force | Out-Null
        Set-Content (Join-Path $projDir 'Temp\auto_play.flag') '1'
        Start-Process -FilePath $unityExe -ArgumentList "-projectPath `"$projDir`"" -WindowStyle Minimized
        Write-Host "[*] Unity launching: $unityExe"
    } else {
        Write-Host '[!] Unity Editor not found, skipping.'
    }
}

# --- Poll health endpoints (up to ~100s) ---
Write-Host '[*] Polling health endpoints...'
$gwOk = $false; $feOk = $false
for ($i = 0; $i -lt 50; $i++) {
    Start-Sleep -Seconds 2
    if (-not $gwOk) {
        try {
            # Use 127.0.0.1 (not localhost) - uvicorn binds IPv4 only, localhost resolves to ::1 first
            $r = Invoke-WebRequest 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { $gwOk = $true; Write-Host '[OK] Gateway  ready: http://localhost:8000/health' }
        } catch {}
    }
    if (-not $feOk) {
        try {
            $r = Invoke-WebRequest 'http://127.0.0.1:3000' -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { $feOk = $true; Write-Host '[OK] Frontend ready: http://localhost:3000' }
        } catch {}
    }
    if ($gwOk -and $feOk) { break }
    if ($i % 5 -eq 0) { Write-Host "    ... polling ($i)`n        gw:$gwOk fe:$feOk" }
}

if (-not $gwOk) { Write-Host '[!] Gateway not ready. Check: gateway\gw_run_err.log' }
if (-not $feOk) { Write-Host '[!] Frontend not ready. Check: frontend\fe_run_err.log' }

Write-Host '[*] Done.'
