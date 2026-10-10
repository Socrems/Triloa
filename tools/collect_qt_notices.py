"""Retain copyright/license notices from the matching upstream Qt source."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen


def fetch(url):
    with urlopen(Request(url, headers={'User-Agent':'Triloa-release-preparation'}), timeout=30) as response:
        return response.read()


def main():
    source = Path(__file__).resolve().parents[1]
    directory = source / 'packaging/licenses/qt-source-notices'
    directory.mkdir(parents=True, exist_ok=True)
    entries = []
    for repo in ('qtbase', 'qtsvg'):
        tree = json.loads(fetch(f'https://api.github.com/repos/qt/{repo}/git/trees/v6.9.2?recursive=1'))
        if tree.get('truncated'):
            raise RuntimeError('Incomplete Qt source listing')
        revision = tree['sha']
        for item in tree['tree']:
            path = item['path']
            if item['type'] == 'blob' and path.startswith('src/3rdparty/') and re.search(r'(^|/)(licen[cs]e[^/]*|copying[^/]*|copyright[^/]*|notice[^/]*|authors[^/]*|qt_attribution\.json)$',path,re.I):
                entries.append((repo, revision, path))
    def retain(entry):
        repo, revision, path = entry
        url = f'https://raw.githubusercontent.com/qt/{repo}/{revision}/{path}'
        body = fetch(url)
        target = (directory / repo / path).resolve()
        if not target.is_relative_to(directory.resolve()):
            raise RuntimeError('Unsafe source path')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        return {'path':str(target.relative_to(directory)).replace('\\','/'),'url':url,'sha256':sha256(body).hexdigest()}
    with ThreadPoolExecutor(max_workers=6) as executor:
        records = list(executor.map(retain, entries))
    (directory/'SOURCES.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    print(f'Qt 6.9.2 upstream notice files retained: {len(records)}',flush=True)


if __name__ == '__main__':
    main()
