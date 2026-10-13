$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run setup.ps1 first.' }
$env:TEMP = Join-Path $projectRoot 'cache\tmp'
$env:TMP = $env:TEMP
$env:TMPDIR = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $projectRoot 'cache\pip'
$env:CUDA_CACHE_PATH = Join-Path $projectRoot 'cache\cuda'
$env:TORCHINDUCTOR_CACHE_DIR = Join-Path $projectRoot 'cache\torchinductor'
$cudaTarget = Join-Path $projectRoot 'runtime\qwen-cuda'
New-Item -ItemType Directory -Force -Path $env:TEMP, $env:PIP_CACHE_DIR, $cudaTarget | Out-Null
& $pythonExe -m pip install --disable-pip-version-check --no-input -r (Join-Path $projectRoot 'requirements-qwen-asr.txt')
if ($LASTEXITCODE -ne 0) { throw 'Qwen3-ASR dependencies failed to install.' }
if (-not (Test-Path -LiteralPath (Join-Path $cudaTarget 'runtime-ready.json'))) {
    & $pythonExe -m pip install --disable-pip-version-check --no-input --target $cudaTarget --upgrade --no-deps 'torch==2.14.0+cu130' --index-url https://download.pytorch.org/whl/cu130
    if ($LASTEXITCODE -ne 0) { throw 'CUDA wheel installation failed. Existing CPU environment is retained.' }
}
& $pythonExe -B -c 'import json,pathlib,sys; sys.path.insert(0,sys.argv[1]); import torch; assert torch.cuda.is_available(), "CUDA is unavailable: check the NVIDIA driver"; torch.ones(1,device="cuda").cpu(); result={"python":list(sys.version_info[:2]),"torch":torch.__version__,"cuda":torch.version.cuda,"gpu":torch.cuda.get_device_name(0)}; pathlib.Path(sys.argv[1],"runtime-ready.json").write_text(json.dumps(result,indent=2),encoding="utf-8"); print(json.dumps(result))' $cudaTarget
if ($LASTEXITCODE -ne 0) { throw 'CUDA verification failed. Check the NVIDIA driver and available GPU memory.' }
Write-Host 'CUDA runtime ready. Exit the old Triloa instance, then run run.ps1. Source Triloa automatically uses this runtime.'
