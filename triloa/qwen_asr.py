"""Local Qwen3-ASR recognition using the official Transformers model classes."""
from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec
import json
from pathlib import Path
import re

from . import preferences
from .paths import MODELS, ROOT, configure_paths
from .speech import SAMPLE_RATE, SpeechSubtitleRunner, _Utterance

QWEN_ASR_MODEL_PATH = MODELS / "qwen3-asr"
_REQUIRED = ("config.json", "preprocessor_config.json", "tokenizer_config.json",
             "vocab.json", "merges.txt", "chat_template.json")
_LANGUAGES = {"en": "English", "ja": "Japanese"}


def model_path() -> Path:
    saved = preferences.get("speech.qwen_asr_path")
    if not saved:
        return QWEN_ASR_MODEL_PATH
    path = Path(saved)
    return path if path.is_absolute() else ROOT / path


def select_model_folder(folder: Path | str) -> Path:
    folder = validate_model_folder(folder)
    saved = str(folder.relative_to(ROOT)) if folder.is_relative_to(ROOT) else str(folder)
    preferences.put("speech.qwen_asr_path", saved)
    return folder


def runtime_available() -> bool:
    return all(find_spec(name) is not None for name in ("torch", "transformers", "accelerate"))


def validate_model_folder(folder: Path | str) -> Path:
    """Check local files and safetensors boundaries without loading weights or code."""
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise ValueError("请选择完整的 Qwen3-ASR-0.6B 模型目录。")
    missing = [name for name in _REQUIRED if not (folder / name).is_file() or not (folder / name).stat().st_size]
    if missing:
        raise ValueError("模型目录不完整，缺少：" + "、".join(missing))
    try:
        config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
        if not isinstance(config, dict) or config.get("model_type") != "qwen3_asr":
            raise ValueError("该目录不是 Qwen3-ASR 语音识别模型，不能使用文本 Qwen 或 GGUF。")
        for name in ("preprocessor_config.json", "tokenizer_config.json", "chat_template.json"):
            json.loads((folder / name).read_text(encoding="utf-8"))
        weights = [folder / "model.safetensors"]
        if not weights[0].is_file():
            index = json.loads((folder / "model.safetensors.index.json").read_text(encoding="utf-8"))
            names = set(index["weight_map"].values())
            if not names or any(Path(name).name != name or not name.endswith(".safetensors") for name in names):
                raise ValueError("模型权重索引不正确。")
            weights = [folder / name for name in sorted(names)]
        for file in weights:
            size = file.stat().st_size
            with file.open("rb") as stream:
                length_bytes = stream.read(8)
                length = int.from_bytes(length_bytes, "little")
                if len(length_bytes) != 8 or not 2 <= length <= min(64 * 1024 * 1024, size - 8):
                    raise ValueError(f"权重文件未下载完整或格式错误：{file.name}")
                header = json.loads(stream.read(length))
            if not isinstance(header, dict):
                raise ValueError(f"权重文件格式错误：{file.name}")
            offsets = [value["data_offsets"] for key, value in header.items() if key != "__metadata__"]
            if not offsets or any(len(pair) != 2 or not 0 <= pair[0] <= pair[1] <= size - 8 - length for pair in offsets) or max(pair[1] for pair in offsets) != size - 8 - length:
                raise ValueError(f"权重文件未下载完整：{file.name}")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取完整模型文件：{exc}") from exc
    return folder


def model_ready(folder: Path | str) -> bool:
    try:
        validate_model_folder(folder)
    except (ValueError, OSError):
        return False
    return True


def parse_transcription(raw: str, forced_language: str | None = None) -> tuple[str, str]:
    raw = raw.strip()
    if not raw:
        return "", ""
    if forced_language:
        return forced_language, raw
    if "<asr_text>" not in raw:
        return "", raw
    metadata, text = raw.split("<asr_text>", 1)
    match = re.search(r"\blanguage\s+([^\n<]+)", metadata, re.I)
    language = match.group(1).strip() if match else ""
    if language.lower() == "none":
        return "", ""
    code = {"english": "en", "japanese": "ja"}.get(language.lower(), language.lower())
    return code, text.strip()


@dataclass
class _Model:
    model: object
    processor: object
    device: str


class QwenASRSpeechSubtitleRunner(SpeechSubtitleRunner):
    """Reuse WASAPI capture, bounded draft/final queues and translation scheduling."""

    def _load_model(self) -> _Model:
        configure_paths()
        try:
            folder = validate_model_folder(self.model_path)
        except ValueError as exc:
            raise RuntimeError(f"Qwen3-ASR 模型不可用：{exc}\n请打开资源管理下载，或选择完整的本地目录。") from exc
        if not runtime_available():
            raise RuntimeError("缺少 Qwen3-ASR 运行依赖。源码版请运行 setup_qwen_asr.ps1；便携版请使用 v0.1.3 或更新的完整包。")
        try:
            import torch
            from ._vendor.qwen3_asr import Qwen3ASRForConditionalGeneration, Qwen3ASRProcessor
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
            self.inference_device = device
            dtype = (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16) if device.startswith("cuda") else torch.float32
            self.on_status and self.on_status(f"正在加载 Qwen3-ASR-0.6B · {'CUDA' if device.startswith('cuda') else 'CPU'}…")
            model = Qwen3ASRForConditionalGeneration.from_pretrained(
                str(folder), dtype=dtype, device_map=device,
                attn_implementation="sdpa", local_files_only=True, use_safetensors=True,
            ).eval()
            processor = Qwen3ASRProcessor.from_pretrained(str(folder), local_files_only=True, fix_mistral_regex=True)
            return _Model(model, processor, device)
        except Exception as exc:
            raise RuntimeError(f"无法加载 Qwen3-ASR：{exc}\n请检查模型是否完整，以及可用内存。") from exc

    def _transcribe(self, loaded: _Model, utterance: _Utterance) -> tuple[str, str]:
        import numpy as np
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList

        stop, runner = self.stop_event, self
        class StopRequested(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return stop.is_set() or (not utterance.final and runner._partial_is_stale(utterance))

        audio = np.asarray(utterance.audio, dtype=np.float32)
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        if not audio.size or stop.is_set():
            return "", ""
        forced = None if self.language == "auto" else _LANGUAGES[self.language]
        messages = [{"role": "system", "content": ""},
                    {"role": "user", "content": [{"type": "audio", "audio": ""}]}]
        prompt = loaded.processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        if forced:
            prompt += f"language {forced}<asr_text>"
        with torch.inference_mode():
            inputs = loaded.processor(text=[prompt], audio=[audio], sampling_rate=SAMPLE_RATE,
                                      return_tensors="pt", padding=True)
            inputs = inputs.to(loaded.model.device).to(loaded.model.dtype)
            output = loaded.model.generate(**inputs, max_new_tokens=512, do_sample=False,
                                           stopping_criteria=StoppingCriteriaList([StopRequested()]))
            if stop.is_set() or (not utterance.final and self._partial_is_stale(utterance)):
                return "", ""
            raw = loaded.processor.batch_decode(output.sequences[:, inputs["input_ids"].shape[1]:],
                                                skip_special_tokens=True, clean_up_tokenization_spaces=False)[0]
        language, text = parse_transcription(raw, None if self.language == "auto" else self.language)
        return text, language
