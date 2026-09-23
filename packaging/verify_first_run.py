"""Exercise a fresh package and its repair entry point using only a CI sandbox."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tomllib

from dotenv import dotenv_values


def dashboard_snapshot(root, environment):
    # Import the installed app with its normal path defaults, without collectors,
    # services, requests, or monkeypatched database paths.
    code = '''import json, sys
from pathlib import Path
from unittest.mock import patch
root = Path(sys.argv[1])
sys.path[:0] = [str(root / "dashboard"), str(root)]
with patch("threading.Thread.start"):
    import app
stats = app.collect_rtk()
assert Path(app.RTK_DB_PATH) == root / "data/rtk/history.db", app.RTK_DB_PATH
assert stats is not None and stats["records_readable"], stats
assert stats["total_commands"] == 0 and stats["total_saved"] == 0, stats
print(json.dumps({"path": app.RTK_DB_PATH, "history_exists": stats["history_exists"]}))
'''
    result = subprocess.run([str(root / 'dashboard/.venv/Scripts/python.exe'), '-c', code, str(root)],
                            cwd=root, env=environment, capture_output=True, text=True,
                            encoding='utf-8', check=True, timeout=30)
    return json.loads(result.stdout)


def verify(root, package, config_home):
    # Never accept the normal user installation/profile as a synthetic test target.
    assert root.parent == config_home.parent and root.name == 'bundle' and config_home.name == 'codex'
    assert root.parent.name.startswith('token-saver-package-'), 'Use Smoke-Package.ps1 to create an isolated sandbox.'
    for name in ('Repair-Team-Setup.cmd', 'Setup-Request-Compression.cmd',
                 'Disable-Token-Saver.cmd', 'Get-Token-Saver-Diagnostics.cmd'):
        assert (package / name).read_bytes() == (package / 'payload' / name).read_bytes()
        assert (root / name).read_bytes() == (package / name).read_bytes()
    for relative in ('Repair-Team-Setup.ps1', 'repair_team_setup.py', 'Setup-Request-Compression.ps1',
                     'scripts/setup_request_compression.py', 'packaging/configure_install.py'):
        assert (package / 'payload' / relative).is_file(), relative

    environment = os.environ.copy()
    for key in ('RTK_DB_PATH', 'RTK_BIN'):
        environment.pop(key, None)
    environment.update(CODEX_HOME=str(config_home), RTK_TELEMETRY_DISABLED='1')
    db = root / 'data/rtk/history.db'
    assert not (root / 'dashboard/.env').exists(), 'Fresh package unexpectedly includes dashboard settings.'
    before = dashboard_snapshot(root, environment)
    assert before['history_exists'] is False, 'RTK smoke target must have no prior command history.'
    gain = subprocess.run([str(root / 'bin/rtk.exe'), 'gain', '--all', '--format', 'json'],
                          cwd=root, env=environment, capture_output=True, text=True,
                          encoding='utf-8', check=True, timeout=30)
    assert isinstance(json.loads(gain.stdout), dict)
    with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)) as connection:
        assert connection.execute('SELECT COUNT(*) FROM commands').fetchone()[0] == 0
    assert dashboard_snapshot(root, environment)['history_exists'] is True

    env_file = root / 'dashboard/.env'
    env_file.write_text('CUSTOM_SETTING=preserve-me\nRTK_DB_PATH=wrong-history-path\nRTK_BIN=wrong-binary\n', encoding='utf-8')
    config = config_home / 'config.toml'
    auth = config_home / 'auth.json'
    original_settings = tomllib.loads(config.read_text(encoding='utf-8-sig'))
    original_auth = auth.read_bytes()
    receipts = [root / 'desktop-integration.json', root / 'automatic-headroom.json']
    assert not any(path.exists() for path in receipts), 'Fresh skipped integration unexpectedly wrote receipts.'
    repair = package / 'payload/Repair-Team-Setup.ps1'
    for attempt in range(2):
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                        '-File', str(repair), '-BundleRoot', str(root)],
                       cwd=package, env=environment, check=True, timeout=60)
        values = dotenv_values(env_file)
        assert values['CUSTOM_SETTING'] == 'preserve-me'
        assert Path(values['RTK_DB_PATH']) == db
        assert Path(values['RTK_BIN']) == root / 'bin/rtk.exe'
        settings = tomllib.loads(config.read_text(encoding='utf-8-sig'))
        assert {k: v for k, v in settings.items() if k != 'mcp_servers'} == original_settings
        assert auth.read_bytes() == original_auth
        desktop, hook = [json.loads(path.read_text(encoding='utf-8-sig')) for path in receipts]
        assert desktop['configured'] and desktop['loading_in_codex_verified'] is False
        assert hook['configured'] and hook['trust_granted_by_installer'] is False
        paths = [config, config_home / 'AGENTS.md', config_home / 'hooks.json', env_file, *receipts]
        current = {path: path.read_bytes() for path in paths}
        if attempt:
            assert current == repaired_once, 'Repeated repair changed registration or receipt timestamps.'
        repaired_once = current
        assert dashboard_snapshot(root, environment)['history_exists'] is True
    print(json.dumps({'passed': True, 'fresh_history_existed': before['history_exists'],
                      'rtk_records': 0, 'artifact_repair_verified': True, 'repeat_repair_idempotent': True}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for argument in ('root', 'package', 'codex-home'):
        parser.add_argument('--' + argument, type=Path, required=True)
    args = parser.parse_args()
    verify(args.root.resolve(), args.package.resolve(), args.codex_home.resolve())
