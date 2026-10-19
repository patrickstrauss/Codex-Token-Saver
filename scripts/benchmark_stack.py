"""Temporary production relay and reviewed hook for the full-configuration study."""
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

SERVE = '''import asyncio,json,logging,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from aiohttp import web
from desktop_proxy import create_app
logging.disable(logging.CRITICAL)
async def main():
 root=Path(sys.argv[2]); (root/'proxy').mkdir(parents=True)
 (root/'proxy/settings.json').write_text(json.dumps({'enabled':True,'upstream_mode':'auto'}))
 runner=web.AppRunner(create_app(root,allow_test_host=True),access_log=None)
 await runner.setup()
 site=web.TCPSite(runner,'127.0.0.1',0); await site.start()
 port=site._server.sockets[0].getsockname()[1]
 (root/'ready.json').write_text(json.dumps({'url':'http://127.0.0.1:'+str(port)}))
 try: await asyncio.Event().wait()
 finally: await runner.cleanup()
asyncio.run(main())
'''


def get_json(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=5) as response:
        return json.load(response)


def hook_offset(installed):
    path = installed / 'headroom/desktop-state/hook-events.jsonl'
    return path.stat().st_size if path.exists() else 0


def hook_counts(installed, offset, stdout):
    identities = set()
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
            if event.get('type') == 'thread.started' and isinstance(event.get('thread_id'), str):
                identities.add(event['thread_id'])
        except (ValueError, AttributeError):
            continue
    path = installed / 'headroom/desktop-state/hook-events.jsonl'
    counts = Counter()
    if not path.exists():
        return {'observed': False, 'events': {}, 'coverage_complete': True}
    with path.open('rb') as stream:
        size = path.stat().st_size
        if size < offset or size - offset > 1024 * 1024:
            return {'observed': False, 'events': {}, 'coverage_complete': False}
        stream.seek(offset)
        for raw in stream:
            try:
                event = json.loads(raw)
                if event.get('task_id') in identities and event.get('outcome') in ('rewritten', 'skipped'):
                    counts[event['outcome']] += 1
            except (ValueError, AttributeError):
                continue
    return {'observed': bool(counts), 'events': dict(counts), 'coverage_complete': True}


@contextmanager
def full_configuration(installed, state, profile, env):
    health = get_json('http://127.0.0.1:8789/health')
    if health.get('service') != 'headroom-proxy' or health.get('ready') is not True or health.get('status') != 'healthy':
        raise ValueError('The existing Headroom backend must already be ready; no service enabled')
    # Use the source reviewed in this checkout; never trust an unseen hook variant.
    source = Path(__file__).resolve().parents[1] / 'Headroom-PreToolUse.ps1'
    hook = installed / source.name
    if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(hook.read_bytes()).digest():
        raise ValueError('Installed hook differs from the reviewed source')
    root = state / 'relay'
    root.mkdir()
    child_env = dict(env, CODEX_HOME=str(state / 'no-credentials'))
    process = subprocess.Popen([str(installed / 'headroom/.venv/Scripts/python.exe'), '-u', '-c', SERVE,
                                str(installed), str(root)], env=child_env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        deadline = time.monotonic() + 20
        ready = root / 'ready.json'
        while not ready.exists():
            if process.poll() is not None or time.monotonic() >= deadline:
                raise ValueError('Temporary relay did not start')
            time.sleep(.1)
        url = json.loads(ready.read_bytes())['url']
        if not url.startswith('http://127.0.0.1:'):
            raise ValueError('Unexpected relay endpoint')
        config = profile / 'config.toml'
        config.write_text('openai_base_url = ' + json.dumps(url + '/v1') + '\n' + config.read_text(), encoding='utf-8')
        hook_command = 'powershell.exe -NoProfile -NonInteractive -File "' + str(hook) + '"'
        (profile / 'hooks.json').write_text(json.dumps({'hooks': {'PreToolUse': [
            {'matcher': '^Bash$', 'hooks': [{'type': 'command', 'command': hook_command, 'timeout': 5,
             'statusMessage': 'Checking automatic Headroom command compression'}]}]}}), encoding='utf-8')
        env['PATH'] = str(installed / 'bin') + os.pathsep + env.get('PATH', '')
        offset = hook_offset(installed)
        def observe(stdout):
            deadline = time.monotonic() + 3
            stats = get_json(url + '/stats').get('requests', {})
            while stats.get('active') and time.monotonic() < deadline:
                time.sleep(.1)
                stats = get_json(url + '/stats').get('requests', {})
            return {'relay_connections': stats, 'hook': hook_counts(installed, offset, stdout),
                    'backend_version': str(health.get('version', 'not reported'))}
        yield observe
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
