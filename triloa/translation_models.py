"""Local GGUF model records; weights remain at their original locations."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import preferences

PROFILES = {'generic': '通用对话模型', 'qwen': 'Qwen · 关闭思考', 'hy': 'HY-MT · 翻译模型'}
EXECUTIONS = {'auto': '自动分配显卡 / 内存', 'cpu': '仅 CPU'}


@dataclass(frozen=True)
class LocalModel:
    id: str
    name: str
    path: Path
    profile: str = 'generic'
    execution: str = 'auto'

    def record(self) -> dict:
        return {'id': self.id, 'name': self.name, 'path': str(self.path),
                'profile': self.profile, 'execution': self.execution}


def registered_models() -> list[LocalModel]:
    records = preferences.get('translation.models', [])
    if not isinstance(records, list):
        return []
    models, seen = [], set()
    for record in records:
        if not isinstance(record, dict):
            continue
        identifier, name, path = (record.get(key) for key in ('id', 'name', 'path'))
        profile, execution = record.get('profile', 'generic'), record.get('execution', 'auto')
        if (not all(isinstance(value, str) and value.strip() and '\0' not in value for value in (identifier, name, path))
                or identifier in seen or not isinstance(profile, str) or profile not in PROFILES
                or not isinstance(execution, str) or execution not in EXECUTIONS):
            continue
        models.append(LocalModel(identifier, name[:80], Path(path), profile, execution))
        seen.add(identifier)
    return models


def same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def validate_gguf(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    if path.suffix.lower() != '.gguf' or not path.is_file():
        raise ValueError('请选择已下载的 .gguf 模型文件')
    with path.open('rb') as stream:
        if stream.read(4) != b'GGUF':
            raise ValueError('文件不是有效的 GGUF 模型，可能下载不完整')
    return path


def guess_profile(path: Path) -> str:
    name = path.name.lower()
    if 'qwen' in name:
        return 'qwen'
    if 'hy-mt' in name or 'hy_mt' in name:
        return 'hy'
    return 'generic'
