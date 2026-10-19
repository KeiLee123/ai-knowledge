param(
    [Parameter(Mandatory = $true)]
    [string]$DriveOutDir,

    [string]$Deck = "Jason OS::Construction Drawing",

    [string]$Tag = "jason-os",

    [string]$PythonLauncher = "py"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$syncScript = Join-Path $repoRoot "sync_anki_reviews_v1.py"

if (-not (Test-Path $syncScript)) {
    throw "SR-G connector not found: $syncScript"
}

$DriveOutDir = [System.IO.Path]::GetFullPath(
    $DriveOutDir
)

$snapshotDir = Join-Path $DriveOutDir "snapshots"

New-Item -ItemType Directory -Force -Path $snapshotDir |
    Out-Null

$stamp = [DateTime]::UtcNow.ToString(
    "yyyyMMddTHHmmssZ"
)

$timestamped = Join-Path $snapshotDir (
    "anki_" + $stamp + ".json"
)

$latest = Join-Path $DriveOutDir "latest.json"
$latestTemp = Join-Path $DriveOutDir "latest.json.tmp"

Write-Host "Jason OS Anki sync"
Write-Host "Deck:" $Deck
Write-Host "Output:" $timestamped

$scriptArgs = @(
    $syncScript,
    "--deck",
    $Deck,
    "--tag",
    $Tag,
    "--output",
    $timestamped
)

if ($PythonLauncher -eq "py") {
    & py -3 @scriptArgs
}
else {
    & $PythonLauncher @scriptArgs
}

if ($LASTEXITCODE -ne 0) {
    throw "SR-G snapshot generation failed."
}

Copy-Item -Force $timestamped $latestTemp
Move-Item -Force $latestTemp $latest

Write-Host
Write-Host "Snapshot created:" $timestamped
Write-Host "Latest updated:" $latest
Write-Host "Anki write performed: False"
