"""Local GGUF translation through one owned llama.cpp process."""

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

from .paths import CACHE, MODELS, ROOT

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


def ensure_server(timeout: float = 90.0, cancel=None, *, backend='hy', model=None, execution='auto') -> None:
    global _process, _loaded
    model = MODEL if backend == 'hy' else model
    if model is None or not Path(model).is_file():
        raise RuntimeError('翻译模型文件不存在，请重新选择本地 GGUF')
    if execution not in {'auto', 'cpu'}:
        raise ValueError('不支持的模型运行方式')
    identity = (backend, str(Path(model).resolve()), execution)
    if _process is not None and _loaded != identity:
        stop_owned_server()
    if _process is not None and _process.poll() is None and _ready():
        return
    if _ready():
        raise RuntimeError('翻译服务端口 8766 被另一进程占用，请退出另一个 Triloa 后重试')
    if not SERVER.is_file():
        raise RuntimeError('缺少本地 llama.cpp 运行库，请按 README 安装到 runtime/llama')
    if backend == 'hy' and not available():
        raise RuntimeError("HY-MT 模型或 llama.cpp 程序缺失。请运行 setup_hy.ps1。")
    if _process is None or _process.poll() is not None:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        layers = '0' if execution == 'cpu' else 'auto' if backend == 'custom' else '99'
        arguments = [str(SERVER), '-m', str(model), '-ngl', layers, '-c', '4096',
                     '--host', '127.0.0.1', '--port', '8766', '--parallel', '1', '--offline']
        if backend == 'custom':
            arguments.append('--jinja')
        if execution == 'cpu':
            arguments += ['--device', 'none']
        CACHE.mkdir(parents=True, exist_ok=True)
        with (CACHE / 'llama-server.log').open('wb') as log:
            _process = subprocess.Popen(
                arguments, cwd=SERVER.parent, stdin=subprocess.DEVNULL,
                stdout=log, stderr=log, creationflags=creation_flags, env=os.environ.copy(),
            )
    _loaded = identity
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        from .translator import check_cancel
        check_cancel(cancel)
        if _ready():
            return
        if _process.poll() is not None:
            raise RuntimeError(f'llama.cpp 加载失败（退出码 {_process.returncode}）。'
                               '请检查运行库是否支持此模型、驱动和可用内存；可尝试仅 CPU。'
                               f'详细原因见 {CACHE / "llama-server.log"}')
        time.sleep(0.25)
    raise RuntimeError('本地 GGUF 模型加载超时，请检查模型大小和可用内存')


def translate(text: str, cancel=None, *, backend='hy', model=None, profile=None, execution='auto', label=None) -> str:
    from .translator import check_cancel
    profile = profile or ('qwen' if backend == 'qwen' else 'generic' if backend == 'custom' else 'hy')
    if profile not in {'generic', 'qwen', 'hy'}:
        raise ValueError('不支持的模型提示类型')
    label = label or ('Qwen' if backend == 'qwen' else Path(model).stem if backend == 'custom' and model else 'HY-MT')
    check_cancel(cancel)
    ensure_server(cancel=cancel, backend=backend, model=model, execution=execution)
    prompt = (
        "请把以下英文或日文准确翻译成中文。按原文顺序翻译，不补充或猜测内容；"
        "保留数字、专有名词和缩写。只输出译文，不输出说明或原文。\n\n" + text
    )
    if profile == 'hy':
        prompt = 'Translate the following segment into Chinese, without additional explanation.\n\n' + text
    if profile == 'qwen':
        prompt += '\n/no_think'
    options = {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": min(1024, max(128, len(text) * 2)),
            "temperature": 0.0,
            "repeat_penalty": 1.0,
            "stream": False,
        }
    if profile == 'qwen':
        options['chat_template_kwargs'] = {'enable_thinking': False}
    payload = json.dumps(options, ensure_ascii=False).encode('utf-8')
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
    if backend in {'qwen', 'custom'}:
        result = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL).strip()
        if '<think>' in result:
            raise RuntimeError(f'{label} 未返回完整译文，请选择支持直接输出译文的模型或 Qwen 关闭思考配置')
    if not result or len(result) > max(200, len(text) * 4):
        raise RuntimeError(f"{label} 返回了空白或异常长度的译文。")
    return result


def stop_owned_server() -> None:
    """Release only the llama.cpp process started by this Triloa instance."""
    global _process, _loaded
    process = _process
    _process = None
    _loaded = None
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
