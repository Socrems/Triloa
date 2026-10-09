$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run setup.ps1 and setup_speech.ps1 first.' }
Set-Location -LiteralPath $projectRoot
& $pythonExe -m triloa.subtitles
