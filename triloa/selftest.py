"""Offline checks for a packaged folder build; writes results under its cache."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .paths import CACHE, MODELS, ROOT


def run() -> int:
    results: dict[str, str] = {}

    profile_file = ROOT / "package-profile.txt"
    common = profile_file.exists() and profile_file.read_text(encoding="utf-8-sig").strip() == "Common"
    for size in ("base", "small"):
        if common and not (MODELS / "faster-whisper" / size).exists():
            results[f"whisper_{size}"] = "ok: excluded by Common profile"
            continue
        try:
            from .speech import SpeechSubtitleRunner

            SpeechSubtitleRunner(
                model_path=MODELS / "faster-whisper" / size
            )._load_model()
            results[f"whisper_{size}"] = "ok"
        except Exception as exc:
            results[f"whisper_{size}"] = f"{type(exc).__name__}: {exc}"

    try:
        from .nemotron import (
            NEMOTRON_EXECUTABLE_PATH, NEMOTRON_MODEL_PATH, nemotron_available,
        )

        if nemotron_available():
            environment = os.environ.copy()
            environment["NEMO_SPEECH_MODEL_DIR"] = str(MODELS / "nemotron")
            process = subprocess.run(
                [str(NEMOTRON_EXECUTABLE_PATH), "model", "info", str(NEMOTRON_MODEL_PATH)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=20, env=environment, check=True,
            )
            model_info = json.loads(process.stdout)
            if not model_info.get("runtime_compatible"):
                raise RuntimeError("Nemotron model is incompatible with the local runtime")
            results["nemotron"] = "ok: local model and runtime compatible"
        else:
            results["nemotron"] = "ok: optional model not installed"
    except Exception as exc:
        results["nemotron"] = f"{type(exc).__name__}: {exc}"

    try:
        from PIL import Image
        from .ocr import recognize

        image_path = CACHE / "tmp" / "packaging-ocr-check.png"
        Image.new("RGB", (320, 100), "white").save(image_path)
        try:
            recognize(image_path)
        finally:
            image_path.unlink(missing_ok=True)
        results["ocr"] = "ok"
    except Exception as exc:
        results["ocr"] = f"{type(exc).__name__}: {exc}"

    try:
        from .speech import list_loopback_devices

        devices = list_loopback_devices()
        results["audio_loopback"] = f"ok: {len(devices)} device(s)"
    except Exception as exc:
        results["audio_loopback"] = f"{type(exc).__name__}: {exc}"

    report = CACHE / "packaging-selftest.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(value.startswith("ok") for value in results.values()) else 1
