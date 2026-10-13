"""Build a separate model-free Windows folder using the current Python env."""
from __future__ import annotations

import argparse
import ast
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def within(path: Path, root: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError(f"Unsafe build path: {path}")
    return path


def copy_licenses(bundle: Path, source: Path, work: Path):
    """Map PyInstaller's source records to installed distribution metadata."""
    records = ast.literal_eval((work / "Triloa-Portable/Analysis-00.toc").read_text(encoding="utf-8"))
    paths = set()
    def visit(value):
        if isinstance(value, str):
            paths.add(value.replace('\\', '/').lower())
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)
    visit(records)
    inventory = []
    license_root = bundle / "licenses"
    license_root.mkdir(exist_ok=True)
    for dist in sorted(metadata.distributions(), key=lambda d: d.metadata['Name'].lower()):
        files = tuple(dist.files or ())
        if not any(str(dist.locate_file(file)).replace('\\', '/').lower() in paths for file in files):
            continue
        name = dist.metadata['Name']
        directory = license_root / (re.sub(r'[^a-zA-Z0-9._-]', '_', name) + '-' + dist.version)
        directory.mkdir(exist_ok=True)
        copied = []
        for file in files:
            if any(re.search(r'^(licenses?|notices?|copying|copyright)(\b|[-_.])', part, re.I) for part in file.parts):
                src = Path(dist.locate_file(file))
                if src.is_file():
                    # Preserve file layout without allowing ../ from wheel RECORD.
                    relative = Path(*[p for p in file.parts if p not in ('..', '.')])
                    target = within(directory / relative, directory)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, target)
                    copied.append(str(target.relative_to(bundle)).replace('\\', '/'))
        (directory / 'METADATA.txt').write_text(dist.read_text('METADATA') or '', encoding='utf-8')
        inventory.append({'name': name, 'version': dist.version,
                          'license': dist.metadata.get('License-Expression') or dist.metadata.get('License') or '; '.join(c for c in dist.metadata.get_all('Classifier', ()) if c.startswith('License')),
                          'project_urls': dist.metadata.get_all('Project-URL', ()),
                          'license_files': copied})
    prefix = Path(sys.base_prefix)
    python_license = next((prefix / name for name in ('LICENSE.txt', 'LICENSE_PYTHON.txt') if (prefix / name).is_file()), None)
    if python_license is None:
        raise RuntimeError('Python license not found')
    shutil.copy2(python_license, license_root / 'Python-LICENSE.txt')
    # Conda-built CPython can also supply native DLLs outside site-packages.
    # Include only packages with files present in the actual analysis records.
    for record in sorted((prefix / 'conda-meta').glob('*.json')):
        info = json.loads(record.read_text(encoding='utf-8'))
        if not any(str(prefix / file).replace('\\', '/').lower() in paths for file in info.get('files', ())):
            continue
        name, version, build = info['name'], info['version'], info['build']
        package = prefix / 'pkgs' / f'{name}-{version}-{build}'
        copied = []
        for file in (package / 'info/licenses').rglob('*'):
            if file.is_file():
                target = license_root / 'native' / f'{name}-{version}' / file.relative_to(package / 'info/licenses')
                within(target, license_root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, target)
                copied.append(str(target.relative_to(bundle)).replace('\\', '/'))
        inventory.append({'kind':'native/conda', 'name':name, 'version':version,
                          'license':info.get('license'), 'license_files':copied})
    extra = source / 'packaging/licenses'
    for file in extra.iterdir():
        if file.is_file():
            shutil.copy2(file, license_root / file.name)
        elif file.is_dir():
            shutil.copytree(file, license_root / file.name, dirs_exist_ok=True)
    for item in inventory:
        additional = extra / (item['name'].lower() + '-LICENSE.txt')
        if additional.exists():
            item['license_files'].append('licenses/' + additional.name)
    vendor = source / 'triloa/_vendor/qwen3_asr'
    destination = license_root / 'Qwen3-ASR'
    destination.mkdir(exist_ok=True)
    for name in ('LICENSE', 'NOTICE.md'):
        shutil.copy2(vendor / name, destination / name)
    inventory.append({'kind':'vendored', 'name':'Qwen3-ASR Transformers backend', 'version':'0.0.6',
                      'license':'Apache-2.0', 'project_urls':['https://github.com/QwenLM/Qwen3-ASR'],
                      'license_files':['licenses/Qwen3-ASR/LICENSE', 'licenses/Qwen3-ASR/NOTICE.md']})
    (license_root / 'DEPENDENCIES.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--llama-runtime', type=Path)
    options = parser.parse_args()
    source = options.source.resolve()
    output = (options.output or source / 'dist').resolve()
    cache = (options.cache or source / 'cache/pyinstaller/portable').resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    temporary = cache / 'tmp'
    temporary.mkdir(exist_ok=True)
    for name in ('TEMP', 'TMP', 'TMPDIR'):
        environment[name] = str(temporary)
    environment['PYINSTALLER_CONFIG_DIR'] = str(cache / 'config')
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    for name, relative in {'XDG_DATA_HOME':'data', 'XDG_CONFIG_HOME':'config',
                           'XDG_CACHE_HOME':'dependency-cache', 'ARGOS_PACKAGES_DIR':'models/argos',
                           'HF_HOME':'huggingface', 'HUGGINGFACE_HUB_CACHE':'huggingface/hub',
                           'HF_XET_CACHE':'huggingface/xet', 'TORCH_HOME':'torch',
                           'PIP_CACHE_DIR':'pip'}.items():
        environment[name] = str(cache / relative)
    environment['ARGOS_DEVICE_TYPE'] = 'cpu'
    environment['TRILOA_CPU_RUNTIME'] = '1'
    environment['ARGOS_CHUNK_TYPE'] = 'MINISBD'
    bundle = within(output / 'Triloa-Portable', output)
    if bundle.exists():
        raise RuntimeError(f'Output already exists; choose another output folder: {bundle}')
    work = cache / 'work'
    arguments = [sys.executable, '-B', '-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed',
                 '--name', 'Triloa-Portable', '--icon', str(source / 'assets/triloa.ico'),
                 '--distpath', str(output), '--workpath', str(work), '--specpath', str(cache / 'spec'),
                 '--paths', str(source)]
    arguments.extend(('--additional-hooks-dir', str(source / 'tools/pyinstaller-hooks')))
    for module in ('triloa.desktop', 'triloa.subtitles', 'triloa.speech', 'triloa.nemotron',
                   'triloa.resource_setup', 'triloa.resources', 'triloa.selftest', 'triloa.qwen_asr',
                   'transformers.models.qwen2.tokenization_qwen2_fast',
                   'transformers.models.qwen2.tokenization_qwen2',
                   'transformers.models.whisper.feature_extraction_whisper',
                   'transformers.models.auto.configuration_auto',
                   'transformers.models.auto.tokenization_auto', 'accelerate',
                   'argostranslate.translate', 'soundcard'):
        arguments.extend(('--hidden-import', module))
    for module in ('rapidocr', 'faster_whisper', 'ctranslate2', 'onnxruntime'):
        arguments.extend(('--collect-all', module))
    arguments.append(str(source / 'triloa_gui.py'))
    subprocess.run(arguments, cwd=source, env=environment, check=True)
    # These are upstream model assets, not Python runtime dependencies.
    embedded = bundle / '_internal'
    for relative in ('rapidocr/models', 'onnxruntime/datasets'):
        directory = within(embedded / relative, bundle)
        if directory.exists():
            shutil.rmtree(directory)
    for model in (embedded / 'faster_whisper/assets').glob('*.onnx'):
        within(model, bundle).unlink()
    # The app reads PDF pages through screen capture, not Qt's PDF decoder.
    for relative in ('Qt6Pdf.dll', 'PySide6/plugins/imageformats/qpdf.dll'):
        within(embedded / relative, bundle).unlink(missing_ok=True)
    (bundle / 'Triloa-Portable.exe').rename(bundle / 'Triloa.exe')
    (bundle / 'package-profile.txt').write_text('Portable\n', encoding='utf-8')
    for name in ('assets', 'extension', 'docs'):
        shutil.copytree(source / name, bundle / name)
    for name in ('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md', 'RELEASE_NOTES.md', 'CONTRIBUTING.md'):
        shutil.copy2(source / name, bundle / name)
    runtime = options.llama_runtime
    if runtime and runtime.is_dir():
        destination = bundle / 'runtime/llama'
        destination.mkdir(parents=True)
        for file in runtime.iterdir():
            if not file.is_file():
                continue
            name = file.name.lower()
            if name in {'llama-server.exe', 'llama-server-impl.dll', 'llama-common.dll', 'llama.dll', 'mtmd.dll', 'ggml.dll', 'ggml-base.dll', 'libomp.dll', 'license-llvm-openmp'} or name.startswith('ggml-cpu-'):
                try:
                    os.link(file, destination / file.name)
                except OSError:
                    shutil.copy2(file, destination / file.name)
        if not (destination / 'llama-server.exe').is_file():
            raise RuntimeError('llama-server.exe not found in the provided runtime')
    dependencies = copy_licenses(bundle, source, work)
    forbidden = [str(p.relative_to(bundle)) for p in bundle.rglob('*') if p.is_file() and
                 (p.suffix.lower() in {'.gguf', '.onnx', '.pth', '.argosmodel', '.safetensors'} or p.name in {'model.bin', 'sentencepiece.model'})]
    if forbidden:
        raise RuntimeError('Models unexpectedly bundled: ' + ', '.join(forbidden))
    report = {'profile': 'Portable', 'dependencies': len(dependencies), 'bundled_models': forbidden,
              'bytes': sum(p.stat().st_size for p in bundle.rglob('*') if p.is_file())}
    (cache / 'portable-build.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)
    print(f'Portable folder: {bundle}', flush=True)


if __name__ == '__main__':
    main()
