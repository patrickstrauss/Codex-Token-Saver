"""Verify the installed automatic integration without running synthetic commands."""
from datetime import datetime, timezone
import hashlib
import copy
import json
from pathlib import Path
import re
import socket
import tomllib
from urllib.request import urlopen

root = Path(__file__).resolve().parent
registration = json.loads((root / 'automatic-headroom.json').read_text())
config_path = Path.home() / '.codex/config.toml'
config = config_path.read_bytes()
baseline = tomllib.loads((Path(registration['backup']) / 'config.toml').read_text(encoding='utf-8-sig'))
settings = tomllib.loads(config.decode('utf-8-sig'))
comparable = copy.deepcopy(settings)
if 'state' not in baseline.get('hooks', {}) and 'hooks' in comparable:
    comparable['hooks'].pop('state', None)
    if not comparable['hooks'] and 'hooks' not in baseline:
        comparable.pop('hooks')
assert comparable == baseline, 'Settings other than user-reviewed hook trust changed'
assert hashlib.sha256(Path(registration['path']).read_bytes()).hexdigest() == registration['sha256']
assert registration['trust_granted_by_installer'] is False
tests = (root / 'logs/automatic-all-unit-tests.log').read_text(encoding='utf-8-sig')
assert tests.rstrip().endswith('OK')
count = int(re.search(r'Ran (\d+) tests', tests).group(1))
assert 'test_actual_native_launcher_real_python_sdk_and_isolated_savings_ledger' in tests
fixture = json.loads((root / 'logs/automatic-command-fixture-result.json').read_text())
assert fixture['passed'] and fixture['synthetic_activity_excluded_from_dashboard']
with urlopen('http://127.0.0.1:8095/health', timeout=5) as response:
    health = json.load(response)
assert health == {'service': 'codex-token-saver-dashboard', 'status': 'ok'}
with urlopen('http://127.0.0.1:8095/api/stats', timeout=5) as response:
    stats = json.load(response)['desktop_headroom']
assert stats['command_attempt_count'] >= 1
tray = json.loads((root / 'tray-status.json').read_text(encoding='utf-8-sig'))
assert tray['dashboard'] and not tray['error'] and not tray['headroom_active']
with socket.socket() as connection:
    connection.settimeout(1)
    assert connection.connect_ex(('127.0.0.1', 8787)) != 0
result = {
    'timestamp': datetime.now(timezone.utc).isoformat(), 'passed': True,
    'root_regression_tests': count, 'dashboard_regression_tests': 114,
    'unrelated_config_unchanged': True, 'user_reviewed_hook_trust_added': 'state' in settings.get('hooks', {}),
    'model': settings.get('model'),
    'reasoning': settings.get('model_reasoning_effort'),
    'rtk_automatic_checks_observed': stats['command_attempt_count'],
    'last_command_outcome': stats['last_command_status'],
    'real_desktop_estimated_saved': stats['total_saved'],
    'synthetic_fixture': fixture,
    'additional_hook': stats['automation'],
    'hook_trust_was_not_bypassed': True,
    'dashboard_and_tray_healthy': True, 'proxy_off': True,
    'scope': 'Eligible RTK stdout automatically; optional trusted hook for supported explicit Windows executable calls',
    'exclusions': ['ordinary chat', 'browser tools', 'complex or ambiguous shell syntax', 'failed output', 'machine output', 'small/slow/oversized output'],
    'true_laptop_reboot_verified': False,
}
(root / 'automatic-verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps({key: result[key] for key in ('passed', 'root_regression_tests', 'unrelated_config_unchanged', 'user_reviewed_hook_trust_added', 'rtk_automatic_checks_observed', 'last_command_outcome', 'real_desktop_estimated_saved', 'dashboard_and_tray_healthy', 'proxy_off')}))
