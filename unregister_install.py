"""Remove only the already-disabled registrations owned by this installation."""
from datetime import datetime, timezone
from pathlib import Path
import tomllib
import tomlkit
from disable_bundle import disable_config, read, apply_changes


def unregister(root, home):
    root, home = Path(root), Path(home)
    path = home / 'config.toml'
    before = read(path)
    if before is None:
        return
    # Reuse the ownership checks. Unrecognized registrations must stop removal.
    disabled = disable_config(before, root)
    if disabled != before:
        raise RuntimeError('Disable owned integrations before removing registrations')
    source = (before or b'').decode('utf-8-sig')
    document = tomlkit.parse(source)
    for name in ('headroom_desktop', 'bundle_serena', 'bundle_laya_router'):
        if name in document.get('mcp_servers', {}):
            del document['mcp_servers'][name]
    after = tomlkit.dumps(document).encode()
    if (before or b'').startswith(b'\xef\xbb\xbf'):
        after = b'\xef\xbb\xbf' + after
    if before != after:
        backup = root / 'backups' / ('unregister-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        backup.mkdir(parents=True)
        apply_changes([(path, before, after)], backup)


if __name__ == '__main__':
    import os
    import sys
    from disable_bundle import assert_codex_closed
    from desktop_proxy_control import routing_lock
    root = Path(sys.argv[1]).resolve()
    assert_codex_closed()
    with routing_lock(root / 'updates/operation.lock'):
        unregister(root, Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex'))
