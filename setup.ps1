param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $projectRoot
$env:TEMP = Join-Path $projectRoot 'cache\tmp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $projectRoot 'cache\pip'
$env:XDG_DATA_HOME = Join-Path $projectRoot 'data'
$env:XDG_CONFIG_HOME = Join-Path $projectRoot 'data\config'
$env:XDG_CACHE_HOME = Join-Path $projectRoot 'cache'
$env:ARGOS_PACKAGES_DIR = Join-Path $projectRoot 'models\argos'
$env:HF_HOME = Join-Path $projectRoot 'cache\huggingface'
$env:HUGGINGFACE_HUB_CACHE = Join-Path $env:HF_HOME 'hub'
$env:HF_XET_CACHE = Join-Path $env:HF_HOME 'xet'
New-Item -ItemType Directory -Force -Path $env:TEMP, $env:PIP_CACHE_DIR, $env:ARGOS_PACKAGES_DIR | Out-Null
$pythonCheck = 'import sys; sys.exit(0 if (3, 11) <= sys.version_info[:2] < (3, 14) and sys.maxsize > 2**32 else 1)'
if (-not (Test-Path (Join-Path $projectRoot '.venv\Scripts\python.exe'))) {
    $basePython = (Get-Command -Name $Python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    & $basePython -c $pythonCheck
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11-3.13 x64 is required. Specify it with -Python.' }
    & $basePython -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败' }
}
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
& $pythonExe -c $pythonCheck
if ($LASTEXITCODE -ne 0) { throw 'The existing virtual environment must use Python 3.11-3.13 x64.' }
& $pythonExe -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }
& $pythonExe -m triloa.install_models
if ($LASTEXITCODE -ne 0) { throw '模型安装失败' }
Write-Host '安装完成。运行 .\run.ps1 启动 Triloa。'
