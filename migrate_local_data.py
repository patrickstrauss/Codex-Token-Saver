"""One-time, non-destructive migration from the prior installation."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tomllib

root = Path(__file__).resolve().parent
database = root / 'data/rtk/history.db'
database.parent.mkdir(parents=True, exist_ok=True)
if not database.exists():
    source = Path(os.environ['LOCALAPPDATA']) / 'rtk/history.db'
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as old:
        with sqlite3.connect(database) as new:
            old.backup(new)
    print('RTK history preserved with SQLite backup.')

(root / 'tools').mkdir(exist_ok=True)
old_binary = root / 'bin/rtk.exe'
if old_binary.exists():
    shutil.copy2(old_binary, root / 'tools/rtk.exe')
    # Exact file within the new bundle; leave the original installation intact.
    old_binary.unlink()

config = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'config.toml'
before = tomllib.loads(config.read_text(encoding='utf-8-sig'))
subprocess.run([sys.executable, str(root / 'routing.py'), 'disable'], check=True)
after = tomllib.loads(config.read_text(encoding='utf-8-sig'))
assert before == after, 'Unexpected semantic config change'
print(json.dumps({'global_route': after.get('model_provider'), 'model': after.get('model'),
                  'reasoning': after.get('model_reasoning_effort'), 'settings_preserved': True}))

instructions = config.with_name('AGENTS.md')
text = instructions.read_text(encoding='utf-8-sig')
updated = text.replace('$env:LOCALAPPDATA\\CodexTokenSaver\\bin\\rtk.exe', '$env:USERPROFILE\\CodexTokenSaver\\bin\\rtk.cmd')
updated = updated.replace("Headroom runs locally; preserve the user's selected model and reasoning settings.",
    "Codex desktop uses its normal connection. Never enable global Headroom routing; codex-headroom is experimental CLI only. Preserve the user's selected model and reasoning settings.")
if updated != text:
    shutil.copy2(instructions, root / 'backups/AGENTS-before-stable-path.md')
    instructions.write_text(updated, encoding='utf-8')
