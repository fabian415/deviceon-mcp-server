<#
.SYNOPSIS
  Registers a Task Scheduler job that runs mem_leak.exe every N minutes.

.DESCRIPTION
  Each run grows memory for -GrowSeconds, holds it for -HoldSeconds, then exits, so the
  device shows a periodic memory saw-tooth and every run has a new PID.
  mem_leak.exe is copied to -InstallDir so the task does not depend on this folder.
  The task runs as the current user, only while that user is logged on (no password stored).
  Re-running this script replaces the existing task.

.EXAMPLE
  .\install.ps1                                   # every 5 min: grow 120 s, hold 30 s, max 2048 MB
  .\install.ps1 -IntervalMinutes 3 -GrowSeconds 60 -HoldSeconds 30 -MaxMB 1024 -RunNow
#>
[CmdletBinding()]
param(
    [ValidateRange(2, 1440)][int]$IntervalMinutes = 5,
    [ValidateRange(5, 3600)][int]$GrowSeconds = 120,
    [ValidateRange(0, 3600)][int]$HoldSeconds = 30,
    [ValidateRange(64, 65536)][int]$MaxMB = 2048,
    [ValidateRange(1, 80)][int]$MaxPercent = 40,
    [ValidateRange(5, 90)][int]$FloorPercent = 15,
    [string]$TaskName = 'MemLeak',
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'DeviceOnSim'),
    [switch]$RunNow
)
$ErrorActionPreference = 'Stop'
$TaskPath = '\DeviceOnSim\'

$src = Join-Path $PSScriptRoot 'mem_leak.exe'
if (-not (Test-Path $src)) { throw "mem_leak.exe not found next to this script. Run build.bat first." }

$runSec = $GrowSeconds + $HoldSeconds
if ($runSec + 30 -gt $IntervalMinutes * 60) {
    throw "GrowSeconds + HoldSeconds ($runSec s) must be at least 30 s shorter than the interval ($($IntervalMinutes * 60) s), otherwise runs overlap and the pattern is not periodic."
}

# Replace an existing install: stop the task and any running instance before overwriting the exe.
$existing = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($existing) {
    Stop-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
}
Get-Process -Name 'mem_leak' -ErrorAction SilentlyContinue | Stop-Process -Force

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -Path $src -Destination $InstallDir -Force
$exe = Join-Path $InstallDir 'mem_leak.exe'
$log = Join-Path $InstallDir 'mem_leak.log'

$arguments = "--grow $GrowSeconds --hold $HoldSeconds --max-mb $MaxMB --max-pct $MaxPercent --floor-pct $FloorPercent --log `"$log`""
$action = New-ScheduledTaskAction -Execute $exe -Argument $arguments -WorkingDirectory $InstallDir

# First run in 1 minute, then every IntervalMinutes, indefinitely.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Seconds ($runSec + 120)) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

$user = if ($env:USERDOMAIN) { "$env:USERDOMAIN\$env:USERNAME" } else { $env:USERNAME }
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "DeviceOn MCP PoC: memory-growth simulator (grow $GrowSeconds s / hold $HoldSeconds s every $IntervalMinutes min). Remove with uninstall.ps1." `
    -Force | Out-Null

if ($RunNow) { Start-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath }

$info = Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath $TaskPath
Write-Host "Registered task $TaskPath$TaskName"
Write-Host "  exe      : $exe $arguments"
Write-Host "  pattern  : grow $GrowSeconds s -> hold $HoldSeconds s -> exit, every $IntervalMinutes min (cap $MaxMB MB / $MaxPercent% of RAM)"
Write-Host "  next run : $($info.NextRunTime)$(if ($RunNow) { ' (also started now)' })"
Write-Host "  log      : $log"
Write-Host "Remove with: .\uninstall.ps1"
