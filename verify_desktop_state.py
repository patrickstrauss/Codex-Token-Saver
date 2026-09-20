"""Read-only installed-state checks; writes a local verification receipt."""
import copy
import json
import socket
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

root = Path(__file__).resolve().parent
receipt = json.loads((root / 'desktop-integration.json').read_text())
config = Path(receipt['config'])
before = tomllib.loads((Path(receipt['backup']) / 'config.toml').read_text(encoding='utf-8-sig'))
after = tomllib.loads(config.read_text(encoding='utf-8-sig'))
comparison = copy.deepcopy(after)
server = comparison['mcp_servers'].pop('headroom_desktop')
if 'mcp_servers' not in before and not comparison['mcp_servers']:
    comparison.pop('mcp_servers')
assert comparison == before, 'Unrelated Codex configuration changed'
assert server['required'] is False and server['enabled'] is True
assert Path(server['command']).is_file()
assert Path(server['args'][-1]).is_file()
assert after.get('model') == receipt['model'] == 'gpt-6-astra'
assert after.get('model_reasoning_effort') == receipt['reasoning'] == 'ultra'
assert after.get('model_provider', 'openai') == 'openai'
assert '8787' not in str(after.get('openai_base_url', ''))

with urlopen('http://127.0.0.1:8095/health', timeout=5) as response:
    health = json.load(response)
with urlopen('http://127.0.0.1:8095/api/stats', timeout=5) as response:
    stats = json.load(response)
tray = json.loads((root / 'tray-status.json').read_text(encoding='utf-8-sig'))
assert tray['dashboard'] and not tray['error']
assert tray['desktop_headroom_configured'] and not tray['headroom_active']
assert stats['desktop_headroom']['configured']
with socket.socket() as probe:
    probe.settimeout(1)
    proxy_listener = probe.connect_ex(('127.0.0.1', 8787)) == 0
assert not proxy_listener, 'Optional CLI proxy unexpectedly listening'
live = json.loads((root / 'logs/desktop-use-smoke-result.json').read_text())
missing = json.loads((root / 'logs/desktop-missing-smoke-result.json').read_text())
assert live['passed'] and missing['passed']
assert live['config_unchanged'] and missing['config_unchanged']
assert live['synthetic_activity_excluded_from_dashboard']
tests = (root / 'logs/desktop-final-unit-tests.log').read_text(encoding='utf-8-sig')
assert 'Ran 87 tests' in tests and tests.rstrip().endswith('OK')

result = {
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'installed_state_checks_passed': True,
    'unrelated_config_preserved': True,
    'model': after['model'], 'reasoning': after['model_reasoning_effort'],
    'provider': after.get('model_provider', 'openai'),
    'optional_mcp_registered': True, 'cli_proxy_listening': proxy_listener,
    'unit_tests': 87, 'unit_test_log': 'logs/desktop-final-unit-tests.log',
    'live_tool_use': live, 'missing_optional_server': missing,
    'dashboard_health': health,
    'desktop_counter': stats['desktop_headroom'],
    'tray_dashboard_healthy': True,
    'existing_desktop_process_restarted': False,
    'true_laptop_reboot_verified': False,
    'user_next_step': 'Restart Codex once and open a new task to load the local tools',
}
(root / 'desktop-verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result, indent=2))
