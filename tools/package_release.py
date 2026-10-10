"""Create reviewable release archives from the prepared public checkout."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile


def digest(path):
    value=sha256()
    with path.open('rb') as file:
        while chunk:=file.read(1024*1024):
            value.update(chunk)
    return value.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--git',default=shutil.which('git'))
    args=parser.parse_args()
    source,bundle=args.source.resolve(),args.bundle.resolve()
    destination=args.destination.resolve()
    destination.mkdir(parents=True,exist_ok=True)
    version=re.search(r'__version__\s*=\s*"([0-9.]+)"',(source/'triloa/__init__.py').read_text(encoding='utf-8')).group(1)
    names=subprocess.check_output([args.git,'-C',str(source),'ls-files','--cached','--others','--exclude-standard','-z']).decode('utf-8').split('\0')
    names=sorted(set(n for n in names if n))
    forbidden_directories={'.git','.venv','cache','data','downloads','models','runtime','dist','__pycache__'}
    secrets=re.compile(r'C:[/\\]+Users[/\\]+Socrem|D:[/\\]+学校相关|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|github_pat_[A-Za-z0-9_]{20,}')
    for name in names:
        file=source/name
        if forbidden_directories.intersection(file.relative_to(source).parts) or file.suffix in {'.pyc','.zip','.log','.gguf','.onnx','.argosmodel'}:
            raise RuntimeError('Unexpected private/runtime file in source archive: '+name)
        if file.suffix in {'.py','.ps1','.md','.json','.js','.txt'} and secrets.search(file.read_text(encoding='utf-8-sig',errors='replace')):
            raise RuntimeError('Potential private content in '+name)
    source_zip=destination/f'Triloa-v{version}-source.zip'
    portable_zip=destination/f'Triloa-v{version}-windows-x64.zip'
    if source_zip.exists() or portable_zip.exists():
        raise RuntimeError('Review archives already exist; do not overwrite an existing release')
    with zipfile.ZipFile(source_zip,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name in names:
            archive.write(source/name,f'Triloa-v{version}/'+name)
    files=[]
    for file in bundle.rglob('*'):
        if not file.is_file():
            continue
        relative=file.relative_to(bundle)
        if relative.parts[0] in {'cache','data','downloads','models'}:
            raise RuntimeError('Portable build contains user data or models: '+str(relative))
        if file.suffix.lower() in {'.gguf','.onnx','.safetensors','.argosmodel'} or file.name in {'model.bin','sentencepiece.model'}:
            raise RuntimeError('Unexpected model weight: '+str(relative))
        files.append(file)
    with zipfile.ZipFile(portable_zip,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
        for file in sorted(files):
            archive.write(file,'Triloa/'+str(file.relative_to(bundle)).replace('\\','/'))
    archives=[{'name':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in (portable_zip,source_zip)]
    (destination/f'SHA256SUMS-v{version}.txt').write_text(''.join(f"{a['sha256']}  {a['name']}\n" for a in archives),encoding='utf-8')
    report={'version':version,'archives':archives,'source_files':len(names),'portable_files':len(files),
            'portable_unpacked_bytes':sum(p.stat().st_size for p in files),'bundled_models':0}
    (destination/f'v{version}-artifacts.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    main()
