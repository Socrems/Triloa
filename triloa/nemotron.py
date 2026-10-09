"""Offline Windows loopback subtitles using NVIDIA NeMo-Speech.cpp realtime ASR.

Expected local files:
    runtime/nemo-speech/bin/nemo-speech.exe
    models/nemotron/nemotron-3.5-asr-streaming-0.6b.q8_0.gguf

The runner starts the local HTTP/WebSocket server itself. It captures mono 16 kHz
system loopback audio, streams little-endian PCM16 in 100 ms frames, commits
phrases on the shared endpoint VAD, and translates transcripts on a worker thread.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .local_websocket import LocalWebSocket, WebSocketClosed, WebSocketError
from .paths import CACHE, MODELS, ROOT, configure_paths
from .speech import (
    FRAME_SAMPLES,
    SAMPLE_RATE,
    EndpointSettings,
    EndpointVAD,
    SpeechSubtitle,
    _load_audio_dependencies,
)
from . import audio_feedback
from .stable_phrase import StablePhrase
from .translator import detect_source, prepare_translator, translate_texts, TranslationCancelled

NEMOTRON_EXECUTABLE_PATH = (
    ROOT / "runtime" / "nemo-speech" / "bin" / "nemo-speech.exe"
)
NEMOTRON_MODEL_PATH = (
    MODELS / "nemotron" / "nemotron-3.5-asr-streaming-0.6b.q8_0.gguf"
)
NEMOTRON_HOST = "127.0.0.1"
NEMOTRON_WS_PATH = "/v1/audio/transcriptions/realtime"
NEMOTRON_STARTUP_TIMEOUT_SECONDS = 90.0
MAX_PENDING_FINALS = 8
MAX_FINAL_QUEUE_WAIT_SECONDS = 10.0

_LANGUAGE_TO_SERVER = {
    "auto": "auto",
    "en": "en-US",
    "en-US": "en-US",
    "ja": "ja-JP",
    "ja-JP": "ja-JP",
}
_LANGUAGE_TO_APP = {
    "en": "en",
    "en-us": "en",
    "ja": "ja",
    "ja-jp": "ja",
}
_LANGUAGE_TAG = re.compile(r"^\s*<(en-US|ja-JP)>\s*", re.IGNORECASE)


def nemotron_available() -> bool:
    """Return whether both documented local Nemotron runtime files are present."""
    return NEMOTRON_EXECUTABLE_PATH.is_file() and NEMOTRON_MODEL_PATH.is_file()


@dataclass(frozen=True)
class _Translation:
    language: str
    original: str
    captured_at: float
    final: bool
    queued_at: float = field(default_factory=time.monotonic, compare=False)


class NemotronSpeechSubtitleRunner:
    """Stream loopback audio to a local NeMo-Speech.cpp transcription server."""

    def __init__(
        self,
        mode: str = "live",
        language: str = "auto",
        on_subtitle: Callable[[SpeechSubtitle], None] | None = None,
        on_ready: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_level: Callable[[int], None] | None = None,
        on_status: Callable[[str], None] | None = None,
        *,
        device_name: str | None = None,
        endpoint_settings: EndpointSettings | None = None,
    ) -> None:
        if mode not in {"sentence", "live"}:
            raise ValueError("字幕模式必须是 sentence 或 live")
        if language not in _LANGUAGE_TO_SERVER:
            raise ValueError("Nemotron 语言必须是 auto、en-US 或 ja-JP")
        self.mode = mode
        self.language = language
        self.device_name = device_name
        self.endpoint_settings = endpoint_settings or EndpointSettings()
        self.on_subtitle = on_subtitle or self._print_subtitle
        self.on_ready = on_ready
        self.on_error = on_error
        self.on_level = on_level
        self.on_status = on_status
        self.stop_event = threading.Event()

        self._server_process: subprocess.Popen[bytes] | None = None
        self._translation_condition = threading.Condition()
        self._pending_finals: deque[_Translation] = deque()
        self._pending_draft: _Translation | None = None
        self._latest_final_at = 0.0
        self._stop_translator = False

    def run(self) -> None:
        """Start the local server, capture audio, and emit translated subtitles."""
        if self.stop_event.is_set():
            return
        configure_paths()
        numpy, soundcard = _load_audio_dependencies()
        microphone = self._select_loopback(soundcard)

        websocket: LocalWebSocket | None = None
        translator: threading.Thread | None = None
        try:
            process, port = self._start_server()
            self._server_process = process
            if self.stop_event.is_set() or not self._wait_for_server(process, port):
                return

            websocket = LocalWebSocket.connect(
                NEMOTRON_HOST,
                port,
                NEMOTRON_WS_PATH,
                timeout=10.0,
            )
            self._wait_for_session_event(websocket, "session.created")
            if self.stop_event.is_set():
                return
            websocket.send_json(
                {
                    "type": "session.update",
                    "session": {
                        "sample_rate": SAMPLE_RATE,
                        "language": _LANGUAGE_TO_SERVER[self.language],
                    },
                }
            )
            self._wait_for_session_event(websocket, "session.updated")
            if self.stop_event.is_set():
                return
            prepare_translator(cancel=self.stop_event)
            if self.stop_event.is_set():
                return

            translator = threading.Thread(
                target=self._translation_loop,
                name="triloa-nemotron-translation",
                daemon=True,
            )
            translator.start()
            if self.on_ready:
                self.on_ready(microphone.name)

            self._capture(numpy, microphone, websocket)
        except WebSocketClosed as exc:
            if not self.stop_event.is_set():
                raise RuntimeError(f"Nemotron 实时连接已断开：{exc}") from exc
        except WebSocketError as exc:
            if not self.stop_event.is_set():
                raise RuntimeError(f"Nemotron 本地 WebSocket 失败：{exc}") from exc
        finally:
            if websocket is not None:
                websocket.close()
            if translator is not None:
                self._stop_translation_worker(translator)
            self._stop_server(self._server_process)
            self._server_process = None

    def stop(self) -> None:
        """Stop capture, discard queued translations and terminate local ASR."""
        self.stop_event.set()
        with self._translation_condition:
            self._pending_finals.clear()
            self._pending_draft = None
            self._stop_translator = True
            self._translation_condition.notify_all()
        process = self._server_process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def _start_server(self) -> tuple[subprocess.Popen[bytes], int]:
        if not NEMOTRON_EXECUTABLE_PATH.is_file():
            raise RuntimeError(
                "找不到本地 NeMo-Speech.cpp 程序："
                f"{NEMOTRON_EXECUTABLE_PATH}"
            )
        if not NEMOTRON_MODEL_PATH.is_file():
            raise RuntimeError(
                "找不到本地 Nemotron GGUF 模型："
                f"{NEMOTRON_MODEL_PATH}"
            )

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port_socket:
            port_socket.bind((NEMOTRON_HOST, 0))
            port = port_socket.getsockname()[1]

        command = [
            str(NEMOTRON_EXECUTABLE_PATH),
            "serve",
            "--asr-model",
            str(NEMOTRON_MODEL_PATH.resolve()),
            "--host",
            NEMOTRON_HOST,
            "--port",
            str(port),
            "--asr.batching.enabled=false",
        ]
        environment = os.environ.copy()
        environment["TMP"] = str(CACHE / "tmp")
        environment["TEMP"] = str(CACHE / "tmp")
        environment["TMPDIR"] = str(CACHE / "tmp")
        environment["NEMO_SPEECH_MODEL_DIR"] = str(MODELS / "nemotron")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise RuntimeError(
                f"无法启动本地 NeMo-Speech.cpp 程序：{exc}"
            ) from exc
        return process, port

    def _wait_for_server(
        self,
        process: subprocess.Popen[bytes],
        port: int,
    ) -> bool:
        deadline = time.monotonic() + NEMOTRON_STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline and not self.stop_event.is_set():
            return_code = process.poll()
            if return_code is not None:
                raise RuntimeError(
                    "NeMo-Speech.cpp 在就绪前退出，"
                    f"进程代码 {return_code}。请检查运行时和本地 GGUF 文件。"
                )
            connection = http.client.HTTPConnection(
                NEMOTRON_HOST,
                port,
                timeout=1.0,
            )
            try:
                connection.request("GET", "/ready")
                response = connection.getresponse()
                body = response.read(65_536)
                if response.status == 200:
                    try:
                        readiness = json.loads(body.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        readiness = {}
                    if isinstance(readiness, dict) and readiness.get("ready") is True:
                        return True
            except (OSError, http.client.HTTPException):
                pass
            finally:
                connection.close()
            time.sleep(0.2)

        if self.stop_event.is_set():
            return False
        raise RuntimeError(
            "NeMo-Speech.cpp 未能在 "
            f"{NEMOTRON_STARTUP_TIMEOUT_SECONDS:.0f} 秒内就绪。"
        )

    def _wait_for_session_event(
        self,
        websocket: LocalWebSocket,
        expected: str,
        timeout: float = 15.0,
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                return
            for event in websocket.receive_json(0.2):
                event_type = str(event.get("type", ""))
                if event_type == "error" or "error" in event:
                    raise RuntimeError(self._server_error_message(event))
                if event_type == expected:
                    return
        raise RuntimeError(f"Nemotron 服务端未返回 {expected}。")

    def _capture(
        self,
        numpy: object,
        microphone: object,
        websocket: LocalWebSocket,
    ) -> None:
        detector = EndpointVAD(numpy, self.endpoint_settings)
        committed_times: deque[float] = deque()
        item_capture_times: dict[str, float] = {}
        drafts: dict[str, str] = {}
        finalized_items: set[str] = set()
        anonymous_capture_at: float | None = None
        active_capture_at: float | None = None
        pending_final_count = 0
        stable_drafts = {}

        with microphone.recorder(
            samplerate=SAMPLE_RATE,
            blocksize=FRAME_SAMPLES,
        ) as recorder:
            try:
                while not self.stop_event.is_set():
                    audio = recorder.record(numframes=FRAME_SAMPLES)
                    audio_feedback.level(self, numpy, audio)
                    was_active = detector._active
                    completed = detector.push(audio)
                    if detector._active:
                        active_capture_at = detector._started_at

                    # Do not feed idle silence to the server. At activation,
                    # EndpointVAD._frames contains the current frame and preroll.
                    if was_active:
                        websocket.send_binary(self._pcm16_bytes(numpy, audio))
                    elif detector._active:
                        for frame in detector._frames:
                            websocket.send_binary(self._pcm16_bytes(numpy, frame))
                    elif completed:
                        websocket.send_binary(self._pcm16_bytes(numpy, audio))

                    for utterance in completed:
                        websocket.send_json({"type": "input_audio_buffer.commit"})
                        committed_times.append(utterance.captured_at)
                        pending_final_count += 1

                    if not detector._active:
                        active_capture_at = None

                    for event in websocket.receive_json(0.02):
                        event_type = str(event.get("type", ""))
                        if event_type == "error" or "error" in event:
                            raise RuntimeError(self._server_error_message(event))
                        if event_type == "input_audio_buffer.committed":
                            item_id = str(event.get("item_id", ""))
                            capture_at = (
                                committed_times.popleft()
                                if committed_times
                                else active_capture_at or time.monotonic()
                            )
                            if item_id:
                                item_capture_times[item_id] = capture_at
                            else:
                                anonymous_capture_at = capture_at
                            continue

                        is_delta = self._is_delta_event(event)
                        is_completed = self._is_completed_event(event)
                        if not is_delta and not is_completed:
                            continue
                        if is_delta and self.mode != "live":
                            continue

                        item_id = str(event.get("item_id", ""))
                        key = item_id or "__anonymous__"
                        if is_completed and item_id and item_id in finalized_items:
                            continue
                        now = time.monotonic()
                        capture_at = self._resolve_capture_time(
                            item_id=item_id,
                            final=is_completed,
                            item_capture_times=item_capture_times,
                            committed_times=committed_times,
                            anonymous_capture_at=anonymous_capture_at,
                            active_capture_at=active_capture_at,
                        )
                        if is_delta:
                            delta = str(event.get("delta", ""))
                            if not delta:
                                continue
                            previous = drafts.get(key, "")
                            # NeMo emits token deltas. Also tolerate cumulative partials.
                            drafts[key] = (
                                delta
                                if previous and delta.startswith(previous)
                                else previous + delta
                            )
                            original, language_tag = self._clean_transcript(drafts[key])
                            if original:
                                source = self._source_language(original, language_tag)
                                if key not in stable_drafts:
                                    stable_drafts[key] = (StablePhrase(), source, capture_at)
                                stable_drafts[key][0].observe(original, now)
                            continue

                        transcript = str(event.get("transcript", ""))
                        if not transcript:
                            transcript = drafts.get(key, "")
                        original, language_tag = self._clean_transcript(transcript)
                        if original:
                            source = self._source_language(original, language_tag)
                            self._queue_translation(
                                _Translation(source, original, capture_at, True)
                            )
                        if item_id:
                            finalized_items.add(item_id)
                            item_capture_times.pop(item_id, None)
                            if committed_times and committed_times[0] == capture_at:
                                committed_times.popleft()
                        else:
                            anonymous_capture_at = None
                            if committed_times and committed_times[0] == capture_at:
                                committed_times.popleft()
                        pending_final_count = max(0, pending_final_count - 1)
                        drafts.pop(key, None)
                        stable_drafts.pop(key, None)

                    # Poll even when ASR sends no new tokens, bounding the draft wait.
                    for stabilizer, source, capture_at in stable_drafts.values():
                        candidate = stabilizer.poll()
                        if candidate:
                            self._queue_translation(_Translation(source, candidate, capture_at, False))

            finally:
                if self.stop_event.is_set():
                    return
                flushed = detector.flush()
                for utterance in flushed:
                    websocket.send_json({"type": "input_audio_buffer.commit"})
                    committed_times.append(utterance.captured_at)
                    pending_final_count += 1
                if pending_final_count:
                    pending_final_count = self._drain_final_events(
                        websocket,
                        item_capture_times,
                        committed_times,
                        drafts,
                        finalized_items,
                        anonymous_capture_at,
                        active_capture_at,
                        pending_final_count,
                        timeout=4.0,
                    )

    def _drain_final_events(
        self,
        websocket: LocalWebSocket,
        item_capture_times: dict[str, float],
        committed_times: deque[float],
        drafts: dict[str, str],
        finalized_items: set[str],
        anonymous_capture_at: float | None,
        active_capture_at: float | None,
        pending_final_count: int,
        *,
        timeout: float,
    ) -> int:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and pending_final_count:
            for event in websocket.receive_json(0.1):
                event_type = str(event.get("type", ""))
                if event_type == "error" or "error" in event:
                    raise RuntimeError(self._server_error_message(event))
                if not self._is_completed_event(event):
                    continue
                item_id = str(event.get("item_id", ""))
                key = item_id or "__anonymous__"
                if item_id and item_id in finalized_items:
                    continue
                capture_at = self._resolve_capture_time(
                    item_id=item_id,
                    final=True,
                    item_capture_times=item_capture_times,
                    committed_times=committed_times,
                    anonymous_capture_at=anonymous_capture_at,
                    active_capture_at=active_capture_at,
                )
                transcript = str(event.get("transcript", "")) or drafts.get(key, "")
                original, language_tag = self._clean_transcript(transcript)
                if original:
                    source = self._source_language(original, language_tag)
                    self._queue_translation(
                        _Translation(source, original, capture_at, True)
                    )
                if item_id:
                    finalized_items.add(item_id)
                    item_capture_times.pop(item_id, None)
                    if committed_times and committed_times[0] == capture_at:
                        committed_times.popleft()
                elif committed_times and committed_times[0] == capture_at:
                    committed_times.popleft()
                    anonymous_capture_at = None
                pending_final_count = max(0, pending_final_count - 1)
                drafts.pop(key, None)
        return pending_final_count

    @staticmethod
    def _pcm16_bytes(numpy: object, audio: object) -> bytes:
        samples = numpy.asarray(audio, dtype=numpy.float32)
        if samples.ndim >= 2:
            samples = numpy.mean(samples, axis=1, dtype=numpy.float32)
        samples = numpy.asarray(samples, dtype=numpy.float32).reshape(-1)
        samples = numpy.nan_to_num(samples, nan=0.0, posinf=1.0, neginf=-1.0)
        samples = numpy.clip(samples, -1.0, 1.0)
        return (samples * 32767.0).astype("<i2", copy=False).tobytes()

    def _queue_translation(self, item: _Translation) -> None:
        skipped = 0
        with self._translation_condition:
            if self.stop_event.is_set() or self._stop_translator:
                return
            if item.final:
                self._latest_final_at = max(self._latest_final_at, item.captured_at)
                if (
                    self._pending_draft is not None
                    and self._pending_draft.captured_at <= self._latest_final_at
                ):
                    self._pending_draft = None
                while self._pending_finals and (
                    len(self._pending_finals) >= MAX_PENDING_FINALS
                    or self._final_is_stale(self._pending_finals[0])
                ):
                    self._pending_finals.popleft()
                    skipped += 1
                self._pending_finals.append(item)
            elif item.captured_at > self._latest_final_at:
                # One draft slot keeps translation work current under load.
                self._pending_draft = item
            self._translation_condition.notify()
        if skipped:
            self._report_skipped_finals(skipped)

    @staticmethod
    def _final_is_stale(item: _Translation) -> bool:
        # Age starts when ASR supplies the final text, not when a long phrase begins.
        return time.monotonic() - item.queued_at > MAX_FINAL_QUEUE_WAIT_SECONDS

    def _report_skipped_finals(self, count: int = 1) -> None:
        audio_feedback.phase(self, f"翻译暂时跟不上，已跳过 {count} 句积压字幕")

    def _translation_loop(self) -> None:
        while True:
            with self._translation_condition:
                if self.stop_event.is_set():
                    return
                while (
                    not self._pending_finals
                    and self._pending_draft is None
                    and not self._stop_translator
                ):
                    self._translation_condition.wait()
                if self._pending_finals:
                    item = self._pending_finals.popleft()
                elif self._pending_draft is not None:
                    item = self._pending_draft
                    self._pending_draft = None
                elif self._stop_translator:
                    return
                else:
                    continue

            if self.stop_event.is_set():
                return
            if item.final and self._final_is_stale(item):
                self._report_skipped_finals()
                continue
            if not item.final and self._draft_is_stale(item, superseded=True):
                continue
            try:
                audio_feedback.phase(self, '正在翻译…')
                chinese = translate_texts(
                    [item.original],
                    source=item.language,
                    target="zh",
                    priority=0, cancel=self.stop_event, use_cache=not item.final,
                    is_obsolete=(lambda: self._final_is_stale(item)) if item.final
                    else lambda: self._draft_is_stale(item, superseded=True),
                )[0].strip()
                if self.stop_event.is_set():
                    return
                if not item.final and self._draft_is_stale(item):
                    continue
                self.on_subtitle(
                    SpeechSubtitle(
                        language=item.language,
                        original=item.original,
                        chinese=chinese,
                        captured_at=item.captured_at,
                        final=item.final,
                    )
                )
            except TranslationCancelled:
                if item.final and not self.stop_event.is_set():
                    self._report_skipped_finals()
                continue
            except Exception as exc:
                audio_feedback.error(self, '字幕翻译失败', exc)

    def _draft_is_stale(self, item: _Translation, superseded=False) -> bool:
        with self._translation_condition:
            return (item.captured_at <= self._latest_final_at or (
                superseded and self._pending_draft is not None and
                self._pending_draft.captured_at >= item.captured_at and
                self._pending_draft.original != item.original
            ))

    def _stop_translation_worker(self, worker: threading.Thread) -> None:
        with self._translation_condition:
            self._stop_translator = True
            self._translation_condition.notify_all()
        worker.join()

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

    @staticmethod
    def _resolve_capture_time(
        *,
        item_id: str,
        final: bool,
        item_capture_times: dict[str, float],
        committed_times: deque[float],
        anonymous_capture_at: float | None,
        active_capture_at: float | None,
    ) -> float:
        if item_id and item_id in item_capture_times:
            return item_capture_times[item_id]
        if item_id and committed_times:
            item_capture_times[item_id] = committed_times[0]
            return item_capture_times[item_id]
        if not item_id and anonymous_capture_at is not None:
            return anonymous_capture_at
        if not item_id and committed_times:
            return committed_times[0]
        if active_capture_at is not None:
            return active_capture_at
        return time.monotonic()

    def _source_language(self, text: str, language_tag: str | None) -> str:
        if self.language in {"en", "en-US"}:
            return "en"
        if self.language in {"ja", "ja-JP"}:
            return "ja"
        if language_tag:
            return _LANGUAGE_TO_APP.get(language_tag.lower(), detect_source(text))
        return detect_source(text)

    @staticmethod
    def _clean_transcript(text: str) -> tuple[str, str | None]:
        match = _LANGUAGE_TAG.match(text)
        language_tag = match.group(1) if match else None
        cleaned = _LANGUAGE_TAG.sub("", text, count=1).strip()
        cleaned = re.sub(r"</?(?:en-US|ja-JP)>", "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned, language_tag

    @staticmethod
    def _is_delta_event(event: dict[str, object]) -> bool:
        event_type = str(event.get("type", ""))
        return event_type.endswith(".delta") or event_type == "delta"

    @staticmethod
    def _is_completed_event(event: dict[str, object]) -> bool:
        event_type = str(event.get("type", ""))
        return event_type.endswith(".completed") or event_type == "completed"

    @staticmethod
    def _server_error_message(event: dict[str, object]) -> str:
        error = event.get("error", event)
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                return str(message)
        return str(error)

    @staticmethod
    def _stop_server(process: subprocess.Popen[bytes] | None) -> None:
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)

    @staticmethod
    def _print_subtitle(subtitle: SpeechSubtitle) -> None:
        language_name = {"ja": "日语", "en": "英语"}.get(
            subtitle.language, subtitle.language
        )
        prefix = "草稿" if not subtitle.final else "定稿"
        print(
            f"\n[{prefix} · {language_name}] {subtitle.original}\n"
            f"[中文] {subtitle.chinese}\n",
            flush=True,
        )
