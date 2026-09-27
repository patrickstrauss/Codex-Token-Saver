"""Managed proxy policy remains isolated and preserves the user's requests."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class ProxyRuntimeTests(unittest.TestCase):
    def test_environment_is_local_and_does_not_mutate_parent(self):
        from proxy_runtime import build_proxy_environment
        before = dict(os.environ)
        inherited = {'PATH': 'original', 'OPENAI_API_KEY': 'fake-test-key',
                     'OPENAI_TARGET_API_URL': 'http://127.0.0.1:18889/v1',
                     'CODEX_MODEL': 'user-chosen', 'CODEX_REASONING_EFFORT': 'ultra',
                     'HEADROOM_MODEL_ROUTES': '[{"model":"cheap"}]',
                     'HEADROOM_SAVINGS_PATH': 'outside.json',
                     'HEADROOM_PROXY_CONFIG_JSON': '{"model_router":{}}',
                     'hf_home': 'outside-models', 'TRANSFORMERS_CACHE': 'outside-models',
                     'PYTHONPATH': 'outside', 'PYTHONHOME': 'outside'}
        original = dict(inherited)
        state = ROOT / 'proxy-test-state'
        env = build_proxy_environment(state, inherited)
        self.assertEqual(inherited, original)
        self.assertEqual(os.environ, before)
        for key in ('PATH', 'OPENAI_API_KEY', 'OPENAI_TARGET_API_URL', 'CODEX_MODEL', 'CODEX_REASONING_EFFORT'):
            self.assertEqual(env[key], inherited[key])
        for key in ('PYTHONPATH', 'PYTHONHOME', 'HEADROOM_PROXY_CONFIG_JSON', 'HEADROOM_MODEL_ROUTES', 'HEADROOM_SAVINGS_PATH'):
            self.assertNotIn(key, env)
        self.assertNotIn('hf_home', env)
        self.assertNotIn('TRANSFORMERS_CACHE', env)
        self.assertEqual(Path(env['HEADROOM_WORKSPACE_DIR']), state)
        self.assertFalse(state.exists())

    def test_explicit_disabled_controls_override_ambient_settings(self):
        from proxy_runtime import build_proxy_environment
        disabled = ['HEADROOM_OUTPUT_SHAPER', 'HEADROOM_EFFORT_ROUTER',
                    'HEADROOM_MODEL_ROUTER_ENABLED', 'HEADROOM_VERBOSITY_AUTOTUNE',
                    'HEADROOM_LOG_MESSAGES', 'HEADROOM_DEBUG_DUMP',
                    'HEADROOM_CODEX_WIRE_DEBUG', 'HEADROOM_CC_SWITCH_RECONCILE']
        env = build_proxy_environment(ROOT / 'proxy-test-state', {key: '1' for key in disabled})
        for key in disabled:
            self.assertEqual(env[key], '0', key)
        self.assertEqual(env['HEADROOM_TELEMETRY'], 'off')
        self.assertEqual(env['HEADROOM_BEACON'], 'off')
        self.assertEqual(env['HF_HUB_OFFLINE'], '1')
        self.assertEqual(env['HEADROOM_MODE'], 'token')
        self.assertEqual(env['HEADROOM_SAVINGS_PROFILE'], 'coding')
        self.assertEqual(env['HEADROOM_BACKGROUND_COMPRESSION'], '1')
        self.assertEqual(env['HEADROOM_DEDUPE'], '1')

    def test_rejects_relative_state_and_public_bind(self):
        from proxy_runtime import build_proxy_environment, build_proxy_command
        with self.assertRaises(ValueError):
            build_proxy_environment('relative', {})
        for host in ('0.0.0.0', 'example.org', '127.0.0.1;bad'):
            with self.assertRaises(ValueError):
                build_proxy_command(ROOT / 'headroom/.venv', host=host)
        for port in (0, -1, 65536, True, '8789'):
            with self.assertRaises(ValueError):
                build_proxy_command(ROOT / 'headroom/.venv', port=port)

    def test_command_uses_explicit_runtime_without_shell(self):
        from proxy_runtime import build_proxy_command
        runtime = (ROOT / 'headroom/.venv').resolve()
        args = build_proxy_command({'runtime': str(runtime)}, port=8789)
        self.assertEqual(args[0], str(runtime / 'Scripts/python.exe'))
        self.assertEqual(args[1], str(ROOT / 'proxy_runtime.py'))
        self.assertEqual(args[2:], ['--serve', '--host', '127.0.0.1', '--port', '8789'])
        transformed = build_proxy_command(runtime, mode='opencodex')
        self.assertEqual(transformed[2], '--serve-transform')
        with self.assertRaises(ValueError):
            build_proxy_command(runtime, mode='opencodex', port=8790)
        with self.assertRaises(ValueError):
            build_proxy_command(runtime, mode='unknown')

    def test_installed_sdk_effective_config_keeps_requests_and_profile(self):
        from proxy_runtime import validate_proxy_runtime
        production_marker = ROOT / 'proxy/backend-state/exact-retrieval-runtime.json'
        production_before = production_marker.read_bytes() if production_marker.exists() else None
        with tempfile.TemporaryDirectory(prefix='headroom-proxy-config-') as state:
            report = validate_proxy_runtime(ROOT / 'headroom/.venv', state, timeout=45)
            self.assertFalse((Path(state) / 'exact-retrieval-runtime.json').exists())
        self.assertEqual(production_marker.read_bytes() if production_marker.exists() else None, production_before)
        self.assertTrue(report['ok'], report)
        self.assertRegex(report['version'], r'^\d+\.\d+\.\d+')
        self.assertFalse(report['compress_user_messages'])
        self.assertFalse(report['compress_system_messages'])
        self.assertFalse(report['output_shaper'])
        self.assertFalse(report['effort_router'])
        self.assertFalse(report['model_router'])
        self.assertTrue(report['read_maturation'])
        self.assertTrue(report['code_aware'])
        self.assertEqual(report['mode'], 'token')
        self.assertTrue(report['request_invariants_preserved'])
        self.assertTrue(report['exact_retrieval_protected'])
        self.assertFalse(report['log_requests'])
        self.assertEqual(report['savings_flush_every'], 1)

    def test_startup_receipt_requires_installed_guard_and_is_atomic(self):
        from proxy_runtime import _write_exact_retrieval_runtime_receipt, _guard_exact_responses
        from headroom.proxy.handlers.openai import OpenAIHandlerMixin
        method_name = '_compress_openai_responses_live_text_units_with_router'
        def unpatched(self, payload, **kwargs):
            return payload, False, 0, [], {}, [], 0
        with tempfile.TemporaryDirectory(prefix='headroom-proof-') as state:
            receipt = Path(state) / 'exact-retrieval-runtime.json'
            with patch.dict(os.environ, {'HEADROOM_WORKSPACE_DIR': state}):
                with patch.object(OpenAIHandlerMixin, method_name, unpatched):
                    with self.assertRaisesRegex(RuntimeError, 'not installed'):
                        _write_exact_retrieval_runtime_receipt()
                    self.assertFalse(receipt.exists())
                with patch.object(OpenAIHandlerMixin, method_name, _guard_exact_responses(unpatched)):
                    _write_exact_retrieval_runtime_receipt()
            content = json.loads(receipt.read_text(encoding='utf-8'))
            self.assertTrue(content['protected'])
            self.assertEqual(content['pid'], os.getpid())
            self.assertEqual(set(content['source_hashes']), {'proxy_runtime.py', 'exact_retrieval.py'})
            self.assertEqual(list(Path(state).iterdir()), [receipt])

    def test_model_loads_offline_and_lossy_content_is_retrievable(self):
        from proxy_runtime import validate_proxy_model
        if not (ROOT / 'models/headroom-proxy-model.json').is_file():
            self.skipTest('Optional public ONNX model is not downloaded')
        with tempfile.TemporaryDirectory(prefix='headroom-proxy-model-') as state:
            report = validate_proxy_model(ROOT / 'headroom/.venv', state, timeout=45)
        self.assertTrue(report['ok'], report)
        self.assertTrue(report['model_ready'])
        self.assertTrue(report['exact_original_recovered'])
        self.assertTrue(report['small_saving_recovered'])
        self.assertGreater(report['tokens_before'], report['tokens_after'])
        self.assertLess(report['load_seconds'], 45)

    def test_model_probe_budget_is_isolated_from_production_and_parent(self):
        from proxy_runtime import validate_proxy_model, validate_proxy_runtime, build_proxy_environment
        before = dict(os.environ)
        state = ROOT / 'proxy-test-state'
        result = subprocess.CompletedProcess([], 0, stdout='{"ok": true}')
        with patch('proxy_runtime.subprocess.run', return_value=result) as run:
            validate_proxy_model(ROOT / 'headroom/.venv', state)
            model_env = run.call_args.kwargs['env']
            self.assertEqual(model_env['HEADROOM_KOMPRESS_TIME_BUDGET_SECONDS'], '15')
            self.assertEqual(model_env['HEADROOM_KOMPRESS_ACQUIRE_TIMEOUT_SECONDS'], '3')
            self.assertEqual(run.call_args.kwargs['timeout'], 45)
            validate_proxy_runtime(ROOT / 'headroom/.venv', state)
            self.assertEqual(run.call_args.kwargs['env'], build_proxy_environment(state))
        production_env = build_proxy_environment(state)
        self.assertEqual(production_env['HEADROOM_KOMPRESS_TIME_BUDGET_SECONDS'], '3')
        self.assertEqual(production_env['HEADROOM_KOMPRESS_ACQUIRE_TIMEOUT_SECONDS'], '0.25')
        self.assertEqual(os.environ, before)

    def test_negative_model_report_preserves_diagnostics(self):
        from proxy_runtime import validate_proxy_model
        report = {'ok': False, 'model_ready': True, 'tokens_before': 1250,
                  'tokens_after': 1250, 'exact_original_recovered': False}
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps(report))
        with patch('proxy_runtime.subprocess.run', return_value=result):
            actual = validate_proxy_model(ROOT / 'headroom/.venv', ROOT / 'proxy-test-state')
        for key, value in report.items():
            self.assertEqual(actual[key], value)
        self.assertEqual(actual['error'], 'Headroom runtime validation checks failed')

    def test_validation_rejects_non_boolean_status(self):
        from proxy_runtime import validate_proxy_model
        result = subprocess.CompletedProcess([], 0, stdout='{"ok": "false"}')
        with patch('proxy_runtime.subprocess.run', return_value=result):
            actual = validate_proxy_model(ROOT / 'headroom/.venv', ROOT / 'proxy-test-state')
        self.assertIs(actual['ok'], False)
        self.assertEqual(actual['error'], 'Headroom runtime is unavailable or invalid')

    def test_completed_request_savings_survive_abrupt_exit_and_fresh_process(self):
        from proxy_runtime import build_proxy_environment
        with tempfile.TemporaryDirectory(prefix='headroom-proxy-durability-') as state:
            environment = build_proxy_environment(state)
            environment.update(HEADROOM_OFFLINE='1', LITELLM_LOCAL_MODEL_COST_MAP='True')
            writer = '''
import asyncio, os
from proxy_runtime import _configure_sdk
_configure_sdk()
from headroom.proxy.prometheus_metrics import PrometheusMetrics
metrics = PrometheusMetrics()
async def record():
    for saved in (17, 23):
        await metrics.record_request(provider='openai', model='gpt-4o', input_tokens=100,
            output_tokens=5, tokens_saved=saved, attempted_input_tokens=100+saved,
            latency_ms=1, client='codex')
asyncio.run(record())
# No tracker.flush, no graceful server shutdown, and no atexit handlers.
os._exit(0)
'''
            written = subprocess.run([sys.executable, '-c', writer], env=environment, cwd=ROOT,
                                     capture_output=True, timeout=20)
            self.assertEqual(written.returncode, 0, written.stderr.decode(errors='replace'))
            self.assertTrue((Path(state) / 'proxy_savings.json').is_file(), 'Completed requests were never persisted')
            reader = '''
import json
from headroom.proxy.savings_tracker import SavingsTracker
tracker = SavingsTracker()
print(json.dumps(tracker.snapshot()))
'''
            restored = subprocess.run([sys.executable, '-c', reader], env=environment, cwd=ROOT,
                                      capture_output=True, timeout=20)
            self.assertEqual(restored.returncode, 0, restored.stderr.decode(errors='replace'))
            snapshot = json.loads(restored.stdout)
            self.assertEqual(snapshot['lifetime']['requests'], 2)
            self.assertEqual(snapshot['lifetime']['tokens_saved'], 40)


if __name__ == '__main__':
    unittest.main()
