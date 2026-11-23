<#
.SYNOPSIS
  Removes the scenario 4 tasks (\DeviceOnSim\PressureLeak, \DeviceOnSim\MemGuard), stops both
  processes and deletes the installed files. Run as administrator.

.EXAMPLE
  .\uninstall.ps1                       # keeps the 'DeviceOnSim' event source so old events stay readable
  .\uninstall.ps1 -KeepFiles            # keep the exes and logs
  .\uninstall.ps1 -RemoveEventSource
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:ProgramData 'DeviceOnSim\Shutdown'),
    [switch]$KeepFiles,
    [switch]$RemoveEventSource
)
$ErrorActionPreference = 'Stop'
$TaskPath = '\DeviceOnSim\'

foreach ($t in 'PressureLeak', 'MemGuard') {
    if (Get-ScheduledTask -TaskName $t -TaskPath $TaskPath -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $t -TaskPath $TaskPath -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $t -TaskPath $TaskPath -Confirm:$false
        Write-Host "Removed task $TaskPath$t"
    }
}

# Remove the \DeviceOnSim\ task folder if nothing else (e.g. scenario 2's MemLeak) is left in it.
try {
    $svc = New-Object -ComObject 'Schedule.Service'
    $svc.Connect()
    $folder = $svc.GetFolder($TaskPath.TrimEnd('\'))
    if ($folder.GetTasks(1).Count -eq 0 -and $folder.GetFolders(0).Count -eq 0) {
        $svc.GetFolder('\').DeleteFolder($TaskPath.Trim('\'), 0)
    }
} catch {
}

$procs = Get-Process -Name 'pressure_leak', 'mem_guard' -ErrorAction SilentlyContinue
if ($procs) {
    $procs | Stop-Process -Force
    Write-Host "Stopped $(($procs | ForEach-Object { "$($_.ProcessName) ($($_.Id))" }) -join ', ')"
}
# A shutdown that mem_guard already started can still be cancelled during its grace period.
shutdown.exe /a 2>$null | Out-Null

if (-not $KeepFiles -and (Test-Path $InstallDir)) {
    Remove-Item -Recurse -Force $InstallDir
    Write-Host "Deleted $InstallDir"
}
if ($RemoveEventSource -and [Diagnostics.EventLog]::SourceExists('DeviceOnSim')) {
    Remove-EventLog -Source 'DeviceOnSim'
    Write-Host "Removed event source DeviceOnSim"
}
