"""An inline PowerShell exact-output preference survives automatic wrapping."""
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
PS = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
CSC = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
FIXTURE = r'''
using System; using System.IO; using System.Text; using System.Web.Script.Serialization;
class Fixture {
 static int Main(string[] args) {
  string root=Environment.GetEnvironmentVariable("EXACT_FIXTURE_ROOT");
  File.AppendAllText(Path.Combine(root,"runs.txt"),"run\n");
  File.WriteAllText(Path.Combine(root,"argv.json"),new JavaScriptSerializer().Serialize(args));
  using(var input=File.Create(Path.Combine(root,"stdin.bin"))) Console.OpenStandardInput().CopyTo(input);
  byte[] output=File.ReadAllBytes(Path.Combine(root,"stdout.bin"));
  Console.OpenStandardOutput().Write(output,0,output.Length);
  Console.Error.Write("unchanged stderr\n");
  return Int32.Parse(Environment.GetEnvironmentVariable("EXACT_FIXTURE_EXIT") ?? "0");
 }
}
'''


def literal(path):
    return "'" + str(path).replace("'", "''") + "'"


@unittest.skipUnless(os.name == 'nt', 'Windows native Headroom wrapper')
class HeadroomExactEnvironmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory(prefix='headroom-exact-compile ')
        cls.fixture = Path(cls.build.name) / 'pytest.exe'
        source = cls.fixture.with_suffix('.cs')
        source.write_text(FIXTURE, encoding='utf-8-sig')
        subprocess.run([str(CSC), '/nologo', '/reference:System.Web.Extensions.dll',
                        '/out:' + str(cls.fixture), str(source)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='Headroom exact environment ')
        self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name)
        for name in ('bin', 'headroom/.venv/Scripts'):
            (self.bundle / name).mkdir(parents=True)
        shutil.copy2(ROOT / 'bin/headroom-run.exe', self.bundle / 'bin/headroom-run.exe')
        shutil.copy2(ROOT / 'headroom_run.py', self.bundle / 'headroom_run.py')
        shutil.copy2(ROOT / 'headroom/.venv/Scripts/python.exe', self.bundle / 'headroom/.venv/Scripts/python.exe')
        shutil.copy2(ROOT / 'headroom/.venv/pyvenv.cfg', self.bundle / 'headroom/.venv/pyvenv.cfg')
        shutil.copy2(self.fixture, self.bundle / 'pytest.exe')
        self.original = (json.dumps([{'id': i, 'status': 'CRITICAL_73' if i == 73 else 'healthy',
                                     'detail': 'Routine status repeated. ' * 5} for i in range(100)],
                                   indent=2).replace('\n', '\r\n') + '\r\n').encode()
        (self.bundle / 'stdout.bin').write_bytes(self.original)
        # Any accidental SDK use is both detected and prevented. Neither this
        # fixture nor its command can create production savings or fetch models.
        (self.bundle / 'sitecustomize.py').write_text(
            "import os, sys\nfrom pathlib import Path\n"
            "class NoSdk:\n"
            " def find_spec(self, fullname, path=None, target=None):\n"
            "  if fullname == 'headroom':\n"
            "   Path(os.environ['EXACT_FIXTURE_ROOT'], 'sdk-attempt.txt').write_text('attempted')\n"
            "   raise ImportError('SDK deliberately blocked in exact-mode fixture')\n"
            "sys.meta_path.insert(0, NoSdk())\n", encoding='utf-8')
        self.state = self.bundle / 'isolated-state'
        self.environment = dict(os.environ, EXACT_FIXTURE_ROOT=str(self.bundle),
                                HEADROOM_WORKSPACE_DIR=str(self.state),
                                PYTHONPATH=os.pathsep.join([str(self.bundle), str(ROOT),
                                                           str(ROOT / 'headroom/.venv/Lib/site-packages')]))
        self.environment.pop('HEADROOM_EXACT', None)

    def run_case(self, explicit_flag=False, exit_code=0):
        script = (
            '[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); '
            "$env:HEADROOM_EXACT = '1'; & " + literal(self.bundle / 'bin/headroom-run.exe') +
            (' --exact' if explicit_flag else '') + ' -- ' + literal(self.bundle / 'pytest.exe') +
            " '-q' 'literal|argument'; exit $LASTEXITCODE"
        )
        result = subprocess.run([str(PS), '-NoProfile', '-NonInteractive', '-Command', script],
                                input=b'exact stdin\r\n', capture_output=True, cwd=self.bundle,
                                env=dict(self.environment, EXACT_FIXTURE_EXIT=str(exit_code)), timeout=15)
        self.assertEqual(result.returncode, exit_code, result.stderr)
        self.assertEqual(result.stdout, self.original)
        self.assertEqual(result.stderr.count(b'unchanged stderr'), 1)
        self.assertIn(b'CRITICAL_73', result.stdout)
        self.assertEqual((self.bundle / 'runs.txt').read_text().splitlines(), ['run'])
        self.assertEqual(json.loads((self.bundle / 'argv.json').read_text(encoding='utf-8-sig')),
                         ['-q', 'literal|argument'])
        self.assertEqual((self.bundle / 'stdin.bin').read_bytes(), b'exact stdin\r\n')
        self.assertFalse((self.bundle / 'sdk-attempt.txt').exists(), 'Exact request entered the SDK')
        self.assertFalse((self.state / 'originals.db').exists())
        with closing(sqlite3.connect(self.state / 'activity.db')) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM events').fetchone()[0], 0)
            row = connection.execute('SELECT status,input_tokens,output_tokens,return_code FROM command_attempts').fetchone()
            self.assertEqual(row, ('exact_requested', None, None, exit_code))

    def test_inline_environment_exact_preserves_native_command_output(self):
        self.run_case()

    def test_environment_and_explicit_flag_preserve_argv_and_failure_exit(self):
        self.run_case(explicit_flag=True, exit_code=37)
