"""Owned CLI entry points, opt-in controls and argument-free activity counters."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from bundle_preferences import load_preferences, set_preference
from desktop_proxy_control import atomic_write, routing_lock

TOOLS = {'playwright_cli': '@playwright/cli', 'ast_grep': '@ast-grep/cli'}


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
    return {'available': runtime['available'], 'version': runtime['versions'].get(TOOLS[component]),
            'last_use': data.get('last_use'),
            'activity': {key: value if type(value := data.get(key)) is int and value >= 0 else 0
                         for key in ('completed', 'failed', 'blocked')}}


def record(root, component, outcome):
    path = Path(root) / 'data/cli-tools' / (component + '.json')
    try:
        with routing_lock(path.with_suffix('.lock')):
            data = status(root, component)
            counters = data['activity']
            counters[outcome] += 1
            counters['last_use'] = datetime.now(timezone.utc).isoformat() if outcome != 'blocked' else data['last_use']
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


def run(root, component, args):
    if component not in TOOLS:
        raise ValueError('Unknown CLI component.')
    if not load_preferences(root)[component]:
        print('Codex Token Saver: this CLI is Off. Enable it in Your toolkit.', file=sys.stderr)
        record(root, component, 'blocked')
        return 126
    if not runtime_status(root)['available']:
        print('Codex Token Saver: CLI runtime is missing or unvalidated. Run the bundle CLI installer.', file=sys.stderr)
        return 127
    environment = dict(os.environ)
    environment['PLAYWRIGHT_BROWSERS_PATH'] = str(Path(root) / 'tools/playwright-browsers')
    try:
        result = subprocess.run([*command(root, component), *args], env=environment)
        code = result.returncode
    except OSError as error:
        print('Codex Token Saver: CLI could not start: ' + str(error), file=sys.stderr)
        code = 127
    record(root, component, 'completed' if code == 0 else 'failed')
    return code


if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in TOOLS:
        raise SystemExit('Usage: cli_tools.py playwright_cli|ast_grep [arguments...]')
    raise SystemExit(run(Path(__file__).resolve().parent, sys.argv[1], sys.argv[2:]))
