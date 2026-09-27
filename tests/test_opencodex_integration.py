import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import opencodex_integration as module
except ImportError:
    module = None


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(module, 'OpenCodex discovery is missing')
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.exe = self.root / 'ocx.exe'
        self.exe.touch()
        self.calls = []
        self.resolved = {'schema': 'ocx-resolve/1', 'cliVersion': '2.64.0',
                         'configHome': str(self.root), 'port': {'effective': 10421},
                         'liveness': {'status': 'live', 'pid': 42, 'port': 10421}}
        self.readiness = {'ready': True, 'status': 'ready', 'pid': 42, 'port': 10421}

    def run_cli(self, argv, timeout_seconds):
        self.calls.append((argv[1:], timeout_seconds))
        data = self.resolved if argv[1] == 'resolve' else self.readiness
        return subprocess.CompletedProcess(argv, 0, json.dumps(data), '')

    def probe(self):
        return module.probe_opencodex(executable=self.exe, run=self.run_cli)

    def test_installed_is_not_ready(self):
        self.resolved['liveness']['status'] = 'absent-proven'
        result = self.probe()
        self.assertTrue(result.installed)
        self.assertFalse(result.ready)
        self.assertIsNone(result.transform_protocol)

    def test_legacy_has_no_transform(self):
        result = self.probe()
        self.assertTrue(result.ready)
        self.assertIsNone(result.transform_protocol)
        self.assertEqual(result.endpoint, 'http://127.0.0.1:10421/v1')
        self.assertEqual(result.config_home, self.root)

    def test_control_capability_is_typed_and_contains_no_untrusted_fields(self):
        self.readiness['tokenSaver'] = {'protocol': 1, 'control': 1, 'enabled': False, 'secret': 'hidden'}
        result = self.probe()
        self.assertEqual(result.control_protocol, 1)
        self.assertIs(result.extension_enabled, False)
        self.readiness['tokenSaver']['control'] = True
        self.assertIsNone(self.probe().control_protocol)

    def test_probe_is_read_only(self):
        before = list(self.root.iterdir())
        self.probe()
        self.assertEqual(self.calls, [(['resolve', '--json'], 2.0), (['ready', '--json'], 2.0)])
        self.assertEqual(list(self.root.iterdir()), before)

    def test_wrong_listener_is_not_opencodex(self):
        self.resolved['liveness']['status'] = 'unknown'
        self.assertFalse(self.probe().ready)
        self.resolved['liveness']['status'] = 'live'
        self.readiness['pid'] = 43
        self.assertFalse(self.probe().ready)

    def test_absent_executable_never_runs(self):
        self.exe.unlink()
        self.assertFalse(self.probe().installed)
        self.assertEqual(self.calls, [])

    def test_invalid_or_large_output_is_unavailable_without_private_errors(self):
        for text in ('not json SECRET', '[' + ' ' * 65536 + ']', '[]'):
            result = module.probe_opencodex(executable=self.exe,
                run=lambda *a: subprocess.CompletedProcess([], 0, text, 'SECRET'))
            self.assertFalse(result.ready)
            self.assertNotIn('SECRET', result.reason)

    def test_timeout_is_unavailable(self):
        def timeout(*args):
            raise subprocess.TimeoutExpired('SECRET', 2)
        result = module.probe_opencodex(executable=self.exe, run=timeout)
        self.assertFalse(result.ready)
        self.assertNotIn('SECRET', result.reason)

    def test_protocol_requires_live_runtime_agreement(self):
        self.readiness['tokenSaver'] = {'protocol': 1}
        self.assertEqual(self.probe().transform_protocol, 1)
        self.readiness['port'] = 10422
        self.assertIsNone(self.probe().transform_protocol)

    def test_effective_profile_and_environment_control_route(self):
        config = self.root / 'config.toml'
        config.write_text('openai_base_url="http://127.0.0.1:10421/v1"\n'
                          'profile="other"\n[profiles.other]\nmodel_provider="custom"\n'
                          '[model_providers.custom]\nbase_url="https://example.invalid/v1"\n')
        self.assertFalse(module.routing_uses_opencodex(self.probe(), self.root, {}))
        config.write_text('openai_base_url="http://127.0.0.1:10421/backend-api/codex"\n')
        self.assertTrue(module.routing_uses_opencodex(self.probe(), self.root, {}))
        self.assertFalse(module.routing_uses_opencodex(self.probe(), self.root,
                         {'OPENAI_BASE_URL': 'https://example.invalid/v1'}))
        config.write_text('profile="missing"\n')
        self.assertIsNone(module.routing_uses_opencodex(self.probe(), self.root, {}))


if __name__ == '__main__':
    unittest.main()
