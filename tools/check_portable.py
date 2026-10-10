"""Check the empty and installed portable package without redownloading models.

For the maintainer's existing local model files only. Test copies use hard links
under cache/tmp; they do not change the portable output or the owner's settings.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from threading import Event


def copy_links(source: Path, destination: Path):
    for file in source.rglob('*'):
        if not file.is_file():
            continue
        target = destination / file.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(file, target)
        except OSError:
            shutil.copy2(file, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    options = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    import sys
    sys.path.insert(0, str(project))
    from triloa.resources import ResourceManager, RESOURCES
    from triloa.paths import configure_paths
    configure_paths()
    temporary_root = project / 'cache/tmp'
    report_dir = project / 'cache/v012-package-check'
    report_dir.mkdir(exist_ok=True)
    before = sha256((project/'data/preferences.json').read_bytes()).hexdigest()
    results = {}
    environment = os.environ.copy()
    environment.pop('TRILOA_DATA_DIR', None)
    environment.pop('TRILOA_TRANSLATOR', None)
    environment['QT_QPA_PLATFORM'] = 'offscreen'
    if os.name == 'nt':
        environment['QT_QPA_FONTDIR'] = str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts')
    for state in ('empty', 'installed'):
        with TemporaryDirectory(prefix='portable-' + state + '-', dir=temporary_root) as temporary:
            root = Path(temporary)
            copy_links(options.bundle.resolve(), root)
            if state == 'installed':
                manager = ResourceManager(root=root, models=root/'models', data=root/'data', downloads=root/'downloads', legacy=False)
                manager.downloads.mkdir(exist_ok=True)
                original = ResourceManager()
                for resource in RESOURCES:
                    if resource.pair:
                        name = 'translate-en_zh.argosmodel' if resource.pair[0]=='en' else 'translate-ja_en.argosmodel'
                        source = project/'cache/argos-translate/downloads'/name
                        os.link(source, manager.downloads/(resource.id+'.download'))
                    else:
                        source = original.installed_path(resource)
                        if source is None:
                            raise RuntimeError('Existing local test resource missing: '+resource.id)
                        target = manager.target(resource)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        os.link(source, target)
                # Downloads are forbidden: use cached, checksum-verified archives.
                from unittest.mock import patch
                with patch('triloa.resources.urlopen', side_effect=AssertionError('Unexpected network request')):
                    manager.install(('subtitles',), Event())
                assert manager.ready('subtitles')
            process = subprocess.run([str(root/'Triloa.exe'), 'selftest'], env=environment, timeout=90,
                                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            report = root/'cache/packaging-selftest.json'
            result = json.loads(report.read_text(encoding='utf-8'))
            results[state] = result
            (report_dir/(state+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            if state == 'empty':
                shutil.copy2(root/'cache/packaging-onboarding.png', report_dir/'onboarding.png')
            if process.returncode != 0:
                raise RuntimeError('Packaged check failed: '+json.dumps(result,ensure_ascii=True))
    after = sha256((project/'data/preferences.json').read_bytes()).hexdigest()
    assert before == after, 'Original settings changed'
    results['original_preferences_unchanged'] = before
    (report_dir/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=True),flush=True)


if __name__ == '__main__':
    main()
