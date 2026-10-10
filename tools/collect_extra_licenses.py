"""Retain upstream license texts missing from the installed wheel metadata."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SOURCES = (
    ('antlr4-python3-runtime','4.9.3','antlr/antlr4','4.9.3','LICENSE.txt','master'),
    ('ctranslate2','4.8.2','OpenNMT/CTranslate2','v4.8.2','LICENSE','master'),
    ('flatbuffers','25.12.19','google/flatbuffers','v25.12.19','LICENSE','master'),
    ('rapidocr','3.9.2','RapidAI/RapidOCR','v3.9.2','LICENSE','main'),
    ('sentencepiece','0.2.2','google/sentencepiece','v0.2.2','LICENSE','master'),
    ('tokenizers','0.23.2','huggingface/tokenizers','v0.23.2','LICENSE','main'),
)


def main():
    directory=Path(__file__).resolve().parents[1]/'packaging/licenses'
    def retain(entry):
        name,version,repo,ref,file,fallback=entry
        for revision in (ref,fallback):
            url=f'https://raw.githubusercontent.com/{repo}/{revision}/{file}'
            try:
                with urlopen(Request(url,headers={'User-Agent':'Triloa-release-preparation'}),timeout=25) as response:
                    body=response.read()
                break
            except HTTPError as exc:
                if exc.code != 404 or revision == fallback:
                    raise
        path=directory/(name+'-LICENSE.txt')
        path.write_bytes(body)
        return {'name':name,'version':version,'source':url,'sha256':sha256(body).hexdigest(),'path':path.name}
    with ThreadPoolExecutor(max_workers=6) as executor:
        inventory=list(executor.map(retain,SOURCES))
    (directory/'EXTRA_SOURCES.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
    print(json.dumps(inventory),flush=True)


if __name__ == '__main__':
    main()
