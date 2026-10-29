param(
    [string]$RevitAddinsDirectory = (Join-Path $env:APPDATA 'Autodesk\Revit\Addins\2027'),
    [string]$AssemblyPath = (Join-Path $PSScriptRoot 'bin\Scan.Revit.ReCapCountProbe.dll'),
    [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'ScanStudio\Revit\2027')
)
$ErrorActionPreference = 'Stop'
$id = 'fe5b298d-87e2-43b2-89a2-184e8ea697c3'
$class = 'Scan.Revit.ReCapCountProbe.ReCapCountProbeCommand'
if (Get-Process -Name Revit -ErrorAction SilentlyContinue) { throw 'Закройте Revit перед установкой add-in.' }
if (-not (Test-Path -LiteralPath $AssemblyPath -PathType Leaf)) { throw "Сначала соберите probe: $AssemblyPath" }
$source = (Resolve-Path -LiteralPath $AssemblyPath).Path
$installRoot = [System.IO.Path]::GetFullPath($InstallDirectory)
$addinRoot = [System.IO.Path]::GetFullPath($RevitAddinsDirectory)
$assemblyTarget = Join-Path $installRoot 'Scan.Revit.ReCapCountProbe.dll'
$manifestPath = Join-Path $addinRoot 'SCAN.ReCapCountProbe.addin'
$receiptPath = Join-Path $installRoot 'recap-count-probe.install.json'
if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    try { $current = [xml](Get-Content -Raw -LiteralPath $manifestPath) }
    catch { throw "Существующий manifest не является корректным XML; он не изменён: $manifestPath" }
    $entries = @($current.RevitAddIns.AddIn)
    if ($entries.Count -ne 1 -or [string]$entries[0].AddInId -ne $id -or [string]$entries[0].FullClassName -ne $class) {
        throw "Существующий manifest принадлежит другой add-in; отказ от перезаписи: $manifestPath"
    }
}
if (Test-Path -LiteralPath $assemblyTarget -PathType Leaf) {
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) { throw "Целевая DLL есть без receipt; отказ от перезаписи: $assemblyTarget" }
    $prior = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
    if ($prior.product -ne 'scan-recap-count-probe/1' -or [System.IO.Path]::GetFullPath([string]$prior.assembly) -ne $assemblyTarget) {
        throw "Receipt не подтверждает владение DLL; отказ от перезаписи: $assemblyTarget"
    }
}
New-Item -ItemType Directory -Force -Path $installRoot,$addinRoot | Out-Null
$stageAssembly = Join-Path $installRoot ('.ReCapCountProbe.'+[guid]::NewGuid().ToString('N')+'.tmp')
$stageManifest = Join-Path $addinRoot ('.SCAN.ReCapCountProbe.'+[guid]::NewGuid().ToString('N')+'.tmp')
$stageReceipt = Join-Path $installRoot ('.recap-count-probe.'+[guid]::NewGuid().ToString('N')+'.tmp')
try {
    Copy-Item -LiteralPath $source -Destination $stageAssembly
    $sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $stageAssembly).Hash
    $manifest = @"
<?xml version="1.0" encoding="utf-8" standalone="no"?>
<RevitAddIns>
  <AddIn Type="Command">
    <Name>SCAN · сверка числа точек ReCap</Name>
    <Assembly>$assemblyTarget</Assembly>
    <AddInId>$id</AddInId>
    <FullClassName>$class</FullClassName>
    <Text>SCAN ReCap count probe</Text>
    <VendorId>SCAN</VendorId>
    <VendorDescription>SCAN Studio · read-only ReCap count audit</VendorDescription>
  </AddIn>
</RevitAddIns>
"@
    $receipt = [ordered]@{product='scan-recap-count-probe/1';assembly=$assemblyTarget;sha256=$sha;source=$source;installed_at=[DateTimeOffset]::Now.ToString('o')} | ConvertTo-Json -Depth 3
    [System.IO.File]::WriteAllText($stageManifest,$manifest+"`n",[System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::WriteAllText($stageReceipt,$receipt+"`n",[System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $stageAssembly -Destination $assemblyTarget -Force
    Move-Item -LiteralPath $stageManifest -Destination $manifestPath -Force
    Move-Item -LiteralPath $stageReceipt -Destination $receiptPath -Force
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $assemblyTarget).Hash -ne $sha) { throw 'Проверка SHA-256 установленной DLL не прошла.' }
    $installed = [xml](Get-Content -Raw -LiteralPath $manifestPath)
    if ([string]$installed.RevitAddIns.AddIn.Assembly -ne $assemblyTarget) { throw 'Проверка manifest не прошла.' }
    Write-Output "Revit add-in установлен: $manifestPath"
    Write-Output "Сборка: $assemblyTarget"
    Write-Output "SHA-256: $sha"
} finally {
    Remove-Item -LiteralPath $stageAssembly,$stageManifest,$stageReceipt -Force -ErrorAction SilentlyContinue
}