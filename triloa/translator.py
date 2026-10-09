"""Shared offline translation through built-in or user-selected local models."""

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
        model = selected_local_model() if backend == 'custom' else qwen_model() if backend == 'qwen' else None
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
    value = os.getenv('TRILOA_TRANSLATOR') or preferences.get('translation.backend', 'auto')
    return value.lower() if isinstance(value, str) else 'auto'


def qwen_model():
    from . import preferences
    from .paths import MODELS
    configured = preferences.get('translation.qwen_path')
    if configured:
        if not isinstance(configured, str):
            return None
        path = Path(configured)
        return path if path.is_file() else None
    return next(iter(sorted((MODELS / 'qwen3').glob('*.gguf'))), None)


def _check_model_change():
    if _requests or _active or _sessions or _waiting:
        raise RuntimeError('请先停止字幕并等待当前翻译结束，再修改或切换模型')
    if os.getenv('TRILOA_TRANSLATOR'):
        raise RuntimeError('当前由 TRILOA_TRANSLATOR 环境变量指定模型，请取消该变量后切换')


def model_busy() -> bool:
    with _condition:
        return bool(_requests or _active or _sessions or _waiting)


def selected_local_model():
    from . import preferences
    from .translation_models import registered_models
    identifier = preferences.get('translation.model_id')
    return next((model for model in registered_models() if model.id == identifier), None)


def model_label() -> str:
    backend = selected_backend()
    if backend == 'custom':
        model = selected_local_model()
        return model.name if model is not None else '自选模型 · 未找到记录'
    return {'auto': 'HY-MT / Argos 备用', 'hy': 'HY-MT',
            'qwen': 'Qwen', 'argos': 'Argos'}.get(backend, backend)


def _validate_selected_model(backend):
    if backend == 'qwen' and qwen_model() is None:
        raise RuntimeError('Qwen 模型文件不存在，请重新选择')
    if backend == 'custom':
        model = selected_local_model()
        if model is None:
            raise RuntimeError('未找到所选翻译模型，请重新添加或选择')
        if not model.path.is_file():
            raise RuntimeError(f'模型“{model.name}”的文件已移动或删除，请在模型设置中重新选择')


def _invalidate_model():
    global _model_revision
    _cache.clear()
    _model_revision += 1


def set_backend(backend, qwen_path=None, *, model_id=None):
    from . import preferences
    from .translation_models import registered_models, validate_gguf
    if backend not in {'auto', 'hy', 'qwen', 'argos', 'custom'}:
        raise ValueError('不支持的翻译模型')
    with _condition:
        _check_model_change()
        values = {'translation.backend': backend}
        if qwen_path:
            values['translation.qwen_path'] = str(validate_gguf(qwen_path))
        if backend == 'qwen' and not qwen_path and qwen_model() is None:
            raise RuntimeError('请先选择已下载的 Qwen3 GGUF 文件')
        if backend == 'custom':
            model = next((item for item in registered_models() if item.id == model_id), None)
            if model is None:
                raise ValueError('未找到所选模型记录')
            validate_gguf(model.path)
            values['translation.model_id'] = model.id
        preferences.update(values)
        _invalidate_model()


def save_local_model(path, name='', profile='generic', execution='auto', *, model_id=None):
    """Add or edit one record and select it, without copying any weights."""
    from . import preferences
    from .translation_models import LocalModel, PROFILES, EXECUTIONS, registered_models, same_path, validate_gguf
    if profile not in PROFILES or execution not in EXECUTIONS:
        raise ValueError('不支持的模型类型或运行方式')
    with _condition:
        _check_model_change()
        path = validate_gguf(path)
        records = registered_models()
        existing = next((item for item in records if item.id == model_id), None) if model_id else None
        if model_id and existing is None:
            raise ValueError('要修改的模型记录已不存在')
        duplicate = next((item for item in records if same_path(item.path, path) and item.id != model_id), None)
        if model_id and duplicate is not None:
            raise ValueError('此文件已经添加，请直接选择已有模型')
        existing = existing or duplicate
        identifier = existing.id if existing is not None else uuid4().hex
        model = LocalModel(identifier, (name.strip() or path.stem)[:80], path, profile, execution)
        updated = [model if item.id == identifier else item for item in records]
        if existing is None:
            updated.append(model)
        preferences.update({'translation.models': [item.record() for item in updated],
                            'translation.backend': 'custom', 'translation.model_id': identifier})
        _invalidate_model()
        return model


def remove_local_model(identifier):
    """Remove a saved choice, never the model file itself."""
    from . import preferences
    from .translation_models import registered_models
    with _condition:
        _check_model_change()
        records = registered_models()
        remaining = [item.record() for item in records if item.id != identifier]
        if len(remaining) == len(records):
            return
        values = {'translation.models': remaining}
        if selected_backend() == 'custom' and preferences.get('translation.model_id') == identifier:
            values.update({'translation.backend': 'auto', 'translation.model_id': None})
            _invalidate_model()
        preferences.update(values)


def begin_subtitle_session():
    global _sessions
    with _condition:
        _validate_selected_model(selected_backend())
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
        model = selected_local_model() if backend == 'custom' else qwen_model() if backend == 'qwen' else None
        _requests += 1
    if backend not in {"auto", "argos", "hy", "qwen", "custom"}:
        with _condition:
            _requests -= 1
        raise ValueError("TRILOA_TRANSLATOR 只能是 auto、argos、hy、qwen 或 custom")
    from . import hy_mt
    from .diagnostics import report_error
    chunks = [_chunks(text) if text.strip() else [] for text in texts]
    total = sum(map(len, chunks))
    done = 0
    result = []
    try:
        _validate_selected_model(backend)
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
                        if backend == 'custom':
                            value = hy_mt.translate(part, cancel=cancel, backend='custom', model=model.path,
                                                    profile=model.profile, execution=model.execution, label=model.name)
                        elif backend == 'qwen':
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
                            hy_mt.stop_owned_server()
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
