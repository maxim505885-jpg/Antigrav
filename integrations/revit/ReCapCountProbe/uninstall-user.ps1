param(
    [string]$RevitAddinsDirectory = (Join-Path $env:APPDATA 'Autodesk\Revit\Addins\2027'),
    [string]$InstallDirectory = (Join-Path $env:LOCALAPPDATA 'ScanStudio\Revit\2027')
)
$ErrorActionPreference = 'Stop'
if (Get-Process -Name Revit -ErrorAction SilentlyContinue) { throw 'Закройте Revit перед удалением add-in.' }
$id='fe5b298d-87e2-43b2-89a2-184e8ea697c3'
$class='Scan.Revit.ReCapCountProbe.ReCapCountProbeCommand'
$installRoot=[System.IO.Path]::GetFullPath($InstallDirectory)
$addinRoot=[System.IO.Path]::GetFullPath($RevitAddinsDirectory)
$assembly=Join-Path $installRoot 'Scan.Revit.ReCapCountProbe.dll'
$receiptPath=Join-Path $installRoot 'recap-count-probe.install.json'
$manifestPath=Join-Path $addinRoot 'SCAN.ReCapCountProbe.addin'
if(-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)){throw "Receipt не найден; безопасное удаление невозможно: $receiptPath"}
$receipt=Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
if($receipt.product -ne 'scan-recap-count-probe/1' -or [System.IO.Path]::GetFullPath([string]$receipt.assembly) -ne $assembly){throw 'Receipt не подтверждает владение add-in; файлы не удалены.'}
if((Test-Path -LiteralPath $assembly -PathType Leaf) -and (Get-FileHash -Algorithm SHA256 -LiteralPath $assembly).Hash -ne [string]$receipt.sha256){throw 'DLL отличается от receipt; файлы сохранены для ручной проверки.'}
if(Test-Path -LiteralPath $manifestPath -PathType Leaf){
    try{$manifest=[xml](Get-Content -Raw -LiteralPath $manifestPath)}catch{throw "Manifest повреждён; файлы не удалены: $manifestPath"}
    $entry=@($manifest.RevitAddIns.AddIn)
    if($entry.Count -ne 1 -or [string]$entry[0].AddInId -ne $id -or [string]$entry[0].FullClassName -ne $class -or [System.IO.Path]::GetFullPath([string]$entry[0].Assembly) -ne $assembly){throw 'Manifest изменён или принадлежит другой add-in; файлы не удалены.'}
    Remove-Item -LiteralPath $manifestPath -Force
}
if(Test-Path -LiteralPath $assembly -PathType Leaf){Remove-Item -LiteralPath $assembly -Force}
Remove-Item -LiteralPath $receiptPath -Force
Write-Output 'SCAN ReCap count probe удалён; другие файлы не затрагивались.'