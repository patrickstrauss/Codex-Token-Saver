"""Offline quality gates and paired latency samples; never calls Codex or an LLM."""
import argparse
from datetime import datetime, timezone
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
from statistics import median
import subprocess
import sys
import tempfile
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def compare_content(original, overview, recovered, critical_facts):
    """Compare exact UTF-8 content, not just the presence of selected facts."""
    if not critical_facts or any(fact not in original for fact in critical_facts):
        raise ValueError('Each fixture must contain its declared critical facts.')
    missing_overview = [fact for fact in critical_facts if fact not in overview]
    missing_recovered = [fact for fact in critical_facts if fact not in recovered]
    identical = original.encode('utf-8') == recovered.encode('utf-8')
    return {
        'passed': identical and not missing_overview and not missing_recovered,
        'original_identical': identical,
        'original_sha256': hashlib.sha256(original.encode('utf-8')).hexdigest(),
        'missing_overview_facts': missing_overview,
        'missing_recovered_facts': missing_recovered,
    }


def summarize_samples(samples):
    if not samples:
        raise ValueError('At least one paired measurement is required.')
    return {
        'passed': all(item['passed'] for item in samples),
        'repeats': len(samples),
        'original_median_ms': round(median(item['original_ms'] for item in samples), 3),
        'optimized_median_ms': round(median(item['optimized_ms'] for item in samples), 3),
        'median_added_ms': round(median(item['optimized_ms'] - item['original_ms']
                                       for item in samples), 3),
    }


def timed(action):
    started = perf_counter()
    value = action()
    return value, (perf_counter() - started) * 1000


def headroom_case(backend, folder, name, original, facts, repeats):
    source = folder / name
    source.write_bytes(original.encode('utf-8'))
    samples = []
    cold_ms = None
    # Warm up once, then measure repeated calls without imports/tokenizer startup.
    for index in range(repeats + 1):
        raw, raw_ms = timed(lambda: source.read_bytes().decode('utf-8'))
        overview, compressed_ms = timed(lambda: backend.read_file(str(source)))
        compressed = 'Compressed overview:' in overview
        key = hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]
        exact, retrieval_ms = timed(lambda: backend.retrieve(key) if compressed else overview)
        recovered = exact.split('\n\n', 1)[1]
        check = compare_content(raw, overview, recovered, facts)
        if index == 0:
            cold_ms = compressed_ms
            continue
        samples.append({**check, 'original_ms': raw_ms, 'optimized_ms': compressed_ms,
                        'retrieval_ms': retrieval_ms, 'compressed': compressed,
                        'original_tokens': backend._count(raw),
                        'optimized_tokens': backend._count(overview),
                        'retrieval_tokens': backend._count(exact) if compressed else 0})
    sample = samples[-1]
    return {
        'fixture': name, **summarize_samples(samples),
        'first_call_ms': round(cold_ms, 3),
        'retrieval_median_ms': round(median(item['retrieval_ms'] for item in samples), 3),
        'compressed': all(item['compressed'] for item in samples),
        'original_identical': all(item['original_identical'] for item in samples),
        'missing_overview_facts': sorted({fact for item in samples for fact in item['missing_overview_facts']}),
        'original_tokens': sample['original_tokens'], 'optimized_tokens': sample['optimized_tokens'],
        'estimated_tokens_avoided_before_retrieval': sample['original_tokens'] - sample['optimized_tokens'],
        'estimated_tokens_avoided_after_full_retrieval':
            sample['original_tokens'] - sample['optimized_tokens'] - sample['retrieval_tokens'],
    }


def rtk_case(installed, folder, backend, repeats):
    # Call the underlying binary, not the launcher that forces the live ledger.
    binary = installed / 'tools/rtk.exe'
    git = shutil.which('git')
    if not binary.is_file() or not git:
        return {'status': 'skipped', 'reason': 'Installed tools/rtk.exe and Git are required.'}
    repo = folder / 'git-fixture'
    repo.mkdir()
    (folder / 'empty-gitconfig').write_text('', encoding='utf-8')
    env = dict(os.environ, RTK_DB_PATH=str(folder / 'rtk.db'), RTK_TELEMETRY_DISABLED='1',
               HOME=str(folder), USERPROFILE=str(folder),
               APPDATA=str(folder / 'roaming'), LOCALAPPDATA=str(folder / 'local'),
               XDG_CONFIG_HOME=str(folder / 'config'), XDG_DATA_HOME=str(folder / 'data'),
               GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=str(folder / 'empty-gitconfig'),
               GIT_CONFIG_COUNT='0', HEADROOM_EXACT='1', NO_COLOR='1')

    def run(command):
        return subprocess.run(command, cwd=repo, env=env, check=True, capture_output=True,
                              timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.decode('utf-8')

    run([git, 'init', '--quiet'])
    source = repo / 'settings.txt'
    source.write_text('timeout_seconds=30\nretry_limit=3\n', encoding='utf-8')
    run([git, 'add', 'settings.txt'])
    source.write_text('timeout_seconds=60\nretry_limit=0\n', encoding='utf-8')
    samples = []
    for _ in range(repeats):
        original, original_ms = timed(lambda: run([git, 'diff', '--no-ext-diff', '--no-color']))
        optimized, optimized_ms = timed(lambda: run([str(binary), 'git', 'diff']))
        # Native re-read is RTK's recovery path. Both removed and added values matter.
        recovered = run([git, 'diff', '--no-ext-diff', '--no-color'])
        check = compare_content(original, optimized, recovered,
                                ['-timeout_seconds=30', '+timeout_seconds=60',
                                 '-retry_limit=3', '+retry_limit=0'])
        samples.append({**check, 'original_ms': original_ms, 'optimized_ms': optimized_ms})
    return {'status': 'measured', **summarize_samples(samples),
            'original_tokens': backend._count(original), 'optimized_tokens': backend._count(optimized),
            'missing_overview_facts': sorted({fact for item in samples for fact in item['missing_overview_facts']}),
            'recovery': 'Native git diff repeated against the unchanged fixture; RTK does not store originals.',
            'scope': 'Underlying RTK binary only; launcher and stacked Headroom overhead excluded.'}


def run_benchmark(installed, repeats):
    from desktop_headroom import DesktopHeadroom
    from exact_retrieval import sign_exact_response

    def deny_network(*args, **kwargs):
        raise RuntimeError('Network access is disabled for this offline benchmark.')

    with tempfile.TemporaryDirectory(prefix='token-saver-benchmark-') as temporary:
        folder = Path(temporary)
        env = {
            'HEADROOM_WORKSPACE_DIR': str(folder / 'headroom'), 'HEADROOM_OFFLINE': '1',
            'HEADROOM_TELEMETRY': 'off', 'HEADROOM_LOG_PAYLOAD_PREVIEW': '0',
            'HF_HUB_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1',
            'TRANSFORMERS_OFFLINE': '1', 'LITELLM_LOCAL_MODEL_COST_MAP': 'True',
            'TIKTOKEN_CACHE_DIR': str(installed / 'headroom/tokenizer-cache'),
        }
        # Isolate ledgers, original storage and the exact-response signing key.
        with patch.dict(os.environ, env), patch.object(socket.socket, 'connect', deny_network), \
             patch('desktop_headroom.sign_exact_response', partial(sign_exact_response, root=folder)):
            backend = DesktopHeadroom(folder / 'headroom', bundle_root=folder)
            try:
                records = json.dumps({'records': [
                    {'id': i, 'level': 'ERROR' if i == 78 else 'INFO',
                     'message': 'CRITICAL_DB_FAILURE E78' if i == 78 else 'completed successfully',
                     'service': 'api'} for i in range(150)]})
                logs = ''.join(
                    '2026-09-20T10:00:00Z ERROR CRITICAL_FAILURE_73 database unavailable\r\n'
                    if i == 73 else f'2026-09-20T10:00:00Z INFO worker={i} health check OK latency=10ms\r\n'
                    for i in range(200))
                headroom = [
                    headroom_case(backend, folder, 'records.json', records, ['CRITICAL_DB_FAILURE E78'], repeats),
                    headroom_case(backend, folder, 'worker.log', logs, ['CRITICAL_FAILURE_73'], repeats),
                ]
                rtk = rtk_case(installed, folder, backend, repeats)
            finally:
                if backend._cache is not None:
                    backend._cache._backend._conn.close()
                from headroom.cache.compression_store import get_compression_store
                sdk_connection = getattr(get_compression_store()._backend, '_conn', None)
                if sdk_connection is not None:
                    sdk_connection.close()
    return {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'passed': all(case['passed'] and case['compressed'] for case in headroom)
                  and rtk.get('passed', False),
        'headroom': headroom, 'rtk': rtk,
        'isolated_from_live_ledgers': True, 'external_model_calls': 0,
        'limitations': ['Synthetic fixtures measure fact preservation and exact recovery, not LLM answer quality.',
                        'Local token estimates are not measured Codex usage or quota savings.',
                        'Full retrieval consumes tokens; the report includes this cost.',
                        'This does not exercise request-proxy compression or Serena language servers.'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed', type=Path, required=True)
    parser.add_argument('--repeats', type=int, choices=range(3, 11), default=3)
    parser.add_argument('--output', type=Path, default=ROOT / 'logs/performance-benchmark.json')
    args = parser.parse_args()
    result = run_benchmark(args.installed.resolve(), args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
