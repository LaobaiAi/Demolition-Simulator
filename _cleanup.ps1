# XuanwuAI Cleanup — removes ALL leftover processes from this project.
# This is the single source of truth for killing leftover node/python processes,
# so that node processes never accumulate and crash the machine.
param([switch]$Quiet)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$self = $PID
$killed = @()

# All project-related python/node command line markers
# - watchdog.py / main.py / gateway: the backend gateway
# - next / next-server / npm run dev / frontend: the frontend dev server
# Only match when the command line also references this project root, to avoid
# killing unrelated node/python services on the machine.
$rootEsc = [regex]::Escape($root)

$procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessId -and $_.ProcessId -gt 4 -and $_.ProcessId -ne $self })

foreach ($p in $procs) {
    $cmd = $p.CommandLine
    if (-not $cmd) { continue }

    $isProjectProc = ($cmd -match 'watchdog\.py|gateway\\main\.py|main\.py') -and ($cmd -match $rootEsc)
    $isProjectNode = ($cmd -match 'next-server|next dev|next build|npm run dev|node_modules\\.bin\\next|node_modules\\next|\.next\\dev\\build\\') -and ($cmd -match $rootEsc)
    $isPortBlocker  = $false

    if ($isProjectProc -or $isProjectNode) {
        # Kill the whole process tree so we never leave orphan children
        taskkill /F /T /PID $p.ProcessId 2>$null | Out-Null
        $killed += $p.ProcessId
    }
}

# Any process holding our ports (8000 gateway, 3000 frontend) is project-related.
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
