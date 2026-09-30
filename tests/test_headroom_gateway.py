import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import headroom_run
import subprocess
from unittest.mock import AsyncMock

import pytest
import bundle_activity
import bundle_router
from bundle_preferences import set_preference

CALLER = 'a6e593dc-4bd7-40f6-8250-ae9d8990efe4'


def enable(root, *components):
    for component in ('laya_router', *components):
        set_preference(root, component, True)


@pytest.mark.parametrize('exit_code', [0, 7])
def test_explicit_headroom_records_real_command_outcome(tmp_path, monkeypatch, capsys, exit_code):
    enable(tmp_path, 'headroom_local')
    monkeypatch.setattr(headroom_run, 'ROOT', tmp_path)
    monkeypatch.setenv('CODEX_THREAD_ID', CALLER)
    monkeypatch.delenv('CTS_LAYA_INTERNAL', raising=False)
    monkeypatch.delenv('HEADROOM_EXACT', raising=False)
    monkeypatch.delenv('CTS_ACTIVITY_KIND', raising=False)
    # The old compressor worker is separate accounting and already covered elsewhere.
    monkeypatch.setattr(headroom_run, 'record_in_worker', lambda *args: None)
    assert headroom_run.main(['--', sys.executable, '-c', f'print("fixture"); raise SystemExit({exit_code})']) == exit_code
    events = bundle_activity.snapshot(tmp_path, task_id=CALLER)['recent']
    component = [event for event in events if event['component'] == 'headroom_local']
    assert len(component) == 1
    assert component[0]['outcome'] == ('completed' if exit_code == 0 else 'failed')
    assert len([event for event in events if event['component'] == 'laya_router']) == 1
    assert 'fixture' in capsys.readouterr().out


def test_headroom_launch_failure_and_gateway_block_are_recorded(tmp_path, monkeypatch):
    enable(tmp_path, 'headroom_local')
    monkeypatch.setattr(headroom_run, 'ROOT', tmp_path)
    monkeypatch.setenv('CODEX_THREAD_ID', CALLER)
    monkeypatch.delenv('CTS_LAYA_INTERNAL', raising=False)
    monkeypatch.delenv('HEADROOM_EXACT', raising=False)
    args = ['--', str(tmp_path / 'missing.exe')]
    assert headroom_run.main(args) == 127
    set_preference(tmp_path, 'laya_router', False)
    assert headroom_run.main(args) == 126
    events = [event for event in bundle_activity.snapshot(tmp_path)['recent'] if event['component'] == 'headroom_local']
    assert [event['outcome'] for event in events] == ['blocked', 'failed']
    assert all(event['task_id'] == CALLER for event in events)


@pytest.mark.parametrize('automatic', [True, False])
def test_automatic_and_internal_headroom_do_not_duplicate_parent_activity(tmp_path, monkeypatch, automatic):
    enable(tmp_path, 'headroom_local')
    monkeypatch.setattr(headroom_run, 'ROOT', tmp_path)
    monkeypatch.setenv('CTS_LAYA_INTERNAL', '0' if automatic else '1')
    monkeypatch.delenv('HEADROOM_EXACT', raising=False)
    monkeypatch.setattr(headroom_run, 'record_in_worker', lambda *args: None)
    with patch('laya_dispatch.authorize_explicit', side_effect=AssertionError('automatic/internal path must stay fast')):
        args = (['--cts-automatic'] if automatic else []) + ['--', sys.executable, '-c', 'pass']
        assert headroom_run.main(args) == 0
    assert bundle_activity.snapshot(tmp_path)['total'] == 0


@pytest.mark.parametrize('route,component', list(bundle_router.COMPONENT.items()))
@pytest.mark.parametrize('fails', [False, True])
def test_natural_routes_record_one_parent_component_outcome(tmp_path, monkeypatch, route, component, fails):
    from desktop_headroom import DesktopHeadroom
    from local_summaries import LocalSummaries
    import cli_tools
    enable(tmp_path, *bundle_router.COMPONENT.values())
    project = tmp_path / 'project'
    project.mkdir()
    target = project / 'fixture.py'
    target.write_text('fixture')
    request = {'intent': 'fixture operation', 'project': str(project), 'path': target.name,
               'caller_task_id': CALLER, 'task_id': 'b6e593dc-4bd7-40f6-8250-ae9d8990efe4',
               'pattern': 'fixture', 'language': 'python', 'browser_session': 'fixture',
               'git_operation': 'status', 'summary_action': 'read', 'exact': True}
    monkeypatch.setenv('CODEX_THREAD_ID', request['task_id'])  # Stale shared-server identity must never win.
    monkeypatch.delenv('CTS_ACTIVITY_KIND', raising=False)
    def backend(*args, **kwargs):
        if fails:
            raise OSError('private backend error')
        return 'fixture result'
    monkeypatch.setattr(DesktopHeadroom, 'read_file', backend)
    monkeypatch.setattr(LocalSummaries, 'get_summary', backend)
    monkeypatch.setattr(bundle_router, 'serena_query', AsyncMock(side_effect=OSError('private backend error')) if fails else AsyncMock(return_value='fixture result'))
    monkeypatch.setattr(cli_tools, 'runtime_status', lambda _: {'available': True, 'versions': {}})
    monkeypatch.setattr(cli_tools, 'command', lambda *args: ['fixture.exe'])
    def command(argv, **kwargs):
        backend()
        kwargs['stdout'].write(b'fixture result')
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(bundle_router.subprocess, 'run', command)
    predictor = lambda *_: {'route': route, 'confidence': .99, 'delivery': 'exact'}
    if fails:
        with pytest.raises(OSError):
            bundle_router.query(tmp_path, request, predictor=predictor)
    else:
        assert 'fixture result' in bundle_router.query(tmp_path, request, predictor=predictor)['result']
    events = bundle_activity.snapshot(tmp_path)['recent']
    assert len(events) == 2
    assert {event['component'] for event in events} == {'laya_router', component}
    assert all(event['task_id'] == CALLER and event['outcome'] == ('failed' if fails else 'completed') for event in events)
    assert 'private backend error' not in str(events)


def test_missing_natural_caller_stays_unknown_even_with_shared_startup_identity(tmp_path, monkeypatch):
    from desktop_headroom import DesktopHeadroom
    monkeypatch.setattr(DesktopHeadroom, '_count', lambda self, text: len(text) // 4)
    enable(tmp_path, 'headroom_local')
    (tmp_path / 'fixture.txt').write_text('fixture source')
    monkeypatch.setenv('CODEX_THREAD_ID', CALLER)
    request = {'intent': 'read file', 'project': str(tmp_path), 'path': 'fixture.txt', 'exact': True}
    bundle_router.query(tmp_path, request, predictor=lambda *_: {'route': 'file_read', 'confidence': .99, 'delivery': 'exact'})
    events = bundle_activity.snapshot(tmp_path)['recent']
    assert len(events) == 2
    assert all(event['task_id'] is None for event in events)


def test_explicit_command_is_not_started_if_gateway_rejects(tmp_path):
    with patch.object(headroom_run, 'ROOT', tmp_path), \
         patch('laya_dispatch.authorize_explicit', side_effect=RuntimeError('Laya Off')), \
         patch.object(headroom_run, 'capture_command') as capture, \
         patch.object(headroom_run.subprocess, 'run') as run:
        assert headroom_run.main(['--', sys.executable, '-c', 'print(1)']) == 126
    capture.assert_not_called()
    run.assert_not_called()
