"""Keep application data and third-party caches under the project root."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)
_data_default = (
    ROOT.parent.parent / "data" if getattr(sys, "frozen", False) and ROOT.parent.name.lower() == "dist"
    else ROOT.parent / (ROOT.name + "Data") if getattr(sys, "frozen", False)
    else ROOT / "data"
)
DATA = Path(os.environ.get("TRILOA_DATA_DIR", str(_data_default)))
CACHE = ROOT / "cache"
MODELS = ROOT / "models"
DOWNLOADS = ROOT / "downloads"


def configure_paths() -> None:
    for path in (DATA, CACHE, MODELS, DOWNLOADS, CACHE / "tmp", CACHE / "pip"):
        path.mkdir(parents=True, exist_ok=True)

    paths = {
        "TMP": CACHE / "tmp",
        "TEMP": CACHE / "tmp",
        "TMPDIR": CACHE / "tmp",
        "PIP_CACHE_DIR": CACHE / "pip",
        "XDG_DATA_HOME": DATA,
        "XDG_CONFIG_HOME": DATA / "config",
        "XDG_CACHE_HOME": CACHE,
        "ARGOS_PACKAGES_DIR": MODELS / "argos",
        "HF_HOME": CACHE / "huggingface",
        "HUGGINGFACE_HUB_CACHE": CACHE / "huggingface" / "hub",
        "HF_XET_CACHE": CACHE / "huggingface" / "xet",
        "TORCH_HOME": CACHE / "torch",
    }
    for key, path in paths.items():
        os.environ[key] = str(path)
    os.environ["ARGOS_DEVICE_TYPE"] = "cpu"
    os.environ["ARGOS_CHUNK_TYPE"] = "MINISBD"
