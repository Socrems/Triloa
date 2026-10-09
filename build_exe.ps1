param([ValidateSet("Full", "Common")][string]$Profile = "Full")
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = [System.IO.Path]::GetFullPath($projectRoot).TrimEnd('\')
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run setup.ps1 first.' }

$cacheRoot = Join-Path $projectRoot 'cache'
$env:TEMP = Join-Path $cacheRoot 'tmp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $cacheRoot 'pip'
$env:PYINSTALLER_CONFIG_DIR = Join-Path $cacheRoot 'pyinstaller\config'
$env:PYTHONDONTWRITEBYTECODE = '1'
foreach ($dir in @($env:TEMP, $env:PIP_CACHE_DIR, $env:PYINSTALLER_CONFIG_DIR)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

$distRoot = Join-Path $projectRoot 'dist'
$bundleName = if ($Profile -eq 'Common') { 'Triloa-Common' } else { 'Triloa' }
$bundleDir = Join-Path $distRoot $bundleName
$workDir = Join-Path $cacheRoot 'pyinstaller\build'
$specDir = Join-Path $cacheRoot 'pyinstaller\spec'
foreach ($target in @($distRoot, $bundleDir, $workDir, $specDir)) {
    $full = [System.IO.Path]::GetFullPath($target)
    if (-not $full.StartsWith($projectRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe build path outside project: $full"
    }
}

& $pythonExe -B -c 'import PyInstaller'
if ($LASTEXITCODE -ne 0) {
    & $pythonExe -m pip install --disable-pip-version-check --no-input 'pyinstaller>=6,<7'
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed.' }
}

$args = @(
    '--noconfirm', '--onedir', '--windowed',
    '--name', $bundleName,
    '--icon', (Join-Path $projectRoot 'assets\triloa.ico'),
    '--distpath', $distRoot,
    '--workpath', $workDir,
    '--specpath', $specDir,
    '--hidden-import', 'triloa.desktop',
    '--hidden-import', 'triloa.subtitles',
    '--hidden-import', 'triloa.speech',
    '--hidden-import', 'triloa.nemotron',
    '--hidden-import', 'triloa.local_websocket',
    '--hidden-import', 'triloa.ocr',
    '--hidden-import', 'triloa.selftest',
    '--hidden-import', 'argostranslate.translate',
    '--hidden-import', 'soundcard',
    '--collect-all', 'rapidocr',
    '--collect-all', 'faster_whisper',
    '--collect-all', 'ctranslate2',
    '--collect-all', 'onnxruntime',
    (Join-Path $projectRoot 'triloa_gui.py')
)
& $pythonExe -m PyInstaller @args
if ($LASTEXITCODE -ne 0) { throw 'Triloa EXE build failed.' }

function Add-ResourceTree {
    param([string]$Source, [string]$Destination)
    $sourceRoot = (Resolve-Path -LiteralPath $Source).Path.TrimEnd('\')
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    foreach ($file in Get-ChildItem -LiteralPath $sourceRoot -Recurse -File) {
        $relative = $file.FullName.Substring($sourceRoot.Length).TrimStart('\')
        if ($relative -match '(^|[\\/])\.cache([\\/]|$)') { continue }
        $target = Join-Path $Destination $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        try {
            New-Item -ItemType HardLink -Path $target -Target $file.FullName -ErrorAction Stop | Out-Null
        }
        catch {
            Copy-Item -LiteralPath $file.FullName -Destination $target -Force
        }
    }
}

if ($Profile -eq 'Common') {
    foreach ($model in @('hy-mt', 'nemotron')) {
        $source = Join-Path $projectRoot ('models\' + $model)
        if (-not (Test-Path -LiteralPath $source)) { throw "Required Common model missing: $source" }
        Add-ResourceTree $source (Join-Path $bundleDir ('models\' + $model))
    }
} else {
    Add-ResourceTree (Join-Path $projectRoot 'models') (Join-Path $bundleDir 'models')
}
Add-ResourceTree (Join-Path $projectRoot 'runtime\llama') (Join-Path $bundleDir 'runtime\llama')
$nemoRuntime = Join-Path $projectRoot 'runtime\nemo-speech'
if (Test-Path -LiteralPath $nemoRuntime) {
    Add-ResourceTree $nemoRuntime (Join-Path $bundleDir 'runtime\nemo-speech')
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'extension') -Destination $bundleDir -Recurse -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'assets') -Destination $bundleDir -Recurse -Force
Copy-Item -LiteralPath (Join-Path $projectRoot 'README.md') -Destination $bundleDir -Force
foreach ($noticeFile in @('LICENSE', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $noticeFile) -Destination $bundleDir -Force
}
foreach ($dir in @('cache\tmp', 'downloads')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $bundleDir $dir) | Out-Null
}
$exe = Join-Path $bundleDir ($bundleName + '.exe')
if (-not (Test-Path -LiteralPath $exe)) { throw 'Triloa.exe was not produced.' }
Set-Content -LiteralPath (Join-Path $bundleDir 'package-profile.txt') -Value $Profile -Encoding UTF8
Write-Host "Folder build complete ($Profile): $bundleDir"
Write-Host 'Resources are hard-linked when supported on the same volume to avoid duplicate storage.'
Write-Host 'Copy the whole folder if moving it elsewhere.'
