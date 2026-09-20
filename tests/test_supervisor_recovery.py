import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import desktop_proxy_service as service
from desktop_proxy_control import DesktopProxyControl
from service_control import ServiceController


class SupervisorRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'proxy').mkdir()
        (self.root / 'proxy/settings.json').write_text('{"installed":true,"enabled":true}')

    def test_stale_or_reused_pid_is_not_live_even_with_available_flag(self):
        stamp = datetime.now(timezone.utc)
        identity = {'created': 'first', 'executable': 'python.exe'}
        raw = {'available': True, 'pid': 42, 'process_identity': identity,
               'timestamp': stamp.isoformat()}
        path = self.root / 'proxy/service-status.json'
        path.write_text(json.dumps(raw))
        with patch.object(service, 'process_identity', return_value=identity):
            self.assertTrue(service.read_status(self.root)['live'])
            raw['timestamp'] = (stamp - timedelta(minutes=5)).isoformat()
            path.write_text(json.dumps(raw))
            self.assertFalse(service.read_status(self.root)['live'])
        raw['timestamp'] = stamp.isoformat()
        path.write_text(json.dumps(raw))
        with patch.object(service, 'process_identity', return_value={'created': 'reused'}):
            self.assertFalse(service.read_status(self.root)['live'])

    def test_tray_default_start_recovers_installed_supervisor_without_owning_workers(self):
        control = ServiceController(self.root)
        with patch.object(control, 'ensure', return_value={'ready': True}), \
             patch.object(service, 'ensure_supervisor', return_value={'live': False, 'starting': True}) as recover:
            result = control.start_default()
        recover.assert_called_once_with(self.root)
        self.assertTrue(result['supervisor']['starting'])

    def test_existing_owner_is_never_duplicated_even_with_stale_heartbeat(self):
        with service.lifetime_lock(self.root / 'proxy/supervisor.lock'), \
             patch.object(service.subprocess, 'Popen') as spawn:
            result = service.ensure_supervisor(self.root)
        spawn.assert_not_called()
        self.assertFalse(result['live'])
        self.assertIn('held', result['last_error'])

    def test_missing_owner_restarts_once_and_respects_cooldown(self):
        runtime = self.root / 'headroom/.venv/Scripts/pythonw.exe'
        runtime.parent.mkdir(parents=True)
        runtime.write_bytes(b'fixture')
        with patch.object(service.subprocess, 'Popen') as spawn:
            first = service.ensure_supervisor(self.root)
            second = service.ensure_supervisor(self.root)
        self.assertTrue(first['starting'])
        self.assertTrue(second['starting'])
        spawn.assert_called_once()
        self.assertEqual(spawn.call_args.args[0][-1], 'run')
        self.assertEqual(spawn.call_args.kwargs['stdin'], service.subprocess.DEVNULL)

    def test_recovery_does_nothing_if_bundle_proxy_is_not_installed(self):
        (self.root / 'proxy/settings.json').unlink()
        with patch.object(service.subprocess, 'Popen') as spawn:
            service.ensure_supervisor(self.root)
        spawn.assert_not_called()

    def test_transient_supervisor_error_recovers_without_killing_stream_workers(self):
        supervisor = service.DesktopProxyService(self.root)
        stop = threading.Event()
        calls = []
        def step():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError('private-request-do-not-log')
            stop.set()
        with patch.object(supervisor, 'step', side_effect=step), \
             patch.object(supervisor, 'shutdown') as shutdown, \
             patch.object(stop, 'wait'):
            supervisor.run(stop)
        self.assertEqual(len(calls), 2)
        shutdown.assert_not_called()
        log = (self.root / 'logs/proxy-supervisor.log').read_text()
        self.assertIn('RuntimeError', log)
        self.assertNotIn('private-request-do-not-log', log)

    def test_offline_savings_freshness_uses_lifetime_activity_after_history_cap(self):
        state = self.root / 'proxy/backend-state'
        state.mkdir()
        (state / 'proxy_savings.json').write_text(json.dumps({
            'lifetime': {'tokens_saved': 120, 'requests': 9},
            'history': [{'timestamp': '2026-09-16T04:26:03Z'}],
            'lifetime_metrics': {'last_activity_at': '2026-09-18T13:46:29Z'}}))
        control = DesktopProxyControl(self.root, config_home=self.root / 'config')
        with patch.object(control, '_fetch', side_effect=OSError):
            result = control.status()
        self.assertEqual(result['savings']['last_recorded_at'], '2026-09-18T13:46:29Z')
        self.assertFalse(result['supervisor']['live'])
        self.assertTrue(result['savings']['historical'])

    def test_online_stats_without_metrics_use_persisted_activity_only(self):
        state = self.root / 'proxy/backend-state'
        state.mkdir()
        (state / 'proxy_savings.json').write_text(json.dumps({
            'lifetime': {'tokens_saved': 999, 'requests': 999},
            'lifetime_metrics': {'last_activity_at': '2026-09-18T13:46:29Z'}}))
        control = DesktopProxyControl(self.root, config_home=self.root / 'config')
        health = {'service': 'codex-token-saver-proxy', 'status': 'ok', 'ready': True}
        relay = dict(health, backend_ready=True)
        backend = {'persistent_savings': {
            'lifetime': {'tokens_saved': 120, 'requests': 9},
            'recent_history': [{'timestamp': '2026-09-16T04:26:03Z'}]}}
        with patch.object(control, '_fetch', side_effect=[health, relay, backend]):
            result = control.status()
        self.assertEqual(result['savings']['last_recorded_at'], '2026-09-18T13:46:29Z')
        self.assertEqual(result['savings']['saved_tokens'], 120)
        self.assertEqual(result['savings']['requests'], 9)
        self.assertFalse(result['savings']['historical'])

    @unittest.skipUnless(os.name == 'nt', 'Windows hidden supervisor recovery')
    def test_real_supervisor_recovery_preserves_existing_relay(self):
        class Relay(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"service":"codex-token-saver-proxy","status":"ok","ready":true}')
            def log_message(self, *args):
                pass
        relay = ThreadingHTTPServer(('127.0.0.1', 0), Relay)
        threading.Thread(target=relay.serve_forever, daemon=True).start()
        self.addCleanup(relay.server_close)
        self.addCleanup(relay.shutdown)
        (self.root / 'proxy/settings.json').write_text('{"installed":true,"enabled":false}')
        runtime = self.root / 'headroom/.venv'
        (runtime / 'Scripts').mkdir(parents=True)
        shutil.copy2(Path(sys.prefix) / 'pyvenv.cfg', runtime / 'pyvenv.cfg')
        shutil.copy2(Path(sys.prefix) / 'Scripts/pythonw.exe', runtime / 'Scripts/pythonw.exe')
        # Import source from the checkout but constrain the real subprocess to the fixture.
        (self.root / 'desktop_proxy_service.py').write_text(
            'import sys\nfrom pathlib import Path\n'
            f'sys.path.insert(0, {str(Path(service.__file__).parent)!r})\n'
            'from desktop_proxy_service import DesktopProxyService\n'
            's=DesktopProxyService(Path(__file__).parent)\n'
            f's.ports["frontdoor"]={relay.server_port}\n'
            's.run()\n', encoding='utf-8')
        spawned = []
        original = subprocess.Popen
        def launch(*args, **kwargs):
            child = original(*args, **kwargs)
            spawned.append(child)
            return child
        def wait_live():
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                value = service.read_status(self.root)
                if value['live'] and value.get('frontdoor', {}).get('ready'):
                    return value
                time.sleep(.05)
            self.fail('Isolated supervisor did not publish a live heartbeat')
        try:
            with patch.object(service.subprocess, 'Popen', side_effect=launch):
                service.ensure_supervisor(self.root)
                first = wait_live()
                self.assertFalse(first['frontdoor']['owned'])
                self.assertTrue(ServiceController.cleanup_created_process(spawned[0])['stopped'])
                self.assertFalse(service.read_status(self.root)['live'])
                (self.root / 'proxy/recovery-attempt.json').write_text('{"attempted_at":0}')
                service.ensure_supervisor(self.root)
                second = wait_live()
                self.assertNotEqual(first['process_identity'], second['process_identity'])
                self.assertFalse(second['frontdoor']['owned'])
                self.assertTrue(second['frontdoor']['ready'])
        finally:
            for child in spawned:
                if child.poll() is None:
                    self.assertTrue(ServiceController.cleanup_created_process(child)['stopped'])


if __name__ == '__main__':
    unittest.main()
