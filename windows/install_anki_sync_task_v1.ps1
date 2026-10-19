param(
    [Parameter(Mandatory=$true)]
    [string]$DriveOutDir,
    [int]$IntervalMinutes = 30,
    [string]$TaskName = "Jason OS Anki Sync"
)

$ErrorActionPreference = "Stop"

if ($IntervalMinutes -lt 1) {
    throw "IntervalMinutes must be at least 1."
}

$Runner = Join-Path $PSScriptRoot "run_anki_sync_catchup_v1.ps1"

if (-not (Test-Path $Runner)) {
    throw "Catch-up runner not found: $Runner"
}

if (-not (Test-Path $DriveOutDir)) {
    throw "Google Drive output path not found: $DriveOutDir"
}

$user = "$env:USERDOMAIN\$env:USERNAME"

$taskCommand = 'powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $Runner + '" -DriveOutDir "' + $DriveOutDir + '"'

Write-Host "Task name:" $TaskName
Write-Host "User:" $user
Write-Host "Interval:" $IntervalMinutes "minutes"
Write-Host "Runner:" $Runner
Write-Host "Drive output:" $DriveOutDir

& schtasks.exe /Create /TN $TaskName /SC MINUTE /MO $IntervalMinutes /TR $taskCommand /RU $user /IT /RL LIMITED /F

if ($LASTEXITCODE -ne 0) {
    throw "schtasks.exe failed with exit code $LASTEXITCODE."
}

Write-Host ""
Write-Host "Scheduled task created."

& schtasks.exe /Query /TN $TaskName /V /FO LIST
