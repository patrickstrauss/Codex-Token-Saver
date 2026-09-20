"""Fetch fixed public Kompress artifacts into the bundle cache, never user state.

Run as a separate bounded setup process; the serving backend stays offline for
model loading. Provider authentication, model requests and Codex config are not
read by this installer.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from proxy_runtime import build_proxy_environment, MODEL_CACHE


def main():
    env = build_proxy_environment(ROOT / 'desktop-proxy' / 'setup')
    env['HF_HUB_OFFLINE'] = '0'
    env['TRANSFORMERS_OFFLINE'] = '0'
    env['HF_HUB_ETAG_TIMEOUT'] = '15'
    env['HF_HUB_DOWNLOAD_TIMEOUT'] = '30'
    env['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
    os.environ.clear()
    os.environ.update(env)
    from huggingface_hub import get_hf_file_metadata, hf_hub_download, hf_hub_url
    assets = (
        ('chopratejas/kompress-v2-base', 'onnx/kompress-int8-wo.onnx', 350_000_000),
        ('answerdotai/ModernBERT-base', 'config.json', 1_000_000),
        ('answerdotai/ModernBERT-base', 'tokenizer.json', 25_000_000),
        ('answerdotai/ModernBERT-base', 'tokenizer_config.json', 1_000_000),
        ('answerdotai/ModernBERT-base', 'special_tokens_map.json', 1_000_000),
    )
    receipt = {'source': 'Headroom 0.37.0 Kompress ONNX defaults', 'assets': []}
    commits = {}
    for repo, filename, max_bytes in assets:
        metadata = get_hf_file_metadata(hf_hub_url(repo, filename), token=False, timeout=15)
        if not isinstance(metadata.size, int) or not 0 < metadata.size <= max_bytes:
            raise ValueError('Model artifact size is outside its expected bound')
        commit = metadata.commit_hash
        if not commit or len(commit) != 40 or any(ch not in '0123456789abcdef' for ch in commit):
            raise ValueError('Model revision is invalid')
        if repo in commits and commits[repo] != commit:
            raise ValueError('Tokenizer revision changed during download')
        commits[repo] = commit
        print(json.dumps({'stage': 'download', 'repository': repo, 'file': filename,
                          'bytes': metadata.size, 'revision': commit}), flush=True)
        path = Path(hf_hub_download(repo, filename, revision=commit, token=False,
                                   cache_dir=str(MODEL_CACHE / 'hub')))
        if not path.resolve().is_relative_to(MODEL_CACHE.resolve()):
            raise ValueError('Model artifact escaped its managed cache')
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        sha = digest.hexdigest()
        if path.stat().st_size != metadata.size:
            raise ValueError('Model artifact size verification failed')
        # LFS/xet artifacts publish a SHA-256 etag. Small git blobs use git SHA-1;
        # verify that format with its canonical blob header as well.
        if len(metadata.etag or '') == 64:
            valid = sha == metadata.etag
        elif len(metadata.etag or '') == 40:
            data = path.read_bytes()
            valid = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == metadata.etag
        else:
            valid = False
        if not valid:
            raise ValueError('Model artifact digest verification failed')
        receipt['assets'].append({'repository': repo, 'file': filename,
                                  'revision': commit, 'bytes': metadata.size,
                                  'sha256': sha, 'publisher_digest_verified': True})
    # Publish local-only main refs only after every required artifact verifies.
    for repo, commit in commits.items():
        refs = MODEL_CACHE / 'hub' / ('models--' + repo.replace('/', '--')) / 'refs'
        refs.mkdir(parents=True, exist_ok=True)
        staged = refs / 'main.new'
        staged.write_text(commit, encoding='ascii')
        os.replace(staged, refs / 'main')
    vocabularies = {
        'cl100k_base': '223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7',
        'o200k_base': '446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d',
    }
    vocab_dir = ROOT / 'models' / 'tiktoken'
    vocab_dir.mkdir(parents=True, exist_ok=True)
    for name, expected_sha in vocabularies.items():
        url = 'https://openaipublic.blob.core.windows.net/encodings/' + name + '.tiktoken'
        path = vocab_dir / hashlib.sha1(url.encode()).hexdigest()
        data = path.read_bytes() if path.exists() else b''
        if hashlib.sha256(data).hexdigest() != expected_sha:
            with urllib.request.urlopen(url, timeout=30) as source:
                data = source.read(5_000_001)
            if len(data) > 5_000_000 or hashlib.sha256(data).hexdigest() != expected_sha:
                raise ValueError('Tokenizer vocabulary verification failed')
            staged = path.with_suffix('.tmp')
            staged.write_bytes(data)
            os.replace(staged, path)
        receipt['assets'].append({'file': name + '.tiktoken', 'source': url,
                                  'bytes': len(data), 'sha256': expected_sha,
                                  'publisher_digest_verified': True})
    receipt['verified_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    path = ROOT / 'models' / 'headroom-proxy-model.json'
    staged = path.with_suffix('.tmp')
    staged.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    os.replace(staged, path)
    print(json.dumps({'ok': True, 'receipt': str(path), 'assets': len(receipt['assets'])}), flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['--worker']:
        main()
    else:
        # The model-serving process never waits for this installer. A download
        # that exceeds its setup budget is stopped and can resume on the next run.
        try:
            child = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'],
                                   timeout=900,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            raise SystemExit(child.returncode)
        except subprocess.TimeoutExpired:
            print(json.dumps({'ok': False, 'error': 'Model prefetch timed out'}))
            raise SystemExit(1)
