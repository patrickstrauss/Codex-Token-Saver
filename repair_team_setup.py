"""Repair first-run configuration without replacing installed source or runtimes."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess

from dotenv import dotenv_values, set_key
from install_desktop_mcp import replace_checked


def repair(root, config_home):
    root = Path(root).resolve()
    from harness_clients import codex_enabled, registrations
    native = codex_enabled(root)
    marker = root / 'team-install-source.json'
    try:
        source = json.loads(marker.read_text(encoding='utf-8-sig'))
        if not isinstance(source, dict) or not re.fullmatch('[a-fA-F0-9]{64}', source.get('package_sha256', '')):
            raise ValueError('Invalid team installation receipt')
    except (OSError, ValueError, TypeError) as error:
        raise ValueError('Choose an existing team installation; no files were changed.') from error
    binary, env_file, db = (root / name for name in ('bin/rtk.exe', 'dashboard/.env', 'data/rtk/history.db'))
    for path in (marker, binary, env_file, db, root / 'backups'):
        if not path.resolve().is_relative_to(root):
            raise ValueError('Repair paths must remain within the installation.')
    if not binary.is_file() or not env_file.parent.is_dir():
        raise ValueError('Installed RTK launcher or dashboard is missing; finish installation first.')

    # RTK creates its own schema; do not invent command records or savings.
    run = subprocess.run([str(binary), 'gain', '--all', '--format', 'json'], cwd=root,
                         capture_output=True, text=True, encoding='utf-8', timeout=30,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if run.returncode or not isinstance(json.loads(run.stdout), dict):
        raise RuntimeError('RTK history could not be opened; configuration was not changed.')
    connection = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=2)
    try:
        count = connection.execute('SELECT COUNT(*) FROM commands').fetchone()[0]
    finally:
        connection.close()

    old = env_file.read_bytes() if env_file.exists() else None
    if old is not None:
        old.decode('utf-8-sig')
    backup = root / 'backups' / ('team-repair-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True)
    if old is not None:
        (backup / 'dashboard.env').write_bytes(old)
    candidate = backup / 'dashboard.env.repaired'
    # Preserve existing Windows line endings; text-mode writes would expand CRLF twice.
    candidate.write_bytes(old.decode('utf-8-sig').encode('utf-8') if old is not None else b'')
    existing = dotenv_values(candidate)
    if existing.get('RTK_DB_PATH') != str(db):
        set_key(str(candidate), 'RTK_DB_PATH', str(db), quote_mode='always', encoding='utf-8')
    if existing.get('RTK_BIN') != str(binary):
        set_key(str(candidate), 'RTK_BIN', str(binary), quote_mode='always', encoding='utf-8')
    values = dotenv_values(candidate)
    if values.get('RTK_DB_PATH') != str(db) or values.get('RTK_BIN') != str(binary):
        raise RuntimeError('Dashboard path repair did not validate.')
    desired = old if existing == values and old is not None else candidate.read_bytes()
    written, created = None, False
    try:
        if old is None:
            with env_file.open('xb'):
                pass
            created = True
        replace_checked(env_file, old or b'', desired)
        written = desired
        if native:
            path = Path(__file__).resolve().parent / 'packaging/configure_install.py'
            spec = importlib.util.spec_from_file_location('team_repair_configuration', path)
            configuration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(configuration)
            registered = configuration.configure(root, Path(config_home).resolve())
        else:
            registered = {'codex': False, 'clients': registrations(root)}
    except BaseException:
        # Do not overwrite changes made by another process during the repair.
        if written is not None and env_file.exists() and env_file.read_bytes() == written:
            replace_checked(env_file, written, old or b'')
        if created and env_file.exists() and env_file.read_bytes() == b'':
            env_file.unlink()
        raise
    overrides = [key for key, expected in (('RTK_DB_PATH', str(db)), ('RTK_BIN', str(binary)))
                 if os.environ.get(key) and os.environ[key] != expected]
    return {'repaired': True, 'backup': str(backup), 'recorded_commands': count,
            'registration': registered, 'codex_integration': native, 'environment_overrides': overrides,
            'next_step': ('Use Restart / repair dashboard in the tray, then reopen Codex and review hook trust.'
                          if native else 'Use Restart / repair dashboard in the tray. Review client setup in Coding clients.')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path.home() / 'CodexTokenSaver')
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex'))
    args = parser.parse_args()
    print(json.dumps(repair(args.root, args.codex_home)))
