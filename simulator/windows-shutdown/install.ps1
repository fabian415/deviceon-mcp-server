<#
.SYNOPSIS
  Scenario 4: memory pressure builds up until a protective watchdog powers the machine off.

.DESCRIPTION
  Registers two Task Scheduler jobs that run as SYSTEM at every boot (so they also come back
  after the device is woken up with Wake-on-LAN, even when nobody logs on):

    \DeviceOnSim\PressureLeak  pressure_leak.exe  the culprit: grows memory by -LeakMBPerMin, never frees it
    \DeviceOnSim\MemGuard      mem_guard.exe      the watchdog: physical load >= -ThresholdPercent OR commit
                                                  >= -CommitThresholdPercent for -SustainSeconds
                                                  -> event 3001 + power off (with -Arm)

  The leak stops growing at -LeakMaxCommitPercent of the commit limit (RAM + page file) and keeps
  re-writing what it holds so it stays in RAM. Do not use very high rates (e.g. 2048 MB/min):
  Windows then pages heavily and the machine freezes before the watchdog can act.

  Without -Arm the watchdog only logs "DRY RUN" (safe rehearsal). With -Arm it really powers the
  machine off; the leak restarts on the next boot, so the machine shuts down again until its task is
  disabled (or uninstall.ps1 is run). Must be run as administrator. Re-running replaces the install.

.EXAMPLE
  .\install.ps1 -RunNow                         # rehearsal: everything except the power-off
  .\install.ps1 -Arm -RunNow                    # real run (the script prints its time estimate)
  .\install.ps1 -Arm -RunNow -LeakMBPerMin 512  # faster; 512 is the recommended maximum
#>
[CmdletBinding()]
param(
    [ValidateRange(16, 1024)][int]$LeakMBPerMin = 256,
    [ValidateRange(0, 3600)][int]$LeakStartDelaySec = 120,
    [ValidateRange(50, 99)][int]$LeakMaxLoadPercent = 97,
    [ValidateRange(50, 99)][int]$LeakMaxCommitPercent = 95,
    [ValidateRange(50, 98)][int]$ThresholdPercent = 90,
    [ValidateRange(50, 98)][int]$CommitThresholdPercent = 90,
    [ValidateRange(5, 3600)][int]$SustainSeconds = 60,
    [ValidateRange(0, 600)][int]$GraceSeconds = 30,
    [string]$InstallDir = (Join-Path $env:ProgramData 'DeviceOnSim\Shutdown'),
    [switch]$Arm,
    [switch]$RunNow
)
$ErrorActionPreference = 'Stop'
$TaskPath = '\DeviceOnSim\'
$Tasks = @{ PressureLeak = 'pressure_leak'; MemGuard = 'mem_guard' }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'Run this script as administrator (the tasks run as SYSTEM).' }
if ($LeakMaxLoadPercent -le $ThresholdPercent) {
    throw "LeakMaxLoadPercent ($LeakMaxLoadPercent) must be above ThresholdPercent ($ThresholdPercent), otherwise the leak stops before the watchdog trips."
}
if ($LeakMaxCommitPercent -le $CommitThresholdPercent) {
    throw "LeakMaxCommitPercent ($LeakMaxCommitPercent) must be above CommitThresholdPercent ($CommitThresholdPercent), otherwise the leak stops before the watchdog trips."
}
foreach ($n in $Tasks.Values) {
    if (-not (Test-Path (Join-Path $PSScriptRoot "$n.exe"))) { throw "$n.exe not found next to this script. Run build.bat first." }
}

# Replace an existing install.
foreach ($t in $Tasks.Keys) {
    if (Get-ScheduledTask -TaskName $t -TaskPath $TaskPath -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $t -TaskPath $TaskPath -ErrorAction SilentlyContinue
    }
}
Get-Process -Name ($Tasks.Values) -ErrorAction SilentlyContinue | Stop-Process -Force

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
foreach ($n in $Tasks.Values) { Copy-Item -Path (Join-Path $PSScriptRoot "$n.exe") -Destination $InstallDir -Force }

# Event source for mem_guard's warning (event 3001 in the Application log).
if (-not [Diagnostics.EventLog]::SourceExists('DeviceOnSim')) { New-EventLog -LogName Application -Source 'DeviceOnSim' }

$taskArgs = @{
    PressureLeak = "--rate $LeakMBPerMin --start-delay $LeakStartDelaySec --max-load $LeakMaxLoadPercent --max-commit $LeakMaxCommitPercent --log `"$InstallDir\pressure_leak.log`""
    MemGuard     = "--threshold $ThresholdPercent --commit-threshold $CommitThresholdPercent --sustain $SustainSeconds --grace $GraceSeconds$(if ($Arm) { ' --arm' }) --log `"$InstallDir\mem_guard.log`""
}
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$trigger = New-ScheduledTaskTrigger -AtStartup

foreach ($t in $Tasks.Keys) {
    $exe = Join-Path $InstallDir "$($Tasks[$t]).exe"
    $action = New-ScheduledTaskAction -Execute $exe -Argument $taskArgs[$t] -WorkingDirectory $InstallDir
    Register-ScheduledTask -TaskName $t -TaskPath $TaskPath -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force `
        -Description "DeviceOn MCP PoC scenario 4 ($($Tasks[$t]).exe). Remove with uninstall.ps1." | Out-Null
    if ($RunNow) { Start-ScheduledTask -TaskName $t -TaskPath $TaskPath }
}

# Estimate: whichever limit (physical load or commit) the leak reaches first. Win32_OperatingSystem values are KB.
$os = Get-CimInstance Win32_OperatingSystem
$totalMb = [math]::Round($os.TotalVisibleMemorySize / 1KB)
$loadNow = [math]::Round(100 - $os.FreePhysicalMemory * 100 / $os.TotalVisibleMemorySize)
$commitLimitMb = [math]::Round($os.TotalVirtualMemorySize / 1KB)
$commitNow = [math]::Round(100 - $os.FreeVirtualMemory * 100 / $os.TotalVirtualMemorySize)
$needMb = [math]::Min([math]::Max(0, $ThresholdPercent - $loadNow) / 100 * $totalMb,
                      [math]::Max(0, $CommitThresholdPercent - $commitNow) / 100 * $commitLimitMb)
$minutes = [math]::Ceiling($needMb / $LeakMBPerMin + $LeakStartDelaySec / 60 + $SustainSeconds / 60)

Write-Host "Registered $($TaskPath)PressureLeak and $($TaskPath)MemGuard (SYSTEM, at startup$(if ($RunNow) { ', also started now' }))"
Write-Host "  leak     : +$LeakMBPerMin MB/min after $LeakStartDelaySec s, holds at $LeakMaxLoadPercent% load or $LeakMaxCommitPercent% commit"
Write-Host "  watchdog : load >= $ThresholdPercent% or commit >= $CommitThresholdPercent% for $SustainSeconds s -> $(if ($Arm) { "POWER OFF after $GraceSeconds s warning" } else { 'DRY RUN (log + event 3001 only)' })"
Write-Host "  estimate : RAM $totalMb MB (load $loadNow%), commit limit $commitLimitMb MB (commit $commitNow%) -> trips in about $minutes min"
Write-Host "  logs     : $InstallDir\pressure_leak.log, $InstallDir\mem_guard.log"
Write-Host "Remove with: .\uninstall.ps1"
