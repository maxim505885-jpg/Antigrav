param(
    [string]$RevitInstallDir = 'C:\Program Files\Autodesk\Revit 2027',
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'bin')
)
$ErrorActionPreference = 'Stop'
$api = Join-Path $RevitInstallDir 'RevitAPI.dll'
$ui = Join-Path $RevitInstallDir 'RevitAPIUI.dll'
$recap = Join-Path $RevitInstallDir 'AdskRcManaged.dll'
foreach ($reference in @($api, $ui, $recap)) {
    if (-not (Test-Path -LiteralPath $reference)) { throw "Required Revit reference is missing: $reference" }
}
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$output = Join-Path $OutputDirectory 'Scan.Revit.ReCapCountProbe.dll'
if ($PSVersionTable.PSEdition -ne 'Core' -or [Environment]::Version.Major -lt 10) {
    throw 'Revit 2027 count probe must be built from PowerShell Core on the .NET 10 runtime.'
}
$runtimeDirectory = Split-Path -Parent ([object].Assembly.Location)
$frameworkReferences = @(
    [object].Assembly.Location,
    (Join-Path $runtimeDirectory 'System.Runtime.dll'),
    [System.Security.Cryptography.SHA256].Assembly.Location
)
foreach ($reference in $frameworkReferences) {
    if (-not (Test-Path -LiteralPath $reference)) { throw "Required .NET reference is missing: $reference" }
}
$definition = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'ReCapCountProbeCommand.cs') -Raw
$stagingDirectory = Join-Path $OutputDirectory ('.build-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stagingDirectory | Out-Null
$stagedOutput = Join-Path $stagingDirectory ([IO.Path]::GetFileName($output))
try {
    Add-Type -TypeDefinition $definition -Language CSharp -ReferencedAssemblies (@($api, $ui, $recap) + $frameworkReferences) -OutputAssembly $stagedOutput
    Move-Item -LiteralPath $stagedOutput -Destination $output -Force
} finally {
    Remove-Item -LiteralPath $stagedOutput -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stagingDirectory -Force -ErrorAction SilentlyContinue
}
Write-Output "Built Revit 2027 ReCap count probe: $output"

