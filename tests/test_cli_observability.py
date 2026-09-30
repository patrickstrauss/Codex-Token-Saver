import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cli_tools
from bundle_preferences import set_preference


def enabled(root, component):
    set_preference(root, component, True)
    set_preference(root, 'laya_router', True)


def test_help_is_informational_and_does_not_advance_operational_use(tmp_path):
    enabled(tmp_path, 'ast_grep')
    with patch.object(cli_tools, 'runtime_status', return_value={'available': True, 'versions': {}}), \
         patch.object(cli_tools, 'command', return_value=['fixture.exe']), \
         patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
        assert cli_tools.run(tmp_path, 'ast_grep', ['--help']) == 0
    status = cli_tools.status(tmp_path, 'ast_grep')
    assert status['activity']['completed'] == 0
    assert status['activity']['informational'] == 1
    assert status['last_use'] is None


def test_closed_cdp_endpoint_is_rejected_before_daemon_start(tmp_path):
    enabled(tmp_path, 'playwright_cli')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with patch.object(cli_tools, 'runtime_status', return_value={'available': True, 'versions': {}}), \
         patch.object(cli_tools, 'authorize_explicit', create=True), \
         patch.object(cli_tools, 'command', return_value=['fixture.exe']), \
         patch.object(subprocess, 'run') as run:
        assert cli_tools.run(tmp_path, 'playwright_cli', ['-s=test', 'attach', '--cdp=http://127.0.0.1:' + str(port)]) == 1
    run.assert_not_called()
    state = cli_tools.status(tmp_path, 'playwright_cli')
    assert state['activity']['failed'] == 1
    assert state['diagnostics']['last_failure_code'] == 'connection_refused'


def test_open_cdp_endpoint_passes_preflight_without_browser_actions():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        sock.listen()
        endpoint = 'http://127.0.0.1:' + str(sock.getsockname()[1])
        assert cli_tools.cdp_preflight(['attach', '--cdp', endpoint]) is None


def test_ast_no_matches_is_completed_and_native_exit_one_is_preserved(tmp_path):
    enabled(tmp_path, 'ast_grep')
    calls = []
    with patch.object(cli_tools, 'runtime_status', return_value={'available': True, 'versions': {}}), \
         patch.object(cli_tools, 'authorize_explicit', side_effect=lambda *a, **k: calls.append('laya'), create=True), \
         patch.object(cli_tools, 'command', return_value=['fixture.exe']), \
         patch.object(subprocess, 'run', side_effect=lambda *a, **k: (calls.append('tool') or subprocess.CompletedProcess([], 1))):
        assert cli_tools.run(tmp_path, 'ast_grep', ['run', '-p', 'missing()']) == 1
    assert calls == ['laya', 'tool']
    assert cli_tools.status(tmp_path, 'ast_grep')['activity']['completed'] == 1


def test_explicit_cli_stops_if_laya_rejects(tmp_path):
    enabled(tmp_path, 'ast_grep')
    with patch.object(cli_tools, 'runtime_status', return_value={'available': True, 'versions': {}}), \
         patch.object(cli_tools, 'authorize_explicit', side_effect=ValueError('ambiguous routing'), create=True), \
         patch.object(cli_tools, 'command', return_value=['fixture.exe']), \
         patch.object(subprocess, 'run') as run:
        assert cli_tools.run(tmp_path, 'ast_grep', ['run', '-p', 'foo()']) == 126
    run.assert_not_called()


def test_browser_failure_categories_do_not_include_private_text():
    assert cli_tools.browser_failure('Error: strict mode violation: locator(SECRET) resolved to 2 elements') == 'ambiguous_selector'
    assert cli_tools.browser_failure('ECONNREFUSED 127.0.0.1:1234 private') == 'connection_refused'
    assert cli_tools.browser_failure('Timeout 1000ms exceeded; SECRET') == 'timeout'
