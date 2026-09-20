"""Exercise CLI argument forwarding against a fake Python executable only."""
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
using System.Web.Script.Serialization;
class Fixture {
    static int Main(string[] args) {
        Console.InputEncoding = new UTF8Encoding(false);
        Console.OutputEncoding = new UTF8Encoding(false);
        Console.Out.Write(new JavaScriptSerializer().Serialize(new {
            args = args, input = Console.In.ReadToEnd(), cwd = Environment.CurrentDirectory
        }));
        Console.Error.Write("fixture stderr ภาษาไทย\n");
        return Array.IndexOf(args, "--fixture-nonzero") >= 0 ? 37 : 0;
    }
}
'''


@unittest.skipUnless(os.name == "nt", "Windows native launchers")
class NativeCodexLauncherTests(unittest.TestCase):
    def setUp(self):
        for name in ("codex-saver", "codex-headroom"):
            self.assertTrue((ROOT / "bin" / (name + ".exe")).is_file(), name + " has not been built")
        self.temp = tempfile.TemporaryDirectory(prefix="Codex launcher ภาษาไทย ")
        self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name).resolve()
        (self.bundle / "bin").mkdir()
        for name in ("codex-saver", "codex-headroom"):
            shutil.copy2(ROOT / "bin" / (name + ".exe"), self.bundle / "bin" / (name + ".exe"))
        self.python = self.bundle / "dashboard/.venv/Scripts/python.exe"
        self.python.parent.mkdir(parents=True)
        self.script = self.bundle / "launch_codex.py"
        self.script.write_text("# Not executed: fake Python captures arguments.\n", encoding="utf-8")
        source = self.bundle / "Fixture.cs"
        source.write_text(FIXTURE_SOURCE, encoding="utf-8-sig")
        subprocess.run([str(CSC), "/nologo", "/target:exe", "/reference:System.Web.Extensions.dll",
                        "/out:" + str(self.python), str(source)], check=True, capture_output=True)

    def run_launcher(self, name, args):
        return subprocess.run([str(self.bundle / "bin" / (name + ".exe")), *args],
                              input="stdin ภาษาไทย\n".encode(), cwd=self.bundle,
                              capture_output=True, timeout=15)

    def test_both_launchers_preserve_literal_arguments_streams_cwd_and_nonzero_exit(self):
        arguments = ["--fixture-nonzero", "mcp|Codex|desktop", "& exit 99", ">redirect.txt", "<input.txt",
                     "$(test)", "space value", "", 'quote"inside', "trailing slash \\",
                     'slashes\\\\before"quote', "ภาษาไทย", "one\ntwo"]
        for name in ("codex-saver", "codex-headroom"):
            with self.subTest(name=name):
                result = self.run_launcher(name, arguments)
                self.assertEqual(result.returncode, 37, result.stderr)
                data = json.loads(result.stdout.decode("utf-8-sig"))
                prefix = [str(self.script)]
                if name == "codex-headroom":
                    prefix.append("--experimental-headroom")
                self.assertEqual(data["args"], prefix + ["--"] + arguments)
                self.assertEqual(data["input"], "stdin ภาษาไทย\n")
                self.assertEqual(Path(data["cwd"]), self.bundle)
                self.assertEqual(result.stderr.decode("utf-8"), "fixture stderr ภาษาไทย\n")
                self.assertFalse((self.bundle / "redirect.txt").exists())

    def test_both_launchers_preserve_success_exit(self):
        for name in ("codex-saver", "codex-headroom"):
            with self.subTest(name=name):
                self.assertEqual(self.run_launcher(name, []).returncode, 0)

    def test_missing_python_is_a_clear_local_error(self):
        self.python.unlink()
        result = self.run_launcher("codex-saver", [])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"Python runtime is missing", result.stderr)

    def test_missing_script_is_a_clear_local_error(self):
        self.script.unlink()
        result = self.run_launcher("codex-headroom", [])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"CLI launcher script is missing", result.stderr)


if __name__ == "__main__":
    unittest.main()
