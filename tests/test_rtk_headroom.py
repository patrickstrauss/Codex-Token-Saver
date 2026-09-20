"""Native RTK runs once even when its optional Headroom worker is broken."""
import base64
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
SOURCE = r'''
using System; using System.IO; using System.Threading; using System.Diagnostics;
using System.Web.Script.Serialization;
class Fixture {
 static int Main(string[] args) {
  string root = Environment.GetEnvironmentVariable("FIXTURE_ROOT");
  bool worker = AppDomain.CurrentDomain.BaseDirectory.Contains("Scripts");
  if (!worker) {
   File.AppendAllText(Path.Combine(root,"executions.txt"),"run\n");
   byte[] data=File.ReadAllBytes(Path.Combine(root,"stdout.bin"));
   Stream stdout=Console.OpenStandardOutput();
   if(Environment.GetEnvironmentVariable("FIXTURE_SLOW")=="1") {
    stdout.Write(data,0,3000); stdout.Flush(); Thread.Sleep(5500);
    stdout.Write(data,3000,data.Length-3000);
   } else stdout.Write(data,0,data.Length);
   Console.Error.Write("stderr unchanged\n");
   return Int32.Parse(Environment.GetEnvironmentVariable("FIXTURE_EXIT") ?? "0");
  }
  if(Array.IndexOf(args,"--record-result")>=0) {
   using(var file=File.Create(Path.Combine(root,"record.json"))) Console.OpenStandardInput().CopyTo(file);
   return 0;
  }
  File.AppendAllText(Path.Combine(root,"filter.txt"),"filter\n");
  File.WriteAllText(Path.Combine(root,"filter.pid"),Process.GetCurrentProcess().Id.ToString());
  string mode=Environment.GetEnvironmentVariable("FIXTURE_FILTER") ?? "success";
  if(mode=="hang") {Thread.Sleep(30000); return 0;}
  using(var file=File.Create(Path.Combine(root,"filter-input.json"))) Console.OpenStandardInput().CopyTo(file);
  if(mode=="failed") return 41;
  if(mode=="invalid") {Console.Write("bad json");return 0;}
  string candidate="[Headroom: compressed command stdout; exit 0]\ncompact fixture\n";
  Console.Write(new JavaScriptSerializer().Serialize(new {
   output=Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(candidate)),
   status="compressed",input_tokens=2400,output_tokens=25,
   content_hash="0123456789abcdef01234567"
  }));
  return 0;
 }
}
'''


@unittest.skipUnless(os.name == 'nt', 'Windows native launcher')
class RtkHeadroomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiled = tempfile.TemporaryDirectory(prefix='rtk-headroom-compiler ')
        cls.fixture = Path(cls.compiled.name) / 'fixture.exe'
        source = cls.fixture.with_suffix('.cs')
        source.write_text(SOURCE, encoding='utf-8-sig')
        subprocess.run([str(CSC), '/nologo', '/target:exe', '/reference:System.Web.Extensions.dll',
                        '/out:' + str(cls.fixture), str(source)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.compiled.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='RTK Headroom ภาษาไทย ')
        self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name)
        for name in ('bin', 'tools', 'headroom/.venv/Scripts', 'data/rtk'):
            (self.bundle / name).mkdir(parents=True)
        shutil.copy2(ROOT / 'bin/rtk.exe', self.bundle / 'bin/rtk.exe')
        shutil.copy2(self.fixture, self.bundle / 'tools/rtk.exe')
        shutil.copy2(self.fixture, self.bundle / 'headroom/.venv/Scripts/python.exe')
        (self.bundle / 'headroom_run.py').write_text('# fixture API', encoding='utf-8')
        self.original = (b'line of repetitive command output\r\n' * 500)
        (self.bundle / 'stdout.bin').write_bytes(self.original)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('CODEX_', 'HEADROOM_'))}
        self.env.update(FIXTURE_ROOT=str(self.bundle), CODEX_THREAD_ID='isolated-fixture')

    def run_launcher(self, args=('rg', 'fixture'), **env):
        result = subprocess.run([str(self.bundle / 'bin/rtk.exe'), *args], input=b'',
                                capture_output=True, cwd=self.bundle, env=dict(self.env, **env), timeout=18)
        self.assertEqual((self.bundle / 'executions.txt').read_text().splitlines(), ['run'])
        self.assertEqual(result.stderr, b'stderr unchanged\n')
        return result

    def test_successful_filter_delivers_compression_and_records_only_selected_result(self):
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'[Headroom: compressed command stdout; exit 0]\ncompact fixture\n')
        receipt = json.loads((self.bundle / 'record.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(receipt['result']['status'], 'compressed')
        packet = json.loads((self.bundle / 'filter-input.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(base64.b64decode(packet['input']), self.original)

    def test_missing_runtime_keeps_original_and_executes_once(self):
        (self.bundle / 'headroom/.venv/Scripts/python.exe').unlink()
        self.assertEqual(self.run_launcher().stdout, self.original)

    def test_broken_runtime_keeps_original_and_executes_once(self):
        (self.bundle / 'headroom/.venv/Scripts/python.exe').write_bytes(b'not an executable')
        self.assertEqual(self.run_launcher().stdout, self.original)

    def test_failed_worker_keeps_original_without_receipt(self):
        self.assertEqual(self.run_launcher(FIXTURE_FILTER='failed').stdout, self.original)
        receipt = json.loads((self.bundle / 'record.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(receipt['result']['status'], 'compression_unavailable')
        self.assertIsNone(receipt['result']['input_tokens'])

    def test_invalid_worker_keeps_original_without_receipt(self):
        self.assertEqual(self.run_launcher(FIXTURE_FILTER='invalid').stdout, self.original)
        receipt = json.loads((self.bundle / 'record.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(receipt['result']['status'], 'compression_unavailable')

    def test_timed_out_worker_is_terminated_and_original_is_delivered_once(self):
        self.assertEqual(self.run_launcher(FIXTURE_FILTER='hang').stdout, self.original)
        pid = (self.bundle / 'filter.pid').read_text()
        check = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                                f'if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ exit 1 }}'],
                               capture_output=True, timeout=10)
        self.assertEqual(check.returncode, 0, 'optional filter process was left running')
        receipt = json.loads((self.bundle / 'record.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(receipt['result']['status'], 'compression_unavailable')

    def test_non_codex_invocation_is_unchanged(self):
        self.env.pop('CODEX_THREAD_ID')
        self.assertEqual(self.run_launcher().stdout, self.original)
        self.assertFalse((self.bundle / 'filter.txt').exists())

    def test_existing_headroom_wrapper_suppresses_double_filtering(self):
        self.assertEqual(self.run_launcher(HEADROOM_COMMAND_ACTIVE='1').stdout, self.original)
        self.assertFalse((self.bundle / 'filter.txt').exists())

    def test_gain_machine_output_is_never_filtered(self):
        self.assertEqual(self.run_launcher(('gain', '--all', '--format', 'json')).stdout, self.original)
        self.assertFalse((self.bundle / 'filter.txt').exists())

    def test_json_output_is_never_filtered(self):
        self.assertEqual(self.run_launcher(('rg', '--json', 'fixture')).stdout, self.original)
        self.assertFalse((self.bundle / 'filter.txt').exists())

    def test_failed_command_preserves_original_exit_and_output(self):
        result = self.run_launcher(FIXTURE_EXIT='37')
        self.assertEqual(result.returncode, 37)
        self.assertEqual(result.stdout, self.original)
        self.assertFalse((self.bundle / 'filter.txt').exists())
        receipt = json.loads((self.bundle / 'record.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(receipt['result']['status'], 'command_failed')

    def test_output_over_limit_streams_raw_without_filter(self):
        self.original = b'x' * (2 * 1024 * 1024 + 1)
        (self.bundle / 'stdout.bin').write_bytes(self.original)
        self.assertEqual(self.run_launcher().stdout, self.original)
        self.assertFalse((self.bundle / 'filter.txt').exists())

    def test_slow_command_switches_to_raw_streaming_without_filter(self):
        self.assertEqual(self.run_launcher(FIXTURE_SLOW='1').stdout, self.original)
        self.assertFalse((self.bundle / 'filter.txt').exists())

    def test_small_output_records_a_check_without_claiming_token_savings(self):
        self.original = b'short output\r\n'
        (self.bundle / 'stdout.bin').write_bytes(self.original)
        self.assertEqual(self.run_launcher().stdout, self.original)
        receipt = json.loads((self.bundle / 'record.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(receipt['result']['status'], 'small_output')
        self.assertIsNone(receipt['result']['input_tokens'])
        self.assertFalse((self.bundle / 'filter.txt').exists())

    def test_medium_output_reaches_optional_worker_and_runs_command_once(self):
        self.original = b'ordinary output\r\n' * 100
        self.assertTrue(1024 <= len(self.original) < 6144)
        (self.bundle / 'stdout.bin').write_bytes(self.original)
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0)
        self.assertLess(len(result.stdout), len(self.original))
        receipt = json.loads((self.bundle / 'record.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(receipt['result']['status'], 'compressed')
        packet = json.loads((self.bundle / 'filter-input.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(base64.b64decode(packet['input']), self.original)

    def test_packet_preserves_original_utf8_bom(self):
        self.original = b'\xef\xbb\xbf' + self.original
        (self.bundle / 'stdout.bin').write_bytes(self.original)
        self.run_launcher()
        packet = json.loads((self.bundle / 'filter-input.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(base64.b64decode(packet['input']), self.original)

    def test_explicit_exact_mode_preserves_output_without_filter(self):
        self.assertEqual(self.run_launcher(HEADROOM_EXACT='1').stdout, self.original)
        self.assertFalse((self.bundle / 'filter.txt').exists())

    def test_filename_and_count_modes_preserve_output_without_filter(self):
        for flag in ('--files', '--count', '--only-matching', '--vimgrep', '--files-with-matches', '--message-format=json'):
            with self.subTest(flag=flag):
                (self.bundle / 'executions.txt').unlink(missing_ok=True)
                self.assertEqual(self.run_launcher(('rg', flag, 'fixture')).stdout, self.original)
                self.assertFalse((self.bundle / 'filter.txt').exists())

    def test_actual_native_launcher_real_python_sdk_and_isolated_savings_ledger(self):
        shutil.copy2(ROOT / 'headroom/.venv/Scripts/python.exe', self.bundle / 'headroom/.venv/Scripts/python.exe')
        shutil.copy2(ROOT / 'headroom/.venv/pyvenv.cfg', self.bundle / 'headroom/.venv/pyvenv.cfg')
        shutil.copy2(ROOT / 'headroom_run.py', self.bundle / 'headroom_run.py')
        state = self.bundle / 'isolated-real-headroom-state'
        self.env['HEADROOM_WORKSPACE_DIR'] = str(state)
        self.env['PYTHONPATH'] = os.pathsep.join([str(ROOT), str(ROOT / 'headroom/.venv/Lib/site-packages')])
        records = [{'id': i, 'status': 'CRITICAL_FAILURE_73' if i == 73 else 'healthy',
                    'detail': 'Routine service health measurement completed successfully. ' * 4}
                   for i in range(150)]
        self.original = json.dumps(records, indent=2).encode()
        (self.bundle / 'stdout.bin').write_bytes(self.original)
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith(b'[Headroom: compressed command stdout; exit 0]'), result.stdout[:1000])
        self.assertLess(len(result.stdout), len(self.original))
        self.assertIn(b'CRITICAL_FAILURE_73', result.stdout)
        with closing(sqlite3.connect(state / 'activity.db')) as connection:
            row = connection.execute('SELECT status,input_tokens,output_tokens,content_hash FROM command_attempts').fetchone()
            self.assertEqual(row[0], 'compressed')
            self.assertGreater(row[1], row[2])
            self.assertEqual(connection.execute('SELECT count(*) FROM events').fetchone()[0], 1)
        # Verify that the cache contains the exact original bytes, not the
        # transport's optional .NET UTF-8 preamble or its base64 envelope.
        with closing(sqlite3.connect(state / 'originals.db')) as connection:
            cached = json.loads(connection.execute('SELECT entry_json FROM ccr_entries WHERE hash=?', (row[3],)).fetchone()[0])
        self.assertEqual(cached['original_content'].encode(), self.original)
