import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class Proxy:
    def __init__(self):
        self.calls = []
        self.value = {'installed': True, 'validated': True, 'enabled': False,
                      'route_enabled': False, 'backend_ready': False, 'ready': True,
                      'requests': {}, 'savings': {}, 'supervisor': {'live': True}}

    def status(self):
        return self.value

    def set_enabled(self, enabled):
        self.calls.append(enabled)
        self.value['enabled'] = enabled


class Integrations:
    def status(self):
        return {name: {'installed': False, 'configured': False, 'managed': False}
                for name in ('serena', 'local_summaries')}

    def set_enabled(self, component, enabled):
        raise AssertionError('Unavailable integrations cannot be enabled')


class Summaries:
    def status(self):
        return {'available': False, 'runtime_available': False, 'running': False}


@pytest.fixture
def control(tmp_path):
    from bundle_controls import BundleControls
    for name in ('bin/rtk.exe', 'tools/rtk.exe', 'headroom/.venv/Scripts/python.exe', 'desktop_headroom.py'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return BundleControls(tmp_path, proxy=Proxy(), integrations=Integrations(), summaries=Summaries())


def by_id(control, observations=None):
    return {row['id']: row for row in control.status(observations)['components']}


def test_readable_history_does_not_claim_current_activity(control):
    rows = by_id(control, {'rtk': {'records_readable': True, 'recent_use': False, 'last_recorded_at': '2026-01-01T00:00:00Z'}})
    assert rows['rtk']['state'] == 'ready'
    assert rows['rtk']['last_use'] == '2026-01-01T00:00:00Z'
    assert 'No recent use' in rows['rtk']['reason']


def test_rtk_off_keeps_local_filter_choice_and_request_routing_independent(control):
    control.set_enabled('rtk', False)
    rows = by_id(control)
    assert rows['rtk']['state'] == 'off'
    assert rows['headroom_local']['requested_enabled'] is True
    assert not control.proxy.calls
    control.set_enabled('headroom_requests', True)
    assert control.proxy.calls == [True]


def test_requested_but_bypassed_request_compression_degrades_overall(control):
    control.proxy.value.update(enabled=True, route_enabled=True)
    status = control.status()
    row = next(row for row in status['components'] if row['id'] == 'headroom_requests')
    assert row['state'] == 'bypassed' and not row['effective_enabled']
    assert status['overall_health'] != 'ok'


def test_selected_optional_component_dependencies_are_explicit(control):
    from bundle_preferences import set_preference
    set_preference(control.root, 'local_summaries', True)
    rows = by_id(control)
    assert rows['local_summaries']['state'] in ('unavailable', 'bypassed')
    assert not rows['local_summaries']['effective_enabled']
    assert rows['llama_cpp']['state'] == 'off'
    with pytest.raises(RuntimeError):
        control.set_enabled('serena', True)


def test_off_components_do_not_mask_or_create_health_failures(control):
    control.set_enabled('rtk', False)
    control.set_enabled('headroom_local', False)
    status = control.status()
    assert status['overall_health'] == 'ok'
    assert status['selected_count'] == 0


@pytest.mark.parametrize('last_use', [None, '2026-01-01T00:00:00Z', '2026-09-20T08:00:00Z'])
def test_serena_configuration_and_history_do_not_establish_loaded_task_readiness(control, monkeypatch, last_use):
    import json
    from bundle_preferences import set_preference
    set_preference(control.root, 'serena', True)
    monkeypatch.setattr(control.integrations, 'status', lambda: {
        'serena': {'installed': True, 'configured': True, 'managed': True}})
    if last_use:
        path = control.root / 'serena/activity.json'
        path.parent.mkdir()
        path.write_text(json.dumps({'last_activity_at': last_use, 'last_outcome': 'completed', 'completed': 2}))
    snapshot = control.status()
    row = next(item for item in snapshot['components'] if item['id'] == 'serena')
    assert row['state'] == 'configured'
    assert row['effective_enabled'] is None
    assert row['last_use'] == last_use
    assert row['restart_required'] is False
    assert snapshot['unverified_count'] == 1
    assert 'unverified' in row['reason']
