"""Offline English/Japanese to Chinese through HY-MT or Argos."""

from __future__ import annotations

import os
import re
from hashlib import sha256
from uuid import uuid4
from pathlib import Path
from threading import Condition
from contextlib import contextmanager
from time import monotonic
from collections import OrderedDict

_condition = Condition()
_waiting = []
_active = False
_requests = 0
_serial = 0
_sessions = 0
_cache = OrderedDict()
_model_instance = uuid4().hex
_model_revision = 0


def model_identity() -> str:
    """Opaque cache identity, including model changes and service restarts."""
    with _condition:
        backend = selected_backend()
        model = qwen_model() if backend == 'qwen' else None
        identity = f'{_model_instance}\0{_model_revision}\0{backend}\0{model}'
        return sha256(identity.encode('utf-8')).hexdigest()


@contextmanager
def model_session():
    """Keep the response identity and its translation on the same model."""
    begin_subtitle_session()
    try:
        yield model_identity()
    finally:
        end_subtitle_session()


def selected_backend():
    from . import preferences
    return os.getenv('TRILOA_TRANSLATOR', preferences.get('translation.backend', 'auto')).lower()


def qwen_model():
    from . import preferences
    from .paths import MODELS
    configured = preferences.get('translation.qwen_path')
    if configured:
        path = Path(configured)
        if path.is_file():
            return path
    return next(iter(sorted((MODELS / 'qwen3').glob('*.gguf'))), None)


def set_backend(backend, qwen_path=None):
    global _model_revision
    from . import preferences
    if backend not in {'auto', 'hy', 'qwen'}:
        raise ValueError('不支持的翻译模型')
    with _condition:
        if _requests or _active or _sessions or _waiting:
            raise RuntimeError('请先停止字幕并等待当前翻译结束，再切换模型')
        if os.getenv('TRILOA_TRANSLATOR'):
            raise RuntimeError('当前由 TRILOA_TRANSLATOR 环境变量指定模型，请取消该变量后切换')
        if qwen_path:
            path = Path(qwen_path)
            with path.open('rb') as stream:
                if stream.read(4) != b'GGUF':
                    raise ValueError('请选择有效的 GGUF 模型文件')
            preferences.put('translation.qwen_path', str(path.resolve()))
        if backend == 'qwen' and qwen_model() is None:
            raise RuntimeError('请先选择已下载的 Qwen3 GGUF 文件')
        preferences.put('translation.backend', backend)
        _cache.clear()
        _model_revision += 1


def begin_subtitle_session():
    global _sessions
    with _condition:
        if selected_backend() == 'qwen' and qwen_model() is None:
            raise RuntimeError('Qwen3 模型文件不存在，请重新选择')
        _sessions += 1


def end_subtitle_session():
    global _sessions
    with _condition:
        _sessions = max(0, _sessions - 1)


class TranslationCancelled(RuntimeError):
    pass

def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise TranslationCancelled('已取消翻译')

@contextmanager
def translation_turn(priority=10, cancel=None):
    """Serialize native inference, yield between chunks, age waiting work fairly."""
    global _serial, _active
    with _condition:
        _serial += 1
        ticket = (priority, monotonic(), _serial)
        _waiting.append(ticket)
        try:
            while True:
                check_cancel(cancel)
                now = monotonic()
                first = min(_waiting, key=lambda t: (0 if now - t[1] >= 3 else t[0], t[2]))
                if not _active and first == ticket:
                    break
                _condition.wait(0.1)
            _waiting.remove(ticket)
            _active = True
        except BaseException:
            _waiting.remove(ticket)
            _condition.notify_all()
            raise
    try:
        yield
    finally:
        with _condition:
            _active = False
            _condition.notify_all()


def detect_source(text: str) -> str:
    if any("\u3040" <= char <= "\u30ff" or "\u4e00" <= char <= "\u9fff" for char in text):
        return "ja"
    return "en"


def _chunks(text: str, limit: int = 450) -> list[str]:
    """Split on sentence and word boundaries without cutting decimal numbers."""
    sentences = re.split(r"(?<=[。！？；])|(?<=[.!?;])(?=\s+|$)", text.strip())
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        while sentence:
            room = limit - len(current)
            separator = " " if current and current[-1].isascii() and sentence[0].isascii() else ""
            if len(sentence) + len(separator) <= room:
                current += separator + sentence
                break
            if current:
                chunks.append(current)
                current = ""
                continue
            split_at = max(sentence.rfind(" ", 0, limit + 1), sentence.rfind("、", 0, limit + 1))
            if split_at < limit // 2:
                split_at = limit
            chunks.append(sentence[:split_at].rstrip())
            sentence = sentence[split_at:].lstrip()
    if current:
        chunks.append(current)
    return chunks


def _argos(texts: list[str], source: str) -> list[str]:
    try:
        from argostranslate import translate
    except ImportError as exc:
        raise RuntimeError("尚未安装离线翻译引擎。请先运行安装脚本。") from exc

    languages = {item.code for item in translate.get_installed_languages()}
    results = []
    for text in texts:
        if not text.strip():
            results.append("")
            continue
        actual_source = detect_source(text) if source == "auto" else source
        if actual_source == "en" and not {"en", "zh"} <= languages:
            raise RuntimeError("缺少英语→中文离线模型。请运行模型安装脚本。")
        if actual_source == "ja" and not {"ja", "en", "zh"} <= languages:
            raise RuntimeError("缺少日语→英语或英语→中文离线模型。请运行模型安装脚本。")
        try:
            if actual_source == "ja":
                intermediate = translate.translate(text, "ja", "en")
                results.append(translate.translate(intermediate, "en", "zh"))
            else:
                results.append(translate.translate(text, "en", "zh"))
        except Exception as exc:
            raise RuntimeError(f"本地翻译失败：{exc}") from exc
    return results


def translate_preserving_paragraphs(text: str, source: str = "auto", *, cancel=None, on_progress=None) -> str:
    """Translate paragraph text while keeping blank-line separators."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    pieces = re.split(r"(\n(?:[ \t]*\n)+)", normalized)
    blocks = []
    for index, piece in enumerate(pieces):
        if index % 2 or not piece.strip():
            continue
        lines = [line.strip() for line in piece.split("\n") if line.strip()]
        merged = ""
        for line in lines:
            if merged and merged[-1].isascii() and merged[-1].isalnum() and line[0].isascii() and line[0].isalnum():
                merged += " "
            merged += line
        blocks.append(merged)
    translated = iter(translate_texts(blocks, source, cancel=cancel, on_progress=on_progress))
    result = []
    for index, piece in enumerate(pieces):
        if index % 2:
            result.append("\n" * piece.count("\n"))
        elif piece.strip():
            result.append(next(translated).strip())
        else:
            result.append(piece)
    return "".join(result)


def prepare_translator(cancel=None) -> None:
    """Prime a real local translation before audio capture begins."""
    translate_texts(["Hello"], source="en", target="zh", priority=0, cancel=cancel, use_cache=False)


def release_translator() -> None:
    """Do not unload a model used by another feature or a queued request."""
    global _active
    with _condition:
        if _requests or _active or _waiting or _sessions:
            return
        _active = True
    try:
        from . import hy_mt
        hy_mt.stop_owned_server()
    finally:
        with _condition:
            _active = False
            _condition.notify_all()


def translate_texts(texts: list[str], source: str = "auto", target: str = "zh", *, priority=10, cancel=None, on_progress=None, use_cache=True, is_obsolete=None) -> list[str]:
    global _requests
    if source not in {"auto", "en", "ja"} or target != "zh":
        raise ValueError("目前仅支持英文或日文翻译为中文")
    with _condition:
        backend = selected_backend()
        model = qwen_model() if backend == "qwen" else None
        _requests += 1
    if backend not in {"auto", "argos", "hy", "qwen"}:
        with _condition:
            _requests -= 1
        raise ValueError("TRILOA_TRANSLATOR 只能是 auto、argos、hy 或 qwen")
    from . import hy_mt
    from .diagnostics import report_error
    chunks = [_chunks(text) if text.strip() else [] for text in texts]
    total = sum(map(len, chunks))
    done = 0
    result = []
    try:
        for pieces in chunks:
            translated = []
            for part in pieces:
                with translation_turn(priority, cancel):
                    check_cancel(cancel)
                    if is_obsolete is not None and is_obsolete():
                        raise TranslationCancelled("草稿已被新识别结果替代")
                    key = (backend, str(model), source, part)
                    if use_cache and key in _cache:
                        value = _cache[key]
                        _cache.move_to_end(key)
                    else:
                        fallback = False
                        if backend == 'qwen':
                            value = hy_mt.translate(part, cancel=cancel, backend='qwen', model=model)
                        elif backend != 'argos' and (backend == 'hy' or hy_mt.available()):
                            try:
                                value = hy_mt.translate(part, cancel=cancel)
                            except TranslationCancelled:
                                raise
                            except RuntimeError as exc:
                                if backend == 'hy':
                                    raise
                                report_error('HY-MT 回退到备用翻译', exc)
                                check_cancel(cancel)
                                value = _argos([part], source)[0]
                                fallback = True
                        else:
                            value = _argos([part], source)[0]
                        check_cancel(cancel)
                        if not fallback:
                            _cache[key] = value
                            while len(_cache) > 256:
                                _cache.popitem(last=False)
                    translated.append(value)
                done += 1
                if on_progress:
                    on_progress(done, total)
            result.append(''.join(translated))
        check_cancel(cancel)
        return result
    finally:
        with _condition:
            _requests -= 1
            _condition.notify_all()
