"""Run one ephemeral Codex connectivity check without storing conversation data."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from launch_codex import find_codex
from desktop_proxy_control import DesktopProxyControl


def main():
    control = DesktopProxyControl(ROOT)
    config_bytes = control.config_file.read_bytes()
    config = tomllib.loads(config_bytes.decode('utf-8-sig'))
    before = control.status()
    command = [str(find_codex()), 'exec', '--ephemeral', '--skip-git-repo-check',
               '--color', 'never', '--json', '-c',
               'openai_base_url="http://127.0.0.1:8788/v1"',
               'Connectivity check only. Do not use tools or change any files. '
               'Reply with exactly PROXY_OK.']
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=180)
    replies, usage, error_types = [], None, []
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'item.completed':
            item = event.get('item', {})
            if item.get('type') == 'agent_message':
                replies.append(item.get('text', ''))
        if event.get('type') == 'turn.completed':
            usage = event.get('usage')
        if event.get('type') in ('error', 'turn.failed'):
            error_types.append(event['type'])
    after = control.status()
    receipt = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'passed': result.returncode == 0 and bool(replies) and replies[-1].strip() == 'PROXY_OK',
        'exit_code': result.returncode, 'reply_matched': bool(replies) and replies[-1].strip() == 'PROXY_OK',
        'config_unchanged': config_bytes == control.config_file.read_bytes(),
        'configured_model': config.get('model'),
        'configured_reasoning': config.get('model_reasoning_effort'),
        'usage': usage, 'error_types': error_types,
        'connections_before': before['requests'], 'connections_after': after['requests'],
        'backend_requests_before': before['savings']['requests'],
        'backend_requests_after': after['savings']['requests'],
    }
    target = ROOT / 'logs' / ('request-proxy-live-' + ('optimized' if before['enabled'] else 'direct') + '.json')
    target.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt))
    return 0 if receipt['passed'] and receipt['config_unchanged'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
