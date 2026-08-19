param([switch]$Quiet)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$self = $PID
$killed = @()

$procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessId -and $_.ProcessId -gt 4 -and $_.ProcessId -ne $self })

foreach ($p in $procs) {
    $cmd = $p.CommandLine
    if (-not $cmd) { continue }
    $isWatchdog = $cmd -match 'watchdog\.py'
    $isProjectNode = ($cmd -match 'next|npm|frontend') -and ($cmd -match [regex]::Escape($root))
    if ($isWatchdog -or $isProjectNode) {
        taskkill /F /T /PID $p.ProcessId 2>$null | Out-Null
        $killed += $p.ProcessId
    }
}

foreach ($port in 8000, 3000) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object {
            if ($_.OwningProcess -gt 4 -and $_.OwningProcess -ne $self -and $killed -notcontains $_.OwningProcess) {
                taskkill /F /T /PID $_.OwningProcess 2>$null | Out-Null
                $killed += $_.OwningProcess
            }
        }
}

if (-not $Quiet) {
    if ($killed.Count -eq 0) {
        Write-Host "No leftovers found"
    } else {
        Write-Host ("Killed leftover PIDs: " + ($killed -join ", "))
    }
}
