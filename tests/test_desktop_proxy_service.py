import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from desktop_proxy_service import DesktopProxyService, lifetime_lock, read_status
except ImportError:
    DesktopProxyService = None


class DesktopProxyServiceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(DesktopProxyService, 'Desktop proxy supervisor is not implemented')
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.clock = [0.0]
        self.service = DesktopProxyService(self.root, clock=lambda: self.clock[0])
        self.service.probe = Mock(return_value=False)
        self.service.port_in_use = Mock(return_value=False)
        self.service._command = Mock(side_effect=lambda name: [sys.executable, name])
        self.service._environment = Mock(return_value={'PYTHONUTF8': '1'})
        self.children = []

        def spawn(*args, **kwargs):
            process = Mock(pid=10000 + len(self.children))
            process.poll.return_value = None
            self.children.append(process)
            return process

        self.spawn = self.enterContext(patch('desktop_proxy_service.subprocess.Popen', side_effect=spawn))
        self.cleanup = self.enterContext(patch('desktop_proxy_service.ServiceController.cleanup_created_process', return_value={'stopped': True, 'error': None}))

    def settings(self, **values):
        self.service.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.service.settings_path.write_text(json.dumps(values), encoding='utf-8')

    def test_absent_settings_do_not_start_services(self):
        result = self.service.step()
        self.spawn.assert_not_called()
        self.assertFalse(result['installed'])

    def test_explicit_installed_paused_starts_only_frontdoor(self):
        self.settings(installed=True, enabled=False)
        result = self.service.step()
        self.assertEqual(self.spawn.call_count, 1)
        self.assertEqual(self.spawn.call_args.args[0][-1], 'frontdoor')
        self.assertFalse(result['enabled'])

    def test_enabled_starts_frontdoor_then_backend_without_waiting_for_cold_boot(self):
        self.settings(installed=True, enabled=True)
        result = self.service.step()
        self.assertEqual([call.args[0][-1] for call in self.spawn.call_args_list], ['frontdoor', 'backend'])
        self.assertTrue(result['frontdoor']['running'])
        self.assertTrue(result['backend']['running'])
        self.assertFalse(result['backend']['ready'])

    def test_pause_preserves_owned_backend_for_inflight_requests(self):
        self.settings(installed=True, enabled=True)
        self.service.step()
        self.settings(installed=True, enabled=False)
        result = self.service.step()
        self.cleanup.assert_not_called()
        self.assertEqual(self.spawn.call_count, 2)
        self.assertTrue(result['backend']['running'])
        self.assertFalse(result['enabled'])

    def test_paused_backend_exit_does_not_restart_but_frontdoor_does(self):
        self.settings(installed=True, enabled=True)
        self.service.step()
        self.settings(installed=True, enabled=False)
        for child in self.children:
            child.poll.return_value = 7
        self.service.step()
        self.clock[0] = 2
        self.service.step()
        self.assertEqual(self.spawn.call_count, 3)
        self.assertEqual(self.spawn.call_args.args[0][-1], 'frontdoor')
        self.cleanup.assert_not_called()

    def test_backend_crash_uses_backoff_without_restarting_frontdoor(self):
        self.settings(installed=True, enabled=True)
        self.service.step()
        self.children[1].poll.return_value = 9
        first = self.service.step()
        self.assertEqual(self.spawn.call_count, 2)
        self.assertIn('9', first['backend']['last_error'])
        self.clock[0] = .5
        self.service.step()
        self.assertEqual(self.spawn.call_count, 2)
        self.clock[0] = 1.1
        self.service.step()
        self.assertEqual(self.spawn.call_count, 3)
        self.assertEqual(self.spawn.call_args.args[0][-1], 'backend')
        self.cleanup.assert_not_called()

    def test_live_but_slow_workers_are_not_killed_or_duplicated(self):
        self.settings(installed=True, enabled=True)
        self.service.step()
        self.clock[0] = 900
        result = self.service.step()
        self.assertEqual(self.spawn.call_count, 2)
        self.cleanup.assert_not_called()
        self.assertFalse(result['frontdoor']['ready'])

    def test_foreign_listener_is_never_claimed_or_terminated(self):
        self.settings(installed=True, enabled=False)
        self.service.port_in_use.return_value = True
        result = self.service.step()
        self.spawn.assert_not_called()
        self.cleanup.assert_not_called()
        self.assertFalse(result['frontdoor']['owned'])
        self.assertIn('occupied', result['frontdoor']['last_error'])

    def test_healthy_existing_listener_is_reused_without_pid_ownership(self):
        self.settings(installed=True, enabled=False)
        self.service.port_in_use.return_value = True
        self.service.probe.return_value = True
        result = self.service.step()
        self.spawn.assert_not_called()
        self.assertTrue(result['frontdoor']['ready'])
        self.assertFalse(result['frontdoor']['owned'])
        self.service.shutdown()
        self.cleanup.assert_not_called()

    def test_malformed_settings_preserve_children_and_report_safe_error(self):
        self.settings(installed=True, enabled=True)
        self.service.step()
        self.service.settings_path.write_text('{secret-content', encoding='utf-8')
        result = self.service.step()
        self.cleanup.assert_not_called()
        self.assertTrue(result['frontdoor']['running'])
        self.assertFalse(result['enabled'])
        self.assertNotIn('secret-content', json.dumps(result))
        self.assertTrue(result['settings_error'])

    def test_settings_bool_requires_real_boolean(self):
        self.settings(installed='true', enabled='true')
        result = self.service.step()
        self.spawn.assert_not_called()
        self.assertFalse(result['installed'])

    def test_removed_settings_leave_existing_frontdoor_alive(self):
        self.settings(installed=True, enabled=True)
        self.service.step()
        self.service.settings_path.unlink()
        result = self.service.step()
        self.cleanup.assert_not_called()
        self.assertTrue(result['frontdoor']['running'])

    def test_process_spawn_error_is_bounded_and_not_leaked(self):
        self.settings(installed=True, enabled=False)
        self.spawn.side_effect = OSError('secret-content')
        result = self.service.step()
        self.assertFalse(result['frontdoor']['running'])
        self.assertNotIn('secret-content', json.dumps(result))
        self.assertIn('OSError', result['frontdoor']['last_error'])
        self.service.step()
        self.assertEqual(self.spawn.call_count, 1)

    def test_shutdown_targets_only_retained_owned_processes(self):
        self.settings(installed=True, enabled=True)
        self.service.step()
        self.service.shutdown()
        self.assertEqual(self.cleanup.call_count, 2)
        self.assertEqual({id(call.args[0]) for call in self.cleanup.call_args_list}, {id(child) for child in self.children})

    def test_status_written_atomically_without_environment_or_command(self):
        self.settings(installed=True, enabled=True)
        self.service._environment.return_value = {'SECRET_KEY': 'secret-content'}
        result = self.service.step()
        saved = read_status(self.root)
        self.assertEqual(saved, result)
        self.assertNotIn('secret-content', json.dumps(saved))
        self.assertNotIn('command', json.dumps(saved))
        self.assertEqual(list(self.service.status_path.parent.glob('*.tmp')), [])

    def test_single_instance_lifetime_lock(self):
        path = self.root / 'proxy/supervisor.lock'
        with lifetime_lock(path) as first:
            self.assertTrue(first)
            with lifetime_lock(path) as second:
                self.assertFalse(second)
        with lifetime_lock(path) as third:
            self.assertTrue(third)

    def test_status_write_failure_does_not_stop_healthy_children(self):
        self.settings(installed=True, enabled=True)
        with patch('desktop_proxy_service._write_json', side_effect=PermissionError('secret-content')):
            result = self.service.step()
        self.cleanup.assert_not_called()
        self.assertTrue(result['frontdoor']['running'])
        self.assertIn('status_error', result)
        self.assertNotIn('secret-content', json.dumps(result))

    def test_duplicate_supervisor_exits_without_shutdown_of_other_owner(self):
        self.settings(installed=True, enabled=True)
        with lifetime_lock(self.root / 'proxy/supervisor.lock'):
            self.assertEqual(self.service.run(), 0)
        self.spawn.assert_not_called()
        self.cleanup.assert_not_called()


class DesktopProxyServiceIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows owned process-tree recovery')
    def test_real_gateway_crash_recovery_preserves_foreign_backend(self):
        from service_control import ServiceController

        class BackendHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"service":"unrelated-test-backend","ready":true}')

            def log_message(self, *args):
                pass

        backend = ThreadingHTTPServer(('127.0.0.1', 0), BackendHandler)
        backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
        backend_thread.start()
        self.addCleanup(backend.server_close)
        self.addCleanup(backend.shutdown)
        import socket
        with socket.socket() as port_probe:
            port_probe.bind(('127.0.0.1', 0))
            port = port_probe.getsockname()[1]
        with tempfile.TemporaryDirectory(prefix='codex-proxy-supervisor-test-') as folder:
            fixture = Path(folder)
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'desktop_proxy.py', fixture / 'desktop_proxy.py')
            runner = fixture / 'gateway_runner.py'
            runner.write_text(
                'from pathlib import Path\nfrom aiohttp import web\nfrom desktop_proxy import create_app\n'
                f'web.run_app(create_app(root=Path(__file__).parent,allow_test_host=True),host="127.0.0.1",port={port},access_log=None,print=None)\n',
                encoding='utf-8',
            )
            service = DesktopProxyService(fixture)
            service.ports.update(frontdoor=port, backend=backend.server_port)
            service.settings_path.parent.mkdir(parents=True)
            service.settings_path.write_text('{"installed":true,"enabled":false}', encoding='utf-8')
            service._command = lambda name: [sys.executable, '-u', str(runner)]

            def wait_ready():
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    result = service.step()
                    if result['frontdoor']['ready']:
                        return result
                    time.sleep(.05)
                self.fail('The isolated gateway did not become ready within 12 seconds')

            try:
                first = wait_ready()
                first_child = service.workers['frontdoor'].process
                self.assertIsNotNone(first_child)
                self.assertTrue(first['frontdoor']['owned'])
                stopped = ServiceController.cleanup_created_process(first_child)
                self.assertTrue(stopped['stopped'], stopped)
                second = wait_ready()
                second_child = service.workers['frontdoor'].process
                self.assertIsNotNone(second_child)
                self.assertIsNot(first_child, second_child)
                self.assertTrue(second['frontdoor']['ready'])
                self.assertTrue(service.port_in_use('backend'))
                self.assertIsNone(service.workers['backend'].process)
                self.assertFalse((fixture / 'proxy/gateway-stats.json').exists())
            finally:
                stopped = service.shutdown()
                self.assertTrue(stopped.get('frontdoor', {}).get('stopped'), stopped)
            self.assertTrue(service.port_in_use('backend'))

    def test_gateway_command_build_does_not_import_sdk(self):
        root = Path(__file__).resolve().parents[1]
        script = (
            'import json,sys;from desktop_proxy_service import DesktopProxyService;'
            's=DesktopProxyService();c=s._command("frontdoor");'
            'print(json.dumps({"command":c,"sdk_loaded":any(x=="headroom" or x.startswith("headroom.") for x in sys.modules)}))'
        )
        completed = subprocess.run([sys.executable, '-c', script], cwd=root, capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertFalse(result['sdk_loaded'])
        self.assertEqual(result['command'][-4:], ['--port', '8788', '--backend-port', '8789'])

    def test_native_loopback_health_rejects_other_services_and_nonboolean_ready(self):
        payload = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                service = DesktopProxyService(folder)
                service.ports['frontdoor'] = server.server_port
                for value, expected in (
                    ({'service': 'unrelated', 'status': 'ok', 'ready': True}, False),
                    ({'service': 'codex-token-saver-proxy', 'status': 'ok', 'ready': 'true'}, False),
                    ({'service': 'codex-token-saver-proxy', 'status': 'ok', 'ready': True}, True),
                ):
                    payload.clear()
                    payload.update(value)
                    self.assertEqual(service.probe('frontdoor'), expected)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
