"""Local HY-MT GGUF translation through a private llama.cpp process."""

from __future__ import annotations

import atexit
import json
import os
import re
from pathlib import Path
import subprocess
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from .paths import MODELS, ROOT

MODEL = MODELS / "hy-mt" / "HY-MT1.5-1.8B-Q8_0.gguf"
SERVER = ROOT / "runtime" / "llama" / "llama-server.exe"
VERIFIED = MODEL.with_suffix(".verified")
BASE_URL = "http://127.0.0.1:8766"
_process: subprocess.Popen[bytes] | None = None
_loaded = None


def available() -> bool:
    return MODEL.is_file() and SERVER.is_file() and VERIFIED.is_file()


def _ready() -> bool:
    try:
        with urlopen(f"{BASE_URL}/health", timeout=1) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def ensure_server(timeout: float = 90.0, cancel=None, *, backend='hy', model=None) -> None:
    global _process, _loaded
    model = MODEL if backend == 'hy' else model
    if model is None or not Path(model).is_file():
        raise RuntimeError('翻译模型文件不存在，请重新选择本地 GGUF')
    identity = (backend, str(Path(model).resolve()))
    if _process is not None and _loaded != identity:
        stop_owned_server()
    if _process is not None and _process.poll() is None and _ready():
        return
    if _ready():
        raise RuntimeError('翻译服务端口 8766 被另一进程占用，请退出另一个 Triloa 后重试')
    if not SERVER.is_file() or (backend == 'hy' and not available()):
        raise RuntimeError("HY-MT 模型或 llama.cpp 程序缺失。请运行 setup_hy.ps1。")
    if _process is None or _process.poll() is not None:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        _process = subprocess.Popen(
            [str(SERVER), "-m", str(model), "-ngl", "99", "-c", "4096", "--host", "127.0.0.1", "--port", "8766", "--parallel", "1"],
            cwd=SERVER.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
            env=os.environ.copy(),
        )
    _loaded = identity
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        from .translator import check_cancel
        check_cancel(cancel)
        if _ready():
            return
        if _process.poll() is not None:
            raise RuntimeError(f"llama-server 启动失败（退出码 {_process.returncode}）。请检查显卡驱动和 CUDA DLL。")
        time.sleep(0.25)
    raise RuntimeError("HY-MT 模型加载超时。")


def translate(text: str, cancel=None, *, backend='hy', model=None) -> str:
    from .translator import check_cancel
    label = 'Qwen3' if backend == 'qwen' else 'HY-MT'
    check_cancel(cancel)
    ensure_server(cancel=cancel, backend=backend, model=model)
    prompt = (
        "请把以下英文或日文准确翻译成中文。按原文顺序翻译，不补充或猜测内容；"
        "保留数字、专有名词和缩写。只输出译文，不输出说明或原文。\n\n" + text
    )
    if backend == 'qwen':
        prompt += '\n/no_think'
    payload = json.dumps(
        {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": min(1024, max(128, len(text) * 2)),
            "temperature": 0.0,
            "repeat_penalty": 1.0,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        f"{BASE_URL}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=90) as response:
            data = json.load(response)
        choice = data["choices"][0]
        result = choice["message"]["content"].strip()
        if choice.get("finish_reason") == "length":
            raise RuntimeError(f"{label} 译文达到输出长度上限，请缩短待翻译文本。")
    except (OSError, URLError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"{label} 本地翻译失败：{exc}") from exc
    if backend == 'qwen':
        result = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL).strip()
        if '<think>' in result:
            raise RuntimeError('Qwen 未返回有效译文，请确认模型支持非思考模式')
    if not result or len(result) > max(200, len(text) * 4):
        raise RuntimeError(f"{label} 返回了空白或异常长度的译文。")
    return result


def stop_owned_server() -> None:
    """Release only the llama.cpp process started by this Triloa instance."""
    global _process
    process = _process
    _process = None
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    except OSError:
        pass


atexit.register(stop_owned_server)
