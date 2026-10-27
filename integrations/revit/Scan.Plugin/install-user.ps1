param(
    [string]$RevitAddinsDirectory = (Join-Path $env:APPDATA 'Autodesk\Revit\Addins\2027'),
    [string]$AssemblyPath = (Join-Path $PSScriptRoot 'bin\Release\net10.0-windows\Scan.Revit.Plugin.dll')
)

if (-not (Test-Path -LiteralPath $AssemblyPath)) {
    throw "Сначала соберите плагин: $AssemblyPath"
}

$resolvedAssembly = (Resolve-Path -LiteralPath $AssemblyPath).Path
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
  <AddIn Type="Command">
    <Name>SCAN BIM — проверка импорта</Name>
    <Assembly>$resolvedAssembly</Assembly>
    <AddInId>6f697d9a-0f73-47c9-a02c-0d7583c6f949</AddInId>
    <FullClassName>Scan.Revit.Plugin.VerifyImportedModelCommand</FullClassName>
    <Text>Сверить модель с исходником</Text>
    <VendorId>SCAN</VendorId>
    <VendorDescription>Intelligent Scan-to-BIM</VendorDescription>
  </AddIn>
</RevitAddIns>
"@
Set-Content -LiteralPath $manifestPath -Value $manifest -Encoding utf8
Write-Output "Создан манифест Revit add-in: $manifestPath"
