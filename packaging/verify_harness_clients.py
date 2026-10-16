"""Qualify standalone setup/removal in the package CI sandbox, without clients."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def qualify(root, home):
    sys.path.insert(0, str(root))
    from harness_clients import CLIENTS, codex_enabled, change, export_config, registrations
    from repair_team_setup import repair
    from disable_bundle import disable
    from unregister_install import unregister
    assert not codex_enabled(root), 'A standalone package installation is required.'

    def snapshot():
        return {str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in home.rglob('*') if p.is_file()}

    before = snapshot()
    fixture = root.parent / 'client-qualification.jsonc'
    original = '// Retain this unrelated setting.\r\n{"model":"unchanged", "mcpServers":{"other":{"command":"other"}}}\r\n'
    fixture.write_bytes(original.encode())
    for client in CLIENTS:
        assert export_config(root, client), client
    plan = change(root, 'cursor', config=fixture)
    assert not plan['applied'] and fixture.read_bytes() == original.encode()
    change(root, 'cursor', config=fixture, apply=True)
    assert registrations(root)[0]['status'] == 'configured'
    result = repair(root, home)
    assert result['codex_integration'] is False
    assert snapshot() == before, 'Standalone repair touched the Codex profile.'
    disable(root, home)
    assert registrations(root) == []
    unregister(root, home)
    assert snapshot() == before, 'Standalone removal touched the Codex profile.'
    from harness_clients import JsonDocument
    assert JsonDocument(fixture.read_text()).root.value == JsonDocument(original).root.value
    assert '// Retain this unrelated setting.' in fixture.read_text()
    return {'standalone': True, 'adapter_formats': len(CLIENTS), 'config_only': True,
            'plan_read_only': True, 'connect_disconnect': True, 'repair_preserves_codex': True,
            'disable_uninstall_preserves_codex': True, 'external_live_sessions': 'not tested'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--codex-home', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    result = qualify(args.root.resolve(), args.codex_home.resolve())
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))
