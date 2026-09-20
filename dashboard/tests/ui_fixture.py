"""Manual UI fixture: isolated counters and in-memory choices, no bundle operations."""
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with patch('threading.Thread.start'):
    import app as dashboard
from flask import Flask, Response
from component_routes import register_component_routes
from proxy_routes import register_proxy_routes, PANEL_HTML
from update_routes import register_update_routes

FIXTURE_TASK = 'a6e593dc-4bd7-40f6-8250-ae9d8990efe4'


class Controls:
    def __init__(self):
        self.components = [
            {'id': name, 'label': label, 'requested_enabled': name in ('rtk', 'headroom_local'),
             'effective_enabled': name in ('rtk', 'headroom_local'), 'available': name != 'serena',
             'state': 'ready' if name in ('rtk', 'headroom_local') else 'off',
             'reason': 'Fixture only. Changes stay in memory.', 'last_use': '2026-09-20T07:00:00Z'}
            for name, label in (('rtk', 'RTK'), ('headroom_local', 'Headroom local'),
                ('headroom_requests', 'Headroom requests'), ('serena', 'Serena'),
                ('local_summaries', 'LangMem'), ('llama_cpp', 'llama.cpp'))]

    def status(self, observations=None):
        return {'components': self.components, 'overall_health': 'ok',
                'selected_count': sum(row['requested_enabled'] for row in self.components)}

    def set_enabled(self, component, enabled):
        for row in self.components:
            if row['id'] == component:
                row.update(requested_enabled=enabled, effective_enabled=enabled, state='ready' if enabled else 'off')


class Summaries:
    def __init__(self):
        self.generated = False

    def status(self):
        return {'available': True, 'running': False, 'job': None}

    def list_tasks(self):
        return [{'task_id': FIXTURE_TASK, 'project': 'UI fixture · no real conversation', 'updated_at': '2026-09-20T07:00:00Z'}]

    def get_summary(self, task_id):
        return {'summary': 'Fixture summary. Original messages remain unchanged.' if self.generated else None,
                'coverage': {'summarized_messages': 4 if self.generated else 0, 'total_messages': 4,
                             'pending_messages': 0 if self.generated else 4}}

    def start(self, task_id):
        self.generated = True
        return {'status': 'complete'}

    def cancel(self, task_id):
        return {'status': 'cancelled'}


class Proxy:
    def status(self):
        return {'installed': True, 'validated': True, 'enabled': False, 'route_enabled': False,
                'mode': 'paused', 'ready': True, 'backend_ready': True,
                'requests': {'optimized': 42, 'direct': 3, 'failed': 0, 'active': 0},
                'savings': {'available': True, 'saved_tokens': 150000, 'requests': 200, 'last_recorded_at': '2026-09-20T07:00:00Z'}}

    def set_enabled(self, enabled):
        return self.status()


class Updates:
    def status(self):
        return {'busy': False, 'components': [{'id': key, 'current': 'fixture', 'update_available': False}
                for key in ('rtk', 'headroom', 'serena', 'langmem', 'llama_cpp')]}


def create_app():
    root = Path(__file__).resolve().parents[1]
    fixture = Flask(__name__, static_folder=str(root / 'static'))
    guard = register_update_routes(fixture, root, 18795, {}, lambda _: Updates())
    controls, summaries = Controls(), Summaries()
    register_component_routes(fixture, root, guard, lambda _: controls, lambda _: summaries)
    register_proxy_routes(fixture, root, guard, lambda _: Proxy())

    @fixture.route('/')
    def page():
        return guard.page(dashboard.HTML.replace('__REQUEST_PROXY_PANEL__', PANEL_HTML)
                          .replace('__COMPONENTS_PANEL__', (root / 'components.html').read_text(encoding='utf-8')))

    @fixture.route('/events')
    def events():
        def stream():
            while True:
                value = {'total_saved': 100, 'total_commands': 4, 'total_time_ms': 10,
                         'avg_savings_pct': 50, 'optimized_commands': 3, 'largest_saved_share_pct': 75}
                snapshot = {'overall_health': 'ok', 'rtk': {'active': False, 'records_readable': True,
                    'health': 'ok', 'total_saved': 10000, 'total_commands': 200, 'windows': {'today': value, 'seven_days': {**value, 'total_saved': 1000},
                    'lifetime': {**value, 'total_saved': 10000}}, 'last_recorded_at': '2026-09-20T07:00:00Z',
                    'collected_at': '2026-09-20T07:05:00Z', 'recent_use': False, 'version': '0.49.0'},
                    'desktop_headroom': {'configured': True, 'data_status': 'empty', 'total_saved': 0},
                    'headroom': {'active': False, 'data_status': 'empty'}, 'history': []}
                yield 'data: ' + json.dumps(snapshot) + '\n\n'
                time.sleep(2)
        return Response(stream(), mimetype='text/event-stream')
    return fixture


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=18795, debug=False, use_reloader=False)
