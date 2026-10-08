"""Download one revision-pinned classifier and verify every artifact before use."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import subprocess
import urllib.request


def install(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'packaging/laya-model.json').read_bytes())
    target = root / 'laya/model'
    for item in manifest['files']:
        path = target / item['path']
        if not path.resolve().is_relative_to(target.resolve()):
            raise ValueError('Model artifact escaped its directory.')
        if path.is_file():
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() == item['sha256']:
                    continue
            raise ValueError('Existing model artifact was modified: ' + item['path'])
        path.parent.mkdir(parents=True, exist_ok=True)
        url = 'https://huggingface.co/' + manifest['repository'] + '/resolve/' + manifest['revision'] + '/' + item['path']
        print('Downloading Laya ' + item['path'], flush=True)
        partial = path.with_suffix(path.suffix + '.partial')
        with urllib.request.urlopen(url, timeout=60) as response, partial.open('wb') as stream:
            shutil.copyfileobj(response, stream)
        with partial.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
                raise ValueError('Laya model checksum mismatch: ' + item['path'])
        partial.replace(path)
    print('Laya model artifacts verified.', flush=True)
    result = subprocess.run([str(root / 'laya/.venv/Scripts/python.exe'), str(root / 'laya_worker.py'), '--probe'],
                            capture_output=True, text=True, encoding='utf-8', timeout=180, check=True)
    decision = json.loads(result.stdout)
    if decision.get('route') != 'symbols' or decision.get('truncated') or decision.get('confidence', 0) < .55:
        raise RuntimeError('Laya real-inference qualification failed.')
    version = subprocess.run([str(root / 'laya/.venv/Scripts/python.exe'), '-c',
                              'import importlib.metadata; print(importlib.metadata.version("laya"))'],
                             capture_output=True, text=True, timeout=30, check=True).stdout.strip()
    (root / 'laya/ready.json').write_text(json.dumps({'version': version, 'revision': manifest['revision'],
                                                    'inference_verified': True}) + '\n')
    print('Laya local inference verified: ' + result.stdout.strip(), flush=True)


if __name__ == '__main__':
    install(sys.argv[1])
