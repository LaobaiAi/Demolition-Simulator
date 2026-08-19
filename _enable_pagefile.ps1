$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit 0
}

$cs = Get-CimInstance Win32_ComputerSystem
Write-Host ("AutomaticManagedPagefile before: " + $cs.AutomaticManagedPagefile)

if (-not $cs.AutomaticManagedPagefile) {
    Set-CimInstance -InputObject $cs -Property @{ AutomaticManagedPagefile = $true }
    Write-Host "System-managed page file enabled."
} else {
    Write-Host "System-managed page file already enabled."
}

$after = (Get-CimInstance Win32_ComputerSystem).AutomaticManagedPagefile
Write-Host ("AutomaticManagedPagefile after: " + $after)
Write-Host "A reboot is recommended for the page file to take effect."

Read-Host "Press Enter to close..."
