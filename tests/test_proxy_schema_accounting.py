"""Offline regression for Responses HTTP's message-only savings denominator."""
import copy
import inspect
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class ResponsesSchemaAccountingTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_schema_savings_widen_http_pair_without_changing_payload(self):
        from headroom.proxy.handlers.openai import OpenAIHandlerMixin, _json_debug_dumps
        from headroom.proxy.outcome import RequestOutcome
        from proxy_runtime import _responses_schema_accounting

        # Real SDK compaction and a deterministic counter; no model, provider,
        # storage, tokenizer download or live savings ledger is involved.
        counter = SimpleNamespace(count_text=len)
        handler = SimpleNamespace(openai_provider=SimpleNamespace(get_token_counter=lambda _: counter))
        handler._compress_openai_responses_live_text_units_with_router = (
            lambda payload, **kw: (payload, False, 0, [], {}, [], 0))
        payload = {'model': 'test-model', 'reasoning': {'effort': 'ultra'},
                   'instructions': 'Keep this exact.', 'input': [{'role': 'user', 'content': 'Hi'}],
                   'tools': [{'type': 'function', 'name': 'read',
                              'description': ('Read    exact    text.\n' * 50),
                              'parameters': {'type': 'object', 'properties': {}}}]}
        original = copy.deepcopy(payload)
        recorded = []

        async def compress(self, body, **kw):
            with patch('headroom.proxy.helpers.inject_tool_search_deferral_openai',
                       side_effect=lambda tools, *a, **k: tools), \
                    patch('headroom.proxy.turn_hooks.registered_turn_hooks', return_value=[]):
                return (*OpenAIHandlerMixin._compress_openai_responses_payload(self, body, **kw), {})

        async def record(self, outcome):
            recorded.append(outcome)

        compress, record = _responses_schema_accounting(compress, record)
        result = await compress(handler, payload, model='test-model', request_id='http-1')
        saved = result[2]
        # This is the actual 0.37 HTTP derivation that previously exceeded 100%.
        self.assertGreater(saved, 10)
        outcome = RequestOutcome(request_id='http-1', provider='openai', model='test-model',
                                 original_tokens=10, optimized_tokens=max(0, 10-saved),
                                 output_tokens=0, tokens_saved=saved, attempted_input_tokens=result[7],
                                 provider_input_tokens=123, tags={'endpoint': 'responses_http'})
        self.assertGreater(outcome.savings_pct, 100)
        await record(handler, outcome)
        fixed = recorded[-1]
        self.assertEqual(fixed.original_tokens, 10 + len(_json_debug_dumps(original['tools'])))
        self.assertEqual(fixed.original_tokens - fixed.optimized_tokens, saved)
        self.assertLess(fixed.savings_pct, 100)
        self.assertEqual(fixed.provider_input_tokens, 123)
        self.assertEqual(fixed.attempted_input_tokens, outcome.attempted_input_tokens)
        self.assertEqual(payload, original)
        self.assertEqual(result[0]['input'], original['input'])
        self.assertEqual(result[0]['reasoning'], original['reasoning'])
        # The same outcome is never widened twice.
        await record(handler, outcome)
        self.assertIs(recorded[-1], outcome)

    async def test_excludes_websockets_lifted_tools_and_already_fixed_pairs(self):
        from headroom.proxy.outcome import RequestOutcome
        from proxy_runtime import _responses_schema_accounting
        recorded = []
        handler = SimpleNamespace(openai_provider=SimpleNamespace(
            get_token_counter=lambda _: SimpleNamespace(count_text=len)))

        async def compress(self, body, **kw):
            return body, True, 5, [], None, 100, 95, 10, {}

        async def record(self, outcome):
            recorded.append(outcome)

        compress, record = _responses_schema_accounting(compress, record)
        base = RequestOutcome(request_id='r', provider='openai', model='test', original_tokens=20,
                              optimized_tokens=15, output_tokens=0, tokens_saved=5, attempted_input_tokens=10)
        cases = [({'tools': [{'name': 't'}]}, {'timeout': 5}, base),
                 ({'input': [{'type': 'additional_tools', 'tools': [{'name': 't'}]}]}, {}, base),
                 ({'tools': [{'name': 't'}], 'input': [{'type': 'additional_tools'}]}, {}, base),
                 ({'tools': [{'name': 't'}]}, {}, replace(base, tags={'endpoint': 'responses_ws'})),
                 ({'tools': [{'name': 't'}]}, {}, replace(base, optimized_tokens=18)),
                 ({'tools': [{'name': 't'}]}, {}, replace(base, optimized_tokens=0, tokens_saved=5000))]
        for payload, kwargs, outcome in cases:
            with self.subTest(payload=payload, kwargs=kwargs, outcome=outcome):
                await compress(handler, payload, model='test', request_id='r', **kwargs)
                await record(handler, outcome)
                self.assertIs(recorded[-1], outcome)

    async def test_counter_failure_preserves_result_and_error_passthrough(self):
        from proxy_runtime import _responses_schema_accounting
        result = ({}, True, 5, [], None, 100, 95, 10, {})
        async def compress(self, body, **kwargs):
            return result
        async def record(self, outcome):
            return outcome
        wrapped, _ = _responses_schema_accounting(compress, record)
        self.assertIs(await wrapped(object(), {'tools': [{}]}, request_id='r'), result)

    async def test_slow_accounting_has_deadline_and_serializes_off_event_loop(self):
        from headroom.proxy.outcome import RequestOutcome
        from proxy_runtime import _responses_schema_accounting
        release = threading.Event()
        serialized_on = []
        result = ({}, True, 5, [], None, 100, 95, 10, {})
        counter = SimpleNamespace(count_text=lambda _: (release.wait(2), 100)[1])
        handler = SimpleNamespace(openai_provider=SimpleNamespace(get_token_counter=lambda _: counter))
        async def compress(self, body, **kwargs):
            return result
        async def record(self, outcome):
            return outcome
        def serialize(tools):
            serialized_on.append(threading.get_ident())
            return 'schema'
        with patch('headroom.proxy.handlers.openai._json_debug_dumps', side_effect=serialize):
            wrapped, recorded = _responses_schema_accounting(compress, record)
        outcome = RequestOutcome(request_id='r', provider='openai', model='test', original_tokens=20,
                                 optimized_tokens=15, output_tokens=0, tokens_saved=5, attempted_input_tokens=10)
        try:
            started = time.monotonic()
            self.assertIs(await wrapped(handler, {'tools': [{}]}, request_id='r'), result)
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertTrue(serialized_on)
            self.assertNotEqual(serialized_on[0], threading.get_ident())
            self.assertIs(await recorded(handler, outcome), outcome)
        finally:
            release.set()

    async def test_installer_is_version_gated_and_idempotent(self):
        from headroom.proxy.handlers.openai import OpenAIHandlerMixin
        from headroom.proxy.server import HeadroomProxy
        from proxy_runtime import _enable_responses_schema_accounting
        method = '_compress_openai_responses_payload_in_executor'
        original_compress = inspect.unwrap(getattr(OpenAIHandlerMixin, method))
        original_record = inspect.unwrap(HeadroomProxy._record_request_outcome)
        with patch.object(OpenAIHandlerMixin, method, original_compress), \
                patch.object(HeadroomProxy, '_record_request_outcome', original_record):
            with patch('importlib.metadata.version', return_value='0.38.0'):
                self.assertFalse(_enable_responses_schema_accounting())
                self.assertIs(getattr(OpenAIHandlerMixin, method), original_compress)
            with patch('importlib.metadata.version', return_value='0.37.0'), \
                    patch('inspect.getsource', return_value='native fixed handler'):
                self.assertFalse(_enable_responses_schema_accounting())
            with patch('importlib.metadata.version', return_value='0.37.0'):
                self.assertTrue(_enable_responses_schema_accounting())
                wrapped = getattr(OpenAIHandlerMixin, method)
                self.assertTrue(_enable_responses_schema_accounting())
                self.assertIs(getattr(OpenAIHandlerMixin, method), wrapped)


if __name__ == '__main__':
    unittest.main()
