"""End-to-end tests of the native RTK launcher, using an isolated fake tool."""
import json
import os
from pathlib import Path
import shutil
import subprocess
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
    def setUp(self):
        self.assertTrue((ROOT / "bin/rtk.exe").is_file(), "native RTK launcher has not been built")
        self.temp = tempfile.TemporaryDirectory(prefix="RTK fixture ภาษาไทย ")
        self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name).resolve()
        (self.bundle / "bin").mkdir()
        (self.bundle / "tools").mkdir()
        (self.bundle / "data/rtk").mkdir(parents=True)
        self.launcher = self.bundle / "bin/rtk.exe"
        shutil.copy2(ROOT / "bin/rtk.exe", self.launcher)
        fixture = self.bundle / "Fixture.cs"
        fixture.write_text(FIXTURE_SOURCE, encoding="utf-8-sig")
        subprocess.run(
            [str(CSC), "/nologo", "/target:exe", "/reference:System.Web.Extensions.dll",
             "/out:" + str(self.bundle / "tools/rtk.exe"), str(fixture)],
            check=True, capture_output=True,
        )

    def run_launcher(self, args):
        environment = dict(os.environ, RTK_DB_PATH="old-database-must-not-leak.db")
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
            input=b"", capture_output=True, cwd=self.bundle, timeout=15,
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


if __name__ == "__main__":
    unittest.main()
