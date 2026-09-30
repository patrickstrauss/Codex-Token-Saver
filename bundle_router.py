"""Laya-first bundle facade; typed recipes, local execution, no Codex routing edits."""
import asyncio
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from bundle_preferences import load_preferences
from desktop_proxy_control import atomic_write, routing_lock
from laya_worker import RECIPES

COMPONENT = {'file_read': 'headroom_local', 'symbols': 'serena', 'ast_search': 'ast_grep',
             'git_report': 'rtk', 'browser_snapshot': 'playwright_cli', 'summary': 'local_summaries'}


def status(root):
    root = Path(root)
    data = {}
    try:
        data = json.loads((root / 'data/router/activity.json').read_bytes())
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        pass
    available = all((root / name).is_file() for name in (
        'laya/.venv/Scripts/python.exe', 'laya/ready.json', 'laya/model/model.safetensors', 'bundle_router_mcp.py'))
    if available:
        try:
            receipt = json.loads((root / 'laya/ready.json').read_bytes())
            manifest = json.loads((root / 'packaging/laya-model.json').read_bytes())
            available = receipt == {'version': '0.3.22', 'revision': manifest['revision'], 'inference_verified': True}
        except (OSError, ValueError, KeyError, TypeError):
            available = False
    return {'available': available, 'last_use': data.get('last_use'),
            'activity': {key: value if type(value := data.get(key)) is int and value >= 0 else 0
                         for key in ('completed', 'failed', 'blocked')},
            'last_sequence': data.get('sequence', []), 'last_route_ms': data.get('elapsed_ms')}


def record(root, outcome, sequence=(), elapsed_ms=None):
    path = Path(root) / 'data/router/activity.json'
    try:
        with routing_lock(path.with_suffix('.lock')):
            data = status(root)['activity']
            data[outcome] += 1
            data.update(last_use=datetime.now(timezone.utc).isoformat(), sequence=list(sequence), elapsed_ms=elapsed_ms)
            atomic_write(path, (json.dumps(data) + '\n').encode())
    except (OSError, ValueError, RuntimeError):
        pass  # A failed metric write cannot turn completed work into a retry.


def _request(token, body=None, timeout=2):
    path = '/route' if body is not None else '/health'
    request = urllib.request.Request('http://127.0.0.1:8791' + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(16385))


def classify(root, intent, eligible):
    root = Path(root)
    if not load_preferences(root)['laya_router']:
        raise RuntimeError('Laya router is Off.')
    if not status(root)['available']:
        raise RuntimeError('Laya runtime is not installed and validated.')
    with routing_lock(root / 'laya/start.lock'):
        key = root / 'laya/service-key.txt'
        if not key.exists():
            atomic_write(key, secrets.token_hex(32).encode())
        token = key.read_text().strip()
        try:
            ready = _request(token).get('service') == 'cts-laya-router'
        except Exception:
            ready = False
        if not ready:
            # Do not replace or stop an unrelated service occupying this port.
            with socket.socket() as probe:
                if probe.connect_ex(('127.0.0.1', 8791)) == 0:
                    raise RuntimeError('Router port is occupied by an unverified or busy service. Use a direct tool.')
            (root / 'logs').mkdir(exist_ok=True)
            with (root / 'logs/laya-worker.log').open('ab') as log:
                environment = dict(os.environ, PYTHONUTF8='1')
                for name in ('PYTHONPATH', 'PYTHONHOME'):
                    environment.pop(name, None)
                process = subprocess.Popen([str(root / 'laya/.venv/Scripts/python.exe'), str(root / 'laya_worker.py'),
                                            '--root', str(root)], cwd=root, env=environment,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for _ in range(50):
                if process.poll() is not None:
                    raise RuntimeError('Local Laya worker did not start. Use a direct tool.')
                try:
                    if _request(token).get('service') == 'cts-laya-router':
                        break
                except Exception:
                    time.sleep(.1)
            else:
                raise RuntimeError('Local Laya startup timed out. Use a direct tool.')
    return _request(token, {'intent': intent}, timeout=90)


def validated_request(request):
    allowed = {'intent', 'project', 'path', 'symbol', 'pattern', 'language', 'git_operation',
               'browser_session', 'task_id', 'summary_action', 'exact'}
    if not isinstance(request, dict) or not set(request) <= allowed:
        raise ValueError('Unknown bundle query field.')
    if not isinstance(request.get('intent'), str) or not 1 <= len(request['intent']) <= 1200:
        raise ValueError('Provide a short intent (1-1200 characters).')
    if not isinstance(request.get('project'), str) or not Path(request['project']).is_absolute():
        raise ValueError('An absolute project directory is required.')
    project = Path(request['project']).resolve()
    if not project.is_dir() or project == Path(project.anchor) or Path.home().resolve().is_relative_to(project):
        raise ValueError('Select a project, not a drive or home directory.')
    for key in allowed - {'intent', 'project', 'exact'}:
        if key in request and (not isinstance(request[key], str) or not 1 <= len(request[key]) <= 500):
            raise ValueError('Invalid ' + key)
    if 'exact' in request and type(request['exact']) is not bool:
        raise ValueError('exact must be a boolean.')
    relative = request.get('path', '.')
    path = (project / relative).resolve()
    if not path.is_relative_to(project) or not path.exists():
        raise ValueError('The target must exist within the selected project.')
    if request.get('git_operation', 'status') not in ('status', 'diff', 'log'):
        raise ValueError('Supported Git reports: status, diff, log.')
    if request.get('summary_action', 'read') not in ('read', 'start'):
        raise ValueError('Summary action must be read or explicitly requested start.')
    if 'browser_session' in request and not re.fullmatch('[a-zA-Z0-9_-]{1,64}', request['browser_session']):
        raise ValueError('Invalid browser session name.')
    if 'task_id' in request and not re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', request['task_id']):
        raise ValueError('Use an exact local task UUID.')
    return project, path


def eligible_recipes(root, request, path):
    enabled = load_preferences(root)
    candidates = []
    for route, component in COMPONENT.items():
        if not enabled[component]:
            continue
        if route == 'file_read' and not path.is_file():
            continue
        if route == 'symbols' and not (request.get('symbol') or path.is_file()):
            continue
        if route == 'ast_search' and not (request.get('pattern') and request.get('language')):
            continue
        if route == 'git_report' and 'git_operation' not in request:
            continue
        if route == 'browser_snapshot' and not request.get('browser_session'):
            continue
        if route == 'summary' and (not request.get('task_id') or
                request.get('summary_action') == 'start' and not enabled['llama_cpp']):
            continue
        candidates.append(route)
    return candidates + ['clarify']


def validate_decision(decision, eligible, exact):
    if not isinstance(decision, dict) or decision.get('route') not in eligible:
        raise ValueError('Laya returned an invalid route; no tool executed.')
    probability = decision.get('confidence')
    if type(probability) not in (int, float) or not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError('Laya returned an invalid probability; no tool executed.')
    if (decision.get('truncated') or probability < .80 or decision['route'] == 'clarify'):
        raise ValueError('Laya could not confidently select a tool. Provide a narrower intent or use a direct tool.')
    if decision.get('delivery') not in ('exact', 'compact'):
        raise ValueError('Laya returned an invalid delivery mode.')
    return decision['route'], exact or decision['delivery'] == 'exact'


def run_command(argv, project, root, component=None):
    # Bound memory as well as response size. Never execute model-generated shell text.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        env = dict(os.environ, HEADROOM_EXACT='1')
        result = subprocess.run(argv, cwd=project, env=env, stdout=output, stderr=errors,
                                timeout=45, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        output.seek(0); data = output.read(2 * 1024 * 1024 + 1)
        errors.seek(0); error = errors.read(4096)
    if component:
        from cli_tools import record as cli_record
        cli_record(root, component, 'completed' if result.returncode == 0 else 'failed')
    if len(data) > 2 * 1024 * 1024:
        raise RuntimeError('Result exceeded 2 MB. Narrow the query; no result is silently truncated.')
    if result.returncode not in (0, 1) or (result.returncode == 1 and component != 'ast_grep'):
        raise RuntimeError('Selected tool failed (exit ' + str(result.returncode) + '). ' + error.decode('utf-8', 'replace'))
    return data.decode('utf-8', 'strict')


async def serena_query(root, project, path, symbol):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=str(root / 'headroom/.venv/Scripts/python.exe'),
        args=[str(root / 'serena_mcp.py')], cwd=str(project), env=dict(os.environ, PYTHONUTF8='1'))
    async with stdio_client(params, errlog=sys.stderr) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            activation = await session.call_tool('activate_project', {'project': str(project)})
            if activation.isError:
                raise RuntimeError('Serena could not activate the project.')
            arguments = {'relative_path': path.relative_to(project).as_posix()} if path != project else {}
            if symbol:
                arguments.update(name_path_pattern=symbol, include_body=True)
                tool = 'find_symbol'
            else:
                tool = 'get_symbols_overview'
            result = await session.call_tool(tool, arguments)
            if result.isError:
                raise RuntimeError('Serena lookup failed; use a direct navigation tool.')
            return '\n'.join(item.text for item in result.content if item.type == 'text')


def execute(root, route, request, project, path, exact):
    if route not in eligible_recipes(root, request, path):
        raise RuntimeError('The chosen component was disabled before execution.')
    sequence = ['laya', COMPONENT[route]]
    if route == 'file_read':
        from desktop_headroom import DesktopHeadroom
        text = DesktopHeadroom(root / 'headroom/desktop-state', bundle_root=root).read_file(str(path), max_lines=500, compress=not exact)
        return text, sequence
    if route == 'symbols':
        text = asyncio.run(serena_query(root, project, path, request.get('symbol')))
        return text, sequence  # Symbol bodies are already marked for exact retrieval.
    if route in ('ast_search', 'browser_snapshot'):
        from cli_tools import command, runtime_status
        if not runtime_status(root)['available']:
            raise RuntimeError('CLI runtime is unavailable.')
        component = COMPONENT[route]
        args = (['run', '--lang', request['language'], '--pattern', request['pattern'], '--json=compact', str(path)]
                if route == 'ast_search' else ['-s=' + request['browser_session'], 'snapshot', '--depth=3'])
        text = run_command([*command(root, component), *args], project, root, component)
    elif route == 'git_report':
        operation = request['git_operation']
        args = {'status': ['status', '--short'], 'diff': ['diff', '--stat'], 'log': ['log', '-10']}[operation]
        text = run_command([str(root / 'bin/rtk.exe'), 'git', *args], project, root)
    else:
        from local_summaries import LocalSummaries
        summaries = LocalSummaries(root)
        if request.get('summary_action') == 'start':
            value = summaries.start(request['task_id'])
            sequence.append('llama_cpp')
        else:
            value = summaries.get_summary(request['task_id'])
        return json.dumps(value), sequence
    if not exact and load_preferences(root)['headroom_local']:
        from command_compression import CommandCompressor, configure_offline_environment
        state = root / 'headroom/desktop-state'
        configure_offline_environment(state)
        compressor = CommandCompressor(state, bundle_root=root)
        original = text.encode()
        compressed = compressor.process(original, 0)
        compressor.record(compressed, COMPONENT[route], 0, len(original), 0)
        text = compressed.output.decode()
        sequence.append('headroom_local')
    return text, sequence


def query(root, request, predictor=None):
    root = Path(root).resolve()
    sequence, elapsed = [], None
    try:
        if not load_preferences(root)['laya_router']:
            raise ValueError('Laya router is Off. Direct bundle tools remain available.')
        project, path = validated_request(request)
        eligible = eligible_recipes(root, request, path)
        decision = (predictor or classify)(root, request['intent'], eligible)
        elapsed = decision.get('elapsed_ms')
        route, exact = validate_decision(decision, eligible, request.get('exact', False))
        if not load_preferences(root)['laya_router']:
            raise ValueError('Router was disabled before execution.')
        sequence = ['laya']
        text, sequence = execute(root, route, request, project, path, exact)
        record(root, 'completed', sequence, elapsed)
        return {'sequence': sequence, 'routing_ms': elapsed, 'routing_probability': decision['confidence'],
                'experimental': True, 'result': text}
    except Exception:
        record(root, 'blocked' if not sequence else 'failed', sequence, elapsed)
        raise
