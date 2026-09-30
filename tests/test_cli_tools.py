import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import cli_tools
from bundle_preferences import load_preferences


def test_off_blocks_execution_and_records_no_arguments(tmp_path):
    result = cli_tools.run(tmp_path, 'ast_grep', ['run', '-p', 'secret()'])
    assert result == 126
    activity = cli_tools.status(tmp_path, 'ast_grep')['activity']
    assert activity['blocked'] == 1
    assert 'secret' not in (tmp_path / 'data/cli-tools/ast_grep.json').read_text()


def test_toggle_guidance_is_idempotent_and_preserves_personal_text(tmp_path):
    root, home = tmp_path / 'bundle', tmp_path / 'codex'
    home.mkdir()
    agents = home / 'AGENTS.md'
    agents.write_bytes(b'Personal instructions\r\n')
    with patch.object(cli_tools, 'runtime_status', return_value={'available': True}):
        cli_tools.set_enabled(root, 'ast_grep', True, home)
        enabled = agents.read_bytes()
        cli_tools.set_enabled(root, 'ast_grep', True, home)
        assert agents.read_bytes() == enabled
        assert b'Personal instructions\r\n' in enabled
        assert load_preferences(root)['ast_grep']
        cli_tools.set_enabled(root, 'ast_grep', False, home)
        assert agents.read_bytes() == b'Personal instructions\r\n'
        assert not load_preferences(root)['ast_grep']


def test_malformed_guidance_does_not_enable_tool(tmp_path):
    home = tmp_path / 'codex'
    home.mkdir()
    (home / 'AGENTS.md').write_text('<!-- BEGIN CODEX TOKEN SAVER AST_GREP -->')
    with patch.object(cli_tools, 'runtime_status', return_value={'available': True}):
        with pytest.raises(ValueError):
            cli_tools.set_enabled(tmp_path, 'ast_grep', True, home)
    assert not load_preferences(tmp_path)['ast_grep']


def test_invocation_preserves_argv_cwd_exit_and_records_only_metadata(tmp_path):
    from bundle_preferences import set_preference
    set_preference(tmp_path, 'ast_grep', True)
    args = ['run', '-p', '$A.foo("a&b")', 'space path.js']
    with patch.object(cli_tools, 'runtime_status', return_value={'available': True, 'versions': {}}), \
         patch.object(cli_tools, 'command', return_value=['fixture.exe']) as command, \
         patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 7)) as run:
        assert cli_tools.run(tmp_path, 'ast_grep', args) == 7
    assert run.call_args.args[0] == ['fixture.exe', *args]
    assert not run.call_args.kwargs.get('shell')
    assert 'cwd' not in run.call_args.kwargs
    data = cli_tools.status(tmp_path, 'ast_grep')
    assert data['activity']['failed'] == 1
    assert 'space path' not in (tmp_path / 'data/cli-tools/ast_grep.json').read_text()


def test_missing_ready_receipt_is_not_available(tmp_path):
    assert not cli_tools.runtime_status(tmp_path)['available']


def test_failed_guidance_write_restores_toggle(tmp_path):
    home = tmp_path / 'codex'
    home.mkdir()
    (home / 'AGENTS.md').write_bytes(b'Keep personal text')
    with patch.object(cli_tools, 'runtime_status', return_value={'available': True}), \
         patch('install_desktop_mcp.replace_checked', side_effect=OSError('disk fault')):
        with pytest.raises(OSError):
            cli_tools.set_enabled(tmp_path, 'playwright_cli', True, home)
    assert not load_preferences(tmp_path)['playwright_cli']
    assert (home / 'AGENTS.md').read_bytes() == b'Keep personal text'


def test_full_disable_removes_both_guidance_blocks(tmp_path):
    from disable_bundle import disable_guidance
    original = b'Personal text\n'
    value = original
    for component in cli_tools.TOOLS:
        value = cli_tools.guidance(value, tmp_path, component, True)
    disabled = disable_guidance(value)
    assert disabled.strip() == original.strip()
    assert b'CODEX TOKEN SAVER' not in disabled


def test_new_preferences_preserve_the_file_read_by_older_loaded_workers(tmp_path):
    from bundle_preferences import set_preference, preference_status
    set_preference(tmp_path, 'rtk', True)
    original = (tmp_path / 'settings/components.json').read_bytes()
    for name in ('ast_grep', 'playwright_cli', 'laya_router'):
        set_preference(tmp_path, name, True)
    assert (tmp_path / 'settings/components.json').read_bytes() == original
    assert all(load_preferences(tmp_path)[name] for name in ('rtk', 'ast_grep', 'playwright_cli', 'laya_router'))
    (tmp_path / 'settings/extensions.json').write_text('{bad')
    assert preference_status(tmp_path)['extension_error']
    assert load_preferences(tmp_path)['rtk']
    assert not load_preferences(tmp_path)['laya_router']
