"""Apply the user-authorized desktop route after recorded validation passes."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop_proxy_control import DesktopProxyControl, CRITICAL_FILES, LOCAL_URL, atomic_write, _encode, _without_route


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    control = DesktopProxyControl(ROOT)
    before = control.config_file.read_bytes()
    config = tomllib.loads(before.decode('utf-8-sig'))
    if 'openai_base_url' in config:
        raise RuntimeError('This one-time activation verifier requires the initial direct configuration.')
    hooks = control.config_home / 'hooks.json'
    hooks_hash = sha(hooks.read_bytes())
    evidence = {}
    for name in ('request-proxy-live-optimized.json', 'request-proxy-live-direct.json',
                 'request-proxy-live-persistence.json'):
        value = json.loads((ROOT / 'logs' / name).read_text(encoding='utf-8-sig'))
        if value.get('passed') is not True:
            raise RuntimeError('Live proxy validation is incomplete.')
        evidence[name] = True
    core = (ROOT / 'logs/request-proxy-full-core-tests.log').read_text(encoding='utf-8-sig')
    dashboard = (ROOT / 'logs/request-proxy-full-dashboard-tests.log').read_text(encoding='utf-8-sig')
    if 'Ran 260 tests' not in core or not core.rstrip().endswith('OK') or '175 passed' not in dashboard:
        raise RuntimeError('Final regression verification is incomplete.')
    startup = json.loads((ROOT / 'proxy/startup-result.json').read_text(encoding='utf-8-sig'))
    if startup.get('success') is not True:
        raise RuntimeError('Startup installation has not passed verification.')
    validation = {
        'schema': 1, 'passed': True, 'timestamp': datetime.now(timezone.utc).isoformat(),
        'source_hashes': {name: sha((ROOT / name).read_bytes()) for name in CRITICAL_FILES},
        'tests': {'core': 260, 'dashboard': 175}, 'live_checks': evidence,
        'startup_installed': True, 'full_windows_reboot_tested': False,
        'authorization': 'User allowed local proxy routing after validation.',
    }
    atomic_write(ROOT / 'proxy/validation.json', _encode(validation))
    enabled = control.set_enabled(True)
    if not enabled['route_enabled'] or _without_route(control.config_file.read_bytes()) != before:
        raise RuntimeError('Endpoint activation did not preserve the original settings.')
    # Exercise the installed recovery entry point, including its own checks.
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
                             str(ROOT / 'Restore-Codex-Direct.ps1'), '-Quiet'],
                            cwd=ROOT, capture_output=True, text=True, timeout=20)
    if result.returncode or control.config_file.read_bytes() != before:
        raise RuntimeError('Installed recovery did not restore the exact original configuration.')
    restored = json.loads(result.stdout)
    if restored.get('success') is not True:
        raise RuntimeError('Installed recovery did not confirm success.')
    final = control.set_enabled(True)
    after = control.config_file.read_bytes()
    if not final['route_enabled'] or _without_route(after) != before or sha(hooks.read_bytes()) != hooks_hash:
        raise RuntimeError('Final route or preserved settings did not match verification.')
    receipt = {
        'timestamp': datetime.now(timezone.utc).isoformat(), 'passed': True,
        'endpoint': LOCAL_URL, 'config_before_sha256': sha(before), 'config_after_sha256': sha(after),
        'other_config_bytes_preserved': True, 'hooks_unchanged': True,
        'model': config.get('model'), 'reasoning': config.get('model_reasoning_effort'),
        'restore_script_verified': True, 're_enable_verified': True,
        'restart_codex_required': True, 'tests': validation['tests'], 'status': final,
    }
    atomic_write(ROOT / 'proxy/activation.json', _encode(receipt))
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
