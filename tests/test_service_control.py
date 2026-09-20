from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import subprocess
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service_control import ServiceController


class ServiceTests(unittest.TestCase):
    def run_startup_without_processes(self, name, *, exit_code=None, cleanup_error=None):
        """Exercise startup control flow with a virtual clock and no real subprocesses."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        control = ServiceController(Path(folder.name))
        runtime = control.root / name / '.venv/Scripts/python.exe'
        runtime.parent.mkdir(parents=True)
        runtime.touch()
        process = Mock(pid=123456, returncode=exit_code)
        process.poll.return_value = exit_code
        process.wait.return_value = 0
        clock = [0.0]
        def advance(seconds):
            clock[0] += seconds
        completed = subprocess.CompletedProcess([], 5 if cleanup_error else 0, '', cleanup_error or '')
        with patch('service_control.startup_lock', return_value=nullcontext()), \
             patch.object(control, 'probe', return_value=False), \
             patch.object(control, 'port_in_use', return_value=False), \
             patch('service_control.subprocess.Popen', return_value=process), \
             patch('service_control.subprocess.run', return_value=completed) as cleanup, \
             patch('service_control.time.monotonic', side_effect=lambda: clock[0]), \
             patch('service_control.time.sleep', side_effect=advance):
            result = control.ensure(name)
        saved = json.loads((control.logs / f'{name}-status.json').read_text(encoding='utf-8'))
        self.assertEqual(saved, result)
        return result, process, cleanup, clock[0]

    @unittest.skipUnless(os.name == 'nt', 'Windows process-tree termination contract')
    def test_headroom_timeout_removes_only_its_created_process_tree(self):
        result, process, cleanup, elapsed = self.run_startup_without_processes('headroom')
        self.assertFalse(result['ready'])
        self.assertGreaterEqual(elapsed, 60)
        self.assertLess(elapsed, 61)
        cleanup.assert_called_once()
        command = cleanup.call_args.args[0]
        self.assertEqual(command[1:], ['/PID', str(process.pid), '/T', '/F'])
        self.assertLessEqual(cleanup.call_args.kwargs['timeout'], 10)
        self.assertTrue(result.get('cleanup', {}).get('stopped'))

    @unittest.skipUnless(os.name == 'nt', 'Windows process-tree termination contract')
    def test_dashboard_keeps_its_fifteen_second_timeout(self):
        result, _, cleanup, elapsed = self.run_startup_without_processes('dashboard')
        self.assertFalse(result['ready'])
        self.assertGreaterEqual(elapsed, 15)
        self.assertLess(elapsed, 16)
        cleanup.assert_called_once()

    @unittest.skipUnless(os.name == 'nt', 'Windows process-tree termination contract')
    def test_timeout_cleanup_failure_is_saved_and_not_reported_as_stopped(self):
        result, _, cleanup, _ = self.run_startup_without_processes('headroom', cleanup_error='Access denied')
        cleanup.assert_called_once()
        self.assertFalse(result.get('cleanup', {}).get('stopped', True))
        self.assertIn('Access denied', result['error'])

    def test_exited_owned_process_does_not_trigger_tree_termination(self):
        result, _, cleanup, _ = self.run_startup_without_processes('headroom', exit_code=17)
        self.assertFalse(result['ready'])
        self.assertIn('17', result['error'])
        cleanup.assert_not_called()

    def test_launcher_exiting_just_before_cleanup_is_not_targeted(self):
        process = Mock(pid=123456)
        process.poll.return_value = 0
        with patch('service_control.subprocess.run') as cleanup:
            result = ServiceController.cleanup_created_process(process)
        cleanup.assert_not_called()
        self.assertFalse(result['attempted'])
        self.assertFalse(result['stopped'])
        self.assertIn('could not be confirmed', result['error'])

    @unittest.skipUnless(os.name == 'nt', 'Windows process-tree termination contract')
    def test_tree_termination_timeout_is_reported_without_retrying_other_pids(self):
        process = Mock(pid=123456)
        process.poll.return_value = None
        with patch('service_control.subprocess.run', side_effect=subprocess.TimeoutExpired('taskkill', 5)) as cleanup:
            result = ServiceController.cleanup_created_process(process)
        cleanup.assert_called_once()
        process.wait.assert_not_called()
        self.assertFalse(result['stopped'])
        self.assertIn('timed out', result['error'])

    @unittest.skipUnless(os.name == 'nt', 'Windows process-tree termination contract')
    def test_tree_termination_must_verify_the_owned_launcher_exited(self):
        process = Mock(pid=123456)
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired('owned-python', 3)
        with patch('service_control.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            result = ServiceController.cleanup_created_process(process)
        process.wait.assert_called_once_with(timeout=3)
        self.assertFalse(result['stopped'])
        self.assertIn('timed out', result['error'])

    def test_ready_existing_service_is_not_spawned_or_terminated(self):
        with tempfile.TemporaryDirectory() as folder:
            control = ServiceController(Path(folder))
            with patch.object(control, 'probe', return_value=True), \
                 patch('service_control.subprocess.Popen') as spawn, \
                 patch('service_control.subprocess.run') as cleanup:
                result = control.ensure('headroom')
            self.assertTrue(result['ready'])
            spawn.assert_not_called()
            cleanup.assert_not_called()

    def test_default_start_only_requests_dashboard(self):
        with tempfile.TemporaryDirectory() as folder:
            control = ServiceController(Path(folder))
            with patch.object(control, 'ensure', return_value={'ready': True}) as ensure:
                control.start_default()
            ensure.assert_called_once_with('dashboard')

    def test_absent_runtime_is_reported_without_global_config_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            control = ServiceController(Path(folder))
            with patch.object(control, 'probe', return_value=False), patch.object(control, 'port_in_use', return_value=False):
                result = control.ensure('headroom')
            self.assertFalse(result['ready'])
            self.assertIn('missing', result['error'].lower())

    def test_unrelated_listener_is_not_killed_or_replaced(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status":"ok","service":"unrelated"}')
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                control = ServiceController(Path(folder))
                control.ports['dashboard'] = server.server_port
                with patch('service_control.subprocess.Popen') as spawn, patch('service_control.subprocess.run') as cleanup:
                    result = control.ensure('dashboard')
                    spawn.assert_not_called()
                    cleanup.assert_not_called()
                self.assertFalse(result['ready'])
                self.assertIn('occupied', result['error'])
                self.assertTrue(control.port_in_use('dashboard'))
        finally:
            server.shutdown()
            server.server_close()

    def test_health_checks_validate_identity_and_boolean_readiness(self):
        self.assertFalse(ServiceController.valid_health('headroom', {'service':'headroom-proxy','status':'healthy','ready':'true'}))
        self.assertFalse(ServiceController.valid_health('dashboard', {'status':'ok'}))
        self.assertTrue(ServiceController.valid_health('dashboard', {'status':'ok','service':'codex-token-saver-dashboard'}))
        self.assertTrue(ServiceController.valid_health('headroom', {'service':'headroom-proxy','status':'healthy','ready':True}))


if __name__ == '__main__':
    unittest.main()
