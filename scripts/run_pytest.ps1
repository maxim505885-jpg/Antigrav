[CmdletBinding()]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python was not found at $python. Create the project .venv first."
}

if (-not $PytestArgs -or $PytestArgs.Count -eq 0) {
    $PytestArgs = @("backend/tests")
}

$runRoot = Join-Path $repoRoot "data\.t"
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
$runDirectory = Join-Path $runRoot ([Guid]::NewGuid().ToString("N").Substring(0, 12))
New-Item -ItemType Directory -Path $runDirectory | Out-Null
$pytestBase = Join-Path $runDirectory "pytest"
$dataDirectory = Join-Path $runDirectory "app-data"

$oldTemp = $env:TEMP
$oldTmp = $env:TMP
$oldDataDirectory = $env:S2B_DATA_DIR
Push-Location $repoRoot
try {
    # Keep Python and pytest temp files inside this unique, isolated workspace
    # folder. No existing temp directory or application database is reused.
    $env:TEMP = $runDirectory
    $env:TMP = $runDirectory
    $env:S2B_DATA_DIR = $dataDirectory
    & $python -m pytest -p no:cacheprovider @PytestArgs --basetemp $pytestBase --tb=short
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
    $env:TEMP = $oldTemp
    $env:TMP = $oldTmp
    $env:S2B_DATA_DIR = $oldDataDirectory
}

exit $exitCode
