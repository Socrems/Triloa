$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run setup.ps1 first.' }

$downloadDir = Join-Path $projectRoot 'downloads\llama'
$runtimeDir = Join-Path $projectRoot 'runtime\llama'
$modelDir = Join-Path $projectRoot 'models\hy-mt'
$tempDir = Join-Path $projectRoot 'cache\tmp'
foreach ($dir in @($downloadDir, $runtimeDir, $modelDir, $tempDir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}
$env:TEMP = $tempDir
$env:TMP = $tempDir
$env:TMPDIR = $tempDir
$env:HF_HOME = Join-Path $projectRoot 'cache\huggingface'
$env:HUGGINGFACE_HUB_CACHE = Join-Path $env:HF_HOME 'hub'

if (-not ((Test-Path -LiteralPath (Join-Path $runtimeDir 'llama-server.exe')) -and (Test-Path -LiteralPath (Join-Path $runtimeDir 'cudart64_12.dll')))) {
$packages = @(
    @('llama-b10964-bin-win-cuda-12.4-x64.zip', 'https://github.com/ggml-org/llama.cpp/releases/download/b10964/llama-b10964-bin-win-cuda-12.4-x64.zip'),
    @('cudart-llama-bin-win-cuda-12.4-x64.zip', 'https://github.com/ggml-org/llama.cpp/releases/download/b10964/cudart-llama-bin-win-cuda-12.4-x64.zip')
)
foreach ($item in $packages) {
    $zipPath = Join-Path $downloadDir $item[0]
    $zipValid = $false
    if (Test-Path -LiteralPath $zipPath) {
        & $pythonExe -c 'import sys, zipfile; sys.exit(0 if zipfile.is_zipfile(sys.argv[1]) else 1)' $zipPath
        $zipValid = $LASTEXITCODE -eq 0
    }
    if (-not $zipValid) {
        Write-Host "Downloading $($item[0]) to $downloadDir"
        & curl.exe -fL -C - --retry 3 --connect-timeout 20 --output $zipPath $item[1]
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $($item[0])" }
    }
    Expand-Archive -LiteralPath $zipPath -DestinationPath $runtimeDir -Force
}

}

$server = Get-ChildItem -LiteralPath $runtimeDir -Filter 'llama-server.exe' -Recurse -File | Select-Object -First 1
if (-not $server) { throw 'llama-server.exe was not found after extraction.' }
if ($server.DirectoryName -ne $runtimeDir) {
    Copy-Item -Path (Join-Path $server.DirectoryName '*') -Destination $runtimeDir -Recurse -Force
}

& $pythonExe -B -m triloa.download_hy_model
if ($LASTEXITCODE -ne 0) { throw 'HY-MT model download failed.' }
Write-Host "HY-MT installation complete. Files are under $projectRoot."
