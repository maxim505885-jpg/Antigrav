param(
    [Parameter(Mandatory = $true)]
    [string]$InstallRoot
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $InstallRoot).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$required = @(
    $python,
    (Join-Path $root 'backend\scan2bim\api\app.py'),
    (Join-Path $root 'backend\scan2bim\server.py'),
    (Join-Path $root 'contracts\scan2bim.bim-1.0.schema.json'),
    (Join-Path $root 'contracts\structural-model.schema.json'),
    (Join-Path $root 'frontend\dist\index.html'),
    (Join-Path $root 'frontend\dist\templates\registration-controls-template.csv')
)
$missing = @($required | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
if ($missing.Count -gt 0) {
    throw "Installed bundle is missing required files: $($missing -join ', ')"
}

$sourceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$sourceVerifier = Join-Path $sourceRoot 'scripts\verify_installed_sources.py'
$sourceVerification = & $python -B $sourceVerifier $sourceRoot $root
$sourceVerificationExitCode = $LASTEXITCODE
if ($sourceVerificationExitCode -ne 0) {
    throw "Installed Python sources do not match the current SCAN runtime (exit $sourceVerificationExitCode): $($sourceVerification -join ' ')"
}
Write-Output "Installed Python source manifest verified: $sourceVerification"
$assetPattern = '(?:src|href)="(/assets/[^"]+)"'
$sourceIndex = Join-Path $sourceRoot 'frontend\dist\index.html'
$installedIndex = Join-Path $root 'frontend\dist\index.html'
$sourceHtml = Get-Content -LiteralPath $sourceIndex -Raw
$installedHtml = Get-Content -LiteralPath $installedIndex -Raw
$sourceAssets = @([regex]::Matches($sourceHtml, $assetPattern) | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
$installedAssets = @([regex]::Matches($installedHtml, $assetPattern) | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
if ($sourceAssets.Count -eq 0 -or (Compare-Object -ReferenceObject $sourceAssets -DifferenceObject $installedAssets)) {
    throw "Installed UI asset manifest is stale. Source: $($sourceAssets -join ', '); installed: $($installedAssets -join ', '). Rebuild the installer from the current frontend/dist."
}
foreach ($asset in $sourceAssets) {
    $relativeAsset = $asset.TrimStart('/').Replace('/', '\')
    $sourceAssetPath = Join-Path $sourceRoot (Join-Path 'frontend\dist' $relativeAsset)
    $installedAssetPath = Join-Path $root (Join-Path 'frontend\dist' $relativeAsset)
    if (-not (Test-Path -LiteralPath $installedAssetPath -PathType Leaf)) {
        throw "Installed UI asset is missing: $asset"
    }
    $sourceHash = (Get-FileHash -LiteralPath $sourceAssetPath -Algorithm SHA256).Hash
    $installedHash = (Get-FileHash -LiteralPath $installedAssetPath -Algorithm SHA256).Hash
    if ($sourceHash -ne $installedHash) {
        throw "Installed UI asset does not match the current source build: $asset"
    }
}

$sourceControlTemplate = Join-Path $sourceRoot 'frontend\dist\templates\registration-controls-template.csv'
$installedControlTemplate = Join-Path $root 'frontend\dist\templates\registration-controls-template.csv'
$sourceControlTemplateHash = (Get-FileHash -LiteralPath $sourceControlTemplate -Algorithm SHA256).Hash
$installedControlTemplateHash = (Get-FileHash -LiteralPath $installedControlTemplate -Algorithm SHA256).Hash
if ($sourceControlTemplateHash -ne $installedControlTemplateHash) {
    throw 'Installed registration-control CSV template does not match the current production build.'
}

$configPath = Join-Path $root '.venv\pyvenv.cfg'
$config = Get-Content -LiteralPath $configPath -Raw
foreach ($key in @('home = ', 'executable = ', 'command = ')) {
    $line = ($config -split "`r?`n" | Where-Object { $_.StartsWith($key) } | Select-Object -First 1)
    if (-not $line -or -not $line.Contains($root)) {
        throw "Installed Python configuration has an unrelocated '$key' value."
    }
}

$forbidden = @(
    'backend\data',
    'backend\tests',
    'backend\.pytest-data-stage6',
    'backend\.codex-api-8000.err.log',
    'backend\AutodeskReCap.log'
)
foreach ($relativePath in $forbidden) {
    if (Test-Path -LiteralPath (Join-Path $root $relativePath)) {
        throw "Developer data was included in the installed bundle: $relativePath"
    }
}

$pythonSitePackages = @(
    (Join-Path $root '.venv\Lib\site-packages'),
    (Join-Path $root 'python313\Lib\site-packages')
) | Where-Object { Test-Path -LiteralPath $_ -PathType Container }
$bundledDependencyTests = @(
    foreach ($sitePackages in $pythonSitePackages) {
        Get-ChildItem -LiteralPath $sitePackages -File -Recurse -Force |
            Where-Object { $_.FullName -match '\\site-packages\\.*\\tests\\' }
    }
)
if ($bundledDependencyTests.Count -gt 0) {
    $examples = @($bundledDependencyTests | Select-Object -First 5 -ExpandProperty FullName)
    throw "Python dependency test files were included in the installed bundle: $($examples -join '; ')"
}

$jediTypeshed = Join-Path $root '.venv\Lib\site-packages\jedi\third_party\typeshed'
$jediTypeshedFiles = if (Test-Path -LiteralPath $jediTypeshed) {
    @(Get-ChildItem -LiteralPath $jediTypeshed -File -Recurse -Force)
} else {
    @()
}
if ($jediTypeshedFiles.Count -gt 0) {
    $examples = @($jediTypeshedFiles | Select-Object -First 5 -ExpandProperty FullName)
    throw "Jedi's editor-only typeshed files were included in the installed bundle: $($examples -join '; ')"
}

$pythonStdlibTests = Join-Path $root 'python313\Lib\test'
$pythonStdlibTestFiles = if (Test-Path -LiteralPath $pythonStdlibTests) {
    @(Get-ChildItem -LiteralPath $pythonStdlibTests -File -Recurse -Force)
} else {
    @()
}
if ($pythonStdlibTestFiles.Count -gt 0) {
    $examples = @($pythonStdlibTestFiles | Select-Object -First 5 -ExpandProperty FullName)
    throw "The Python standard-library test files were included in the installed bundle: $($examples -join '; ')"
}

$pycBefore = (Get-ChildItem -LiteralPath $root -Filter '*.pyc' -File -Recurse -Force | Measure-Object).Count
if ($pycBefore -ne 0) {
    throw "The installed bundle contains $pycBefore Python bytecode files before startup."
}

$dataRoot = Join-Path $env:TEMP ("scanstudio-acceptance-" + [Guid]::NewGuid().ToString('N'))
$runtimeSmokePath = Join-Path $env:TEMP ("scanstudio-runtime-smoke-" + [Guid]::NewGuid().ToString('N') + '.py')
$stdoutPath = Join-Path $env:TEMP ("scanstudio-runtime-smoke-" + [Guid]::NewGuid().ToString('N') + '.stdout.log')
$stderrPath = Join-Path $env:TEMP ("scanstudio-runtime-smoke-" + [Guid]::NewGuid().ToString('N') + '.stderr.log')
$tempRoot = (Resolve-Path -LiteralPath $env:TEMP).Path
$previousDataDir = $env:S2B_DATA_DIR
$previousPythonPath = $env:PYTHONPATH
$previousNoBytecode = $env:PYTHONDONTWRITEBYTECODE
$previousIngestMode = $env:S2B_INGEST_MODE
try {
    $env:S2B_DATA_DIR = $dataRoot
    $env:PYTHONPATH = "$root\backend;$root"
    $env:PYTHONDONTWRITEBYTECODE = '1'
    $env:S2B_INGEST_MODE = 'worker'
    $pythonCode = @'
import json
import os
import subprocess
import sys
from pathlib import Path
import fastapi, uvicorn, numpy, scipy, ezdxf, desktop_app
from fastapi.testclient import TestClient
from scan2bim.main import app
import scan2bim.structure.models, scan2bim.bim.model

with TestClient(app, client=("127.0.0.1", 8000)) as client:
    health = client.get("/api/v1/health")
    ui = client.get("/")
    remote_client = TestClient(app, client=("192.0.2.10", 12345))
    remote_api = remote_client.get("/api/v1/projects")
    demo = client.post("/api/v1/demo")
    assert demo.status_code == 200, demo.text
    job_id = demo.json()["cloud"]["import_job_id"]
    worker_env = os.environ.copy()
    worker_env["S2B_INGEST_MODE"] = "worker"
    worker_env["S2B_DATA_DIR"] = os.environ["S2B_DATA_DIR"]
    worker = subprocess.run(
        [sys.executable, "-m", "scan2bim.worker", "--once"],
        cwd=str(Path(sys.executable).resolve().parents[2]),
        env=worker_env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    cloud = client.get(f"/api/v1/clouds/{demo.json()['cloud']['id']}").json()
    result = {
        "python": sys.executable,
        "health_status": health.status_code,
        "health": health.json(),
        "ui_status": ui.status_code,
        "ui_title_present": "SCAN STUDIO" in ui.text,
        "remote_api_without_key_status": remote_api.status_code,
        "worker_exit_code": worker.returncode,
        "worker_stdout": worker.stdout,
        "worker_stderr": worker.stderr,
        "durable_worker_job_status": job["status"],
        "durable_worker_progress": job["progress"],
        "durable_worker_cloud_status": cloud["status"],
    }
    print(json.dumps(result))
    assert health.status_code == 200 and health.json().get("status") == "ok"
    assert ui.status_code == 200 and result["ui_title_present"]
    assert remote_api.status_code == 401
    assert worker.returncode == 0, worker.stderr or worker.stdout
    assert job["status"] == "succeeded", job
    assert job["progress"] == 1.0
    assert cloud["status"] == "ready", cloud
'@
    # Redirect native stdout/stderr through Start-Process. Windows PowerShell
    # can turn harmless Python warnings on stderr into terminating
    # NativeCommandError records when ErrorActionPreference=Stop.
    [System.IO.File]::WriteAllText($runtimeSmokePath, $pythonCode, [System.Text.UTF8Encoding]::new($false))
    $pythonProcess = Start-Process -FilePath $python -ArgumentList @($runtimeSmokePath) `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath `
        -PassThru -Wait -WindowStyle Hidden
    $pythonExitCode = $pythonProcess.ExitCode
    $output = if (Test-Path -LiteralPath $stdoutPath) {
        @(Get-Content -LiteralPath $stdoutPath)
    } else { @() }
    if ($pythonExitCode -ne 0) {
        $stderr = if (Test-Path -LiteralPath $stderrPath) {
            Get-Content -LiteralPath $stderrPath -Raw
        } else { '' }
        throw "Installed runtime smoke failed (exit $pythonExitCode): $($output -join [Environment]::NewLine) $stderr"
    }
    $jsonLine = $output | Where-Object { $_ -match '^\{' } | Select-Object -Last 1
    if (-not $jsonLine) {
        throw "Installed runtime smoke did not return JSON: $($output -join [Environment]::NewLine)"
    }
    $result = $jsonLine | ConvertFrom-Json
    $pycAfter = (Get-ChildItem -LiteralPath $root -Filter '*.pyc' -File -Recurse -Force | Measure-Object).Count
    if ($pycAfter -ne 0) {
        throw "The installed launcher/runtime smoke created $pycAfter Python bytecode files."
    }
    $resolvedDataRoot = [System.IO.Path]::GetFullPath($dataRoot)
    if (-not $resolvedDataRoot.StartsWith($tempRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'The temporary acceptance database path escaped the system TEMP directory.'
    }
    $result | Add-Member -NotePropertyName bytecode_files -NotePropertyValue $pycAfter
    $result | Add-Member -NotePropertyName data_directory_isolated_under_temp -NotePropertyValue $true
    $result | ConvertTo-Json -Depth 6
}
finally {
    if ($env:S2B_DATA_DIR -eq $dataRoot -and (Test-Path -LiteralPath $dataRoot)) {
        $resolvedDataRoot = (Resolve-Path -LiteralPath $dataRoot).Path
        if ($resolvedDataRoot.StartsWith($tempRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolvedDataRoot -Recurse -Force
        }
    }
    $env:S2B_DATA_DIR = $previousDataDir
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONDONTWRITEBYTECODE = $previousNoBytecode
    $env:S2B_INGEST_MODE = $previousIngestMode
    foreach ($temporaryOutput in @($runtimeSmokePath, $stdoutPath, $stderrPath)) {
        if (Test-Path -LiteralPath $temporaryOutput) {
            Remove-Item -LiteralPath $temporaryOutput -Force
        }
    }
}
