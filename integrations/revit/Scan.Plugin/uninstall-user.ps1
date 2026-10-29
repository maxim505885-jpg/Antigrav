param(
    [string]$RevitAddinsDirectory = (Join-Path $env:APPDATA 'Autodesk\Revit\Addins\2027'),
    [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'ScanStudio\Revit\2027')
)

$ErrorActionPreference = 'Stop'
if (Get-Process -Name Revit -ErrorAction SilentlyContinue) {
    throw 'Закройте Revit перед удалением add-in.'
}
$installRoot = [System.IO.Path]::GetFullPath($InstallDirectory)
$addinRoot = [System.IO.Path]::GetFullPath($RevitAddinsDirectory)
$assemblyPath = Join-Path $installRoot 'Scan.Revit.Plugin.dll'
$receiptPath = Join-Path $installRoot 'install.json'
$manifestPath = Join-Path $addinRoot 'SCAN.StructuralModel.addin'
if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
    throw "Receipt не найден; безопасное удаление невозможно: $receiptPath"
}
$receipt = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
if ($receipt.product -ne 'scan-revit-structural-model/1' -or
    [System.IO.Path]::GetFullPath([string]$receipt.assembly) -ne $assemblyPath -or
    [System.IO.Path]::GetFileName($assemblyPath) -ne 'Scan.Revit.Plugin.dll') {
    throw 'Receipt не подтверждает владение данным add-in; файлы не удалены.'
}
if (Test-Path -LiteralPath $assemblyPath -PathType Leaf) {
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $assemblyPath).Hash -ne [string]$receipt.sha256) {
        throw 'DLL отличается от receipt; файлы сохранены для ручной проверки.'
    }
}
if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    try { $manifest = [xml](Get-Content -Raw -LiteralPath $manifestPath) }
    catch { throw "Manifest повреждён; файлы не удалены: $manifestPath" }
    $addins = @($manifest.RevitAddIns.AddIn)
    $ids = @($addins | ForEach-Object { ([string]$_.AddInId).ToLowerInvariant() } | Sort-Object)
    $expectedIds = @('cd825db8-599c-48fc-a205-9a30794ee295','6f697d9a-0f73-47c9-a02c-0d7583c6f949' | ForEach-Object { $_.ToLowerInvariant() } | Sort-Object)
    if ($ids.Count -ne 2 -or (Compare-Object $ids $expectedIds) -or
        @($addins | Where-Object { [System.IO.Path]::GetFullPath([string]$_.Assembly) -ne $assemblyPath }).Count) {
        throw 'Manifest содержит чужие или изменённые add-in записи; файлы не удалены.'
    }
    Remove-Item -LiteralPath $manifestPath -Force
}
if (Test-Path -LiteralPath $assemblyPath -PathType Leaf) {
    Remove-Item -LiteralPath $assemblyPath -Force
}
Remove-Item -LiteralPath $receiptPath -Force
Write-Output 'SCAN Revit structural add-in удалён; посторонние файлы не затрагивались.'