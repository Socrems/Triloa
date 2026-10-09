$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Please run setup.ps1 first.' }
$env:TEMP = Join-Path $projectRoot 'cache\tmp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $projectRoot 'cache\pip'
$env:HF_HOME = Join-Path $projectRoot 'cache\huggingface'
$env:HF_XET_CACHE = Join-Path $projectRoot 'cache\huggingface\xet'
New-Item -ItemType Directory -Force -Path $env:TEMP, $env:PIP_CACHE_DIR, $env:HF_HOME | Out-Null
& $pythonExe -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'requirements-speech.txt')
if ($LASTEXITCODE -ne 0) { throw 'Speech dependencies failed to install.' }
& $pythonExe -m triloa.install_speech_model
if ($LASTEXITCODE -ne 0) { throw 'Speech model failed to install.' }
Write-Host 'Speech prototype setup is complete.'
