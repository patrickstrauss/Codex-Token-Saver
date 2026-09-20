"""Fault injection at the two-file registration boundary; no real profile touched."""
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
    configure(root, home)
    configured = config.read_bytes()
    configure(root, home)
    assert config.read_bytes() == configured
    print('PASS: AGENTS failure rolls config back; repeated registration is idempotent')
