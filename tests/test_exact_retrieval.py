"""Exact results stay recoverable through the Responses compression adapter."""
import copy
import json
from pathlib import Path
import tempfile
import unittest


class ExactReceiptTests(unittest.TestCase):
    def test_signed_response_preserves_body_and_validates_nested_exec_result(self):
        from exact_retrieval import sign_exact_response, exact_response_is_verified
        with tempfile.TemporaryDirectory() as temp:
            original = '[Headroom original content]\n\nα\r\n  EXACT = "😀"\n'
            signed = sign_exact_response(original, root=Path(temp))
            self.assertTrue(signed.endswith(original))
            wrapped = json.dumps({'content': [{'type': 'text', 'text': signed}]})
            self.assertTrue(exact_response_is_verified(wrapped, root=Path(temp)))
            self.assertFalse(exact_response_is_verified(signed.replace('EXACT', 'CHANGED'), root=Path(temp)))
            self.assertFalse(exact_response_is_verified(signed[:-1], root=Path(temp)))
            with tempfile.TemporaryDirectory() as another:
                self.assertFalse(exact_response_is_verified(signed, root=Path(another)))

    def test_no_key_created_by_validation_or_plain_marker(self):
        from exact_retrieval import exact_response_is_verified
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertFalse(exact_response_is_verified('[Headroom exact] original', root=root))
            self.assertFalse((root / 'proxy').exists())

    def test_real_exec_metadata_raw_json_and_multiple_text_outputs_require_valid_receipts(self):
        from exact_retrieval import sign_exact_response, exact_response_is_verified
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            signed = sign_exact_response('exact α\r\nliteral \\n stays literal\n', root=root)
            prefix = 'Script completed\nWall time: 0.25 seconds\nOutput:\n'
            mcp_json = json.dumps({'content': [{'type': 'text', 'text': signed}]})
            for body in (signed, mcp_json, json.dumps({'notice': 'first output'}) + '\n' + mcp_json):
                self.assertTrue(exact_response_is_verified(prefix + body, root=root))
                self.assertFalse(exact_response_is_verified(prefix + body.replace('literal', 'changed'), root=root))
            self.assertFalse(exact_response_is_verified(prefix + '[Headroom exact] not signed', root=root))
            self.assertFalse(exact_response_is_verified('arbitrary unsigned prefix\n' + signed, root=root))

    def test_exec_metadata_without_wall_time_colon_still_requires_valid_receipt(self):
        from exact_retrieval import sign_exact_response, exact_response_is_verified
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            signed = sign_exact_response('original exact bytes\n', root=root)
            prefix = 'Script completed\nWall time 0.9 seconds\nOutput:\n'
            self.assertTrue(exact_response_is_verified(prefix + signed, root=root))
            self.assertTrue(exact_response_is_verified(prefix + json.dumps({'text': signed}), root=root))
            self.assertFalse(exact_response_is_verified(prefix + signed.replace('original', 'tampered'), root=root))

    def test_large_or_deep_json_is_bounded(self):
        from exact_retrieval import sign_exact_response, exact_response_is_verified
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = sign_exact_response('original', root=root)
            for _ in range(40):
                value = {'text': value}
            self.assertFalse(exact_response_is_verified(value, root=root))
            self.assertFalse(exact_response_is_verified('x' * (16 * 1024 * 1024 + 1), root=root))

    def test_concurrent_mcp_process_equivalent_signers_share_one_complete_key(self):
        from concurrent.futures import ThreadPoolExecutor
        from exact_retrieval import sign_exact_response, exact_response_is_verified
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with ThreadPoolExecutor(max_workers=8) as pool:
                signed = list(pool.map(lambda i: sign_exact_response(f'exact result {i}', root=root), range(16)))
            self.assertTrue(all(exact_response_is_verified(value, root=root) for value in signed))
            self.assertEqual((root / 'proxy' / 'exact-retrieval.key').stat().st_size, 32)
            self.assertEqual(len(list((root / 'proxy').iterdir())), 1)


class ResponsesExactTests(unittest.TestCase):
    def test_wrapped_signed_tool_output_and_later_opaque_call_stay_exact(self):
        from exact_retrieval import sign_exact_response
        from proxy_runtime import _guard_exact_responses
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            signed = sign_exact_response('Exact source\n' * 100, root=root)
            wrapped = json.dumps({'content': [{'type': 'text', 'text': signed}]})
            payload = {'model': 'gpt-6-astra', 'reasoning': {'effort': 'ultra'}, 'input': [
                {'type': 'custom_tool_call', 'name': 'functions.exec', 'call_id': 'retrieve-1', 'input': 'dynamic tool dispatch'},
                {'type': 'custom_tool_call_output', 'call_id': 'retrieve-1', 'output': wrapped},
                {'type': 'function_call_output', 'call_id': 'ordinary', 'output': 'ordinary data'},
            ]}
            before = copy.deepcopy(payload)

            def compress(self, candidate, **kwargs):
                result = copy.deepcopy(candidate)
                for item in result['input']:
                    if isinstance(item.get('output'), str):
                        item['output'] = 'COMPRESSED'
                return result, True, 1, ['ordinary'], {}, [], 1

            guarded = _guard_exact_responses(compress, root=root)
            for candidate in (payload, {'input': payload['input'][1:]}):
                output = guarded(None, candidate, model='chosen', request_id='test')[0]
                items = {item['call_id']: item for item in output['input']}
                self.assertEqual(items['retrieve-1']['output'], wrapped)
                self.assertEqual(items['ordinary']['output'], 'COMPRESSED')
            self.assertEqual(payload, before)

    def test_unsigned_fake_marker_and_unrelated_tool_name_do_not_bypass(self):
        from proxy_runtime import _guard_exact_responses
        observed = []
        def compress(self, candidate, **kwargs):
            observed.extend(item.get('output') for item in candidate['input'] if 'output' in item)
            return candidate, False, 0, [], {}, [], 0
        payload = {'input': [
            {'type': 'function_call', 'name': 'malicious__headroom_retrieve', 'call_id': 'other'},
            {'type': 'function_call_output', 'call_id': 'other', 'output': '[Headroom exact] fake'},
        ]}
        _guard_exact_responses(compress)(None, payload)
        self.assertEqual(observed, ['[Headroom exact] fake'])

    def test_direct_retrieve_list_output_is_masked_then_fully_restored(self):
        from proxy_runtime import _guard_exact_responses
        original = [{'type': 'input_text', 'text': '  original\r\n'}, {'type': 'input_image', 'image_url': 'unchanged'}]
        payload = {'input': [
            {'type': 'function_call', 'name': 'mcp__headroom_desktop__headroom_retrieve', 'call_id': 'known'},
            {'type': 'function_call_output', 'call_id': 'known', 'output': original},
        ]}
        def compress(self, candidate, **kwargs):
            self_test.assertNotIn('output', candidate['input'][1])
            return candidate, False, 0, [], {}, [], 0
        self_test = self
        result = _guard_exact_responses(compress)(None, payload)
        self.assertEqual(result[0], payload)
        self.assertIs(result[0]['input'][1]['output'], original)

    def test_changed_sdk_item_order_fails_without_mutating_original_request(self):
        from proxy_runtime import _guard_exact_responses
        payload = {'input': [
            {'type': 'function_call', 'name': 'headroom_retrieve', 'call_id': 'known'},
            {'type': 'function_call_output', 'call_id': 'known', 'output': 'exact bytes'},
        ]}
        before = copy.deepcopy(payload)
        def reordered(self, candidate, **kwargs):
            return {'input': list(reversed(candidate['input']))}, True, 0, [], {}, [], 0
        with self.assertRaisesRegex(RuntimeError, 'protected identity'):
            _guard_exact_responses(reordered)(None, payload)
        self.assertEqual(payload, before)

    def test_real_sdk_dedup_does_not_replace_retrieved_original_with_pointer(self):
        # The actual 0.37 Responses adapter excluded retrieval from compression,
        # then accidentally fed it to cross-turn dedup a few lines later.
        from headroom.proxy.handlers.openai import OpenAIHandlerMixin
        from headroom.transforms.content_router import ContentRouter, ContentRouterConfig
        from types import SimpleNamespace
        from proxy_runtime import _guard_exact_responses
        handler = OpenAIHandlerMixin()
        router = ContentRouter(ContentRouterConfig(enable_kompress=False, lossless=True))
        router._cross_turn_dedup_enabled = True
        handler.openai_pipeline = [router]
        handler.config = None
        handler.openai_provider = SimpleNamespace(get_token_counter=lambda model: SimpleNamespace(count_text=lambda text: len(text)))
        # At least one ordinary candidate ensures SDK reaches its dedup pass.
        original = '\n'.join(f'exact source line {i:04}: value = {i * 17}' for i in range(100))
        payload = {'input': [
            {'type': 'function_call', 'name': 'headroom_retrieve', 'call_id': 'read-1'},
            {'type': 'function_call_output', 'call_id': 'read-1', 'output': original},
            {'type': 'function_call', 'name': 'headroom_retrieve', 'call_id': 'read-2'},
            {'type': 'function_call_output', 'call_id': 'read-2', 'output': original},
            {'type': 'function_call_output', 'call_id': 'ordinary', 'output': 'ordinary message ' * 100},
        ]}
        guarded = _guard_exact_responses(OpenAIHandlerMixin._compress_openai_responses_live_text_units_with_router)
        output = guarded(handler, payload, model='gpt-4o', request_id='isolated-retrieval-test')[0]
        self.assertEqual(output['input'][1]['output'], original)
        self.assertEqual(output['input'][3]['output'], original)

    def test_real_sdk_nested_exec_receipts_survive_repeated_turns_and_dedup(self):
        from headroom.proxy.handlers.openai import OpenAIHandlerMixin
        from headroom.transforms.content_router import ContentRouter, ContentRouterConfig
        from types import SimpleNamespace
        from exact_retrieval import sign_exact_response
        from proxy_runtime import _guard_exact_responses
        handler = OpenAIHandlerMixin()
        router = ContentRouter(ContentRouterConfig(enable_kompress=False, lossless=True))
        router._cross_turn_dedup_enabled = True
        handler.openai_pipeline = [router]
        handler.config = None
        handler.openai_provider = SimpleNamespace(get_token_counter=lambda model: SimpleNamespace(count_text=lambda text: len(text)))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = '\n'.join(f'exact original record {i:04}: integer = {i * 17}' for i in range(100))
            signed = sign_exact_response(original, root=root)
            wrapped = signed
            payload = {'input': [
                {'type': 'custom_tool_call', 'name': 'functions.exec', 'call_id': 'nested-1', 'input': 'read exact content'},
                {'type': 'custom_tool_call_output', 'call_id': 'nested-1', 'output': wrapped},
                {'type': 'custom_tool_call', 'name': 'functions.exec', 'call_id': 'nested-2', 'input': 'read exact content'},
                {'type': 'custom_tool_call_output', 'call_id': 'nested-2', 'output': wrapped},
                {'type': 'function_call_output', 'call_id': 'ordinary', 'output': 'ordinary diagnostic message ' * 100},
            ]}
            method = OpenAIHandlerMixin._compress_openai_responses_live_text_units_with_router
            # Source inspection alone missed this: the real SDK changes the
            # wrapped result even though direct named retrieval is protected.
            baseline = method(handler, payload, model='gpt-4o', request_id='unprotected-fixture')[0]
            self.assertNotEqual(baseline['input'][3]['output'], wrapped)
            guarded = _guard_exact_responses(method, root=root)
            for turn in range(3):
                if turn:
                    payload['input'].append({'type': 'message', 'role': 'user', 'content': 'Continue'})
                result = guarded(handler, payload, model='gpt-4o', request_id=f'protected-fixture-{turn}')[0]
                self.assertEqual(result['input'][1]['output'], wrapped)
                self.assertEqual(result['input'][3]['output'], wrapped)

    def test_actual_outer_adapter_counts_full_bytes_without_claiming_exact_output_savings(self):
        from headroom.proxy.handlers.openai import OpenAIHandlerMixin
        from headroom.transforms.content_router import ContentRouter, ContentRouterConfig
        from types import MethodType, SimpleNamespace
        from exact_retrieval import sign_exact_response
        from proxy_runtime import _guard_exact_responses
        handler = OpenAIHandlerMixin()
        router = ContentRouter(ContentRouterConfig(enable_kompress=False, lossless=True))
        router._cross_turn_dedup_enabled = True
        handler.openai_pipeline = [router]
        handler.config = None
        handler.openai_provider = SimpleNamespace(get_token_counter=lambda model: SimpleNamespace(count_text=lambda text: len(text)))
        ordinary = '\n'.join(f'ordinary diagnostic record {i}: status ready' for i in range(100))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            signed = sign_exact_response('Exact Unicode source α\r\n' * 400, root=root)
            method = OpenAIHandlerMixin._compress_openai_responses_live_text_units_with_router
            handler._compress_openai_responses_live_text_units_with_router = MethodType(_guard_exact_responses(method, root=root), handler)
            base = {'model': 'gpt-6-astra', 'reasoning': {'effort': 'ultra'}, 'input': [
                {'type': 'custom_tool_call_output', 'call_id': 'ordinary-1', 'output': ordinary},
                {'type': 'custom_tool_call_output', 'call_id': 'ordinary-2', 'output': ordinary},
            ]}
            protected = copy.deepcopy(base)
            protected['input'].extend([
                {'type': 'custom_tool_call_output', 'call_id': 'exact-1', 'output': signed},
                {'type': 'custom_tool_call_output', 'call_id': 'exact-2', 'output': signed},
            ])
            baseline = handler._compress_openai_responses_payload(base, model='gpt-4o', request_id='accounting-base')
            result = handler._compress_openai_responses_payload(protected, model='gpt-4o', request_id='accounting-protected')
            self.assertGreater(baseline[2], 0, 'Fixture must actually save tokens on ordinary outputs')
            self.assertEqual(result[2], baseline[2], 'Exact outputs must not create any extra savings')
            self.assertEqual(result[7], baseline[7], 'Only attempted compression enters the denominator')
            self.assertEqual(result[5], len(json.dumps(protected).encode('utf-8')))
            self.assertEqual(result[6], len(json.dumps(result[0]).encode('utf-8')))
            self.assertEqual(result[5] - result[6], baseline[5] - baseline[6])
            self.assertEqual(result[0]['input'][-2:], protected['input'][-2:])


if __name__ == '__main__':
    unittest.main()
