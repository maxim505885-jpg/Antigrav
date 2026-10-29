param(
    [string]$AssemblyPath = (Join-Path $PSScriptRoot 'bin\Release\net10.0-windows\Scan.Revit.Plugin.dll'),
    [string]$RevitAddinsDirectory = (Join-Path $env:APPDATA 'Autodesk\Revit\Addins\2027'),
    [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'ScanStudio\Revit\2027')
)

$ErrorActionPreference = 'Stop'
$expected = @(
    @{ Id = 'cd825db8-599c-48fc-a205-9a30794ee295'; Class = 'Scan.Revit.Plugin.ImportStructuralModelCommand'; Name = 'SCAN BIM — импорт конструкций'; Text = 'Импорт SCAN BIM JSON' },
    @{ Id = '6f697d9a-0f73-47c9-a02c-0d7583c6f949'; Class = 'Scan.Revit.Plugin.VerifyImportedModelCommand'; Name = 'SCAN BIM — проверка импорта'; Text = 'Сверить модель с исходником' }
)

if (Get-Process -Name Revit -ErrorAction SilentlyContinue) {
    throw 'Закройте Revit перед установкой add-in.'
}
if (-not (Test-Path -LiteralPath $AssemblyPath -PathType Leaf)) {
    throw "Сначала соберите плагин: $AssemblyPath"
}
$source = (Resolve-Path -LiteralPath $AssemblyPath).Path
$installRoot = [System.IO.Path]::GetFullPath($InstallDirectory)
$addinRoot = [System.IO.Path]::GetFullPath($RevitAddinsDirectory)
$assemblyTarget = Join-Path $installRoot 'Scan.Revit.Plugin.dll'
$manifestPath = Join-Path $addinRoot 'SCAN.StructuralModel.addin'
$receiptPath = Join-Path $installRoot 'install.json'

if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    try { $current = [xml](Get-Content -Raw -LiteralPath $manifestPath) }
    catch { throw "Существующий manifest не является корректным XML; он не изменён: $manifestPath" }
    $currentAddins = @($current.RevitAddIns.AddIn)
    $currentIds = @($currentAddins | ForEach-Object { ([string]$_.AddInId).ToLowerInvariant() } | Sort-Object)
    $expectedIds = @($expected | ForEach-Object { $_.Id.ToLowerInvariant() } | Sort-Object)
    if ($currentIds.Count -ne $expectedIds.Count -or (Compare-Object $currentIds $expectedIds)) {
        throw "Существующий manifest содержит другие add-in записи; отказ от перезаписи: $manifestPath"
    }
    foreach ($entry in $expected) {
        $match = @($currentAddins | Where-Object { ([string]$_.AddInId).ToLowerInvariant() -eq $entry.Id.ToLowerInvariant() })
        if ($match.Count -ne 1 -or [string]$match[0].FullClassName -ne $entry.Class) {
            throw "Существующий manifest не совпадает с SCAN add-in; отказ от перезаписи: $manifestPath"
        }
    }
}

if (Test-Path -LiteralPath $assemblyTarget -PathType Leaf) {
    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
        throw "В каталоге установки уже есть DLL без receipt; отказ от перезаписи: $assemblyTarget"
    }
    $receipt = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
    if ($receipt.product -ne 'scan-revit-structural-model/1' -or
        [System.IO.Path]::GetFullPath([string]$receipt.assembly) -ne $assemblyTarget) {
        throw "Receipt не подтверждает владение целевой DLL; отказ от перезаписи: $assemblyTarget"
    }
}

New-Item -ItemType Directory -Force -Path $installRoot, $addinRoot | Out-Null
$stagedAssembly = Join-Path $installRoot ('.Scan.Revit.Plugin.' + [guid]::NewGuid().ToString('N') + '.tmp')
$stagedManifest = Join-Path $addinRoot ('.SCAN.StructuralModel.' + [guid]::NewGuid().ToString('N') + '.tmp')
$stagedReceipt = Join-Path $installRoot ('.install.' + [guid]::NewGuid().ToString('N') + '.tmp')
$hadTarget = Test-Path -LiteralPath $assemblyTarget -PathType Leaf
try {
    Copy-Item -LiteralPath $source -Destination $stagedAssembly
    $sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $stagedAssembly).Hash
    $manifestEntries = foreach ($entry in $expected) {
        $name = [System.Security.SecurityElement]::Escape($entry.Name)
        $text = [System.Security.SecurityElement]::Escape($entry.Text)
        $class = [System.Security.SecurityElement]::Escape($entry.Class)
        "  <AddIn Type=`"Command`"><Name>$name</Name><Assembly>$assemblyTarget</Assembly><AddInId>$($entry.Id)</AddInId><FullClassName>$class</FullClassName><Text>$text</Text><VendorId>SCAN</VendorId><VendorDescription>Intelligent Scan-to-BIM</VendorDescription></AddIn>"
    }
    $manifest = "<?xml version=`"1.0`" encoding=`"utf-8`" standalone=`"no`"?>`n<RevitAddIns>`n$($manifestEntries -join "`n")`n</RevitAddIns>`n"
    $receipt = [ordered]@{
        product = 'scan-revit-structural-model/1'
        assembly = $assemblyTarget
        sha256 = $sha
        source = $source
        installed_at = [DateTimeOffset]::Now.ToString('o')
        addin_ids = @($expected | ForEach-Object { $_.Id })
    } | ConvertTo-Json -Depth 4
    [System.IO.File]::WriteAllText($stagedManifest, $manifest, [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::WriteAllText($stagedReceipt, $receipt + "`n", [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $stagedAssembly -Destination $assemblyTarget -Force
    Move-Item -LiteralPath $stagedManifest -Destination $manifestPath -Force
    Move-Item -LiteralPath $stagedReceipt -Destination $receiptPath -Force
    $installed = (Get-FileHash -Algorithm SHA256 -LiteralPath $assemblyTarget).Hash
    if ($installed -ne $sha) { throw 'Проверка SHA-256 установленной DLL не прошла.' }
    $installedManifest = [xml](Get-Content -Raw -LiteralPath $manifestPath)
    if (@($installedManifest.RevitAddIns.AddIn).Count -ne 2) { throw 'Проверка установленного manifest не прошла.' }
    Write-Output "Установлено: $manifestPath"
    Write-Output "Сборка: $assemblyTarget"
    Write-Output "SHA-256: $sha"
}
catch {
    Remove-Item -LiteralPath $stagedAssembly, $stagedManifest, $stagedReceipt -Force -ErrorAction SilentlyContinue
    if (-not $hadTarget -and (Test-Path -LiteralPath $assemblyTarget -PathType Leaf) -and -not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        Remove-Item -LiteralPath $assemblyTarget -Force -ErrorAction SilentlyContinue
    }
    throw
}