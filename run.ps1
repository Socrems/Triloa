$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw '尚未安装，请先运行 .\setup.ps1' }
Set-Location -LiteralPath $projectRoot
& $pythonExe -m triloa
