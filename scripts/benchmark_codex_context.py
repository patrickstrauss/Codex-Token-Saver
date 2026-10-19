"""Opt-in paired native Codex log-diagnosis study; not a whole-bundle benchmark."""
import argparse
from datetime import datetime, timezone
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import socket
import subprocess
import sys
import tempfile
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = {'type': 'object', 'properties': {name: {'type': 'string'} for name in
          ('component', 'failure_code', 'recommended_action')},
          'required': ['component', 'failure_code', 'recommended_action'], 'additionalProperties': False}


def fixtures():
    cases = []
    for index, component in enumerate(('storage', 'payments', 'search', 'auth', 'scheduler')):
        expected = {'component': component, 'failure_code': 'FAILURE_' + str(70 + index),
                    'recommended_action': 'REPAIR_' + str(40 + index)}
        text = ''.join(
            f'ERROR component={component} failure_code={expected["failure_code"]} recommended_action={expected["recommended_action"]}\n'
            if row == 73 + index else f'INFO worker={row} health check OK latency=10ms\n'
            for row in range(400))
        cases.append({'id': 'log-' + str(index + 1), 'text': text, 'expected': expected})
    return cases


def parse_events(stdout, expected):
    usage, answer, tools, failed = None, None, 0, False
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get('type') in ('error', 'turn.failed'):
            failed = True
        item = event.get('item') if isinstance(event.get('item'), dict) else {}
        if item.get('type') in ('command_execution', 'mcp_tool_call', 'web_search', 'file_change'):
            tools += event.get('type') == 'item.completed'
        if event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
            try:
                answer = json.loads(item.get('text', ''))
            except (ValueError, TypeError):
                answer = None
        if event.get('type') == 'turn.completed':
            raw = event.get('usage') if isinstance(event.get('usage'), dict) else {}
            keys = ('input_tokens', 'cached_input_tokens', 'output_tokens')
            usage = {key: raw[key] for key in keys} if all(type(raw.get(key)) is int and raw[key] >= 0 for key in keys) else None
    return {'passed': not failed and answer == expected and tools == 0 and usage is not None,
            'usage': usage, 'unexpected_tool_calls': tools,
            'answer_correct': answer == expected, 'runtime_failed': failed}


def run_study(installed, executable, model, pairs, token_budget):
    from desktop_headroom import DesktopHeadroom
    from exact_retrieval import sign_exact_response

    # Never put credentials or raw model output in the repository or report.
    auth_home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    auth_file = auth_home / 'auth.json'
    auth = json.loads(auth_file.read_bytes())
    if auth.get('OPENAI_API_KEY') or not auth.get('tokens'):
        raise ValueError('This study requires an existing native ChatGPT CLI login')
    original_auth_hash = hashlib.sha256(auth_file.read_bytes()).hexdigest()
    rows, spent = [], 0
    with tempfile.TemporaryDirectory(prefix='token-saver-context-study-') as temporary:
        folder = Path(temporary)
        profile = folder / 'profile'
        profile.mkdir()
        shutil.copyfile(auth_file, profile / 'auth.json')
        (profile / 'config.toml').write_text(
            'model = ' + json.dumps(model) + '\nmodel_provider = "openai"\n'
            'model_reasoning_effort = "low"\ncli_auth_credentials_store = "file"\n'
            'approval_policy = "never"\n', encoding='utf-8')
        schema = folder / 'answer-schema.json'
        schema.write_text(json.dumps(SCHEMA), encoding='utf-8')
        env = {**os.environ, 'CODEX_HOME': str(profile), 'HEADROOM_OFFLINE': '1',
               'HEADROOM_TELEMETRY': 'off', 'HF_HUB_OFFLINE': '1',
               'HF_HUB_DISABLE_TELEMETRY': '1', 'TRANSFORMERS_OFFLINE': '1',
               'LITELLM_LOCAL_MODEL_COST_MAP': 'True', 'HEADROOM_WORKSPACE_DIR': str(folder / 'state'),
               'TIKTOKEN_CACHE_DIR': str(installed / 'headroom/tokenizer-cache')}
        for name in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL', 'OPENAI_WS_BASE_URL',
                     'CODEX_THREAD_ID', 'CTS_CLIENT'):
            env.pop(name, None)
        backend = DesktopHeadroom(folder / 'state', bundle_root=folder)
        try:
            for case in fixtures()[:pairs]:
                path = folder / (case['id'] + '.log')
                path.write_text(case['text'], encoding='utf-8')
                with patch.dict(os.environ, env), patch.object(socket.socket, 'connect', side_effect=RuntimeError('Offline compression only')), \
                     patch('desktop_headroom.sign_exact_response', partial(sign_exact_response, root=folder)):
                    overview = backend.read_file(str(path)).replace(str(folder), '<fixture>')
                if not all(value in overview for value in case['expected'].values()):
                    return study_report(rows, model, original_auth_hash == hashlib.sha256(auth_file.read_bytes()).hexdigest(),
                                        'Compression omitted a required fact; no further model request made')
                arms = [('native', case['text']), ('headroom', overview)]
                random.Random(20261019 + len(rows)).shuffle(arms)
                for arm, context in arms:
                    if spent >= token_budget:
                        return study_report(rows, model, original_auth_hash == hashlib.sha256(auth_file.read_bytes()).hexdigest(),
                                            'Reported-usage stop threshold reached; no further CLI invocation made')
                    prompt = ('Diagnose the single ERROR in this synthetic log. Return the exact component, '
                              'failure_code and recommended_action values. Do not invoke tools or read files; '
                              'all evidence is below.\n\n' + context)
                    started = perf_counter()
                    try:
                        result = subprocess.run([str(executable), 'exec', '--ephemeral', '--json', '--color', 'never',
                            '--sandbox', 'read-only', '--skip-git-repo-check', '--cd', str(folder),
                            '--output-schema', str(schema), '-'], input=prompt, capture_output=True,
                            text=True, encoding='utf-8', errors='replace', env=env, timeout=120)
                    except subprocess.TimeoutExpired:
                        rows.append({'fixture': case['id'], 'arm': arm, 'passed': False, 'usage': None,
                                     'runtime_failed': True, 'timed_out': True})
                        return study_report(rows, model, original_auth_hash == hashlib.sha256(auth_file.read_bytes()).hexdigest(),
                                            'CLI task timed out; captured output omitted; no retries made')
                    parsed = parse_events(result.stdout, case['expected'])
                    parsed.update(fixture=case['id'], arm=arm, return_code=result.returncode,
                                  wall_seconds=round(perf_counter() - started, 3),
                                  context_sha256=hashlib.sha256(context.encode()).hexdigest(),
                                  context_tokens=backend._count(context))
                    rows.append(parsed)
                    usage = parsed['usage'] or {}
                    spent += usage.get('input_tokens', 0) + usage.get('output_tokens', 0)
                    if result.returncode or parsed['runtime_failed'] or not parsed['usage']:
                        return study_report(rows, model, original_auth_hash == hashlib.sha256(auth_file.read_bytes()).hexdigest(),
                                            'Native CLI/auth/model request failed or did not report usage; no retries made')
        finally:
            if backend._cache is not None:
                backend._cache._backend._conn.close()
                from headroom.cache.compression_store import get_compression_store
                connection = getattr(get_compression_store()._backend, '_conn', None)
                if connection is not None:
                    connection.close()
    return study_report(rows, model, original_auth_hash == hashlib.sha256(auth_file.read_bytes()).hexdigest())


def study_report(rows, model, auth_unchanged, stopped_reason=None):
    return {'schema_version': 1, 'measured_at': datetime.now(timezone.utc).isoformat(),
            'scope': 'Synthetic log diagnosis: raw context versus local Headroom context; tools not selected by model',
            'model': model, 'reasoning_effort': 'low', 'samples': rows,
            'passed': bool(rows) and not stopped_reason and all(row['passed'] for row in rows),
            'stopped_reason': stopped_reason, 'daily_auth_file_unchanged': auth_unchanged,
            'cli_invocations': len(rows), 'automatic_network_retries_measured': False,
            'profile': 'Temporary native-provider profile; ephemeral fresh sessions',
            'limitations': ['Five synthetic log fixtures are not a representative end-to-end coding benchmark.',
                'Does not measure RTK, Laya routing, Serena, structural search, browser work or request compression.',
                'Cached input is reported separately; input token counts are not quota or billing savings.',
                'Token budget is a stop threshold between tasks, not a hard cap on a single request or internal retries.',
                'No model grading call is used; answers must exactly match preregistered fixture fields.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Opt in to at most ten native account CLI tasks')
    parser.add_argument('--installed', type=Path)
    parser.add_argument('--codex', type=Path, help='Native Codex executable, not a shell shim')
    parser.add_argument('--model')
    parser.add_argument('--pairs', type=int, choices=range(1, 6), default=5)
    parser.add_argument('--token-budget', type=int, default=150000)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.run:
        result = {'plan_only': True, 'model_calls': 0, 'max_cli_invocations': args.pairs * 2,
                  'fixtures': [{'id': case['id'], 'expected': case['expected'],
                                'sha256': hashlib.sha256(case['text'].encode()).hexdigest()} for case in fixtures()[:args.pairs]],
                  'scope': 'Paired context experiment, not a whole-bundle coding benchmark'}
    else:
        if not args.installed or not args.codex or not args.model or args.token_budget <= 0:
            parser.error('--run requires --installed, --codex, --model and a positive token budget')
        try:
            result = run_study(args.installed, args.codex, args.model, args.pairs, args.token_budget)
        except (OSError, ValueError):
            # CLI/setup diagnostics can contain private paths or authentication data.
            result = {'schema_version': 1, 'passed': False,
                      'stopped_reason': 'Local setup or CLI invocation failed; private diagnostic text omitted',
                      'usage': None}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('plan_only', 'passed', 'model_calls', 'cli_invocations', 'stopped_reason') if key in result}))
    return 0 if result.get('plan_only') or result.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
