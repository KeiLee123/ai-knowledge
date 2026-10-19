param(
    [Parameter(Mandatory=$true)]
    [string]$DriveOutDir,
    [string]$LogDir = "D:\JasonOS\AnkiSync\logs",
    [int]$AnkiConnectTimeoutSec = 5
)

$ErrorActionPreference = "Stop"

$SyncScript = Join-Path $PSScriptRoot "run_anki_sync_to_drive_v1.ps1"

New-Item -ItemType Directory -Force $LogDir | Out-Null
$LogPath = Join-Path $LogDir "catchup.log"

function Write-JasonLog {
    param([string]$Message)

    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $LogPath -Value $line
    Write-Host $line
}

Write-JasonLog "Catch-up run started."

if (-not (Test-Path $DriveOutDir)) {
    Write-JasonLog "Google Drive output path unavailable; skip."
    exit 0
}

if (-not (Test-Path $SyncScript)) {
    Write-JasonLog "Sync script missing: $SyncScript"
    exit 1
}

try {
    $body = @{
        action  = "version"
        version = 6
    } | ConvertTo-Json

    $response = Invoke-RestMethod -Uri "http://127.0.0.1:8765" -Method Post -Body $body -ContentType "application/json" -TimeoutSec $AnkiConnectTimeoutSec

    if ($response.error) {
        Write-JasonLog "AnkiConnect returned an error; skip."
        exit 0
    }
}
catch {
    Write-JasonLog "AnkiConnect unavailable; skip."
    exit 0
}

Write-JasonLog "AnkiConnect available; running SR-G sync."

$output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $SyncScript -DriveOutDir $DriveOutDir 2>&1
$exitCode = $LASTEXITCODE

foreach ($line in $output) {
    Add-Content -Path $LogPath -Value ([string]$line)
    Write-Host $line
}

if ($exitCode -ne 0) {
    Write-JasonLog "SR-G sync failed with exit code $exitCode."
    exit $exitCode
}

Write-JasonLog "SR-G sync completed successfully."
exit 0
