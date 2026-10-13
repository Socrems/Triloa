r"""Offline Windows system-audio bilingual speech subtitles.

Optional runtime dependencies (install into this project's virtual environment):
    powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_speech.ps1

The project already lists numpy and onnxruntime. Keep pip's cache under the project drive
(or use --no-cache-dir) and place the CTranslate2-converted Whisper model under
models\faster-whisper\base. This module loads that local directory only and never
downloads a model or calls a network service.

Run from the project directory:
    .\.venv\Scripts\python.exe -m triloa.speech --list-devices
    .\.venv\Scripts\python.exe -m triloa.speech

Limitations:
* This SoundCard WASAPI loopback captures the mix played by an output device.
  Choose the output device carrying Bilibili/PotPlayer.
* The endpoint VAD uses a configurable RMS threshold. Music and effects can trigger it;
  tune --threshold for the current output volume.
* Sentence mode starts recognition after a silence window. Live mode recognizes
  snapshots while speech continues, then replaces the draft with a sentence-final result.
  Recognition and local translation add variable delay; no update rate is guaranteed.
* This module defaults to terminal output. Run triloa.subtitles for a Qt overlay.
  Other GUI clients can consume SpeechSubtitle through on_subtitle.
* Capturing and transcription are mono 16 kHz, CPU INT8. CPU/model speed, language
  detection on short phrases, and recognition quality depend on the machine and audio.
"""

from __future__ import annotations

import argparse
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .paths import MODELS, configure_paths
from . import audio_feedback
from .stable_phrase import StablePhrase
from .translator import prepare_translator, translate_texts, TranslationCancelled

SAMPLE_RATE = 16_000
FRAME_MS = 100
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1_000
LIVE_UPDATE_INTERVAL_MS = 350
LIVE_MIN_SPEECH_MS = 300
_NO_WORK = object()


@dataclass(frozen=True)
class SpeechSubtitle:
    """One completed source transcript and its local Chinese translation."""

    language: str
    original: str
    chinese: str
    captured_at: float
    final: bool = True


@dataclass(frozen=True)
class _Utterance:
    audio: object
    captured_at: float
    final: bool = True


@dataclass(frozen=True)
class EndpointSettings:
    """Tunable settings for the lightweight RMS speech endpoint detector."""

    threshold: float = 0.008
    silence_ms: int = 650
    min_speech_ms: int = 350
    preroll_ms: int = 250
    max_utterance_seconds: float = 15.0


class EndpointVAD:
    """Frame-based energy VAD; returns mono float32 utterances at 16 kHz."""

    def __init__(self, numpy_module: object, settings: EndpointSettings | None = None):
        self._np = numpy_module
        self.settings = settings or EndpointSettings()
        self._preroll = deque(maxlen=max(1, self.settings.preroll_ms // FRAME_MS))
        self._frames: list[object] = []
        self._active = False
        self._silence_ms = 0
        self._speech_ms = 0
        self._started_at = 0.0

    def push(self, samples: object) -> list[_Utterance]:
        np = self._np
        array = np.asarray(samples, dtype=np.float32)
        if array.ndim == 1:
            mono = array
        elif array.ndim >= 2:
            # SoundCard returns frames × channels. Averaging avoids weighting one
            # channel and keeps the Whisper input mono.
            mono = np.mean(array, axis=1, dtype=np.float32)
        else:
            return []

        if mono.size == 0:
            return []

        frame = np.asarray(mono, dtype=np.float32).reshape(-1)
        rms = float(np.sqrt(np.mean(frame * frame, dtype=np.float32)))
        emitted: list[_Utterance] = []

        if not self._active:
            self._preroll.append(frame.copy())
            if rms < self.settings.threshold:
                return emitted
            self._active = True
            self._started_at = time.monotonic()
            self._frames = list(self._preroll)
            self._preroll.clear()
            self._speech_ms = len(self._frames) * FRAME_MS
            self._silence_ms = 0
        else:
            self._frames.append(frame.copy())
            if rms >= self.settings.threshold:
                self._speech_ms += FRAME_MS
                self._silence_ms = 0
            else:
                self._silence_ms += FRAME_MS

        max_frames = max(1, int(self.settings.max_utterance_seconds * 1_000 / FRAME_MS))
        if len(self._frames) >= max_frames:
            emitted.append(self._finish(np))
            # Continue a long monologue as another utterance without dropping frames.
            self._active = True
            self._started_at = time.monotonic()
            self._frames = []
            self._speech_ms = 0
            self._silence_ms = 0
            return emitted

        if self._silence_ms >= self.settings.silence_ms:
            if self._speech_ms >= self.settings.min_speech_ms:
                emitted.append(self._finish(np))
            else:
                self._frames.clear()
                self._preroll.clear()
            self._active = False
            self._silence_ms = 0
            self._speech_ms = 0
            self._preroll.clear()

        return emitted

    def snapshot(self) -> _Utterance | None:
        """Return the current phrase for a provisional subtitle."""
        if not self._active or self._speech_ms < LIVE_MIN_SPEECH_MS or not self._frames:
            return None
        audio = self._np.concatenate(self._frames).astype(self._np.float32, copy=False)
        return _Utterance(audio=audio, captured_at=self._started_at, final=False)

    def flush(self) -> list[_Utterance]:
        if not self._active or self._speech_ms < self.settings.min_speech_ms:
            self._frames.clear()
            self._active = False
            return []
        utterance = self._finish(self._np)
        self._active = False
        return [utterance]

    def _finish(self, np: object) -> _Utterance:
        audio = np.concatenate(self._frames).astype(np.float32, copy=False)
        item = _Utterance(audio=audio, captured_at=self._started_at)
        self._frames.clear()
        return item


def list_loopback_devices() -> list[object]:
    """Return Windows output-loopback devices from SoundCard."""
    _, soundcard = _load_audio_dependencies()
    return [
        microphone
        for microphone in soundcard.all_microphones(include_loopback=True)
        if bool(getattr(microphone, "isloopback", False))
    ]


def _load_audio_dependencies() -> tuple[object, object]:
    # Set TEMP/cache/model locations before importing native and ML dependencies.
    configure_paths()
    try:
        import numpy
        import soundcard
    except ImportError as exc:
        raise RuntimeError(
            "缺少语音原型依赖；请按 triloa.speech 模块说明安装 soundcard。"
        ) from exc
    return numpy, soundcard


class SpeechSubtitleRunner:
    """Capture WASAPI loopback, close phrases by VAD, then emit bilingual captions."""

    def __init__(
        self,
        model_path: Path | str = MODELS / "faster-whisper" / "base",
        *,
        device_name: str | None = None,
        endpoint_settings: EndpointSettings | None = None,
        on_subtitle: Callable[[SpeechSubtitle], None] | None = None,
        on_ready: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_level: Callable[[int], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        queue_size: int = 8,
        cpu_threads: int = 2,
        mode: str = "sentence",
        language: str = "auto",
    ) -> None:
        if mode not in {"sentence", "live"}:
            raise ValueError("字幕模式必须是 sentence 或 live")
        if language not in {"auto", "en", "ja"}:
            raise ValueError("ASR language must be auto, en or ja")
        self.mode = mode
        self.language = language
        self.model_path = Path(model_path)
        self.device_name = device_name
        self.endpoint_settings = endpoint_settings or EndpointSettings()
        self.on_subtitle = on_subtitle or self._print_subtitle
        self.on_ready = on_ready
        self.on_error = on_error
        self.on_level = on_level
        self.on_status = on_status
        self.cpu_threads = max(1, cpu_threads)
        self.stop_event = threading.Event()
        self._queue: queue.Queue[_Utterance | None] = queue.Queue(
            maxsize=max(1, queue_size)
        )
        self._partial_lock = threading.Lock()
        self._latest_partial: _Utterance | None = None
        self._latest_final_at = 0.0

    def run(self) -> None:
        if self.stop_event.is_set():
            return
        numpy, soundcard = _load_audio_dependencies()
        model = self._load_model()
        if self.stop_event.is_set():
            return
        prepare_translator(cancel=self.stop_event)
        if self.stop_event.is_set():
            return
        microphone = self._select_loopback(soundcard)
        detector = EndpointVAD(numpy, self.endpoint_settings)

        worker = threading.Thread(
            target=self._recognize_loop,
            args=(model,),
            name="triloa-speech-asr",
            daemon=True,
        )
        worker.start()
        if self.on_ready:
            self.on_ready(microphone.name)
        print(
            f"正在监听系统输出：{microphone.name}。按 Ctrl+C 停止。",
            flush=True,
        )
        last_partial_at = 0.0
        try:
            with microphone.recorder(
                samplerate=SAMPLE_RATE,
                blocksize=FRAME_SAMPLES,
            ) as recorder:
                while not self.stop_event.is_set():
                    audio = recorder.record(numframes=FRAME_SAMPLES)
                    audio_feedback.level(self, numpy, audio)
                    completed = detector.push(audio)
                    for utterance in completed:
                        self._enqueue(utterance)
                    if completed:
                        last_partial_at = 0.0
                    if self.mode == "live":
                        now = time.monotonic()
                        if (now - last_partial_at) * 1_000 >= LIVE_UPDATE_INTERVAL_MS:
                            partial = detector.snapshot()
                            if partial is not None:
                                self._enqueue(partial)
                                last_partial_at = now
        except KeyboardInterrupt:
            print("\n正在停止语音字幕…", flush=True)
        finally:
            if not self.stop_event.is_set():
                for utterance in detector.flush():
                    self._enqueue(utterance)
            else:
                with self._partial_lock:
                    self._latest_partial = None
                while True:
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        break
            self._queue.put(None)
            worker.join()

    def stop(self) -> None:
        self.stop_event.set()
        with self._partial_lock:
            self._latest_partial = None

    def _load_model(self) -> object:
        configure_paths()
        if not self.model_path.is_dir():
            raise RuntimeError(
                "找不到本地 faster-whisper 模型目录："
                f"{self.model_path}\n"
                "请打开「资源管理」安装实时字幕，或手动放入完整的 CTranslate2 模型。"
            )
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "缺少 faster-whisper；请按 triloa.speech 模块说明安装。"
            ) from exc

        try:
            from .resources import configure_whisper_vad
            configure_whisper_vad()
            return WhisperModel(
                str(self.model_path),
                device="cpu",
                compute_type="int8",
                cpu_threads=self.cpu_threads,
                num_workers=1,
                local_files_only=True,
            )
        except Exception as exc:
            raise RuntimeError(
                f"无法加载本地 faster-whisper 模型：{self.model_path} ({exc})"
            ) from exc

    def _select_loopback(self, soundcard: object) -> object:
        devices = [
            item
            for item in soundcard.all_microphones(include_loopback=True)
            if bool(getattr(item, "isloopback", False))
        ]
        if not devices:
            raise RuntimeError(
                "没有找到 Windows WASAPI 输出回环设备；请检查 Windows 播放设备。"
            )

        if self.device_name:
            exact = [item for item in devices if item.name == self.device_name]
            if len(exact) == 1:
                return exact[0]
            matches = [
                item
                for item in devices
                if self.device_name.casefold() in item.name.casefold()
            ]
            if len(matches) == 1:
                return matches[0]
            if not matches:
                available = "\n".join(f"  - {item.name}" for item in devices)
                raise RuntimeError(
                    f"找不到包含 {self.device_name!r} 的回环设备。可用设备：\n{available}"
                )
            raise RuntimeError(
                f"--device {self.device_name!r} 匹配多个设备，请用更具体的名称。"
            )

        try:
            speaker_name = soundcard.default_speaker().name
        except Exception:
            speaker_name = ""
        normalized_speaker = " ".join(speaker_name.casefold().split())
        matches = [
            item
            for item in devices
            if normalized_speaker
            and normalized_speaker in " ".join(item.name.casefold().split())
        ]
        if len(matches) == 1:
            return matches[0]
        available = "\n".join(f"  - {item.name}" for item in devices)
        raise RuntimeError(
            "无法唯一匹配 Windows 默认播放设备的回环端点。"
            "请用 --device 指定名称片段；可用设备：\n"
            f"{available}"
        )

    def _enqueue(self, utterance: _Utterance) -> None:
        if not utterance.final:
            if self.mode != "live":
                return
            with self._partial_lock:
                if utterance.captured_at > self._latest_final_at:
                    # Keep only the newest draft; the recognizer may run slower than audio.
                    self._latest_partial = utterance
            return
        with self._partial_lock:
            self._latest_final_at = max(self._latest_final_at, utterance.captured_at)
            if (
                self._latest_partial is not None
                and self._latest_partial.captured_at <= self._latest_final_at
            ):
                self._latest_partial = None
        try:
            self._queue.put_nowait(utterance)
        except queue.Full:
            audio_feedback.phase(self, "处理速度暂时跟不上播放速度，已跳过一句语音")

    def _partial_is_stale(self, utterance: _Utterance) -> bool:
        if utterance.final:
            return False
        with self._partial_lock:
            return utterance.captured_at <= self._latest_final_at

    def _next_utterance(self) -> object:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            pass
        if self.mode == "live":
            with self._partial_lock:
                partial = self._latest_partial
                self._latest_partial = None
            if partial is not None:
                return partial
        try:
            return self._queue.get(timeout=0.1)
        except queue.Empty:
            return _NO_WORK

    def _recognize_loop(self, model: object) -> None:
        last_partial: tuple[float, str] | None = None
        stable = StablePhrase()
        stable_capture = None
        while True:
            utterance = self._next_utterance()
            if utterance is _NO_WORK:
                continue
            if utterance is None or self.stop_event.is_set():
                return
            try:
                audio_feedback.phase(self, "正在识别语音…")
                original, detected_language = self._transcribe(model, utterance)
                language = self.language if self.language != "auto" else detected_language
                if self.stop_event.is_set():
                    return
                if not original or self._partial_is_stale(utterance):
                    continue
                if language not in {"ja", "en"}:
                    print(
                        f"跳过不支持的识别语言 {language!r}：{original}",
                        flush=True,
                    )
                    continue
                if not utterance.final and last_partial == (utterance.captured_at, original):
                    continue
                if stable_capture != utterance.captured_at:
                    stable = StablePhrase()
                    stable_capture = utterance.captured_at
                if not utterance.final:
                    stable.observe(original)
                    candidate = stable.poll()
                    if not candidate:
                        continue
                    original = candidate
                audio_feedback.phase(self, '正在翻译…')
                chinese = translate_texts(
                    [original],
                    source=language,
                    target="zh",
                    priority=0, cancel=self.stop_event, use_cache=not utterance.final,
                    is_obsolete=None if utterance.final else lambda: self._partial_is_stale(utterance),
                )[0].strip()
                if self.stop_event.is_set():
                    return
                if self._partial_is_stale(utterance):
                    continue
                if not utterance.final:
                    last_partial = (utterance.captured_at, original)
                self.on_subtitle(
                    SpeechSubtitle(
                        language=language,
                        original=original,
                        chinese=chinese,
                        captured_at=utterance.captured_at,
                        final=utterance.final,
                    )
                )
            except TranslationCancelled:
                continue
            except Exception as exc:
                audio_feedback.error(self, '语音字幕处理失败', exc)

    @staticmethod
    def _print_subtitle(subtitle: SpeechSubtitle) -> None:
        language_name = {"ja": "日语", "en": "英语"}.get(
            subtitle.language, subtitle.language
        )
        print(
            f"\n[{language_name}] {subtitle.original}\n[中文] {subtitle.chinese}\n",
            flush=True,
        )

    def _transcribe(self, model: object, utterance: _Utterance) -> tuple[str, str]:
        segments, info = model.transcribe(
            utterance.audio,
            language=None if self.language == "auto" else self.language,
            task="transcribe", beam_size=1,
            # EndpointVAD already found speech; a second VAD can drop short drafts.
            vad_filter=utterance.final,
            vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 150},
            condition_on_previous_text=False,
        )
        return "".join(segment.text for segment in segments).strip(), str(info.language)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Windows WASAPI 离线日/英语语音双语字幕原型"
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="列出可用的 Windows 输出回环设备后退出",
    )
    parser.add_argument(
        "--device",
        help="输出回环设备名称片段；默认尝试匹配 Windows 默认播放设备",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=MODELS / "faster-whisper" / "base",
        help="本地 CTranslate2 模型目录（默认 D 盘 models/faster-whisper/base）",
    )
    parser.add_argument(
        "--mode",
        choices=("sentence", "live"),
        default="sentence",
        help="sentence：句末显示；live：持续更新并在句末定稿",
    )
    parser.add_argument(
        "--language",
        choices=("auto", "en", "ja"),
        default="auto",
        help="ASR language: auto, English or Japanese",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=EndpointSettings.threshold,
        help="RMS VAD 音量阈值（默认 0.008，按系统音量调整）",
    )
    parser.add_argument(
        "--silence-ms",
        type=int,
        default=EndpointSettings.silence_ms,
        help="静音多少毫秒后提交一句转写（默认 650）",
    )
    parser.add_argument(
        "--cpu-threads",
        type=int,
        default=2,
        help="faster-whisper CPU 线程数（默认 2）",
    )
    args = parser.parse_args()

    try:
        if args.list_devices:
            devices = list_loopback_devices()
            if not devices:
                print("没有找到 Windows WASAPI 输出回环设备。")
                return 1
            for device in devices:
                print(device.name)
            return 0

        runner = SpeechSubtitleRunner(
            model_path=args.model,
            device_name=args.device,
            endpoint_settings=EndpointSettings(
                threshold=args.threshold,
                silence_ms=max(FRAME_MS, args.silence_ms),
            ),
            cpu_threads=args.cpu_threads,
            mode=args.mode,
            language=args.language,
        )
        runner.run()
    except RuntimeError as exc:
        parser.exit(2, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
