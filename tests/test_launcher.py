import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launch_codex


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        environment = patch.dict(os.environ, {'CODEX_HOME': self.home.name})
        environment.start()
        self.addCleanup(environment.stop)
        for name in ('OPENAI_BASE_URL', 'OPENAI_API_BASE', 'AZURE_OPENAI_ENDPOINT', 'CODEX_OSS_BASE_URL'):
            os.environ.pop(name, None)

    def write_config(self, content):
        (Path(self.home.name) / 'config.toml').write_text(content, encoding='utf-8')

    def test_discovery_prefers_current_hashed_binary_over_direct_stub(self):
        root = Path(self.home.name) / 'OpenAI/Codex/bin'
        old, current, direct = root / 'older/codex.exe', root / 'current/codex.exe', root / 'codex.exe'
        for path in (old, current, direct):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'fixture')
        for path, timestamp in ((old, 100), (current, 200), (direct, 300)):
            os.utime(path, (timestamp, timestamp))
        with patch.dict(os.environ, {'LOCALAPPDATA': self.home.name}):
            self.assertEqual(launch_codex.find_codex(), current)

    def test_discovery_accepts_direct_only_installation(self):
        direct = Path(self.home.name) / 'OpenAI/Codex/bin/codex.exe'
        direct.parent.mkdir(parents=True)
        direct.write_bytes(b'fixture')
        with patch.dict(os.environ, {'LOCALAPPDATA': self.home.name}):
            self.assertEqual(launch_codex.find_codex(), direct)

    def test_discovery_accepts_package_localcache_installation(self):
        for suffix in ('codex.exe', 'current/codex.exe'):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as folder:
                executable = Path(folder) / 'Packages/OpenAI.Codex_example/LocalCache/Local/OpenAI/Codex/bin' / suffix
                executable.parent.mkdir(parents=True)
                executable.write_bytes(b'fixture')
                with patch.dict(os.environ, {'LOCALAPPDATA': folder}):
                    self.assertEqual(launch_codex.find_codex(), executable)

    def test_default_does_not_even_read_config(self):
        with patch.object(Path, 'read_text', side_effect=AssertionError('config read forbidden')):
            self.assertEqual(launch_codex.prepare_arguments(['--version']), ['--version'])

    def test_experimental_keeps_builtin_auth_and_provider_identity(self):
        self.write_config('model="chosen-model"\nmodel_reasoning_effort="ultra"\n')
        with patch.object(launch_codex, 'ensure_headroom', return_value=True):
            args = launch_codex.prepare_arguments(['exec', 'hello'], True)
        self.assertEqual(args, ['-c', 'openai_base_url="http://127.0.0.1:8787/v1"', 'exec', 'hello'])

    def test_custom_config_or_invalid_config_falls_back_before_starting_proxy(self):
        configs = ['model_provider="company"\n', 'openai_base_url="https://example.org/v1"\n',
                   'not valid toml', 'profile="work"\n[profiles.work]\nmodel_provider="company"\n']
        for config in configs:
            with self.subTest(config=config):
                self.write_config(config)
                with patch.object(launch_codex, 'ensure_headroom', return_value=True) as ensure:
                    self.assertEqual(launch_codex.prepare_arguments(['exec', 'hello'], True), ['exec', 'hello'])
                    ensure.assert_not_called()

    def test_profile_routing_is_respected(self):
        self.write_config('[profiles.work]\nmodel_provider="company"\n[profiles.personal]\nmodel="chosen-model"\n')
        for args in (['-p', 'work'], ['--profile=work'], ['--profile', 'missing']):
            with self.subTest(args=args), patch.object(launch_codex, 'ensure_headroom', return_value=True) as ensure:
                self.assertEqual(launch_codex.prepare_arguments(args, True), args)
                ensure.assert_not_called()
        with patch.object(launch_codex, 'ensure_headroom', return_value=True):
            args = launch_codex.prepare_arguments(['-p', 'personal'], True)
        self.assertEqual(args[-2:], ['-p', 'personal'])
        self.assertIn('openai_base_url="http://127.0.0.1:8787/v1"', args)

    def test_explicit_route_arguments_fall_back_without_starting_proxy(self):
        cases = [['-c', 'model_provider="company"'], ['--config=openai_base_url="https://example.org"'],
                 ['-cmodel_provider="openai"'], ['-c=model_provider="openai"'],
                 ['--config', 'model_providers.openai.base_url="https://example.org"'],
                 ['--oss'], ['--local-provider', 'ollama']]
        for args in cases:
            with self.subTest(args=args), patch.object(launch_codex, 'ensure_headroom', return_value=True) as ensure:
                self.assertEqual(launch_codex.prepare_arguments(args, True), args)
                ensure.assert_not_called()

    def test_explicit_endpoint_environment_falls_back_and_api_key_is_preserved(self):
        with patch.dict(os.environ, {'OPENAI_BASE_URL': 'https://example.org/v1'}), \
             patch.object(launch_codex, 'ensure_headroom', return_value=True) as ensure:
            self.assertEqual(launch_codex.prepare_arguments(['--version'], True), ['--version'])
            ensure.assert_not_called()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test-placeholder'}), \
             patch.object(launch_codex, 'ensure_headroom', return_value=True):
            args = launch_codex.prepare_arguments(['--version'], True)
            self.assertEqual(os.environ['OPENAI_API_KEY'], 'test-placeholder')
        self.assertEqual(args, ['-c', 'openai_base_url="http://127.0.0.1:8787/v1"', '--version'])

    def test_default_never_starts_proxy_or_adds_route(self):
        with patch.object(launch_codex, 'ensure_headroom') as ensure:
            self.assertEqual(launch_codex.prepare_arguments(['--version'], False), ['--version'])
            ensure.assert_not_called()

    def test_unavailable_experimental_proxy_falls_back_before_execution(self):
        with patch.object(launch_codex, 'ensure_headroom', return_value=False):
            self.assertEqual(launch_codex.prepare_arguments(['exec', 'hello'], True), ['exec', 'hello'])

    def test_proxy_start_exception_cannot_break_launcher(self):
        with patch.object(launch_codex, 'ensure_headroom', side_effect=OSError('missing runtime')):
            self.assertEqual(launch_codex.prepare_arguments(['--version'], True), ['--version'])

    def test_experimental_settings_are_per_invocation_and_preserve_user_args(self):
        original = ['-m', 'chosen-model', '-c', 'model_reasoning_effort="ultra"', 'prompt with "quotes"']
        with patch.object(launch_codex, 'ensure_headroom', return_value=True):
            args = launch_codex.prepare_arguments(original, True)
        self.assertEqual(args[-len(original):], original)
        self.assertIn('openai_base_url="http://127.0.0.1:8787/v1"', args)
        self.assertNotIn('model=', ' '.join(args[:-len(original)]))

    def test_run_preserves_arguments_and_returns_exit_code_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'received.json'
            script = Path(directory) / 'fake_cli.py'
            script.write_text('import json,sys\nfrom pathlib import Path\np=Path(sys.argv[1])\np.write_text(json.dumps(sys.argv[2:]))\nsys.exit(7)\n')
            values = ['spaces here', 'embedded "quotes"', 'ไทย', '$not_executed', 'line1\nline2']
            result = launch_codex.run_cli(Path(sys.executable), [str(script), str(output)] + values)
            self.assertEqual(result, 7)
            self.assertEqual(json.loads(output.read_text()), values)

    def test_launch_does_not_touch_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.toml'
            original = b'model="my-model"\nmodel_reasoning_effort="ultra"\n'
            config.write_bytes(original)
            with patch.dict(os.environ, {'CODEX_HOME': directory}), patch.object(launch_codex, 'ensure_headroom', return_value=True):
                launch_codex.prepare_arguments(['--version'], True)
            self.assertEqual(config.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
