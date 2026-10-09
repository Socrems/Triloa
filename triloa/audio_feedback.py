"""Throttle audio feedback without retaining audio or transcript data."""
import time
from .diagnostics import report_error

def level(runner, numpy, audio):
    now = time.monotonic()
    if runner.on_level and now - getattr(runner, '_last_meter_at', 0) >= 0.15:
        runner._last_meter_at = now
        rms = float(numpy.sqrt(numpy.mean(numpy.square(audio)))) if audio.size else 0.0
        runner.on_level(min(100, max(0, round(rms * 500))))

def error(runner, stage, exc):
    if runner.stop_event.is_set():
        return
    report_error(stage, exc)
    if runner.on_error:
        runner.on_error(f'{stage}：{exc}')

def phase(runner, message):
    if runner.on_status and not runner.stop_event.is_set():
        runner.on_status(message)
