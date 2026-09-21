"""Fault injection at the tools/guidance/hook boundary; no real profile touched."""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_desktop_mcp
from configure_install import configure

with tempfile.TemporaryDirectory() as temporary:
    base = Path(temporary)
    root, home = base / 'bundle', base / 'codex'
    home.mkdir()
    config, agents = home / 'config.toml', home / 'AGENTS.md'
    original = b'model="keep-me"\nmodel_reasoning_effort="high"\n'
    config.write_bytes(original)
    agents.write_bytes(b'Personal guidance')
    real_replace = install_desktop_mcp.replace_checked

    def fail_guidance(path, before, after):
        if path == agents:
            raise PermissionError('Synthetic AGENTS write failure')
        return real_replace(path, before, after)

    with patch.object(install_desktop_mcp, 'replace_checked', fail_guidance):
        try:
            configure(root, home)
        except PermissionError:
            pass
        else:
            raise AssertionError('Injected failure was not raised')
    assert config.read_bytes() == original
    assert agents.read_bytes() == b'Personal guidance'
    result = configure(root, home)
    assert result['command_hook_registered'] is True
    assert result['hook_trust_granted'] is False
    configured = config.read_bytes()
    configured_hooks = (home / 'hooks.json').read_bytes()
    configure(root, home)
    assert config.read_bytes() == configured
    assert (home / 'hooks.json').read_bytes() == configured_hooks

with tempfile.TemporaryDirectory() as temporary:
    base = Path(temporary)
    root, home = base / 'bundle', base / 'codex'
    home.mkdir()
    config, agents, hooks = (home / name for name in ('config.toml', 'AGENTS.md', 'hooks.json'))
    original = b'model="keep-me"\nmodel_reasoning_effort="high"\n'
    config.write_bytes(original)
    agents.write_bytes(b'Personal guidance')

    def fail_hook(path, before, after):
        if path == hooks:
            raise PermissionError('Synthetic hooks write failure')
        return real_replace(path, before, after)

    with patch.object(install_desktop_mcp, 'replace_checked', fail_hook):
        try:
            configure(root, home)
        except PermissionError:
            pass
        else:
            raise AssertionError('Injected hook failure was not raised')
    assert config.read_bytes() == original
    assert agents.read_bytes() == b'Personal guidance'
    assert not hooks.exists()

    other = {'description': 'Keep existing hooks', 'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'existing'}]}]}}
    hooks.write_text(json.dumps(other), encoding='utf-8')
    configure(root, home)
    merged = json.loads(hooks.read_text())
    added = merged['hooks'].pop('PreToolUse')
    assert merged == other
    assert added[0]['matcher'] == '^Bash$'
    assert 'Headroom-PreToolUse.ps1' in added[0]['hooks'][0]['command']

with tempfile.TemporaryDirectory() as temporary:
    base = Path(temporary)
    root, home = base / 'bundle', base / 'codex'
    home.mkdir()
    config, agents, hooks = (home / name for name in ('config.toml', 'AGENTS.md', 'hooks.json'))
    config.write_bytes(b'model="keep-me"\n')
    agents.write_bytes(b'Personal guidance')
    for original_hook in ('{invalid', json.dumps({'hooks': {'PreToolUse': [{'hooks': [
            {'type': 'command', 'command': 'custom Headroom-PreToolUse.ps1'}]}]}})):
        hooks.write_text(original_hook, encoding='utf-8')
        before = {p: p.read_bytes() for p in (config, agents, hooks)}
        try:
            configure(root, home)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid or different hook was replaced')
        assert {p: p.read_bytes() for p in before} == before
    config.write_bytes(b'model="keep-me"\n[features]\nhooks=false\n')
    before_hooks = hooks.read_bytes()
    result = configure(root, home)
    assert result['command_hook_registered'] is False
    assert result['hook_trust_granted'] is False
    assert hooks.read_bytes() == before_hooks
    assert b'hooks=false' in config.read_bytes()

print('PASS: tool/guidance/hook rollback, hook preservation, disabled hooks and idempotence')
