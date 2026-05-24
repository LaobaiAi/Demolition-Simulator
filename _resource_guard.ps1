# XuanwuAI Resource Guard
# Monitors CPU/Memory and pauses operations when thresholds are exceeded.
# Leaves headroom for troubleshooting -- never lets the system get stuck.
#
# Usage:
#   Pre-launch check:  powershell -File _resource_guard.ps1 -mode precheck
#   Background monitor: powershell -File _resource_guard.ps1 -mode monitor
#   One-shot check:     powershell -File _resource_guard.ps1 -mode check

param(
    [ValidateSet("precheck", "monitor", "check")]
    [string]$mode = "check",
    [int]$checkIntervalSeconds = 15,
    [string]$logFile = ""
)

$pct = [char]0x25   # percent sign workaround

# Thresholds -- for 16GB / 6-core system
$minFreeMemMB = 2048
$maxCpuPct = 80
$maxProcessMemMB = 500

$Host.UI.RawUI.ForegroundColor = [ConsoleColor]::White

function Write-Status {
    param([string]$msg, [string]$color = "Gray")
    $Host.UI.RawUI.ForegroundColor = $color
    $now = Get-Date -Format "HH:mm:ss"
    Write-Host "$now $msg"
    $Host.UI.RawUI.ForegroundColor = [ConsoleColor]::White
}

# Main resource check
function Get-ResourceSnapshot {
    $os = Get-WmiObject Win32_OperatingSystem
    $cpu = Get-WmiObject Win32_Processor | Measure-Object -Property LoadPercentage -Average
    $totalMemMB = [math]::Round($os.TotalVisibleMemorySize, 0)
    $freeMemMB  = [math]::Round($os.FreePhysicalMemory, 0)
    $usedMemMB  = $totalMemMB - $freeMemMB
    $pctMemUsed = [math]::Round($usedMemMB / $totalMemMB * 100, 1)

    # Top processes sorted by memory
    $topProcs = Get-Process | Where-Object { $_.WorkingSet -gt 50MB } |
        Sort-Object WorkingSet -Descending |
        Select-Object -First 8 @{N="PID";E={$_.Id}}, ProcessName,
            @{N="MemMB";E={[math]::Round($_.WorkingSet/1MB, 1)}},
            @{N="CpuSec";E={[math]::Round($_.CPU, 1)}}

    $avgCpu = [math]::Round($cpu.Average, 1)
    $healthy = ($freeMemMB -ge $minFreeMemMB) -and ($avgCpu -lt $maxCpuPct)

    return @{
        timestamp    = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        totalMemMB   = $totalMemMB
        freeMemMB    = $freeMemMB
        usedMemMB    = $usedMemMB
        pctMemUsed   = $pctMemUsed
        cpuPct       = $avgCpu
        topProcesses = $topProcs
        isHealthy    = $healthy
    }
}

function Show-ResourceWarning {
    param($snapshot, [string[]]$reasons)
    $Host.UI.RawUI.ForegroundColor = [ConsoleColor]::Red
    Write-Host ""
    Write-Host "============================================"
    Write-Host "  RESOURCE THRESHOLD EXCEEDED"
    Write-Host "============================================"
    $Host.UI.RawUI.ForegroundColor = [ConsoleColor]::Yellow
    Write-Host ""
    Write-Host "SYSTEM:"
    Write-Host "  CPU : $($snapshot.cpuPct)$pct  (threshold: $maxCpuPct$pct)"
    Write-Host ("  MEM : {0:N0}MB / {1:N0}MB used, {2:N0}MB free (need >= {3}MB)" -f $snapshot.usedMemMB, $snapshot.totalMemMB, $snapshot.freeMemMB, $minFreeMemMB)
    Write-Host ""
    Write-Host "TRIGGERED:"
    foreach ($r in $reasons) {
        Write-Host "  * $r"
    }
    Write-Host ""
    Write-Host "TOP PROCESSES:"
    $snapshot.topProcesses | ForEach-Object {
        $line = "  PID:$($_.PID)  $($_.ProcessName)  $($_.MemMB)MB"
        if ($_.CpuSec -gt 0) { $line += "  CPU:$($_.CpuSec)s" }
        Write-Host $line
    }
    Write-Host ""
    $Host.UI.RawUI.ForegroundColor = [ConsoleColor]::Cyan
    Write-Host "============================================"
    Write-Host "  ACTION REQUIRED - choose:"
    Write-Host "    [C] Continue anyway"
    Write-Host "    [P] Pause project processes"
    Write-Host "    [K] Kill top memory consumers"
    Write-Host "    [A] Abort - exit"
    Write-Host "============================================"
    $Host.UI.RawUI.ForegroundColor = [ConsoleColor]::White
}

function Get-UserDecision {
    $timeoutSeconds = 60
    Write-Host "(waiting ${timeoutSeconds}s, auto-pause if no response...)" -ForegroundColor DarkGray
    $elapsed = 0
    while ($elapsed -lt $timeoutSeconds) {
        if ([Console]::KeyAvailable) {
            $key = [Console]::ReadKey($true)
            switch ($key.Key) {
                'C' { return 'continue' }
                'P' { return 'pause' }
                'K' { return 'kill' }
                'A' { return 'abort' }
            }
        }
        Start-Sleep -Seconds 1
        $elapsed++
        if ($elapsed % 10 -eq 0) {
            Write-Host "  [${elapsed}s] C=Continue  P=Pause  K=Kill-top  A=Abort" -ForegroundColor DarkGray
        }
    }
    Write-Host "  [TIMEOUT] Auto-pausing." -ForegroundColor Yellow
    return 'pause'
}

function Invoke-PreCheck {
    Write-Status "=== Pre-Launch Resource Check ===" "Cyan"
    $snap = Get-ResourceSnapshot
    Write-Host "  CPU: $($snap.cpuPct)$pct | MEM: $($snap.usedMemMB)/$($snap.totalMemMB)MB used ($($snap.pctMemUsed)$pct) | Free: $($snap.freeMemMB)MB"

    $reasons = @()
    if ($snap.freeMemMB -lt $minFreeMemMB) {
        $reasons += "Available memory ($($snap.freeMemMB)MB) below $minFreeMemMB MB threshold"
    }
    if ($snap.cpuPct -ge $maxCpuPct) {
        $reasons += "CPU $($snap.cpuPct)$pct above $maxCpuPct$pct threshold"
    }

    if ($reasons.Count -gt 0) {
        Show-ResourceWarning -snapshot $snap -reasons $reasons
        $decision = Get-UserDecision
        return @{ decision = $decision; snapshot = $snap }
    }

    Write-Status "Resources OK - safe to launch." "Green"
    return @{ decision = 'continue'; snapshot = $snap }
}

function Invoke-Check {
    $snap = Get-ResourceSnapshot
    $reasons = @()
    if ($snap.freeMemMB -lt $minFreeMemMB) {
        $reasons += "Low memory: $($snap.freeMemMB)MB free"
    }
    if ($snap.cpuPct -ge $maxCpuPct) {
        $reasons += "High CPU: $($snap.cpuPct)$pct"
    }

    $procs = $snap.topProcesses | ForEach-Object {
        "$($_.ProcessName)($($_.PID)) $($_.MemMB)MB"
    }

    $result = @{
        healthy      = $snap.isHealthy
        freeMemMB    = $snap.freeMemMB
        cpuPct       = $snap.cpuPct
        reasons      = $reasons
        topProcesses = $procs
    }
    return ($result | ConvertTo-Json -Compress)
}

# Monitor: runs continuously, triggers warning when thresholds exceeded
function Invoke-Monitor {
    Write-Status "=== Resource Monitor Started ===" "Cyan"
    Write-Status "Checking every ${checkIntervalSeconds}s | MEM free < ${minFreeMemMB}MB | CPU > ${maxCpuPct}$pct"
    Write-Status "Press Ctrl+C to stop." "DarkGray"

    $consecutiveWarnings = 0

    while ($true) {
        Start-Sleep -Seconds $checkIntervalSeconds
        $snap = Get-ResourceSnapshot

        $reasons = @()
        if ($snap.freeMemMB -lt $minFreeMemMB) {
            $reasons += "Low memory: $($snap.freeMemMB)MB free (need >= $minFreeMemMB MB)"
        }
        if ($snap.cpuPct -ge $maxCpuPct) {
            $reasons += "High CPU: $($snap.cpuPct)$pct (threshold: $maxCpuPct$pct)"
        }
        foreach ($p in $snap.topProcesses) {
            if ($p.MemMB -gt $maxProcessMemMB) {
                $reasons += "Process $($p.ProcessName) (PID:$($p.PID)) using $($p.MemMB)MB"
            }
        }

        if ($reasons.Count -gt 0) {
            $consecutiveWarnings++
            if ($consecutiveWarnings -ge 2) {
                Show-ResourceWarning -snapshot $snap -reasons $reasons
                Write-Status "Threshold exceeded for ${consecutiveWarnings}x checks." "Red"
                return 'triggered'
            } else {
                Write-Status "WARNING: $($reasons[0]) (x${consecutiveWarnings})" "Yellow"
            }
        } else {
            if ($consecutiveWarnings -gt 0) {
                Write-Status "Resources recovered (was warning for ${consecutiveWarnings} checks)" "Green"
            }
            $consecutiveWarnings = 0
        }
    }
}

# Dispatch
switch ($mode) {
    "precheck" {
        $result = Invoke-PreCheck
        $decision = $result.decision
        Write-Host "DECISION:$decision" -ForegroundColor Magenta
        # Exit codes: 0=continue, 1=pause, 2=abort
        switch ($decision) {
            'continue' { exit 0 }
            'pause'    { exit 1 }
            'abort'    { exit 2 }
            'kill'     { exit 3 }
            default    { exit 1 }
        }
    }
    "check" {
        Write-Host (Invoke-Check)
        exit 0
    }
    "monitor" {
        $status = Invoke-Monitor
        if ($status -eq 'triggered') {
            $decision = Get-UserDecision
            Write-Host "DECISION:$decision" -ForegroundColor Magenta
            switch ($decision) {
                'continue' { exit 0 }
                'pause'    { exit 1 }
                'abort'    { exit 2 }
                'kill'     { exit 3 }
                default    { exit 1 }
            }
        }
    }
}
