"""Opt-in paired, tool-using Codex coding benchmark; no VM or daily profile changes."""
import argparse
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import shutil
import subprocess
import sys
import tempfile
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.benchmark_e2e_fixtures import ORACLE, cases, grade, manifest, prepare, schema
from scripts.benchmark_stack import full_configuration

COMMON_GUIDANCE = '''Work only in the task workspace. Do not inspect parent directories, user data,
credentials or other projects. Use available tools to investigate; do not guess.
Do not use the internet, install packages, change providers or spawn subagents.
Prefer bounded output. Only change files explicitly authorized by the task.
Return the requested JSON. The evaluator independently checks files and answers.
'''
BUNDLE_GUIDANCE = '''The enabled Token Saver tools are available. Prefer Headroom for large file
reads and exact retrieval when needed; Serena for named definitions/references;
Laya bundle_query with pattern+language for structural syntax. Explicit bundle
calls consult Laya; respect disabled tools. Prefer Laya for bundle Git reports.
Use native tools when a bundle operation is unhelpful or blocked. Do not repeat
queries merely to exercise a tool. Use exact source before editing.
'''
SERVERS = {'bundle_laya_router': 'bundle_router_mcp.py',
           'headroom_desktop': 'desktop_mcp.py', 'bundle_serena': 'serena_mcp.py'}
SAFE_TOOLS = {'bundle_query', 'headroom_read_file', 'headroom_retrieve', 'headroom_stats',
              'activate_project', 'find_symbol', 'find_referencing_symbols', 'get_symbols_overview'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def runtime_versions(installed):
    probe = '''import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from runtime_selection import selected_runtime
from component_runtime import component_descriptor
root=Path(sys.argv[1])
print(json.dumps({'headroom':selected_runtime(root)['version'],
 'serena':component_descriptor(root,'serena')['version'],
 'laya':component_descriptor(root,'laya')['version']}))
'''
    output = subprocess.run([str(installed / 'headroom/.venv/Scripts/python.exe'), '-c', probe, str(installed)],
                            capture_output=True, text=True, check=True, timeout=20).stdout
    versions = json.loads(output)
    for component in ('rtk', 'ast-grep'):
        value = subprocess.run([str(installed / ('bin/' + component + '.exe')), '--version'],
                               capture_output=True, text=True, check=True, timeout=20).stdout.strip()
        if not re.fullmatch(r'[A-Za-z -]+[0-9]+(?:\.[0-9A-Za-z+-]+)+', value):
            raise ValueError('Unrecognized component version')
        versions[component] = value
    return versions


def study_cases(configuration='explicit'):
    data = cases()
    if configuration == 'full':
        for case in data:
            if case['id'] == 'symbol-tracing':
                case['prompt'] += (' Return implementation and validation as unqualified function names, '
                                   'and source as a project-relative file path using forward slashes.')
    return data


def study_manifest(seed, configuration='explicit'):
    data = manifest(seed)
    for item, case in zip(data['cases'], study_cases(configuration)):
        item['prompt'] = case['prompt']
    rng = random.Random(seed)
    for case in data['cases']:
        case['order'] = rng.sample(['native', 'bundle'], 2)
    data.update(configuration=configuration, oracle_sha256=hashlib.sha256(ORACLE.encode()).hexdigest(),
                native_guidance=COMMON_GUIDANCE, bundle_guidance=COMMON_GUIDANCE + BUNDLE_GUIDANCE,
                excluded=['automatic request proxy', 'automatic command hook', 'browser tasks',
                          'external harnesses', 'account quota/billing measurement'])
    if configuration == 'full':
        data['scope'] = 'Five paired coding tasks: native vs explicit tools plus automatic request compression and reviewed hook'
        data['excluded'] = ['browser tasks', 'external harnesses', 'account quota/billing measurement']
    return data


def child_environment(profile, state):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('CODEX_', 'OPENAI_', 'CTS_', 'HEADROOM_'))}
    env.update(CODEX_HOME=str(profile), PYTHONUTF8='1', NO_COLOR='1', OTEL_SDK_DISABLED='true',
               CTS_ACTIVITY_KIND='diagnostic', HEADROOM_OFFLINE='1', HEADROOM_TELEMETRY='off',
               HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', TRANSFORMERS_OFFLINE='1',
               LITELLM_LOCAL_MODEL_COST_MAP='True', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_COUNT='0', RTK_TELEMETRY_DISABLED='1', RTK_DB_PATH=str(state / 'rtk.db'))
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    return env


def profile_text(model, arm, installed, state):
    text = ('model = ' + json.dumps(model) + '\nmodel_provider = "openai"\n'
            'model_reasoning_effort = "low"\ncli_auth_credentials_store = "file"\n'
            'approval_policy = "never"\nweb_search = "disabled"\n'
            '[features]\nmulti_agent = false\nplugins = false\nremote_plugin = false\napps = false\n'
            'shell_tool = true\nunified_exec = true\n'
            '[windows]\nsandbox = "unelevated"\n')
    if arm == 'bundle':
        environment = {'PYTHONUTF8': '1', 'CTS_ACTIVITY_KIND': 'diagnostic', 'CODEX_THREAD_ID': '',
                       'HEADROOM_WORKSPACE_DIR': str(state / 'headroom'),
                       'CODEX_HOME': str(state / 'no-credentials'), 'RTK_DB_PATH': str(state / 'rtk.db'),
                       'RTK_TELEMETRY_DISABLED': '1'}
        for name, script in SERVERS.items():
            text += ('\n[mcp_servers.' + name + ']\ncommand = ' + json.dumps(str(installed / 'headroom/.venv/Scripts/python.exe')) +
                     '\nargs = ' + json.dumps(['-u', str(installed / script)]) +
                     '\nrequired = true\nstartup_timeout_sec = 40\ntool_timeout_sec = 90\n'
                     'env = { ' + ', '.join(key + ' = ' + json.dumps(value) for key, value in environment.items()) + ' }\n')
    return text


def parse_events(stdout):
    usage, answer, failed, errors, command_failures = None, None, False, 0, 0
    counts, calls = Counter(), []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get('type') in ('turn.failed', 'error'):
            failed, errors = True, errors + 1
        item = event.get('item') if isinstance(event.get('item'), dict) else {}
        if event.get('type') == 'item.completed':
            kind = item.get('type')
            if kind in ('command_execution', 'mcp_tool_call', 'file_change', 'web_search'):
                counts[kind] += 1
            if kind == 'command_execution' and item.get('exit_code') not in (0, None):
                command_failures += 1
            if kind == 'agent_message':
                try:
                    answer = json.loads(item.get('text', ''))
                except (TypeError, ValueError):
                    answer = None
            if kind == 'mcp_tool_call':
                result = item.get('result') if isinstance(item.get('result'), dict) else {}
                calls.append({'server': item.get('server') if item.get('server') in SERVERS else 'other',
                              'tool': item.get('tool') if item.get('tool') in SAFE_TOOLS else 'other',
                              'failed': bool(item.get('error')) or result.get('isError') is True or item.get('status') == 'failed'})
        if event.get('type') == 'turn.completed':
            raw = event.get('usage') if isinstance(event.get('usage'), dict) else {}
            keys = ('input_tokens', 'cached_input_tokens', 'output_tokens')
            if all(type(raw.get(key)) is int and raw[key] >= 0 for key in keys) and raw['cached_input_tokens'] <= raw['input_tokens']:
                usage = {key: raw[key] for key in keys}
                if type(raw.get('reasoning_output_tokens')) is int:
                    usage['reasoning_output_tokens'] = raw['reasoning_output_tokens']
    return {'usage': usage, 'answer': answer, 'runtime_failed': failed, 'error_events': errors,
            'command_failures': command_failures,
            'tool_counts': dict(counts), 'bundle_calls': calls}


def failure_category(text):
    text = text.lower()
    for category, markers in (
        ('sandbox', ('sandbox setup', 'sandbox error', 'sandbox is not', 'failed to create sandbox',
                     'restricted-token sandbox', 'refusing to run unsandboxed')),
        ('authentication', ('unauthorized', '401', 'authentication', 'refresh token')),
        ('model', ('model is not supported', 'model not found', 'model_not_found')),
        ('transport', ('connection', 'stream disconnected', 'websocket', 'timed out')),
        ('configuration', ('error parsing configuration', 'invalid value', 'config.toml')),
    ):
        if any(marker in text for marker in markers):
            return category
    return 'unclassified'


def invoke(command, prompt, env, timeout):
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8', errors='replace', env=env,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        stdout, stderr = process.communicate(prompt, timeout=timeout)
        return process.returncode, stdout, stderr, False
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill.exe', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=15)
            else:
                process.kill()
        stdout, stderr = process.communicate(timeout=15)
        return process.returncode, stdout, stderr, True


def summarize(rows):
    totals = {}
    for arm in ('native', 'bundle'):
        samples = [row for row in rows if row['arm'] == arm]
        measured = [row for row in samples if row['usage'] is not None]
        totals[arm] = {'attempts': len(samples), 'passed': sum(row['passed'] for row in samples),
                       'usage_samples': len(measured), 'wall_seconds': round(sum(row['wall_seconds'] for row in samples), 3),
                       **{key: sum(row['usage'][key] for row in measured)
                          for key in ('input_tokens', 'cached_input_tokens', 'output_tokens')}}
        totals[arm]['uncached_input_tokens'] = totals[arm]['input_tokens'] - totals[arm]['cached_input_tokens']
    complete_usage = all(row['usage'] is not None for row in rows)
    before, after = totals['native']['input_tokens'], totals['bundle']['input_tokens']
    return {'arms': totals,
            'input_reduction_percent': round((before - after) / before * 100, 2) if complete_usage and before and len(rows) == 10 else None,
            'quota_savings_measured': False, 'billing_savings_measured': False,
            'bundle_calls': sum(len(row['bundle_calls']) for row in rows),
            'bundle_call_failures': sum(call['failed'] for row in rows for call in row['bundle_calls'])}


def write_report(path, report):
    report['summary'] = summarize(report['samples'])
    report['complete'] = len(report['samples']) == 10
    report['passed'] = report['complete'] and all(row['passed'] for row in report['samples'])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.pending')
    temporary.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def run(args, frozen):
    installed, executable = args.installed.resolve(), args.codex.resolve()
    git = shutil.which('git')
    if not git or not executable.is_file():
        raise ValueError('Git and an explicit native Codex executable are required')
    version = subprocess.run([str(executable), '--version'], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    if not re.fullmatch(r'codex-cli [0-9A-Za-z.+-]+', version):
        raise ValueError('Unrecognized Codex version response')
    component_flags = {}
    for name in ('components', 'extensions'):
        data = json.loads((installed / ('settings/' + name + '.json')).read_bytes())
        component_flags.update(data['components'])
    if any(component_flags.get(key) is not True for key in ('headroom_local', 'serena', 'ast_grep', 'rtk', 'laya_router')):
        raise ValueError('Required bundle components must already be On; no switches changed')
    source_names = [*SERVERS.values(), 'laya_dispatch.py', 'bundle_router.py', 'desktop_headroom.py']
    if args.configuration == 'full':
        source_names += ['desktop_proxy.py', 'proxy_runtime.py', 'Headroom-PreToolUse.ps1', 'bin/rtk.exe']
    source_files = {name: hashlib.sha256((installed / name).read_bytes()).hexdigest() for name in source_names}
    metadata = {'configured_model': args.model, 'reasoning_effort': 'low', 'codex_version': version,
                'os': platform.system(), 'os_version': platform.version(), 'architecture': platform.machine(),
                'bundle_source_sha256': source_files, 'components_on': sorted(key for key, value in component_flags.items() if value),
                'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'fixture_generator_sha256': hashlib.sha256((ROOT / 'scripts/benchmark_e2e_fixtures.py').read_bytes()).hexdigest(),
                'stack_helper_sha256': hashlib.sha256((ROOT / 'scripts/benchmark_stack.py').read_bytes()).hexdigest(),
                'seed': args.seed, 'manifest_sha256': fingerprint(frozen),
                'automatic_compression': args.configuration == 'full', 'automatic_hook': args.configuration == 'full',
                'configuration': args.configuration,
                'sandbox_mode': args.sandbox, 'bundle_versions': runtime_versions(installed)}
    auth_home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    auth_file = auth_home / 'auth.json'
    auth = json.loads(auth_file.read_bytes())
    if auth.get('OPENAI_API_KEY') or not auth.get('tokens'):
        raise ValueError('An existing native ChatGPT login is required; no login reset performed')
    originals = {path: path.read_bytes() for path in (auth_file, auth_home / 'config.toml', auth_home / 'hooks.json',
                 installed / 'settings/components.json', installed / 'settings/extensions.json',
                 installed / 'proxy/settings.json') if path.exists()}
    if args.output.exists():
        if not args.resume:
            raise ValueError('Output exists; use --resume to continue without repeating completed samples')
        report = json.loads(args.output.read_text(encoding='utf-8'))
        if report.get('metadata') != metadata:
            raise ValueError('CLI, fixture, model or bundle metadata changed; continuation refused')
    else:
        report = {'schema_version': 1, 'started_at': datetime.now(timezone.utc).isoformat(),
                  'scope': frozen['scope'], 'metadata': metadata, 'samples': [],
                  'manual_retries': 0, 'automatic_network_retries_measured': False,
                  'daily_profile_unchanged': None,
                  'limitations': ['Five synthetic paired tasks; no statistical generalization.',
                      'Explicit-tool configuration only; automatic proxy/hooks and browser tasks excluded.',
                      'Provider prefix caches and shared workers are not flushed; cache tokens reported separately.',
                      'Reported tokens are not measured weekly quota or billing savings.',
                      'Bundle events are tagged diagnostic; installed workers may update diagnostic/runtime aggregates.',
                      'Token budget is checked between CLI tasks, not a cap on one task or internal retries.']}
        if args.configuration == 'full':
            report['limitations'][1] = 'Full configured coding stack; browser tasks and external clients excluded.'
            report['limitations'].append('Uses an isolated production relay and the existing warm Headroom backend; no worker restart or global route change.')
    if not args.resume:
        args.output.with_suffix('.manifest.json').write_text(json.dumps(frozen, indent=2) + '\n', encoding='utf-8')
    finished = {(row['case'], row['arm']) for row in report['samples']}
    allowed = {(case['id'], arm) for case in frozen['cases'] for arm in case['order']}
    if len(finished) != len(report['samples']) or not finished <= allowed:
        raise ValueError('Invalid or duplicate checkpoint samples')
    ran_pairs = 0
    try:
        for case, frozen_case in zip(study_cases(args.configuration), frozen['cases']):
            if all((case['id'], arm) in finished for arm in frozen_case['order']):
                continue
            if ran_pairs >= args.max_pairs:
                break
            for arm in frozen_case['order']:
                if (case['id'], arm) in finished:
                    continue
                spent = sum((row['usage'] or {}).get('input_tokens', 0) + (row['usage'] or {}).get('output_tokens', 0)
                            for row in report['samples'])
                if spent >= args.token_budget:
                    report['stopped_reason'] = 'Reported token stop threshold reached before next task'
                    return report
                with tempfile.TemporaryDirectory(prefix='token-saver-e2e-') as temporary, ExitStack() as sessions:
                    folder = Path(temporary)
                    profile, state, workspace = folder / 'profile', folder / 'tool-state', folder / 'workspace'
                    profile.mkdir(); state.mkdir()
                    shutil.copyfile(auth_file, profile / 'auth.json')
                    (profile / 'config.toml').write_text(profile_text(args.model, arm, installed, state), encoding='utf-8')
                    (profile / 'AGENTS.md').write_text(COMMON_GUIDANCE + (BUNDLE_GUIDANCE if arm == 'bundle' else ''), encoding='utf-8')
                    env = child_environment(profile, state)
                    prepare(case, workspace, git, env)
                    schema_file = folder / 'answer-schema.json'
                    schema_file.write_text(json.dumps(schema(case)), encoding='utf-8')
                    command = [str(executable), 'exec', '--ephemeral', '--json', '--color', 'never',
                               '--sandbox', args.sandbox, '--skip-git-repo-check', '--cd', str(workspace),
                               '--output-schema', str(schema_file), '-']
                    observation = None
                    if args.configuration == 'full' and arm == 'bundle':
                        observation = sessions.enter_context(full_configuration(installed, state, profile, env))
                        # Only the exact reviewed production hook in this temporary profile.
                        # No trust is persisted or inherited from the user's other hooks.
                        command.insert(2, '--dangerously-bypass-hook-trust')
                    started = perf_counter()
                    code, stdout, stderr, timed_out = invoke(command, case['prompt'], env, args.task_timeout)
                    elapsed = round(perf_counter() - started, 3)
                    parsed = parse_events(stdout)
                    answer = parsed.pop('answer')
                    quality = grade(case, workspace, answer)
                    row = dict(case=case['id'], arm=arm, **parsed, quality=quality,
                               return_code=code, timed_out=timed_out,
                               wall_seconds=elapsed,
                               failure_category=failure_category(stdout + stderr) if code or timed_out or not quality['passed'] else None,
                               changed_source_sha256={name: hashlib.sha256((workspace / name).read_bytes()).hexdigest()
                                                      for name in case.get('editable', []) if (workspace / name).is_file()})
                    if observation is not None:
                        row['automatic_activity'] = observation(stdout)
                    row['passed'] = code == 0 and not timed_out and not parsed['runtime_failed'] and parsed['usage'] is not None and quality['passed'] and sum(parsed['tool_counts'].values()) > 0
                    report['samples'].append(row)
                    report['daily_profile_unchanged'] = all(path.read_bytes() == content for path, content in originals.items())
                    write_report(args.output, report)
                    print(json.dumps({'case': case['id'], 'arm': arm, 'passed': row['passed'],
                                      'usage': row['usage'], 'tools': row['tool_counts'], 'failure_category': row['failure_category']}), flush=True)
                    if code or timed_out or row['usage'] is None:
                        report['stopped_reason'] = 'CLI/runtime failed or usage absent; no manual retry made'
                        return report
            ran_pairs += 1
    finally:
        report['daily_profile_unchanged'] = all(path.read_bytes() == content for path, content in originals.items())
        write_report(args.output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--installed', type=Path)
    parser.add_argument('--codex', type=Path)
    parser.add_argument('--model', default='gpt-6.1-sol')
    parser.add_argument('--configuration', choices=('explicit', 'full'), default='explicit')
    parser.add_argument('--seed', type=int, default=20261019)
    parser.add_argument('--max-pairs', type=int, choices=range(1, 6), default=5)
    parser.add_argument('--token-budget', type=int, default=1500000)
    parser.add_argument('--task-timeout', type=int, default=240)
    parser.add_argument('--sandbox', choices=('workspace-write', 'danger-full-access'), default='workspace-write',
                        help='Same mode for both arms; full access is opt-in for trusted synthetic tasks only')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    frozen = study_manifest(args.seed, args.configuration)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.run:
        args.output.write_text(json.dumps(frozen, indent=2) + '\n', encoding='utf-8')
        print('PLAN ONLY: zero model calls; five frozen pairs.')
        return 0
    if not args.installed or not args.codex or args.token_budget <= 0 or args.task_timeout <= 0:
        parser.error('--run requires --installed, --codex and positive limits')
    try:
        result = run(args, frozen)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print('Study setup/execution failed; private diagnostic text omitted. Inspect existing redacted checkpoint.', file=sys.stderr)
        return 2
    return 0 if result.get('passed') or not result.get('complete') and not result.get('stopped_reason') else 1


if __name__ == '__main__':
    raise SystemExit(main())
