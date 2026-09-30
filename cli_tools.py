"""Owned CLI entry points, opt-in controls and argument-free activity counters."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from bundle_preferences import load_preferences, set_preference
from desktop_proxy_control import atomic_write, routing_lock

TOOLS = {'playwright_cli': '@playwright/cli', 'ast_grep': '@ast-grep/cli'}
FAILURES = {
    'connection_refused': 'Browser connection unavailable. Refresh the app CDP endpoint before attaching.',
    'invalid_endpoint': 'Use an explicit HTTP or WebSocket CDP endpoint with a host and port.',
    'ambiguous_selector': 'Selector matched multiple elements. Narrow the locator and inspect the result before retrying.',
    'timeout': 'Browser operation timed out. Inspect the current page before retrying.',
    'command_failed': 'The tool reported a failure. Inspect its command output.',
    'router_unavailable': 'Laya did not authorize this request. Narrow the intent or check the router.',
    'runtime_missing': 'The bundled runtime is unavailable.',
}


def authorize_explicit(*args, **kwargs):
    from laya_dispatch import authorize_explicit as authorize
    return authorize(*args, **kwargs)


def runtime_paths(root):
    root = Path(root).resolve()
    lock = (root / 'packaging/package-lock.json').read_bytes()
    pins = json.loads((root / 'packaging/dependencies.json').read_bytes())
    version = pins['node']['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid Node runtime version.')
    digest = hashlib.sha256(lock).hexdigest()
    return root / ('tools/node-v' + version + '-win-x64'), root / ('tools/agent-clis-' + digest[:16]), digest


def command(root, component):
    node, packages, _ = runtime_paths(root)
    if component == 'playwright_cli':
        return [str(node / 'node.exe'), str(packages / 'node_modules/@playwright/cli/playwright-cli.js')]
    if component == 'ast_grep':
        return [str(packages / 'node_modules/@ast-grep/cli-win32-x64-msvc/ast-grep.exe')]
    raise ValueError('Unknown CLI component.')


def runtime_status(root):
    try:
        node, packages, digest = runtime_paths(root)
        receipt = json.loads((packages / 'ready.json').read_bytes())
        expected = json.loads((Path(root) / 'packaging/package.json').read_bytes())['dependencies']
        available = (receipt.get('lock_sha256') == digest and receipt.get('versions') == expected
                     and all(Path(path).is_file() for name in TOOLS for path in command(root, name)))
        return {'available': available, 'versions': expected}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {'available': False, 'versions': {}}


def status(root, component):
    if component not in TOOLS:
        raise ValueError('Unknown CLI component.')
    runtime = runtime_status(root)
    data = {}
    try:
        path = Path(root) / 'data/cli-tools' / (component + '.json')
        with path.open('rb') as stream:
            data = json.loads(stream.read(16385))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        pass
    failure = data.get('last_failure', {})
    diagnostics = {}
    if isinstance(failure, dict) and failure.get('code') in FAILURES:
        diagnostics = {'last_failure': FAILURES[failure['code']], 'last_failure_code': failure['code'],
                       'last_failure_at': failure.get('at')}
    return {'available': runtime['available'], 'version': runtime['versions'].get(TOOLS[component]),
            'last_use': data.get('last_use'),
            'diagnostics': diagnostics,
            'activity': {key: value if type(value := data.get(key)) is int and value >= 0 else 0
                         for key in ('completed', 'failed', 'blocked', 'informational', 'diagnostic')}}


def record(root, component, outcome, *, kind='operation', task_id=None, error_code=None):
    from bundle_activity import record as record_event
    record_event(root, component, outcome, task_id=task_id, kind=kind, error_code=error_code)
    path = Path(root) / 'data/cli-tools' / (component + '.json')
    try:
        with routing_lock(path.with_suffix('.lock')):
            data = status(root, component)
            counters = data['activity']
            counters[outcome if kind == 'operation' else kind] += 1
            now = datetime.now(timezone.utc).isoformat()
            counters['last_use'] = now if outcome != 'blocked' and kind == 'operation' else data['last_use']
            old = data.get('diagnostics', {})
            if old.get('last_failure_code'):
                counters['last_failure'] = {'code': old['last_failure_code'], 'at': old.get('last_failure_at')}
            if error_code in FAILURES:
                counters['last_failure'] = {'code': error_code, 'at': now}
            atomic_write(path, (json.dumps(counters) + '\n').encode())
    except (OSError, ValueError, RuntimeError):
        pass  # Metrics cannot change command behavior or cause a second execution.


def guidance(before, root, component, enabled):
    label = 'CODEX TOKEN SAVER ' + component.upper()
    start, end = (f'<!-- {kind} {label} -->'.encode() for kind in ('BEGIN', 'END'))
    pattern = re.compile(rb'\r?\n' + re.escape(start) + rb'\r?\n.*?\r?\n' + re.escape(end) + rb'\r?\n', re.S)
    matches = list(pattern.finditer(before))
    if len(matches) > 1 or before.count(start) != len(matches) or before.count(end) != len(matches):
        raise ValueError('Managed CLI guidance markers are damaged; no settings changed.')
    exe = 'playwright-cli.exe' if component == 'playwright_cli' else 'ast-grep.exe'
    invocation = '& "' + str(Path(root).resolve() / 'bin' / exe).replace('`', '``').replace('$', '`$') + '"'
    if component == 'playwright_cli':
        text = (f'For browser tasks where CLI automation is appropriate and permitted, use the enabled bundle Playwright CLI: `{invocation}`. '
                'Read `--help` first; use named sessions and bounded snapshots. Honor any mandated browser tool or browser skill. '
                'Electron renderer control requires an explicitly available CDP endpoint: `-s=NAME attach --cdp=URL`; '
                'use `detach` for an externally owned app. Do not restart apps or enable debugging without authorization. '
                'The CLI does not provide Electron main-process or native desktop automation. ')
    else:
        text = (f'For structural code patterns, prefer the enabled bundle ast-grep: `{invocation} run --lang LANGUAGE --pattern \'PATTERN\' PATH`. '
                'Quote metavariables such as `$A` literally in PowerShell. Use rg for literal text and Serena for symbol navigation. '
                'Read exact matches before edits; use rewrite/update flags only within authorized edit scope. ')
    text += 'Respect the bundle toggle; do not enable it automatically. These tools do not report token savings.'
    text += ' Explicit operations pass through Laya. Prefer bundle_query for a read-only bundle task; the CLI remains available for typed operations such as browser interaction and authorized AST rewrites.'
    block = b'\n' + start + b'\n' + text.encode() + b'\n' + end + b'\n' if enabled else b''
    return pattern.sub(lambda _: block, before) if matches else before + block


def set_enabled(root, component, enabled, config_home=None):
    if component not in TOOLS or type(enabled) is not bool:
        raise ValueError('Choose a CLI component and a boolean value.')
    root = Path(root).resolve()
    if enabled and not runtime_status(root)['available']:
        raise RuntimeError('Install and validate the bundled CLIs before enabling.')
    home = Path(config_home or os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    path = home / 'AGENTS.md'
    with routing_lock(root / 'proxy/routing.lock'):
        existed = path.exists()
        before = path.read_bytes() if existed else b''
        if len(before) > 2 * 1024 * 1024:
            raise ValueError('Guidance is too large to manage safely.')
        after = guidance(before, root, component, enabled)
        previous = load_preferences(root)[component]
        if before != after:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            atomic_write(root / 'integrations/backups' / ('cli-agents-' + stamp + '.md'), before)
        try:
            set_preference(root, component, enabled)
            if before != after:
                from install_desktop_mcp import replace_checked
                home.mkdir(parents=True, exist_ok=True)
                if not existed:
                    with path.open('xb'):
                        pass
                replace_checked(path, before, after)
        except BaseException:
            set_preference(root, component, previous)
            raise
    return {'component': component, 'enabled': enabled, 'restart_required': before != after}


def cdp_preflight(args):
    if 'attach' not in args:
        return None
    endpoint = None
    for index, value in enumerate(args):
        if value.startswith('--cdp='):
            endpoint = value.split('=', 1)[1]
        elif value == '--cdp' and index + 1 < len(args):
            endpoint = args[index + 1]
    if endpoint is None:
        return None
    try:
        url = urlsplit(endpoint)
        if url.scheme not in ('http', 'https', 'ws', 'wss') or not url.hostname:
            return 'invalid_endpoint'
        port = url.port or (443 if url.scheme in ('https', 'wss') else 80)
        with socket.create_connection((url.hostname, port), timeout=2):
            pass
    except ValueError:
        return 'invalid_endpoint'
    except OSError:
        return 'connection_refused'
    return None


def browser_failure(text):
    text = text.lower()
    if 'econnrefused' in text or 'connection refused' in text:
        return 'connection_refused'
    if 'strict mode violation' in text or 'resolved to 2 elements' in text:
        return 'ambiguous_selector'
    if 'timeout' in text or 'timed out' in text:
        return 'timeout'
    return 'command_failed'


def browser_run(argv, environment):
    # Spool instead of holding potentially large snapshots in memory. Replay the
    # exact streams once, and retain only fixed failure categories in metrics.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        result = subprocess.run(argv, env=environment, stdout=output, stderr=errors)
        sample = b''
        for stream, target in ((output, sys.stdout), (errors, sys.stderr)):
            stream.seek(0)
            first = stream.read(8192)
            sample += first
            stream.seek(0)
            while chunk := stream.read(65536):
                if hasattr(target, 'buffer'):
                    target.buffer.write(chunk)
                else:
                    target.write(chunk.decode('utf-8', 'replace'))
            target.flush()
        return result.returncode, browser_failure(sample.decode('utf-8', 'replace')) if result.returncode else None


def run(root, component, args):
    if component not in TOOLS:
        raise ValueError('Unknown CLI component.')
    informational = not args or args[0] == 'help' or any(arg in ('--help', '-h', '--version', '-V') for arg in args)
    kind = 'diagnostic' if os.environ.get('CTS_ACTIVITY_KIND') == 'diagnostic' else 'informational' if informational else 'operation'
    task_id = os.environ.get('CODEX_THREAD_ID')
    def observed(outcome, error_code=None):
        record(root, component, outcome, kind=kind, task_id=task_id, error_code=error_code)
    if not load_preferences(root)[component]:
        print('Codex Token Saver: this CLI is Off. Enable it in Your toolkit.', file=sys.stderr)
        observed('blocked')
        return 126
    if not runtime_status(root)['available']:
        print('Codex Token Saver: CLI runtime is missing or unvalidated. Run the bundle CLI installer.', file=sys.stderr)
        observed('failed', 'runtime_missing')
        return 127
    if not informational:
        try:
            authorize_explicit(root, component, ' '.join(arg for arg in args[:2] if not arg.startswith('-')), task_id=task_id)
        except (ValueError, RuntimeError, OSError):
            print('Codex Token Saver: ' + FAILURES['router_unavailable'], file=sys.stderr)
            observed('blocked', 'router_unavailable')
            return 126
    if component == 'playwright_cli' and not informational:
        error = cdp_preflight(args)
        if error:
            print('Codex Token Saver: ' + FAILURES[error], file=sys.stderr)
            observed('failed', error)
            return 1
    environment = dict(os.environ)
    environment['PLAYWRIGHT_BROWSERS_PATH'] = str(Path(root) / 'tools/playwright-browsers')
    try:
        argv = [*command(root, component), *args]
        error = None
        if component == 'playwright_cli' and not informational:
            code, error = browser_run(argv, environment)
        else:
            code = subprocess.run(argv, env=environment).returncode
    except OSError as error:
        print('Codex Token Saver: CLI could not start: ' + str(error), file=sys.stderr)
        code = 127
        error = 'runtime_missing'
    no_matches = component == 'ast_grep' and code == 1 and bool(args) and args[0] == 'run'
    success = code == 0 or no_matches
    observed('completed' if success else 'failed', None if success else error or 'command_failed')
    return code


if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in TOOLS:
        raise SystemExit('Usage: cli_tools.py playwright_cli|ast_grep [arguments...]')
    raise SystemExit(run(Path(__file__).resolve().parent, sys.argv[1], sys.argv[2:]))
