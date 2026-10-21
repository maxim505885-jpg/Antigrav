param(
    [string]$RevitAddinsDirectory = (Join-Path $env:APPDATA 'Autodesk\Revit\Addins\2027')
)

$assembly = Join-Path $PSScriptRoot 'bin\Release\net10.0-windows\Scan.Revit.Plugin.dll'
if (-not (Test-Path -LiteralPath $assembly)) {
    throw "Сначала соберите плагин: $assembly"
}

$resolvedAssembly = (Resolve-Path -LiteralPath $assembly).Path
New-Item -ItemType Directory -Force -Path $RevitAddinsDirectory | Out-Null
$manifestPath = Join-Path $RevitAddinsDirectory 'SCAN.StructuralModel.addin'
$manifest = @"
<?xml version="1.0" encoding="utf-8" standalone="no"?>
<RevitAddIns>
  <AddIn Type="Command">
    <Name>SCAN BIM — импорт конструкций</Name>
    <Assembly>$resolvedAssembly</Assembly>
    <AddInId>cd825db8-599c-48fc-a205-9a30794ee295</AddInId>
    <FullClassName>Scan.Revit.Plugin.ImportStructuralModelCommand</FullClassName>
    <Text>Импорт SCAN BIM JSON</Text>
    <VendorId>SCAN</VendorId>
    <VendorDescription>Intelligent Scan-to-BIM</VendorDescription>
  </AddIn>
</RevitAddIns>
"@
Set-Content -LiteralPath $manifestPath -Value $manifest -Encoding utf8
Write-Output "Создан манифест Revit add-in: $manifestPath"
