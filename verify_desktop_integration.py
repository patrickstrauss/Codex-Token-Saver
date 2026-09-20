"""Manual live checks using the desktop's Codex engine and shared configuration."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from launch_codex import find_codex

root = Path(__file__).resolve().parent
missing = '--missing' in sys.argv
tag = 'desktop-missing-smoke' if missing else 'desktop-use-smoke'
logs = root / 'logs'
reply_path = logs / (tag + '-reply.txt')
config = Path.home() / '.codex/config.toml'
before = hashlib.sha256(config.read_bytes()).hexdigest()
arguments = [str(find_codex())]
if missing:
    value = str(root / 'headroom/does-not-exist.exe')
    arguments += ['-c', 'mcp_servers.headroom_desktop.command=' + json.dumps(value)]
    prompt = 'Reply exactly CODEX_WITHOUT_HEADROOM_OK. Do not call tools or access files.'
else:
    state = root / 'headroom/desktop-verification-state'
    arguments += ['-c', 'mcp_servers.headroom_desktop.env.HEADROOM_WORKSPACE_DIR=' + json.dumps(str(state))]
    source = root / 'headroom/desktop-verification/records.json'
    prompt = ('Inspect this large JSON file and identify the abnormal record: ' + str(source) +
              '. Use the configured local file-inspection tool if available. Reply with only its id and status.')
arguments += ['exec', '--ephemeral', '--skip-git-repo-check', '--sandbox', 'read-only',
              '--json', '--output-last-message', str(reply_path), prompt]
with (logs / (tag + '.stdout.jsonl')).open('w', encoding='utf-8') as stdout, \
     (logs / (tag + '.stderr.log')).open('w', encoding='utf-8') as stderr:
    result = subprocess.run(arguments, cwd=root, stdout=stdout, stderr=stderr, timeout=180)
reply = reply_path.read_text(encoding='utf-8').strip() if reply_path.exists() else ''
calls = []
for line in (logs / (tag + '.stdout.jsonl')).read_text(encoding='utf-8').splitlines():
    try:
        event = json.loads(line)
        item = event.get('item', {})
        if 'mcp' in item.get('type', ''):
            calls.append({key: item.get(key) for key in ('type', 'server', 'tool', 'status')})
    except ValueError:
        pass
passed = result.returncode == 0 and (reply == 'CODEX_WITHOUT_HEADROOM_OK' if missing
    else ('73' in reply and 'CRITICAL_FAILURE_73' in reply and any(c['server'] == 'headroom_desktop' for c in calls)))
record = {'timestamp':datetime.now(timezone.utc).isoformat(), 'passed':passed,
          'exit_code': result.returncode, 'reply':reply, 'tool_calls':calls,
          'config_unchanged': hashlib.sha256(config.read_bytes()).hexdigest() == before,
          'synthetic_activity_excluded_from_dashboard':True}
if not missing and (state / 'activity.db').exists():
    with sqlite3.connect(state / 'activity.db') as connection:
        row = connection.execute('SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(saved_tokens) FROM events').fetchone()
    record['test_ledger'] = dict(zip(('events', 'input_tokens', 'output_tokens', 'net_saved'), row))
(logs / (tag + '-result.json')).write_text(json.dumps(record, indent=2), encoding='utf-8')
print(json.dumps(record))
sys.exit(0 if passed and record['config_unchanged'] else 1)
