"""Triloa: local translation tools for Windows."""

__version__ = "0.1.4"

# The optional CUDA wheel lives beside the source checkout, without replacing
# the CPU environment used for portable builds. Activate it only after setup
# verified CUDA, and only for the Python ABI that installed it.
import json as _json
import os as _os
from pathlib import Path as _Path
import sys as _sys

if not getattr(_sys, "frozen", False) and _os.environ.get("TRILOA_CPU_RUNTIME") != "1":
    _cuda_runtime = _Path(__file__).resolve().parent.parent / "runtime/qwen-cuda"
    try:
        _ready = _json.loads((_cuda_runtime / "runtime-ready.json").read_text(encoding="utf-8"))
        if isinstance(_ready, dict) and _ready.get("python") == list(_sys.version_info[:2]) and (_cuda_runtime / "torch/__init__.py").is_file():
            _sys.path.insert(0, str(_cuda_runtime))
    except (OSError, ValueError):
        pass
