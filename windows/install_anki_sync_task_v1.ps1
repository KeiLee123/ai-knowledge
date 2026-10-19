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

$actionArgs = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $Runner + '" -DriveOutDir "' + $DriveOutDir + '"'

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs
$periodicTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Write-Host "Task name:" $TaskName
Write-Host "User:" $user
Write-Host "Interval:" $IntervalMinutes "minutes"
Write-Host "Runner:" $Runner
Write-Host "Drive output:" $DriveOutDir

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($logonTrigger, $periodicTrigger) -Principal $principal -Settings $settings -Description ("Jason OS read-only Anki review sync. Runs at logon and retries every $IntervalMinutes minutes.") -Force | Out-Null

Write-Host ""
Write-Host "Scheduled task created."

Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State, Author, Description

Write-Host ""
Write-Host "Task action:"
(Get-ScheduledTask -TaskName $TaskName).Actions | Select-Object Execute, Arguments

Write-Host ""
Write-Host "Task triggers:"
(Get-ScheduledTask -TaskName $TaskName).Triggers | Select-Object Enabled, StartBoundary, Repetition, @{N="TriggerType";E={$_.CimClass.CimClassName}}
