"""Atomic local preferences; subtitle text is never persisted here."""
import json
import os
from threading import RLock
from .paths import DATA

_lock = RLock()

def read() -> dict:
    try:
        value = json.loads((DATA / 'preferences.json').read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}

def get(key, default=None):
    with _lock:
        return read().get(key, default)

def update(values: dict):
    with _lock:
        data = read()
        data.update(values)
        DATA.mkdir(parents=True, exist_ok=True)
        temporary = DATA / 'preferences.json.tmp'
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, DATA / 'preferences.json')

def put(key, value):
    update({key: value})

def number(key, default, low, high):
    value = get(key, default)
    return max(low, min(high, value)) if isinstance(value, (int, float)) else default
