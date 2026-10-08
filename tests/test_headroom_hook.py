"""Exercise the real PowerShell parser/hook and the native argv boundary."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
PS = Path(os.environ.get("WINDIR", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
CSC = Path(os.environ.get("WINDIR", "C:/Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
FIXTURE = r'''
using System;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;
class Fixture {
    static int Main(string[] args) {
        Console.InputEncoding = new UTF8Encoding(false);
        Console.OutputEncoding = new UTF8Encoding(false);
        string countPath = Environment.GetEnvironmentVariable("HEADROOM_FIXTURE_COUNT");
        if (!String.IsNullOrEmpty(countPath)) File.AppendAllText(countPath, "dispatch\n");
        Console.Write(new JavaScriptSerializer().Serialize(new {
            args=args, input=Console.In.ReadToEnd(), cwd=Environment.CurrentDirectory
        }));
        Console.Error.Write("fixture stderr\n");
        return 37;
    }
}
'''


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def explicit(bundle, command):
    name, _, arguments = command.partition(" ")
    return "& " + ps_literal(bundle / (name + ".exe")) + " " + arguments


@unittest.skipUnless(os.name == "nt", "Windows PowerShell hook")
class HeadroomHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="Headroom hook fixture ")
        cls.bundle = Path(cls.temp.name).resolve()
        (cls.bundle / "bin").mkdir()
        subprocess.run([str(CSC), '/nologo', '/target:exe',
                        '/out:' + str(cls.bundle / 'bin/headroom-run.exe'),
                        str(ROOT / 'native/HeadroomLauncher.cs')], check=True, capture_output=True)
        (cls.bundle / "headroom/.venv/Scripts").mkdir(parents=True)
        source = cls.bundle / "Fixture.cs"
        source.write_text(FIXTURE, encoding="utf-8-sig")
        cls.fixture = cls.bundle / "git.exe"
        subprocess.run([str(CSC), "/nologo", "/reference:System.Web.Extensions.dll",
                        "/out:" + str(cls.fixture), str(source)], check=True, capture_output=True)
        for name in ("rg", "pytest", "cargo", "dotnet", "python", "uv", "rtk", "node", "unknown"):
            shutil.copy2(cls.fixture, cls.bundle / (name + ".exe"))
        shutil.copy2(cls.fixture, cls.bundle / "headroom/.venv/Scripts/python.exe")
        (cls.bundle / "headroom_run.py").write_text("# Fixture entry point; fake python records argv.\n")
        (cls.bundle / "npm.cmd").write_text("@echo unexpected\n")

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_hook(self, command=None, event=None, raw=None, bundle=None):
        hook = ROOT / "Headroom-PreToolUse.ps1"
        self.assertTrue(hook.is_file(), "PreToolUse hook has not been implemented")
        if raw is None:
            raw = json.dumps(event if event is not None else {
                "hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(self.bundle),
                "tool_input": {"command": command, "timeout_ms": 2500, "description": "Keep me"},
            })
        environment = dict(os.environ, PATH=str(self.bundle) + os.pathsep + os.environ["PATH"])
        started = time.perf_counter()
        result = subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                 "-File", str(hook), "-BundleRoot", str(bundle or self.bundle)],
                                input=raw.encode(), capture_output=True, env=environment, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual(result.stderr, b"")
        return json.loads(result.stdout.decode("utf-8-sig")), time.perf_counter() - started

    def test_disabled_or_invalid_preferences_never_rewrite(self):
        path = self.bundle / 'settings/components.json'
        path.parent.mkdir(exist_ok=True)
        try:
            for data in ['{"schema_version":1,"components":{"headroom_local":false}}',
                         '{broken', '{"schema_version":true,"components":{}}']:
                path.write_text(data)
                value, _ = self.run_hook(explicit(self.bundle, 'git status --short'))
                self.assertEqual(value, {})
            path.write_text('{"schema_version":1,"components":{"rtk":false,"headroom_local":true}}')
            value, _ = self.run_hook(explicit(self.bundle, 'git status --short'))
            self.assertIn('hookSpecificOutput', value)
        finally:
            path.unlink(missing_ok=True)

    def test_rewrites_safe_resolved_external_and_preserves_other_input(self):
        value, elapsed = self.run_hook(explicit(self.bundle, "git status --short"))
        specific = value["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "PreToolUse")

        self.assertEqual(specific["permissionDecision"], "allow")
        updated = specific["updatedInput"]
        self.assertEqual(updated["command"], "& " + ps_literal(self.bundle / "bin/headroom-run.exe") +
                         " --cts-automatic -- " + ps_literal(self.fixture) + " status --short")
        self.assertEqual(updated["timeout_ms"], 2500)
        self.assertEqual(updated["description"], "Keep me")
        self.assertLess(elapsed, 5)

    def test_retired_preference_keys_do_not_disable_retained_hook(self):
        path = self.bundle / 'settings/components.json'
        path.parent.mkdir(exist_ok=True)
        try:
            for retired in (False, True):
                path.write_text(json.dumps({'schema_version': 1, 'components': {
                    'rtk': False, 'headroom_local': True,
                    'local_summaries': retired, 'llama_cpp': retired}}))
                value, _ = self.run_hook(explicit(self.bundle, 'git status --short'))
                self.assertIn('hookSpecificOutput', value)
            path.write_text('{"schema_version":1,"components":{"local_summaries":"true"}}')
            self.assertEqual(self.run_hook(explicit(self.bundle, 'git status --short'))[0], {})
        finally:
            path.unlink(missing_ok=True)

    def test_preferences_directory_is_invalid_not_missing(self):
        path = self.bundle / 'settings/components.json'
        path.mkdir(parents=True)
        try:
            value, _ = self.run_hook(explicit(self.bundle, 'git status --short'))
            self.assertEqual(value, {})
        finally:
            path.rmdir()

    def test_non_utf8_preferences_are_invalid_like_dashboard(self):
        path = self.bundle / 'settings/components.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text('{"schema_version":1,"components":{"headroom_local":true}}', encoding='utf-16')
        try:
            value, _ = self.run_hook(explicit(self.bundle, 'git status --short'))
            self.assertEqual(value, {})
        finally:
            path.unlink()

    def test_accepts_bounded_build_test_search_commands(self):
        for command in ("rg --line-number 'a|b' .", "pytest tests", "cargo test --locked",
                        "dotnet build", "python -m pytest tests", "uv run pytest -q",
                        "rtk git status", "rtk rg 'value' .", "git log -5 --oneline"):
            with self.subTest(command=command):
                self.assertIn("hookSpecificOutput", self.run_hook(explicit(self.bundle, command))[0])

    def test_rewrites_top_level_batch_preserving_unrelated_source_and_metadata(self):
        first = explicit(self.bundle, "git status --short")
        second = explicit(self.bundle, "rg 'a|b' .")
        source = "$heading = 'Thai: ภาษาไทย; icon: 😀'\r\n# Keep this comment and spacing.\r\n  " + first
        source += "  ; Write-Output $heading\r\n\t" + second + " # trailing comment\r\n"
        value, _ = self.run_hook(source)
        self.assertIn("hookSpecificOutput", value)
        updated = value["hookSpecificOutput"]["updatedInput"]
        expected = source
        for command in (first, second):
            single = self.run_hook(command)[0]["hookSpecificOutput"]["updatedInput"]["command"]
            expected = expected.replace(command, single)
        self.assertEqual(updated["command"], expected)
        self.assertEqual(updated["timeout_ms"], 2500)
        self.assertEqual(updated["description"], "Keep me")

    def test_batch_does_not_rewrite_consumed_nested_dynamic_or_machine_output(self):
        candidate = explicit(self.bundle, "git status")
        excluded = [
            "$capture = " + candidate,
            "$env:HEADROOM_EXACT = '1'",
            candidate + " | Out-String",
            candidate + " > result.txt",
            candidate + " 2>&1",
            "if ($true) { " + candidate + " }",
            "& { " + candidate + " }",
            "Write-Output $(" + candidate + ")",
            explicit(self.bundle, "git status $selection"),
            explicit(self.bundle, "rg --json value ."),
            explicit(self.bundle, "git diff"),
        ]
        standalone = self.run_hook(candidate)[0]["hookSpecificOutput"]["updatedInput"]["command"]
        for other in excluded:
            with self.subTest(other=other):
                # An unrelated eligible sibling may be rewritten; never descend
                # into an assignment, pipeline, subexpression, or control flow.
                source = other + "\r\n" + candidate + "; $savedExit = $LASTEXITCODE"
                value = self.run_hook(source)[0]
                self.assertIn("hookSpecificOutput", value)
                self.assertEqual(value["hookSpecificOutput"]["updatedInput"]["command"],
                                 other + "\r\n" + standalone + "; $savedExit = $LASTEXITCODE")
                self.assertEqual(self.run_hook(other)[0], {})

    def test_exact_opt_out_anywhere_disables_entire_batch(self):
        candidate = explicit(self.bundle, "git status")
        for marker in ("# headroom: exact", "<# headroom: exact #>"):
            self.assertEqual(self.run_hook(candidate + "\r\n" + marker + "\r\n" + candidate)[0], {})

    def test_batch_traps_and_background_invocations_are_untouched(self):
        candidate = explicit(self.bundle, "git status")
        for source in ("trap { continue }; " + candidate,
                       candidate + " &\r\n" + candidate,
                       "function Invoke-Sample { " + candidate + " }"):
            with self.subTest(source=source):
                self.assertEqual(self.run_hook(source)[0], {})

    def test_batch_preserves_once_only_dispatch_streams_and_native_status(self):
        candidate = explicit(self.bundle, "git status 'space value' 'a|b' ''")
        source = candidate + "; $nativeOkay = $?; $nativeExit = $LASTEXITCODE; "
        source += "Write-Output ('STATUS:' + $nativeOkay + ':' + $nativeExit); exit $nativeExit"
        value = self.run_hook(source)[0]
        self.assertIn("hookSpecificOutput", value)
        rewritten = value["hookSpecificOutput"]["updatedInput"]["command"]
        # An absent optional runtime makes the native launcher dispatch the
        # original child directly. No fixture compression or production records.
        runtime = self.bundle / "headroom/.venv/Scripts/python.exe"
        saved_runtime = runtime.read_bytes()
        runtime.unlink()
        try:
            results = []
            for label, command in (("original", source), ("wrapped", rewritten)):
                count = self.bundle / (label + "-dispatch.txt")
                count.write_bytes(b"")
                result = subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-Command", command],
                                        input=b"same stdin", capture_output=True, cwd=self.bundle, timeout=10,
                                        env=dict(os.environ, HEADROOM_FIXTURE_COUNT=str(count)))
                self.assertEqual(count.read_text().splitlines(), ["dispatch"])
                self.assertEqual(result.returncode, 37)
                self.assertIn(b"STATUS:False:37", result.stdout)
                results.append(result)
            self.assertEqual(results[0].stdout, results[1].stdout)
            self.assertEqual(results[0].stderr, results[1].stderr)
        finally:
            runtime.write_bytes(saved_runtime)

    def test_declines_scripts_pipelines_interpolation_exact_reads_and_interactive_modes(self):
        cases = [
            "git status; git log", "git status | Out-String", "git status > out.txt",
            "git status 2>&1", "$x = git status", "& { git status }", "git status && git log",
            "git status\ngit log", "Get-Content file.txt", "gci .", "cmd /c git status",
            "powershell -Command 'git status'", "& $env:MY_GIT status", "git status $x",
            'rg "value=$env:TEMP" .', "rg $(Get-Content key.txt) .", "rg @args",
            "rg (Get-Location)", "rg @('a', 'b') .", "git diff", "git show HEAD",
            "git log -p", "git log --patch", "git status # headroom: exact",
            "python", "python -c 'print(1)'", "python -m pytest --pdb", "node script.js",
            "npm.cmd test", "unknown.exe args", "rtk git diff", "rtk read file.txt",
            "rtk proxy git status", "git --paginate log", "git branch -D example",
            "rg --pcre2 - .", "cargo run", "dotnet run", ". 'git.exe' status",
            "git status --% $(Write-Output injected)", "git 'status", "git status;",
        ]
        for command in cases:
            with self.subTest(command=command):
                self.assertEqual(self.run_hook(command)[0], {})
        for command in ("git diff", "git show HEAD", "git log -p", "git log --patch",
                        "python -c 'print(1)'", "python -m pytest --pdb", "node script.js",
                        "rtk git diff", "rtk read file.txt", "rtk proxy git status", "git branch -D example",
                        "cargo run", "dotnet run", "rg --pcre2 - .", "git status $x",
                        'rg "value=$env:TEMP" .', "rg $(Get-Content key.txt) .", "rg @args",
                        "rg (Get-Location)", "rg @('a', 'b') .",
                        "git status | Out-String", "git status > out.txt", "git status 2>&1",
                        "git status # headroom: exact", "git status --% $x"):
            with self.subTest(explicit=command):
                self.assertEqual(self.run_hook(explicit(self.bundle, command))[0], {})

    def test_declines_alias_and_function_shadowing_without_running_them(self):
        # Native Windows `where` is shadowed by a PowerShell alias; unknown names are also declined.
        self.assertEqual(self.run_hook("where.exe git")[0], {})
        self.assertEqual(self.run_hook("where git")[0], {})

    def test_declines_all_git_log_patch_modes(self):
        for flag in ("--patch-with-stat", "--patch-with-raw", "--cc", "-c", "-L1,10:file.txt"):
            with self.subTest(flag=flag):
                self.assertEqual(self.run_hook(explicit(self.bundle, "git log " + flag))[0], {})

    def test_declines_machine_or_exact_output_modes(self):
        commands = ["git status --porcelain", "git status --porcelain=v1", "git status -z",
                    "git log --pretty=oneline", "git log --format=%H", "rtk git status --porcelain",
                    "cargo build --message-format=json", "cargo test --message-format json",
                    "rtk cargo test --message-format=json"]
        commands += ["rg " + flag + " value ." for flag in (
            "--json", "--files", "--count", "--count-matches", "-c", "-l", "--files-with-matches",
            "--files-without-match", "--null", "--null-data", "--vimgrep", "--replace=x", "-r", "-o",
            "--only-matching", "--help", "--version")]
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(self.run_hook(explicit(self.bundle, command))[0], {})

    def test_malformed_irrelevant_events_and_missing_runtime_fail_open(self):
        for raw in ("", "not json", "[]", "null", "{}", '{"tool_input":5}'):
            with self.subTest(raw=raw):
                self.assertEqual(self.run_hook(raw=raw)[0], {})
        for event in ({"tool_name": "Read", "tool_input": {"command": "git status"}},
                      {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "git status"}}):
            self.assertEqual(self.run_hook(event=event)[0], {})
        with tempfile.TemporaryDirectory() as missing:
            self.assertEqual(self.run_hook("git status", bundle=Path(missing))[0], {})

    def test_quoted_injection_strings_remain_arguments_under_real_powershell(self):
        arguments = "'a|b' 'x;exit 99' '$(Write-Output surprise)' '>redirect.txt' 'a&b' 'two words' 'quote\"inside' '' ."
        command = explicit(self.bundle, "rg " + arguments)
        rewritten = self.run_hook(command)[0]["hookSpecificOutput"]["updatedInput"]["command"]
        result = subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-Command",
                                 rewritten + "; exit $LASTEXITCODE"], input=b"test stdin", capture_output=True,
                                cwd=self.bundle, timeout=10)
        self.assertEqual(result.returncode, 37, result.stderr.decode(errors="replace"))
        actual = json.loads(result.stdout)
        original = subprocess.run([str(PS), "-NoProfile", "-NonInteractive", "-Command",
                                   command + "; exit $LASTEXITCODE"],
                                  input=b"test stdin", capture_output=True, cwd=self.bundle, timeout=10)
        baseline = json.loads(original.stdout)
        self.assertEqual(actual["args"][4:], baseline["args"])
        self.assertEqual(actual["input"], baseline["input"])
        self.assertEqual(actual["cwd"], baseline["cwd"])
        self.assertEqual(result.stderr, original.stderr)
        self.assertFalse((self.bundle / "redirect.txt").exists())

    def test_native_wrapper_preserves_argv_streams_and_exit_without_shell(self):
        self.run_hook("git status")  # Copies the installed native wrapper to the fixture bundle.
        args = ["--", str(self.fixture), "space value", "", 'quote"inside', "trailing space\\",
                "|", "&", ">out", "$(echo unsafe)", "line one\nline two", "ภาษาไทย"]
        result = subprocess.run([str(self.bundle / "bin/headroom-run.exe"), *args],
                                input=b"input bytes\n", capture_output=True, cwd=self.bundle, timeout=10)
        self.assertEqual(result.returncode, 37, result.stderr.decode(errors="replace"))
        value = json.loads(result.stdout)
        self.assertEqual(value["args"], [str(self.bundle / "headroom_run.py"), *args])
        self.assertEqual(value["input"], "input bytes\n")
        self.assertEqual(value["cwd"], str(self.bundle))
        self.assertEqual(result.stderr, b"fixture stderr\n")

    def test_native_wrapper_falls_back_once_when_runtime_disappears(self):
        self.run_hook(explicit(self.bundle, "git status"))
        for relative in ("headroom/.venv/Scripts/python.exe", "headroom_run.py"):
            with self.subTest(missing=relative):
                path = self.bundle / relative
                backup = path.with_suffix(path.suffix + ".test-backup")
                path.rename(backup)
                try:
                    argv = ["space value", "", 'quote"inside', "|", "$(unsafe)", "ภาษาไทย"]
                    result = subprocess.run([str(self.bundle / "bin/headroom-run.exe"), "--cts-automatic", "--exact", "--",
                                             str(self.fixture), *argv], input=b"unchanged stdin",
                                            capture_output=True, cwd=self.bundle, timeout=10)
                    self.assertEqual(result.returncode, 37, result.stderr.decode(errors="replace"))
                    value = json.loads(result.stdout)
                    self.assertEqual(value["args"], argv)
                    self.assertEqual(value["input"], "unchanged stdin")
                    self.assertEqual(result.stderr, b"fixture stderr\n")
                finally:
                    backup.rename(path)

    def test_native_wrapper_falls_back_if_existing_runtime_cannot_start(self):
        self.run_hook(explicit(self.bundle, "git status"))
        runtime = self.bundle / "headroom/.venv/Scripts/python.exe"
        original = runtime.read_bytes()
        runtime.write_bytes(b"broken executable fixture")
        try:
            args = ["space value", "", 'quote"inside', "|", "$(unsafe)"]
            result = subprocess.run([str(self.bundle / "bin/headroom-run.exe"), "--cts-automatic", "--", str(self.fixture), *args],
                                    input=b"unchanged stdin", capture_output=True, cwd=self.bundle, timeout=10)
            self.assertEqual(result.returncode, 37, result.stderr.decode(errors="replace"))
            value = json.loads(result.stdout)
            self.assertEqual(value["args"], args)
            self.assertEqual(value["input"], "unchanged stdin")
            self.assertEqual(result.stderr, b"fixture stderr\n")
        finally:
            runtime.write_bytes(original)

    def test_automatic_fallback_to_rtk_remains_internal(self):
        nested = self.bundle / 'nested-rtk'
        (nested / 'bin').mkdir(parents=True)
        (nested / 'tools').mkdir()
        launcher = nested / 'bin/rtk.exe'
        subprocess.run([str(CSC), '/nologo', '/reference:System.Web.Extensions.dll',
                        '/out:' + str(launcher), str(ROOT / 'native/RtkLauncher.cs')],
                       check=True, capture_output=True)
        shutil.copy2(self.fixture, nested / 'tools/rtk.exe')
        runtime = self.bundle / 'headroom/.venv/Scripts/python.exe'
        original = runtime.read_bytes()
        runtime.unlink()
        try:
            environment = {k: v for k, v in os.environ.items()
                           if not k.startswith(('CODEX_', 'HEADROOM_', 'CTS_LAYA_'))}
            result = subprocess.run([str(self.bundle / 'bin/headroom-run.exe'), '--cts-automatic',
                                     '--', str(launcher), 'git', 'status'],
                                    input=b'original stdin', capture_output=True, env=environment, timeout=10)
            self.assertEqual(result.returncode, 37, result.stderr)
            self.assertEqual(json.loads(result.stdout)['args'], ['git', 'status'])
        finally:
            runtime.write_bytes(original)

    def test_diagnostics_do_not_store_command_arguments_or_file_paths(self):
        self.run_hook(explicit(self.bundle, "rg 'private-sentinel-string' ."))
        diagnostics = (self.bundle / "headroom/desktop-state/hook-events.jsonl").read_text(encoding="utf-8-sig")
        self.assertNotIn("private-sentinel-string", diagnostics)
        self.assertNotIn(str(self.bundle), diagnostics)
        records = [json.loads(line) for line in diagnostics.splitlines()]
        self.assertTrue(any(record["outcome"] == "rewritten" for record in records))
        self.assertTrue(all(set(record) <= {"timestamp", "outcome", "reason", "task_id"} for record in records))
        self.assertEqual(set(records[-1]), {"timestamp", "outcome", "reason"})

    def test_diagnostics_include_only_canonical_uuid_session_ids(self):
        task_id = '01a0e142-bea9-7e43-a984-77da94ac1faa'
        for command in (explicit(self.bundle, "git status"), "Get-Content private-sentinel.txt"):
            with self.subTest(command=command):
                self.run_hook(event={
                    'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',
                    'cwd': str(self.bundle), 'session_id': task_id.upper(),
                    'tool_input': {'command': command},
                })
                record = json.loads((self.bundle / 'headroom/desktop-state/hook-events.jsonl')
                                    .read_text(encoding='utf-8-sig').splitlines()[-1])
                self.assertEqual(record.get('task_id'), task_id)
                self.assertEqual(set(record), {'timestamp', 'outcome', 'reason', 'task_id'})

    def test_diagnostics_omit_unknown_or_non_uuid_session_ids(self):
        task_id = '01a0e142-bea9-7e43-a984-77da94ac1faa'
        for session_id in (None, '', 123, [], {}, [task_id], task_id + '\n',
                           '{' + task_id + '}', task_id.replace('-', ''),
                           'private-sentinel ' + task_id, str(self.bundle)):
            with self.subTest(session_id=session_id):
                self.run_hook(event={
                    'tool_name': 'Bash', 'session_id': session_id,
                    'tool_input': {'command': 'Get-Content private-sentinel.txt'},
                })
                record = json.loads((self.bundle / 'headroom/desktop-state/hook-events.jsonl')
                                    .read_text(encoding='utf-8-sig').splitlines()[-1])
                self.assertEqual(set(record), {'timestamp', 'outcome', 'reason'})


if __name__ == "__main__":
    unittest.main()
