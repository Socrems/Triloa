"""Explicit, cancellable installation of the resources used by the desktop app.

No network request is made while importing this module or checking readiness.
Model versions, byte counts and SHA256 digests are pinned together.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from http.client import HTTPException
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock
from time import monotonic
from urllib.request import Request, urlopen
import zipfile

from .paths import DATA, DOWNLOADS, MODELS, ROOT, portable


class InstallationCancelled(Exception):
    pass


class ResourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Resource:
    id: str
    label: str
    feature: str
    url: str
    relative_path: str
    size: int
    digest: str
    area: str = "models"
    pair: tuple[str, str] | None = None


_OCR = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.2/onnx/"
_WHISPER = "https://huggingface.co/Systran/faster-whisper-base/resolve/ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66/"
_SBD = "https://github.com/LibreTranslate/MiniSBD/releases/download/v0.0.1/"
_QWEN_ASR = "https://huggingface.co/Qwen/Qwen3-ASR-0.6B/resolve/5eb144179a02acc5e5ba31e748d22b0cf3e303b0/"
RESOURCES = (
    Resource("argos-en", "英语 → 中文", "basic", "https://argos-net.com/v1/translate-en_zh-1_9.argosmodel", "translate-en_zh-1_9.argosmodel", 70743021, "433e7c4f034d87fbe2353161e05f18646d7999452f801a4e1f0378522b9850ab", pair=("en", "zh")),
    Resource("argos-ja", "日语 → 英语（转译中文）", "basic", "https://argos-net.com/v1/translate-ja_en-1_1.argosmodel", "translate-ja_en-1_1.argosmodel", 117155716, "623e3477959a815eb0a5ef53e09079ae8f1f9d3bbcd230473baf28c03fb83335", pair=("ja", "en")),
    Resource("sbd-en", "英语断句", "basic", _SBD + "en.onnx", "argos-translate/minisbd/en.onnx", 188043, "6fa9f3a3b201687bd43e329b2b0736789efc97b37883b5b759b31988dca9f353", area="data"),
    Resource("sbd-ja", "日语断句", "basic", _SBD + "ja.onnx", "argos-translate/minisbd/ja.onnx", 698618, "5ef874606b0afe24cc799b737ba1d9c09259e80ddee7646fc557a8f9e0e1017c", area="data"),
    Resource("ocr-det", "OCR 文字检测", "basic", _OCR + "PP-OCRv6/det/PP-OCRv6_det_small.onnx", "ocr/PP-OCRv6_det_small.onnx", 9929594, "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f"),
    Resource("ocr-cls", "OCR 文字方向", "basic", _OCR + "PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile.onnx", "ocr/ch_ppocr_mobile_v2.0_cls_mobile.onnx", 585532, "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"),
    Resource("ocr-rec", "OCR 文字识别", "basic", _OCR + "PP-OCRv6/rec/PP-OCRv6_rec_small.onnx", "ocr/PP-OCRv6_rec_small.onnx", 21234383, "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884"),
    Resource("whisper-config", "Whisper 配置", "subtitles", _WHISPER + "config.json", "faster-whisper/base/config.json", 2309, "56a6d8110d311f19c8f0471e562832c7527f146b567275bfca59fcf7c184da9a"),
    Resource("whisper-tokenizer", "Whisper 分词器", "subtitles", _WHISPER + "tokenizer.json", "faster-whisper/base/tokenizer.json", 2203239, "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"),
    Resource("whisper-vocabulary", "Whisper 词表", "subtitles", _WHISPER + "vocabulary.txt", "faster-whisper/base/vocabulary.txt", 459861, "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"),
    Resource("whisper-model", "faster-whisper 多语言 base", "subtitles", _WHISPER + "model.bin", "faster-whisper/base/model.bin", 145217532, "d01c3014881c9c6f3133c182f3d2887eb6ca1c789a7538c5c007196857a0a6a9"),
    Resource("vad", "语音活动检测", "subtitles", "https://raw.githubusercontent.com/SYSTRAN/faster-whisper/v1.2.1/faster_whisper/assets/silero_vad_v6.onnx", "vad/silero_vad_v6.onnx", 1245151, "4cbf549b8326f60f80f2536d9eefeb450a9abe83365a098031c89719f1be17d2"),
    Resource("qwen-asr-config", "Qwen3-ASR 配置", "qwen-asr", _QWEN_ASR + "config.json", "qwen3-asr/config.json", 6193, "76d3ae4601ce939830b2517f4a6cadb86cc51316c3900af6b020b051c21a478c"),
    Resource("qwen-asr-template", "Qwen3-ASR 提示模板", "qwen-asr", _QWEN_ASR + "chat_template.json", "qwen3-asr/chat_template.json", 1161, "75a8cfca24f00de72d796fbfed6858fc9614ef3dabd8696684cc3bc03a9c58ff"),
    Resource("qwen-asr-generation", "Qwen3-ASR 生成配置", "qwen-asr", _QWEN_ASR + "generation_config.json", "qwen3-asr/generation_config.json", 142, "1da527824d81e07118facff437e03f2e24a23311e3bdeb2368973fe77e5f275c"),
    Resource("qwen-asr-preprocessor", "Qwen3-ASR 音频配置", "qwen-asr", _QWEN_ASR + "preprocessor_config.json", "qwen3-asr/preprocessor_config.json", 330, "45e120a4eda2c20c5d7f2ea9354e63536bf35e27aa573fb7cdf78017b378770d"),
    Resource("qwen-asr-tokenizer", "Qwen3-ASR 分词配置", "qwen-asr", _QWEN_ASR + "tokenizer_config.json", "qwen3-asr/tokenizer_config.json", 12487, "4942d005604266809309cabc9f4e9cb89ce855d59b14681fdc0e1cc62ea26c4c"),
    Resource("qwen-asr-merges", "Qwen3-ASR 分词规则", "qwen-asr", _QWEN_ASR + "merges.txt", "qwen3-asr/merges.txt", 1671853, "8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5"),
    Resource("qwen-asr-vocab", "Qwen3-ASR 词表", "qwen-asr", _QWEN_ASR + "vocab.json", "qwen3-asr/vocab.json", 2776833, "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910"),
    Resource("qwen-asr-model", "Qwen3-ASR-0.6B 权重", "qwen-asr", _QWEN_ASR + "model.safetensors", "qwen3-asr/model.safetensors", 1876091704, "79d6cbd4c98c7bbffe9db2edac07f56cd6637d0d5944b27f6c2b8353840323ea"),
)


def check_cancel(cancel: Event) -> None:
    if cancel.is_set():
        raise InstallationCancelled()


def byte_label(size: int) -> str:
    if size >= 1024 ** 3:
        return f"{size / 1024 ** 3:.2f} GB"
    return f"{size / 1024 ** 2:.1f} MB" if size >= 1024 ** 2 else f"{size / 1024:.1f} KB"


class ResourceManager:
    def __init__(self, *, models=MODELS, data=DATA, downloads=DOWNLOADS,
                 root=ROOT, resources=RESOURCES, legacy=True):
        self.models, self.data = Path(models), Path(data)
        self.downloads, self.root = Path(downloads), Path(root)
        self.resources = tuple(resources)
        self.legacy = legacy and not portable()

    def target(self, resource: Resource) -> Path:
        base = self.data if resource.area == "data" else self.models
        return base / resource.relative_path

    def installed_path(self, resource: Resource) -> Path | None:
        if resource.pair:
            for directory in sorted((self.models / "argos").glob("*")):
                try:
                    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
                    if (metadata.get("from_code"), metadata.get("to_code")) != resource.pair:
                        continue
                    if (directory / "model/model.bin").is_file() and any(
                        (directory / name).is_file() for name in ("sentencepiece.model", "bpe.model")
                    ):
                        return directory
                except (OSError, ValueError):
                    continue
            return None
        target = self.target(resource)
        if target.is_file() and target.stat().st_size == resource.size:
            return target
        if self.legacy and (resource.id.startswith("ocr-") or resource.id == "vad"):
            import sys
            package, folder = ("rapidocr", "models") if resource.id.startswith("ocr-") else ("faster_whisper", "assets")
            for base in (self.root / "_internal", Path(sys.prefix) / "Lib/site-packages"):
                old = base / package / folder / target.name
                if old.is_file() and old.stat().st_size == resource.size:
                    return old
        return None

    def plan(self, features) -> tuple[Resource, ...]:
        features = set(features)
        if not features <= {"basic", "subtitles", "qwen-asr"}:
            raise ValueError("未知资源用途")
        if features & {"subtitles", "qwen-asr"}:
            features.add("basic")
        return tuple(r for r in self.resources if r.feature in features)

    def ready(self, feature: str) -> bool:
        return all(self.installed_path(r) is not None for r in self.plan((feature,)))

    def _hash(self, path: Path, cancel: Event) -> str:
        digest = sha256()
        with path.open("rb") as file:
            while block := file.read(1024 * 1024):
                check_cancel(cancel)
                digest.update(block)
        check_cancel(cancel)
        return digest.hexdigest()

    def download(self, resource: Resource, cancel: Event, progress) -> Path:
        self.downloads.mkdir(parents=True, exist_ok=True)
        destination = self.downloads / (resource.id + ".download")
        partial = self.downloads / (resource.id + ".part")
        if destination.is_file():
            if destination.stat().st_size == resource.size and self._hash(destination, cancel) == resource.digest:
                return destination
            destination.unlink()
        for attempt in range(1, 4):
            check_cancel(cancel)
            try:
                offset = partial.stat().st_size if partial.exists() else 0
                if offset > resource.size:
                    partial.unlink()
                    offset = 0
                if offset < resource.size:
                    headers = {"User-Agent": "Triloa/0.1.3", "Accept-Encoding": "identity"}
                    if offset:
                        headers["Range"] = f"bytes={offset}-"
                    with urlopen(Request(resource.url, headers=headers), timeout=20) as response:
                        status = getattr(response, "status", 200)
                        if offset and status == 206:
                            expected = f"bytes {offset}-{resource.size - 1}/{resource.size}"
                            if response.headers.get("Content-Range") != expected:
                                partial.unlink(missing_ok=True)
                                raise ResourceError("下载服务器返回的续传范围不正确")
                        elif status == 200:
                            offset = 0
                        else:
                            raise ResourceError(f"下载服务器返回 HTTP {status}")
                        count, last_update = offset, 0.0
                        progress("download", resource, count, resource.size, attempt)
                        with partial.open("ab" if offset else "wb") as file:
                            while True:
                                check_cancel(cancel)
                                block = response.read(256 * 1024)
                                if not block:
                                    break
                                count += len(block)
                                if count > resource.size:
                                    raise ResourceError("下载文件超过预期大小，请重试")
                                file.write(block)
                                if monotonic() - last_update >= 0.1:
                                    progress("download", resource, count, resource.size, attempt)
                                    last_update = monotonic()
                        if count != resource.size:
                            raise ResourceError("连接提前中断，已保留下载进度")
                progress("verify", resource, resource.size, resource.size, attempt)
                if self._hash(partial, cancel) != resource.digest:
                    partial.unlink(missing_ok=True)
                    raise ResourceError("文件校验未通过，将重新下载")
                os.replace(partial, destination)
                return destination
            except (OSError, HTTPException, ResourceError) as exc:
                if partial.exists() and partial.stat().st_size > resource.size:
                    partial.unlink()
                check_cancel(cancel)
                if attempt == 3:
                    raise ResourceError(f"{resource.label} 下载失败：{exc}\n请检查网络、磁盘空间或文件夹写入权限，然后点击重试。") from exc
                progress("retry", resource, 0, resource.size, attempt)
                if cancel.wait(attempt):
                    raise InstallationCancelled()
        raise AssertionError("unreachable")

    def _install_argos(self, resource: Resource, archive: Path, cancel: Event):
        packages = self.models / "argos"
        packages.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="argos-install-", dir=self.downloads) as temporary:
            stage = Path(temporary).resolve()
            with zipfile.ZipFile(archive) as bundle:
                for item in bundle.infolist():
                    check_cancel(cancel)
                    target = (stage / item.filename).resolve()
                    if not target.is_relative_to(stage) or (item.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ResourceError("模型包包含不安全的文件路径")
                    bundle.extract(item, stage)
            entries = list(stage.iterdir())
            if len(entries) != 1 or not entries[0].is_dir():
                raise ResourceError("Argos 模型包的目录结构不正确")
            model = entries[0]
            metadata = json.loads((model / "metadata.json").read_text(encoding="utf-8"))
            if (metadata.get("from_code"), metadata.get("to_code")) != resource.pair or not (model / "model/model.bin").is_file():
                raise ResourceError("Argos 模型包内容不完整或语言不匹配")
            check_cancel(cancel)
            destination = packages / model.name
            backup = stage / "previous"
            if destination.exists():
                os.replace(destination, backup)
            try:
                os.replace(model, destination)
            except OSError:
                if backup.exists():
                    os.replace(backup, destination)
                raise
        # Argos caches the installed-language list; refresh without restarting.
        import sys
        translation_module = sys.modules.get('argostranslate.translate')
        if translation_module is not None:
            translation_module.get_installed_languages.cache_clear()
        archive.unlink(missing_ok=True)

    def install(self, features, cancel: Event, on_progress=lambda _event: None):
        plan = self.plan(features)
        for index, resource in enumerate(plan, 1):
            def progress(phase, item=resource, done=0, total=0, attempt=1):
                on_progress({"phase": phase, "resource": item.label, "index": index,
                             "count": len(plan), "done": done, "total": total, "attempt": attempt})
            check_cancel(cancel)
            if self.installed_path(resource) is not None:
                progress("installed")
                continue
            downloaded = self.download(resource, cancel, progress)
            check_cancel(cancel)
            progress("install")
            if resource.pair:
                self._install_argos(resource, downloaded, cancel)
            else:
                target = self.target(resource)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(downloaded, target)
            progress("installed")
        return tuple(features)


_install_lock = Lock()


def install_resources(features, cancel: Event, on_progress=lambda _event: None):
    from .paths import configure_paths
    configure_paths()
    if not _install_lock.acquire(blocking=False):
        raise ResourceError("已有资源安装任务正在进行")
    try:
        return ResourceManager().install(features, cancel, on_progress)
    finally:
        _install_lock.release()


def require_translation_resources(source: str):
    manager = ResourceManager()
    required = {"argos-en", "sbd-en"}
    if source == "ja":
        required.update(("argos-ja", "sbd-ja"))
    if any(manager.installed_path(r) is None for r in RESOURCES if r.id in required):
        raise ResourceError("缺少基础翻译资源，请打开「资源管理」安装基础翻译。")


def ocr_model_paths() -> dict[str, str]:
    manager = ResourceManager()
    result = {}
    for identifier, section in (("ocr-det", "Det"), ("ocr-cls", "Cls"), ("ocr-rec", "Rec")):
        resource = next(r for r in RESOURCES if r.id == identifier)
        path = manager.installed_path(resource)
        if path is None:
            raise ResourceError("缺少 OCR 资源，请打开「资源管理」安装基础翻译。")
        result[section + ".model_path"] = str(path)
    return result


def configure_whisper_vad():
    manager = ResourceManager()
    path = manager.installed_path(next(r for r in RESOURCES if r.id == "vad"))
    if path is None:
        raise ResourceError("缺少语音检测资源，请打开「资源管理」安装实时字幕。")
    from faster_whisper import vad
    # faster-whisper 1.2.1 resolves this asset through a module-level function.
    # Redirect it to the explicitly installed file, without fetching anything.
    vad.get_assets_path = lambda: str(path.parent)


def whisper_ready(size: str) -> bool:
    folder = MODELS / "faster-whisper" / size
    return all((folder / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json")) and (
        (folder / "vocabulary.txt").is_file() or (folder / "vocabulary.json").is_file()
    ) and ResourceManager().installed_path(next(r for r in RESOURCES if r.id == "vad")) is not None


def needs_first_run() -> bool:
    from . import preferences
    if preferences.get("setup.seen", False):
        return False
    manager = ResourceManager()
    return not (manager.ready("basic") and manager.ready("subtitles"))
