"""End-to-end tests of the native RTK launcher, using an isolated fake tool."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
FIXTURE_SOURCE = r'''
using System;
using System.Text;
using System.IO;
using System.Web.Script.Serialization;
class Fixture {
    static int Main(string[] args) {
        Console.InputEncoding = new UTF8Encoding(false);
        Console.OutputEncoding = new UTF8Encoding(false);
        if (AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\').EndsWith("Scripts")) {
            string root = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "../../.."));
            if (Array.IndexOf(args, "--record-rtk") >= 0) {
                File.AppendAllText(Path.Combine(root, "activity.jsonl"),
                    new JavaScriptSerializer().Serialize(new {
                        args=args, dispatched=File.ReadAllLines(Path.Combine(root, "dispatch.txt")).Length,
                        task=Environment.GetEnvironmentVariable("CODEX_THREAD_ID"),
                        kind=Environment.GetEnvironmentVariable("CTS_ACTIVITY_KIND")
                    }) + "\n");
                Console.Out.Write("recording chatter");
                Console.Error.Write("recording diagnostic");
                return 47; // Bookkeeping cannot change native output or exit status.
            }
            File.AppendAllText(Path.Combine(root, "authorize.jsonl"),
                new JavaScriptSerializer().Serialize(args) + "\n");
            if (Environment.GetEnvironmentVariable("CTS_LAYA_INTERNAL") == "1")
                File.WriteAllText(Path.Combine(root, "authorization-bypassed.txt"), "internal");
            Console.Out.Write(new string('x', 131072)); // Must never reach command stdout.
            return Int32.Parse(Environment.GetEnvironmentVariable("RTK_FIXTURE_AUTHORIZE_EXIT") ?? "0");
        }
        File.AppendAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "../dispatch.txt"), "run\n");
        var data = new {
            args = args,
            database = Environment.GetEnvironmentVariable("RTK_DB_PATH"),
            working_directory = Environment.CurrentDirectory,
            input = Console.In.ReadToEnd()
        };
        Console.Out.Write(new JavaScriptSerializer().Serialize(data));
        Console.Error.Write("fixture stderr: ภาษาไทย | & < >\n");
        return args.Length > 0 && args[0] == "exit-zero" ? 0 : 37;
    }
}
'''


@unittest.skipUnless(os.name == "nt", "Windows native launcher")
class NativeRtkLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiled = tempfile.TemporaryDirectory(prefix='RTK native compiler ')
        cls.native_launcher = Path(cls.compiled.name) / 'rtk.exe'
        subprocess.run([str(CSC), '/nologo', '/target:exe', '/reference:System.Web.Extensions.dll',
                        '/out:' + str(cls.native_launcher), str(ROOT / 'native/RtkLauncher.cs')],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.compiled.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="RTK fixture ภาษาไทย ")
        self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name).resolve()
        (self.bundle / "bin").mkdir()
        (self.bundle / "tools").mkdir()
        (self.bundle / "data/rtk").mkdir(parents=True)
        self.launcher = self.bundle / "bin/rtk.exe"
        shutil.copy2(self.native_launcher, self.launcher)
        fixture = self.bundle / "Fixture.cs"
        fixture.write_text(FIXTURE_SOURCE, encoding="utf-8-sig")
        subprocess.run(
            [str(CSC), "/nologo", "/target:exe", "/reference:System.Web.Extensions.dll",
             "/out:" + str(self.bundle / "tools/rtk.exe"), str(fixture)],
            check=True, capture_output=True,
        )
        runtime = self.bundle / 'headroom/.venv/Scripts/python.exe'
        runtime.parent.mkdir(parents=True)
        shutil.copy2(self.bundle / 'tools/rtk.exe', runtime)
        (self.bundle / 'laya_dispatch.py').write_text('# isolated authorization stub\n')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('CODEX_', 'HEADROOM_', 'CTS_LAYA_', 'RTK_FIXTURE_'))}
        self.env['RTK_DB_PATH'] = 'old-database-must-not-leak.db'

    def run_launcher(self, args, **env):
        environment = dict(self.env, **env)
        return subprocess.run(
            [str(self.launcher), *args], input="stdin ภาษาไทย\nline two\n".encode(),
            capture_output=True, cwd=self.bundle, env=environment, timeout=15,
        )

    def test_arguments_and_streams_are_literal_and_exit_code_is_preserved(self):
        args = [
            "rg", "mcp|Codex|desktop", "& exit 99", ">redirect.txt", "<input.txt",
            "semi;colon", "$(Write-Output surprise)", "space in value", "", 'quote"inside',
            "path with space\\", 'backslashes\\\\before"quote', "ภาษาไทย", "line one\nline two",
        ]
        result = self.run_launcher(args)
        self.assertEqual(result.returncode, 37, result.stderr.decode("utf-8"))
        data = json.loads(result.stdout.decode("utf-8-sig"))
        self.assertEqual(data["args"], args)
        self.assertEqual(data["input"], "stdin ภาษาไทย\nline two\n")
        self.assertEqual(Path(data["database"]), self.bundle / "data/rtk/history.db")
        self.assertEqual(Path(data["working_directory"]), self.bundle)
        self.assertEqual(result.stderr.decode("utf-8"), "fixture stderr: ภาษาไทย | & < >\n")
        self.assertFalse((self.bundle / "redirect.txt").exists())

    def test_success_exit_code_is_preserved(self):
        self.assertEqual(self.run_launcher(["exit-zero"]).returncode, 0)

    def test_powershell_does_not_interpret_regex_as_a_pipeline(self):
        executable_literal = "'" + str(self.launcher).replace("'", "''") + "'"
        script = (
            "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); "
            "& " + executable_literal + " 'rg' 'mcp|Codex|desktop' 'a&b' 'space value' 'ภาษาไทย'; "
            "exit $LASTEXITCODE"
        )
        powershell = Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
            input=b"", capture_output=True, cwd=self.bundle, env=self.env, timeout=15,
        )
        self.assertEqual(result.returncode, 37, result.stderr.decode("utf-8", errors="replace"))
        self.assertEqual(
            json.loads(result.stdout.decode("utf-8-sig"))["args"],
            ["rg", "mcp|Codex|desktop", "a&b", "space value", "ภาษาไทย"],
        )

    def test_missing_tool_reports_a_clear_error(self):
        (self.bundle / "tools/rtk.exe").unlink()
        result = self.run_launcher(["gain"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"RTK executable is missing", result.stderr)

    def write_preferences(self, value):
        path = self.bundle / 'settings/components.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(value, encoding='utf-8')

    def test_rtk_off_passes_supported_native_argv_to_unfiltered_proxy(self):
        self.write_preferences('{"schema_version":1,"components":{"rtk":false}}')
        args = ['rg', 'a|b', 'space path', 'ภาษาไทย']
        result = self.run_launcher(args)
        self.assertEqual(json.loads(result.stdout.decode('utf-8-sig'))['args'], ['proxy', *args])
        self.assertEqual(result.returncode, 37)
        self.assertIn('fixture stderr', result.stderr.decode())

    def test_retired_preferences_are_ignored_without_disabling_rtk(self):
        for retired in (False, True):
            with self.subTest(retired=retired):
                self.write_preferences(json.dumps({'schema_version': 1, 'components': {
                    'rtk': True, 'headroom_local': False,
                    'local_summaries': retired, 'llama_cpp': retired}}))
                result = self.run_launcher(['rg', 'value'])
                self.assertEqual(json.loads(result.stdout.decode('utf-8-sig'))['args'], ['rg', 'value'])
        self.write_preferences('{"schema_version":1,"components":{"llama_cpp":"true"}}')
        result = self.run_launcher(['rg', 'value'])
        self.assertEqual(json.loads(result.stdout.decode('utf-8-sig'))['args'], ['proxy', 'rg', 'value'])

    def test_rtk_off_rejects_rtk_only_verbs_and_preserves_diagnostics(self):
        self.write_preferences('{"schema_version":1,"components":{"rtk":false}}')
        result = self.run_launcher(['summary', 'example'])
        self.assertEqual(result.returncode, 64)
        self.assertEqual(result.stdout, b'')
        self.assertIn(b'RTK compression is off', result.stderr)
        result = self.run_launcher(['gain', '--all', '--format', 'json'])
        self.assertEqual(json.loads(result.stdout.decode('utf-8-sig'))['args'][0], 'gain')

    def test_corrupt_preferences_bypass_compression(self):
        self.write_preferences('{bad json')
        result = self.run_launcher(['git', 'status'])
        self.assertEqual(json.loads(result.stdout.decode('utf-8-sig'))['args'], ['proxy', 'git', 'status'])

    def test_new_cli_preferences_do_not_disable_rtk(self):
        self.write_preferences('{"schema_version":1,"components":{"rtk":true,"playwright_cli":true,"ast_grep":false,"laya_router":true}}')
        result = self.run_launcher(['git', 'status'])
        self.assertEqual(json.loads(result.stdout.decode('utf-8-sig'))['args'], ['git', 'status'])

    def test_invalid_preferences_path_does_not_restore_default_compression(self):
        (self.bundle / 'settings/components.json').mkdir(parents=True)
        result = self.run_launcher(['git', 'status'])
        self.assertEqual(json.loads(result.stdout.decode('utf-8-sig'))['args'], ['proxy', 'git', 'status'])

    def test_non_utf8_preferences_are_rejected_consistently_with_dashboard(self):
        path = self.bundle / 'settings/components.json'
        path.parent.mkdir()
        path.write_text('{"schema_version":1,"components":{"rtk":true}}', encoding='utf-16')
        result = self.run_launcher(['git', 'status'])
        self.assertEqual(json.loads(result.stdout.decode('utf-8-sig'))['args'], ['proxy', 'git', 'status'])

    def test_explicit_operation_authorizes_once_before_dispatch_without_stdout(self):
        result = self.run_launcher(['rg', 'private pattern', '--cts-automatic'])
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(json.loads(result.stdout)['args'], ['rg', 'private pattern', '--cts-automatic'])
        self.assertEqual((self.bundle / 'dispatch.txt').read_text(), 'run\n')
        self.assertTrue((self.bundle / 'authorize.jsonl').is_file(), 'explicit operation was not authorized')
        calls = [json.loads(line) for line in (self.bundle / 'authorize.jsonl').read_text(encoding='utf-8-sig').splitlines()]
        self.assertEqual(calls, [[str(self.bundle / 'laya_dispatch.py'), '--authorize', 'rtk', 'rg']])
        self.assertFalse((self.bundle / 'authorization-bypassed.txt').exists(),
                         'authorization itself must not receive an internal exemption')

    def test_denied_authorization_never_dispatches_or_prints_success_stdout(self):
        for args in (['git', 'status'], ['proxy', 'git', 'status'], ['summary', 'file.txt']):
            with self.subTest(args=args):
                result = self.run_launcher(args, RTK_FIXTURE_AUTHORIZE_EXIT='23')
                self.assertEqual(result.returncode, 23)
                self.assertEqual(result.stdout, b'')
                self.assertFalse((self.bundle / 'dispatch.txt').exists())

    def test_missing_or_broken_authorizer_blocks_explicit_operations(self):
        for relative in ('laya_dispatch.py', 'headroom/.venv/Scripts/python.exe'):
            path = self.bundle / relative
            original = path.read_bytes()
            try:
                path.unlink()
                result = self.run_launcher(['git', 'status'])
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b'')
                self.assertFalse((self.bundle / 'dispatch.txt').exists())
            finally:
                path.write_bytes(original)
        (self.bundle / 'headroom/.venv/Scripts/python.exe').write_bytes(b'broken executable')
        self.assertNotEqual(self.run_launcher(['git', 'status']).returncode, 0)
        self.assertFalse((self.bundle / 'dispatch.txt').exists())

    def test_real_python_dispatcher_blocks_explicit_rtk_with_laya_off(self):
        shutil.copy2(sys.executable, self.bundle / 'headroom/.venv/Scripts/python.exe')
        shutil.copy2(Path(sys.prefix) / 'pyvenv.cfg', self.bundle / 'headroom/.venv/pyvenv.cfg')
        shutil.copy2(ROOT / 'laya_dispatch.py', self.bundle / 'laya_dispatch.py')
        result = self.run_launcher(['git', 'status'], PYTHONPATH=os.pathsep.join([
            str(ROOT), str(Path(sys.prefix) / 'Lib/site-packages')]))
        self.assertEqual(result.returncode, 126, result.stderr)
        self.assertIn(b'Laya router is Off', result.stderr)
        self.assertEqual(result.stdout, b'')
        self.assertFalse((self.bundle / 'dispatch.txt').exists())

    def test_router_owned_operation_does_not_duplicate_completion(self):
        result = self.run_launcher(['git', 'status'], CTS_LAYA_INTERNAL='1')
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual((self.bundle / 'dispatch.txt').read_text(), 'run\n')
        self.assertFalse((self.bundle / 'activity.jsonl').exists())

    def test_headroom_child_still_records_its_rtk_completion(self):
        result = self.run_launcher(['git', 'status'], HEADROOM_COMMAND_ACTIVE='1')
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(len((self.bundle / 'activity.jsonl').read_text(encoding='utf-8-sig').splitlines()), 1)

    def test_automatic_and_internal_operations_bypass_gate_and_strip_only_initial_flag(self):
        cases = [(['--cts-automatic', 'rg', 'needle'], {}, ['rg', 'needle']),
                 (['git', 'status'], {'HEADROOM_COMMAND_ACTIVE': '1'}, ['git', 'status']),
                 (['rg', 'needle'], {'CTS_LAYA_INTERNAL': '1'}, ['rg', 'needle'])]
        for args, env, expected in cases:
            with self.subTest(args=args, env=env):
                result = self.run_launcher(args, RTK_FIXTURE_AUTHORIZE_EXIT='23', **env)
                self.assertEqual(result.returncode, 37, result.stderr)
                self.assertEqual(json.loads(result.stdout)['args'], expected)
                self.assertFalse((self.bundle / 'authorize.jsonl').exists())

    def test_information_and_off_passthrough_never_authorize(self):
        for args in ([], ['gain'], ['help'], ['--help'], ['-h'], ['--version'], ['-V'], ['recall', 'abc'], ['verify']):
            with self.subTest(args=args):
                result = self.run_launcher(args, RTK_FIXTURE_AUTHORIZE_EXIT='23')
                self.assertEqual(json.loads(result.stdout)['args'], args)
                self.assertFalse((self.bundle / 'authorize.jsonl').exists())
        self.write_preferences('{"schema_version":1,"components":{"rtk":false}}')
        for prefix in ([], ['--cts-automatic']):
            result = self.run_launcher([*prefix, 'rg', 'needle'], RTK_FIXTURE_AUTHORIZE_EXIT='23')
            self.assertEqual(json.loads(result.stdout)['args'], ['proxy', 'rg', 'needle'])
            self.assertFalse((self.bundle / 'authorize.jsonl').exists())

    def test_completion_is_recorded_once_after_dispatch_with_task_context(self):
        task = '01a0e142-bea9-7e43-a984-77da94ac1faa'
        for automatic, verb, expected_exit in ((False, 'rg', 37), (True, 'rg', 37), (False, 'exit-zero', 0)):
            with self.subTest(automatic=automatic, expected_exit=expected_exit):
                for filename in ('dispatch.txt', 'activity.jsonl'):
                    (self.bundle / filename).unlink(missing_ok=True)
                args = (['--cts-automatic'] if automatic else []) + [verb, 'private-sentinel']
                result = self.run_launcher(args, CODEX_THREAD_ID=task, CTS_ACTIVITY_KIND='diagnostic')
                self.assertEqual(result.returncode, expected_exit, result.stderr)
                self.assertEqual(json.loads(result.stdout)['args'], [verb, 'private-sentinel'])
                self.assertEqual(result.stderr.decode('utf-8'), 'fixture stderr: ภาษาไทย | & < >\n')
                activity = self.bundle / 'activity.jsonl'
                self.assertTrue(activity.is_file(), 'native completion was not recorded')
                records = [json.loads(line) for line in activity.read_text(encoding='utf-8-sig').splitlines()]
                self.assertEqual(records, [{
                    'args': [str(self.bundle / 'laya_dispatch.py'), '--record-rtk', str(expected_exit)],
                    'dispatched': 1, 'task': task, 'kind': 'diagnostic',
                }])
        (self.bundle / 'activity.jsonl').unlink(missing_ok=True)
        self.run_launcher(['git', 'status'], RTK_FIXTURE_AUTHORIZE_EXIT='23')
        self.assertFalse((self.bundle / 'activity.jsonl').exists())


if __name__ == "__main__":
    unittest.main()
