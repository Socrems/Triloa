$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Please run setup.ps1 first.' }
$env:TEMP = Join-Path $projectRoot 'cache\tmp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $projectRoot 'cache\pip'
New-Item -ItemType Directory -Force -Path $env:TEMP, $env:PIP_CACHE_DIR | Out-Null
& $pythonExe -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'requirements-qwen-asr.txt')
if ($LASTEXITCODE -ne 0) { throw 'Qwen3-ASR runtime dependencies failed to install.' }
Write-Host 'Runtime ready. Open Triloa resources to download Qwen3-ASR, or select a complete local model folder on the subtitle page.'
