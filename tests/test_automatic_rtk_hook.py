"""Automatic RTK routing at the real Windows hook and native argv boundaries."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_headroom_hook import CSC, FIXTURE, PS, ROOT


@unittest.skipUnless(os.name == 'nt', 'Windows command hook')
class AutomaticRtkHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='automatic RTK fixture ')
        cls.bundle = Path(cls.temp.name).resolve()
        for directory in ('bin', 'tools', 'settings', 'native'):
            (cls.bundle / directory).mkdir()
        source = cls.bundle / 'Fixture.cs'
        source.write_text(FIXTURE, encoding='utf-8-sig')
        subprocess.run([str(CSC), '/nologo', '/reference:System.Web.Extensions.dll',
                        '/out:' + str(cls.bundle / 'native/git.exe'), str(source)],
                       check=True, capture_output=True)
        shutil.copy2(cls.bundle / 'native/git.exe', cls.bundle / 'native/rg.exe')
        shutil.copy2(cls.bundle / 'native/git.exe', cls.bundle / 'tools/rtk.exe')
        shutil.copy2(ROOT / 'bin/rtk.exe', cls.bundle / 'bin/rtk.exe')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('CODEX_', 'HEADROOM_'))}
        self.env['PATH'] = os.pathsep.join([str(self.bundle / 'bin'), str(self.bundle / 'native'), self.env['PATH']])
        self.preferences(rtk=True, headroom_local=False)

    def preferences(self, **components):
        (self.bundle / 'settings/components.json').write_text(json.dumps({
            'schema_version': 1, 'components': components}), encoding='utf-8')

    def hook(self, command, *, cwd=None, **env):
        event = {'hook_event_name': 'PreToolUse', 'tool_name': 'Bash',
                 'cwd': str(self.bundle) if cwd is None else cwd,
                 'tool_input': {'command': command}}
        completed = subprocess.run([str(PS), '-NoProfile', '-NonInteractive', '-File',
                                    str(ROOT / 'Headroom-PreToolUse.ps1'), '-BundleRoot', str(self.bundle)],
                                   input=json.dumps(event).encode(), capture_output=True,
                                   env=dict(self.env, **env), timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, b'')
        return json.loads(completed.stdout.decode('utf-8-sig'))

    def test_real_normalized_hook_input_routes_supported_display_commands(self):
        # Codex supplies Bash + command, without a shell field. The replacement
        # uses the same literal syntax under PowerShell and Windows Git Bash.
        for command in ('git status --short', 'git.exe diff --staged', 'git log -5 --oneline',
                        "rg --line-number 'a|b' .", 'rg.exe needle .'):
            with self.subTest(command=command):
                name, arguments = command.split(' ', 1)
                result = self.hook(command)['hookSpecificOutput']
                self.assertEqual(result['updatedInput']['command'],
                                 'rtk.exe ' + name.removesuffix('.exe') + ' ' + arguments)

    def test_component_toggles_are_independent_and_bad_preferences_skip(self):
        for headroom in (False, True):
            self.preferences(rtk=True, headroom_local=headroom)
            self.assertIn('hookSpecificOutput', self.hook('git status'))
            self.preferences(rtk=False, headroom_local=headroom)
            self.assertEqual(self.hook('git status'), {})
        (self.bundle / 'settings/components.json').write_text('{bad')
        self.assertEqual(self.hook('git status'), {})

    def test_scripts_chains_dynamic_exact_and_machine_commands_stay_native(self):
        for command in ("git status; git log", 'git status\ngit log', 'git status | Out-String',
                        'git status && git log', '$x = git status', 'git status > out.txt',
                        'git status 2>&1', "function git { 'shadow' }; git status", 'git status $x',
                        'git status --porcelain=v2', 'git log --format=%H', 'git diff --numstat',
                        'git diff --exit-code', 'git diff --quiet', 'git diff --no-index a b',
                        'git diff --output=out.txt', 'git diff --word-diff=porcelain',
                        'git diff --check', 'git diff --binary', 'git diff --patch-with-raw',
                        'git diff --check=fixture', 'git diff --binary=fixture', 'git diff --patch-with-raw=fixture',
                        'git --no-pager status', 'git show HEAD',
                        'git log -p', 'rg --json needle .', 'rg --files', 'rg --count needle .',
                        'rg --pre filter.exe needle .', 'rg --ultra-compact needle .',
                        "rg $pattern .", "git status # headroom: exact", "git status # rtk: exact",
                        "$env:HEADROOM_EXACT = '1'; git status"):
            with self.subTest(command=command):
                self.assertEqual(self.hook(command), {})
        self.assertEqual(self.hook('git status', HEADROOM_EXACT='1'), {})

    def test_non_windows_cwd_and_missing_or_shadowed_launcher_skip(self):
        for cwd in ('/home/test', '', r'\\wsl.localhost\Ubuntu\home\test'):
            self.assertEqual(self.hook('git status', cwd=cwd), {})
        self.env['PATH'] = str(self.bundle / 'native') + os.pathsep + os.environ['PATH']
        self.assertEqual(self.hook('git status'), {})

    def test_rewrite_preserves_native_arguments_stdin_cwd_and_failure_once(self):
        source = "rg 'a|b' 'space value' 'x;exit 99' ."
        rewritten = self.hook(source)['hookSpecificOutput']['updatedInput']['command']
        count = self.bundle / 'dispatch.txt'
        count.write_bytes(b'')
        result = subprocess.run([str(PS), '-NoProfile', '-NonInteractive', '-Command',
                                 rewritten + '; exit $LASTEXITCODE'], input=b'input bytes',
                                capture_output=True, cwd=self.bundle,
                                env=dict(self.env, HEADROOM_FIXTURE_COUNT=str(count)), timeout=10)
        self.assertEqual(result.returncode, 37)
        self.assertEqual(count.read_text().splitlines(), ['dispatch'])
        value = json.loads(result.stdout)
        self.assertEqual(value['args'], ['rg', 'a|b', 'space value', 'x;exit 99', '.'])
        self.assertEqual(value['input'], 'input bytes')
        self.assertEqual(Path(value['cwd']), self.bundle)
        self.assertEqual(result.stderr, b'fixture stderr\n')

    @unittest.skipUnless(Path('C:/Program Files/Git/bin/bash.exe').is_file(), 'Windows Git Bash')
    def test_same_replacement_runs_in_windows_bash_without_powershell_syntax(self):
        rewritten = self.hook("rg 'a|b' 'space value' .")['hookSpecificOutput']['updatedInput']['command']
        result = subprocess.run(['C:/Program Files/Git/bin/bash.exe', '--noprofile', '--norc', '-c', rewritten],
                                input=b'input bytes', capture_output=True, cwd=self.bundle,
                                env=self.env, timeout=10)
        self.assertEqual(result.returncode, 37, result.stderr)
        self.assertEqual(json.loads(result.stdout)['args'], ['rg', 'a|b', 'space value', '.'])


if __name__ == '__main__':
    unittest.main()
