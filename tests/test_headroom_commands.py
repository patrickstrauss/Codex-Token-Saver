import importlib.util
import base64
from contextlib import closing
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class CommandFilterTests(unittest.TestCase):
    def test_command_filter_exists(self):
        self.assertIsNotNone(importlib.util.find_spec('command_compression'),
                             'Automatic command output filter has not been implemented')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_filter(self, compressor=lambda s: 'SUMMARY\nCRITICAL_ERROR_73', cache=None):
        from desktop_headroom import DesktopHeadroom
        from command_compression import CommandCompressor
        if cache is None:
            class Cache:
                entries = {}
                def store(self, **kw):
                    from types import SimpleNamespace
                    self.entries[kw['explicit_hash']] = SimpleNamespace(original_content=kw['original'])
                    return kw['explicit_hash']
                def retrieve(self, key):
                    return self.entries.get(key)
            cache = Cache()
        backend = DesktopHeadroom(self.state, compressor=compressor,
                                  token_counter=lambda text: len(text), cache=cache)
        return CommandCompressor(self.state, backend=backend), backend

    def test_compressed_original_is_exactly_retrievable_and_retrieval_cost_subtracted(self):
        service, backend = self.make_filter()
        original = ('repeated ordinary output\r\n' * 400 + 'CRITICAL_ERROR_73').encode()
        result = service.process(original, return_code=0)
        self.assertEqual(result.status, 'compressed')
        self.assertIn(b'headroom_retrieve', result.output)
        self.assertLess(len(result.output), len(original))
        exact = backend.retrieve(result.content_hash, max_lines=10000)
        self.assertTrue(exact.endswith(original.decode()))
        service.record(result, executable='rtk.exe', return_code=0,
                       stdout_bytes=len(original), stderr_bytes=0)
        stats = backend.stats()
        self.assertEqual(stats['command_count'], 1)
        self.assertEqual(stats['total_saved'], len(original) - len(result.output) - len(exact))

    def test_failure_output_is_byte_exact_and_never_compressed(self):
        def forbidden(_):
            raise AssertionError('Nonzero command must not be compressed')
        service, _ = self.make_filter(compressor=forbidden)
        original = b'failure\r\n\x00\xff' * 2000
        result = service.process(original, return_code=17)
        self.assertEqual(result.output, original)
        self.assertEqual(result.status, 'command_failed')
        self.assertIsNone(result.input_tokens)

    def test_invalid_utf8_and_small_and_exact_pass_through(self):
        service, _ = self.make_filter()
        for data, exact, expected in [(b'\xff' * 8000, False, 'non_utf8'),
                                      (b'short\r\n', False, 'small_output'),
                                      (b'A' * 8000, True, 'exact_requested')]:
            with self.subTest(expected):
                result = service.process(data, return_code=0, exact=exact)
                self.assertEqual(result.output, data)
                self.assertEqual(result.status, expected)

    def test_cache_and_sdk_failures_fall_back_to_original(self):
        def broken(_):
            raise RuntimeError('failure')
        class BrokenCache:
            def store(self, **kwargs):
                raise OSError('disk unavailable')
        for compressor, cache in [(broken, None), (lambda s: 'summary', BrokenCache())]:
            service, _ = self.make_filter(compressor=compressor, cache=cache)
            original = b'ordinary text\r\n' * 800
            result = service.process(original, return_code=0)
            self.assertEqual(result.output, original)
            self.assertEqual(result.status, 'compression_unavailable')
            self.assertEqual(result.input_tokens, result.output_tokens)

    def test_header_cost_must_not_make_output_larger(self):
        original = b'x' * 1800
        service, _ = self.make_filter(compressor=lambda s: s[:-2])
        result = service.process(original, return_code=0)
        self.assertEqual(result.output, original)
        self.assertEqual(result.status, 'no_reduction')


class CommandRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_wrapper(self, script, args=(), input=None, exact=False):
        fixture = self.cwd / 'child.py'
        fixture.write_text(script, encoding='utf-8')
        env = dict(os.environ, HEADROOM_WORKSPACE_DIR=str(self.cwd / 'state'),
                   TEST_SENTINEL='original child environment')
        env.pop('HEADROOM_EXACT', None)
        return subprocess.run([sys.executable, str(ROOT / 'headroom_run.py'),
                               *(['--exact'] if exact else []), '--', sys.executable,
                               str(fixture), *args], cwd=self.cwd, env=env,
                              input=input, capture_output=True, timeout=20)

    def test_literal_arguments_cwd_env_stdin_exit_and_binary_output(self):
        args = ['literal|pipe', 'a"b', '', '$(not-command)', 'ไทย', 'a\nb']
        script = ('import json,os,sys\n'
                  'sys.stdout.buffer.write(json.dumps([sys.argv[1:],os.getcwd(),'
                  'os.environ["TEST_SENTINEL"],sys.stdin.buffer.read().decode()],ensure_ascii=False).encode())\n'
                  'sys.stderr.buffer.write(b"raw\\r\\n\\xff\\x00")\n'
                  'sys.exit(19)\n')
        result = self.run_wrapper(script, args=args, input=b'literal stdin')
        self.assertEqual(result.returncode, 19)
        self.assertEqual(result.stderr, b'raw\r\n\xff\x00')
        self.assertEqual(json.loads(result.stdout), [args, str(self.cwd), 'original child environment', 'literal stdin'])

    def test_wrapper_fixture_ignores_parent_exact_opt_out(self):
        # The suite itself may be launched with exact output for verification.
        # Its synthetic child fixtures choose their own compression mode.
        with patch.dict(os.environ, HEADROOM_EXACT='1'):
            result = self.run_wrapper('import os,sys\nsys.stdout.write(str(os.environ.get("HEADROOM_EXACT")))\n')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'None')

    def test_over_two_mebibytes_streams_every_byte(self):
        script = ('import sys\n'
                  'sys.stdout.buffer.write(b"a" * (2*1024*1024+8192))\n'
                  'sys.stderr.buffer.write(b"b"*8192)\n')
        result = self.run_wrapper(script)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'a' * (2*1024*1024+8192))
        self.assertEqual(result.stderr, b'b' * 8192)
        with closing(sqlite3.connect(self.cwd / 'state/activity.db')) as conn:
            self.assertEqual(conn.execute('SELECT status FROM command_attempts').fetchone()[0], 'size_limit')
            self.assertEqual(conn.execute('SELECT count(*) FROM events').fetchone()[0], 0)

    def test_nonzero_child_runs_once_despite_large_utf8_output(self):
        script = ('from pathlib import Path\nimport sys\n'
                  'p=Path("runs.txt"); p.write_text(p.read_text()+"x" if p.exists() else "x")\n'
                  'sys.stdout.buffer.write(b"ordinary output\\r\\n"*1000)\n'
                  'sys.exit(7)\n')
        result = self.run_wrapper(script)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, b'ordinary output\r\n' * 1000)
        self.assertEqual((self.cwd / 'runs.txt').read_text(), 'x')

    def test_exact_mode_skips_compressor_with_original_output(self):
        result = self.run_wrapper('import sys\nsys.stdout.buffer.write(b"repeat output\\r\\n"*1000)', exact=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'repeat output\r\n'*1000)

    def test_buffer_deadline_releases_output_and_keeps_both_streams_exact(self):
        from headroom_run import capture_command
        fixture = self.cwd / 'slow.py'
        fixture.write_text('import sys,time\n'
                           'sys.stdout.buffer.write(b"early\\r\\n");sys.stdout.flush()\n'
                           'time.sleep(.2)\n'
                           'sys.stdout.buffer.write(b"late\\r\\n")\n'
                           'sys.stderr.buffer.write(b"stderr\\xff")\n')
        out, err = io.BytesIO(), io.BytesIO()
        code, captured, counters, reason = capture_command([sys.executable, str(fixture)], out, err,
                                                         buffer_seconds=.03)
        self.assertEqual((code, captured, reason), (0, b'', 'streaming_timeout'))
        self.assertEqual(out.getvalue(), b'early\r\nlate\r\n')
        self.assertEqual(err.getvalue(), b'stderr\xff')
        self.assertEqual(counters, {'stdout': 13, 'stderr': 7})

    def test_compressor_timeout_and_unavailable_worker_return_original(self):
        import headroom_run
        original = b'ordinary text\r\n' * 1000
        with patch.object(headroom_run, 'COMPRESSION_TIMEOUT_SECONDS', 0.0001):
            result = headroom_run.filter_in_worker(original, self.cwd / 'timeout-state')
        self.assertEqual(result.output, original)
        self.assertEqual(result.status, 'compression_timeout')

    def test_broken_state_never_reruns_successful_command_or_loses_output(self):
        # A file occupying the state-directory path breaks both optional SDK
        # bookkeeping and caching, while the requested command must still run.
        (self.cwd / 'state').write_text('not a directory')
        script = ('from pathlib import Path\nimport sys\n'
                  'p=Path("runs.txt");p.write_text(p.read_text()+"x" if p.exists() else "x")\n'
                  'sys.stdout.buffer.write(b"successful output\\r\\n"*1000)\n'
                  'sys.stderr.buffer.write(b"ordinary stderr\\r\\n")\n')
        result = self.run_wrapper(script)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'successful output\r\n'*1000)
        self.assertEqual(result.stderr, b'ordinary stderr\r\n')
        self.assertEqual((self.cwd / 'runs.txt').read_text(), 'x')

    def test_filter_worker_has_no_savings_events_until_parent_records_emitted_output(self):
        from headroom_run import filter_in_worker, record_in_worker
        state = self.cwd / 'separate-state'
        data = ''.join(f'2026-09-13 INFO worker={index} request succeeded\n' for index in range(250)).encode()
        result = filter_in_worker(data, state)
        self.assertEqual(result.status, 'compressed')
        with closing(sqlite3.connect(state / 'activity.db')) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM events').fetchone()[0], 0)
        record_in_worker(result, state, 'rtk.exe', 0, len(data), 0)
        with closing(sqlite3.connect(state / 'activity.db')) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*),SUM(saved_tokens) FROM events').fetchone(),
                             (1, result.input_tokens-result.output_tokens))
            self.assertEqual(conn.execute('SELECT executable,status FROM command_attempts').fetchone(),
                             ('rtk.exe', 'compressed'))

    def test_bom_prefixed_native_packet_preserves_original_bom_with_real_sdk(self):
        original = b'\xef\xbb\xbf' + ''.join(
            f'2026-09-13 INFO worker={index} routine check successful\r\n'
            if index != 73 else '2026-09-13 ERROR CRITICAL_FAILURE_73 service failed\r\n'
            for index in range(220)).encode()
        state = self.cwd / 'packet-state'
        packet = b'\xef\xbb\xbf' + json.dumps({'input': base64.b64encode(original).decode()}).encode()
        env = dict(os.environ, HEADROOM_WORKSPACE_DIR=str(state))
        worker = subprocess.run([sys.executable, str(ROOT / 'headroom_run.py'), '--filter-packet'],
                                input=packet, capture_output=True, env=env, timeout=15)
        self.assertEqual(worker.returncode, 0, worker.stderr.decode(errors='replace'))
        result = json.loads(worker.stdout)
        emitted = base64.b64decode(result['output'])
        self.assertEqual(result['status'], 'compressed')
        self.assertIn(b'CRITICAL_FAILURE_73', emitted)
        self.assertLess(len(emitted), len(original))
        from command_compression import configure_offline_environment
        from desktop_headroom import DesktopHeadroom
        with patch.dict(os.environ):
            configure_offline_environment(state)
            backend = DesktopHeadroom(state)
            cached = backend._get_cache().retrieve(result['content_hash']).original_content
            self.assertEqual(cached.encode(), original)
            self.assertEqual(backend.stats()['command_count'], 0)
            backend._get_cache()._backend._conn.close()
        request = {'result': result, 'executable': 'rtk.exe', 'return_code': 0,
                   'stdout_bytes': len(original), 'stderr_bytes': 0}
        recorded = subprocess.run([sys.executable, str(ROOT / 'headroom_run.py'), '--record-result'],
                                  input=b'\xef\xbb\xbf' + json.dumps(request).encode(),
                                  capture_output=True, env=env, timeout=5)
        self.assertEqual(recorded.returncode, 0, recorded.stderr.decode(errors='replace'))
        with closing(sqlite3.connect(state / 'activity.db')) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*),SUM(saved_tokens) FROM events').fetchone(),
                             (1, result['input_tokens']-result['output_tokens']))

    def test_sdk_compresses_real_json_output_and_retains_critical_record(self):
        rows = [{'id': index, 'name': 'ordinary health check item', 'region': 'local',
                 'status': 'CRITICAL_FAILURE_73' if index == 73 else 'ok',
                 'message': 'routine check completed successfully'} for index in range(160)]
        data = json.dumps(rows, indent=2).encode()
        (self.cwd / 'rows.json').write_bytes(data)
        result = self.run_wrapper('from pathlib import Path\nimport sys\n'
                                  'sys.stdout.buffer.write(Path("rows.json").read_bytes())\n'
                                  'sys.stderr.buffer.write(b"unchanged warning\\r\\n")\n')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b'unchanged warning\r\n')
        self.assertIn(b'[Headroom: compressed command stdout', result.stdout)
        self.assertIn(b'CRITICAL_FAILURE_73', result.stdout)
        self.assertLess(len(result.stdout), len(data))
        content_hash = re.search(rb'content_hash=([a-f0-9]{24})', result.stdout).group(1).decode()
        from command_compression import configure_offline_environment
        from desktop_headroom import DesktopHeadroom
        with patch.dict(os.environ):
            configure_offline_environment(self.cwd / 'state')
            backend = DesktopHeadroom(self.cwd / 'state')
            exact = backend.retrieve(content_hash, max_lines=10000)
            self.assertTrue(exact.endswith(data.decode()))
            stats = backend.stats()
            self.assertEqual(stats['command_count'], 1)
            self.assertEqual(stats['retrieve_count'], 1)
            self.assertEqual(stats['total_saved'], stats['command_saved'] - stats['retrieval_tokens'])
            backend._get_cache()._backend._conn.close()

    def test_sdk_compresses_real_log_output_and_retains_error(self):
        data = ''.join(f'2026-09-13T10:00:00Z INFO worker={index} health check OK latency=10ms\n'
                       if index != 73 else '2026-09-13T10:00:00Z ERROR CRITICAL_FAILURE_73 database unavailable\n'
                       for index in range(200)).encode()
        (self.cwd / 'rows.log').write_bytes(data)
        result = self.run_wrapper('from pathlib import Path\nimport sys\n'
                                  'sys.stdout.buffer.write(Path("rows.log").read_bytes())\n')
        self.assertEqual(result.returncode, 0)
        self.assertIn(b'[Headroom: compressed command stdout', result.stdout)
        self.assertIn(b'CRITICAL_FAILURE_73', result.stdout)
        self.assertLess(len(result.stdout), len(data))

    def test_medium_output_uses_real_sdk_with_exact_recovery_and_net_receipt(self):
        # This falls below the original 6 KiB / 1,500-token admission gate.
        rows = [{'id': i, 'status': 'CRITICAL_FAILURE_7' if i == 7 else 'ok',
                 'region': 'local', 'message': 'Routine health check completed successfully.'}
                for i in range(20)]
        data = json.dumps(rows, indent=2).encode()
        self.assertTrue(1024 <= len(data) < 6144)
        (self.cwd / 'medium.json').write_bytes(data)
        result = self.run_wrapper('from pathlib import Path\nimport sys\n'
                                  'sys.stdout.buffer.write(Path("medium.json").read_bytes())\n')
        self.assertEqual(result.returncode, 0)
        self.assertIn(b'[Headroom: compressed command stdout', result.stdout)
        self.assertIn(b'CRITICAL_FAILURE_7', result.stdout)
        self.assertLess(len(result.stdout), len(data))
        state = self.cwd / 'state'
        with closing(sqlite3.connect(state / 'activity.db')) as connection:
            receipt = connection.execute(
                'SELECT status,input_tokens,output_tokens,content_hash FROM command_attempts').fetchone()
            self.assertEqual(receipt[0], 'compressed')
            self.assertTrue(350 <= receipt[1] < 1500)
            self.assertGreater(receipt[1], receipt[2])
            self.assertEqual(connection.execute('SELECT SUM(saved_tokens) FROM events').fetchone()[0],
                             receipt[1] - receipt[2])
        with closing(sqlite3.connect(state / 'originals.db')) as connection:
            original = json.loads(connection.execute(
                'SELECT entry_json FROM ccr_entries WHERE hash=?', (receipt[3],)).fetchone()[0])
        self.assertEqual(original['original_content'].encode(), data)


if __name__ == '__main__':
    unittest.main()
