<#
.SYNOPSIS
  Removes the mem_leak scheduled task, stops any running instance, and deletes the installed files.

.EXAMPLE
  .\uninstall.ps1              # remove task, stop process, delete %LOCALAPPDATA%\DeviceOnSim
  .\uninstall.ps1 -KeepFiles   # keep the exe and log
#>
[CmdletBinding()]
param(
    [string]$TaskName = 'MemLeak',
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'DeviceOnSim'),
    [switch]$KeepFiles
)
$ErrorActionPreference = 'Stop'
$TaskPath = '\DeviceOnSim\'

$task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Confirm:$false
    Write-Host "Removed task $TaskPath$TaskName"
} else {
    Write-Host "Task $TaskPath$TaskName not found"
}

# Remove the \DeviceOnSim\ folder in Task Scheduler if it is now empty.
try {
    $svc = New-Object -ComObject 'Schedule.Service'
    $svc.Connect()
    $folder = $svc.GetFolder($TaskPath.TrimEnd('\'))
    if ($folder.GetTasks(1).Count -eq 0 -and $folder.GetFolders(0).Count -eq 0) {
        $svc.GetFolder('\').DeleteFolder($TaskPath.Trim('\'), 0)
    }
} catch {
    # folder already gone or not ours to delete
}

$procs = Get-Process -Name 'mem_leak' -ErrorAction SilentlyContinue
if ($procs) {
    $procs | Stop-Process -Force
    Write-Host "Stopped mem_leak.exe (pid $($procs.Id -join ', '))"
}

if (-not $KeepFiles -and (Test-Path $InstallDir)) {
    Remove-Item -Recurse -Force $InstallDir
    Write-Host "Deleted $InstallDir"
}
