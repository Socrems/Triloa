"""Offline checks for a packaged folder build; writes results under D: cache."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .paths import CACHE, MODELS, ROOT, portable


def _portable_check() -> int:
    """Check a fresh portable folder without downloading or requiring models."""
    from . import __version__
    from .resources import ResourceManager, ocr_model_paths
    results = {'version': __version__, 'profile': 'Portable'}
    try:
        from PySide6.QtWidgets import QApplication
        from .resource_setup import ResourceSetupDialog
        from .ui_style import apply_app_style
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        app = QApplication.instance() or QApplication([])
        apply_app_style(app)
        dialog = ResourceSetupDialog(first_run=True)
        dialog.show()
        app.processEvents()
        dialog.grab().save(str(CACHE / 'packaging-onboarding.png'))
        dialog.deleteLater()
        results['onboarding'] = 'ok'
        from argostranslate import translate
        from faster_whisper import WhisperModel
        from rapidocr import RapidOCR
        from ._vendor.qwen3_asr import Qwen3ASRForConditionalGeneration, Qwen3ASRProcessor
        results['dependencies'] = 'ok'
        from .qwen_asr import QwenASRSpeechSubtitleRunner, model_ready
        if model_ready(MODELS / 'qwen3-asr'):
            runner = QwenASRSpeechSubtitleRunner(model_path=MODELS / 'qwen3-asr')
            loaded = runner._load_model()
            prompt = loaded.processor.apply_chat_template(
                [{'role':'system','content':''}, {'role':'user','content':[{'type':'audio','audio':''}]}],
                add_generation_prompt=True, tokenize=False)
            import numpy as np
            inputs = loaded.processor(text=[prompt], audio=[np.zeros(16000, dtype=np.float32)],
                                      sampling_rate=16000, return_tensors='pt', padding=True)
            assert inputs['input_ids'].shape[1] > 0
            del inputs, loaded
            results['qwen_asr'] = 'ok: local model and audio processor loaded offline'
        else:
            results['qwen_asr'] = 'ok: runtime present; optional model deferred to setup'
        manager = ResourceManager()
        if manager.ready('basic'):
            from .translator import _argos
            value = _argos(['Hello world.'], 'en')[0]
            assert value.strip()
            from PIL import Image
            image = CACHE / 'tmp/packaging-ocr-check.png'
            Image.new('RGB', (320, 100), 'white').save(image)
            try:
                from .ocr import recognize
                recognize(image)
            finally:
                image.unlink(missing_ok=True)
            results['basic'] = 'ok: translation and OCR loaded offline'
        else:
            try:
                ocr_model_paths()
            except RuntimeError:
                pass
            results['basic'] = 'ok: resources deferred to setup'
        if manager.ready('subtitles'):
            import numpy as np
            from .speech import SpeechSubtitleRunner
            model = SpeechSubtitleRunner()._load_model()
            segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language='en', vad_filter=True)
            list(segments)
            results['subtitles'] = 'ok: base and VAD loaded offline'
        else:
            results['subtitles'] = 'ok: resources deferred to setup'
        server = ROOT / 'runtime/llama/llama-server.exe'
        if server.is_file():
            process = subprocess.run([str(server), '--version'], cwd=server.parent, capture_output=True,
                                     timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            assert process.returncode == 0, process.stderr.decode('utf-8', 'replace')
            results['llama_cpu'] = 'ok'
    except Exception as exc:
        results['error'] = f'{type(exc).__name__}: {exc}'
    report = CACHE / 'packaging-selftest.json'
    report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    return 1 if 'error' in results else 0


def run() -> int:
    if portable():
        return _portable_check()
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
