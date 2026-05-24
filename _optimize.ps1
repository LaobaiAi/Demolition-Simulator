# XuanwuAI Performance Optimizer
# Analyzes system and project to identify resource bottlenecks.
# Run this before launching the project:  powershell -File _optimize.ps1

$pct = [char]0x25
$Host.UI.RawUI.ForegroundColor = [ConsoleColor]::White

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  XuanwuAI Performance Diagnosis"
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ─── System Info ──────────────────────────────────────────────────
Write-Host "--- SYSTEM ---" -ForegroundColor Yellow
$os = Get-WmiObject Win32_OperatingSystem
$totalMemKB = $os.TotalVisibleMemorySize
$freeMemKB = $os.FreePhysicalMemory
$usedMemKB = $totalMemKB - $freeMemKB
$pctUsed = [math]::Round($usedMemKB / $totalMemKB * 100, 1)
$totalMemGB = [math]::Round($totalMemKB/1024/1024, 2)
$freeMemGB = [math]::Round($freeMemKB/1024/1024, 2)
$usedMemGB = [math]::Round($usedMemKB/1024/1024, 2)

$cpuInfo = Get-WmiObject Win32_Processor
$cpuCores = $cpuInfo.NumberOfLogicalCores
$cpuName = $cpuInfo.Name
Write-Host "  CPU: $cpuName ($cpuCores cores)"
Write-Host "  RAM: ${totalMemGB}GB ($pctUsed$pct used, ${freeMemGB}GB free)"
Write-Host ""

# ─── Project Dir Sizes ────────────────────────────────────────────
Write-Host "--- PROJECT STORAGE ---" -ForegroundColor Yellow
$root = "E:\Claude code workspace\XuanwuAI Demolition Simulator"
$dirs = @(
    @{Name="frontend\node_modules"; Desc="Node.js packages"},
    @{Name="frontend\.next"; Desc="Next.js build cache"},
    @{Name="gateway\venv"; Desc="Gateway Python venv"},
    @{Name=".venv"; Desc="Root Python venv"},
    @{Name="node_modules"; Desc="Root node_modules"}
)

foreach ($d in $dirs) {
    $path = Join-Path $root $d.Name
    if (Test-Path $path) {
        $size = (Get-ChildItem $path -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
        $sizeMB = [math]::Round($size/1MB, 1)
        $warning = ""
        if ($sizeMB -gt 500) { $warning = "  << LARGE" }
        Write-Host "  $($d.Name): ${sizeMB}MB$warning"
    } else {
        Write-Host "  $($d.Name): (not found)"
    }
}
Write-Host ""

# ─── Process Analysis ─────────────────────────────────────────────
Write-Host "--- PROCESS ANALYSIS ---" -ForegroundColor Yellow
$problemProcesses = @()

# Node.js processes
$nodeProcs = Get-Process -Name "node" -ErrorAction SilentlyContinue
if ($nodeProcs) {
    $totalNodeMem = ($nodeProcs | Measure-Object WorkingSet -Sum).Sum
    Write-Host "  Node.js processes: $($nodeProcs.Count) running, $([math]::Round($totalNodeMem/1MB, 1))MB total" -ForegroundColor Red
    $nodeProcs | ForEach-Object {
        Write-Host "    PID:$($_.Id) $($_.CommandLine.Substring(0, [Math]::Min(120, $_.CommandLine.Length)))" -ForegroundColor DarkGray
    }
    $problemProcesses += "node"
}

# Python processes
$pyProcs = Get-Process -Name "python*" -ErrorAction SilentlyContinue
if ($pyProcs) {
    $totalPyMem = ($pyProcs | Measure-Object WorkingSet -Sum).Sum
    Write-Host "  Python processes: $($pyProcs.Count) running, $([math]::Round($totalPyMem/1MB, 1))MB total" -ForegroundColor Red
    $problemProcesses += "python"
}

# IDE processes
$cursorProcs = Get-Process -Name "Cursor" -ErrorAction SilentlyContinue
if ($cursorProcs) {
    $totalCursorMem = ($cursorProcs | Measure-Object WorkingSet -Sum).Sum
    Write-Host "  Cursor IDE processes: $($cursorProcs.Count) instances, $([math]::Round($totalCursorMem/1MB, 1))MB total" -ForegroundColor Yellow
}

$claudeProcs = Get-Process -Name "claude" -ErrorAction SilentlyContinue
if ($claudeProcs) {
    $totalClaudeMem = ($claudeProcs | Measure-Object WorkingSet -Sum).Sum
    Write-Host "  Claude Code: $($claudeProcs.Count) instance(s), $([math]::Round($totalClaudeMem/1MB, 1))MB total" -ForegroundColor Yellow
}

# Unity
$unityProcs = Get-Process -Name "Unity*" -ErrorAction SilentlyContinue
if ($unityProcs) {
    $totalUnityMem = ($unityProcs | Measure-Object WorkingSet -Sum).Sum
    Write-Host "  Unity: $($unityProcs.Count) instance(s), $([math]::Round($totalUnityMem/1MB, 1))MB total" -ForegroundColor Yellow
}

$defender = Get-Process -Name "MsMpEng" -ErrorAction SilentlyContinue
if ($defender) {
    Write-Host "  Windows Defender (MsMpEng): $([math]::Round(($defender|Measure-Object WorkingSet -Sum).Sum/1MB, 1))MB" -ForegroundColor DarkGray
}

Write-Host ""

# ─── Recommendations ──────────────────────────────────────────────
Write-Host "--- RECOMMENDATIONS ---" -ForegroundColor Green

# Check Python venv duplication
$gatewayVenv = Join-Path $root "gateway\venv"
$rootVenv = Join-Path $root ".venv"
if ((Test-Path $gatewayVenv) -and (Test-Path $rootVenv)) {
    Write-Host "  * DUPLICATE VENVS: Both 'gateway/venv' and '.venv' exist (~680MB total)." -ForegroundColor Yellow
    Write-Host "    Consider removing one if not needed."
}

# Check if multiple .next cache dirs exist
$nextCache = Join-Path $root "frontend\.next"
if (Test-Path $nextCache) {
    $nextSize = (Get-ChildItem $nextCache -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    $nextSizeMB = [math]::Round($nextSize/1MB, 1)
    if ($nextSizeMB -gt 200) {
        Write-Host "  * LARGE BUILD CACHE: frontend\.next is ${nextSizeMB}MB. Run 'npm run build' to trim." -ForegroundColor Yellow
    }
}

# General recommendations
Write-Host "  * Close unused Cursor windows to free memory (currently heavy)."
Write-Host "  * Add project dir to Windows Defender exclusion list:" -ForegroundColor Cyan
Write-Host "    PowerShell: Add-MpPreference -ExclusionPath '$root'" -ForegroundColor DarkGray
Write-Host "  * Use fewer browser tabs during development."

# Project startup estimate
Write-Host ""
Write-Host "--- STARTUP IMPACT ESTIMATE ---" -ForegroundColor Yellow
# Next.js dev ~400MB, Gateway ~80MB, anastruct ~60MB
$futureUsedKB = $usedMemKB + 400*1024 + 80*1024 + 60*1024
$futurePct = [math]::Round($futureUsedKB / $totalMemKB * 100, 1)
if ($futurePct -lt 75) {
    Write-Host "  Gateway + Frontend: ~${futurePct}$pct memory (likely OK)" -ForegroundColor Green
} elseif ($futurePct -lt 85) {
    Write-Host "  Gateway + Frontend: ~${futurePct}$pct memory (moderate)" -ForegroundColor Yellow
} else {
    Write-Host "  Gateway + Frontend: ~${futurePct}$pct memory (HIGH - may be tight!)" -ForegroundColor Red
}

# With Unity: +~800MB
$pctAfter = [math]::Round(($futureUsedKB + 800*1024) / $totalMemKB * 100, 1)
Write-Host "  With Unity: ~${pctAfter}$pct (Next.js + Gateway + Unity)"
Write-Host ""
