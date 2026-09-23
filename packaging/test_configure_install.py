"""Fault injection at the tools/guidance/hook boundary; no real profile touched."""
import json
from pathlib import Path
import sys
import tempfile
import tomllib
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
    desktop_receipt = root / 'desktop-integration.json'
    hook_receipt = root / 'automatic-headroom.json'
    desktop = json.loads(desktop_receipt.read_text())
    automatic = json.loads(hook_receipt.read_text())
    assert desktop['configured'] is True and desktop['server'] == 'headroom_desktop'
    assert desktop['config'] == str(config) and desktop['transport'] == 'stdio'
    assert desktop['required'] is False and desktop['loading_in_codex_verified'] is False
    assert automatic['configured'] is True and automatic['hook'] == 'headroom_commands'
    assert automatic['trust_granted_by_installer'] is False
    assert automatic['path'] == str(home / 'hooks.json')
    receipts_before = {p: p.read_bytes() for p in (desktop_receipt, hook_receipt)}
    configure(root, home)
    assert config.read_bytes() == configured
    assert (home / 'hooks.json').read_bytes() == configured_hooks
    assert {p: p.read_bytes() for p in receipts_before} == receipts_before

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
    automatic = json.loads((root / 'automatic-headroom.json').read_text())
    assert automatic['configured'] is False
    assert automatic['trust_granted_by_installer'] is False
    assert 'disabled' in automatic['activation'].lower()

for failed_name in ('desktop-integration.json', 'automatic-headroom.json'):
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        root, home = base / 'bundle', base / 'codex'
        home.mkdir()
        root.mkdir()
        config, agents, hooks = (home / name for name in ('config.toml', 'AGENTS.md', 'hooks.json'))
        config.write_bytes(b'model="keep-me"\nopenai_base_url="https://existing.example/v1"\n')
        agents.write_bytes(b'Personal guidance')
        existing_receipt = root / 'desktop-integration.json'
        existing_receipt.write_bytes(b'{"configured":false,"previous":"keep-on-failure"}')
        originals = {p: p.read_bytes() for p in (config, agents, existing_receipt)}

        def fail_receipt(path, before, after):
            if path.name == failed_name:
                raise PermissionError('Synthetic receipt write failure')
            return real_replace(path, before, after)

        with patch.object(install_desktop_mcp, 'replace_checked', fail_receipt):
            try:
                configure(root, home)
            except PermissionError:
                pass
            else:
                raise AssertionError('Injected receipt failure was not raised')
        assert {p: p.read_bytes() for p in originals} == originals
        assert not hooks.exists()
        assert not (root / 'automatic-headroom.json').exists()

with tempfile.TemporaryDirectory() as temporary:
    base = Path(temporary)
    root, home = base / 'bundle', base / 'codex'
    home.mkdir()
    config = home / 'config.toml'
    initial = install_desktop_mcp.merge_config('model="keep-me"\n', root)
    config.write_text(initial.replace('enabled = true', 'enabled = false'), encoding='utf-8')
    disabled = config.read_bytes()
    configure(root, home)
    assert config.read_bytes() == disabled
    assert tomllib.loads(config.read_text())['mcp_servers']['headroom_desktop']['enabled'] is False
    desktop = json.loads((root / 'desktop-integration.json').read_text())
    assert desktop['configured'] is False and desktop['registered'] is True
    assert desktop['enabled'] is False
    assert desktop['loading_in_codex_verified'] is False

with tempfile.TemporaryDirectory() as temporary:
    base = Path(temporary)
    root, home = base / 'bundle', base / 'codex'
    home.mkdir()
    config, agents, hooks = (home / name for name in ('config.toml', 'AGENTS.md', 'hooks.json'))
    config.write_bytes(b'model="keep-me"\n')
    agents.write_bytes(b'Personal guidance')

    def change_config_after_hook(path, before, after):
        real_replace(path, before, after)
        if path == hooks:
            # Simulate a separate settings writer between registration and receipt verification.
            config.write_bytes(config.read_bytes().replace(b'model="keep-me"', b'model="concurrent-choice"'))

    with patch.object(install_desktop_mcp, 'replace_checked', change_config_after_hook):
        try:
            configure(root, home)
        except RuntimeError:
            pass
        else:
            raise AssertionError('A receipt was accepted without verifying current registration')
    assert b'model="concurrent-choice"' in config.read_bytes()
    assert agents.read_bytes() == b'Personal guidance'
    assert not hooks.exists()
    assert not (root / 'desktop-integration.json').exists()
    assert not (root / 'automatic-headroom.json').exists()

with tempfile.TemporaryDirectory() as temporary:
    base = Path(temporary)
    root, home = base / 'bundle', base / 'codex'
    configure(root, home)
    config, hooks = home / 'config.toml', home / 'hooks.json'
    config.write_bytes(config.read_bytes() + b'\n[features]\nhooks=false\n')
    hook_before = hooks.read_bytes()
    configure(root, home)
    assert hooks.read_bytes() == hook_before
    automatic = json.loads((root / 'automatic-headroom.json').read_text())
    assert automatic['configured'] is False
    assert automatic['trust_granted_by_installer'] is False
    receipt_before = (root / 'automatic-headroom.json').read_bytes()
    configure(root, home)
    assert (root / 'automatic-headroom.json').read_bytes() == receipt_before

print('PASS: transactional receipts, rollback, concurrency, disabled settings and idempotence')
