import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import request_transform as module
except ImportError:
    module = None


def request(text, **changes):
    value = {'protocol': 1, 'request_id': 'r1', 'scope_id': 's1', 'budget_ms': 500,
             'entries': [{'id': 'e1', 'original_sha256': hashlib.sha256(text.encode()).hexdigest(), 'text': text}]}
    value.update(changes)
    return value


class TransformTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.assertIsNotNone(module, 'Transformation service is missing')
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.now = 1000.0
        self.calls = 0
        self.store = module.OriginalStore(self.root / 'originals.db', clock=lambda: self.now)
        def compress(text):
            self.calls += 1
            return 'Useful summary.'
        self.service = module.TransformService(compress, self.store, root=self.root, token_counter=len)
        self.addCleanup(self.service.close)
        self.text = 'Original diagnostic line with full details.\r\n' * 150

    async def test_replacement_has_recoverable_original_and_no_input_mutation(self):
        original = request(self.text)
        before = json.dumps(original)
        result = await self.service.transform(original)
        self.assertEqual(json.dumps(original), before)
        self.assertEqual(result['outcome'], 'compressed')
        entry = result['replacements'][0]
        self.assertEqual(self.store.retrieve(entry['retrieval_reference']), self.text)
        self.assertLess(len(entry['replacement']), len(self.text))

    async def test_live_policy_pauses_cached_results_but_preserves_originals(self):
        policy = [True]
        service = module.TransformService(lambda text: 'Summary.', self.store,
            root=self.root, token_counter=len, enabled_reader=lambda: policy[0])
        self.addCleanup(service.close)
        first = await service.transform(request(self.text))
        self.assertEqual(first['outcome'], 'compressed')
        policy[0] = False
        self.assertEqual((await service.transform(request(self.text)))['outcome'], 'bypassed')
        self.assertEqual(self.store.retrieve(first['replacements'][0]['retrieval_reference']), self.text)
        policy[0] = 'true'
        self.assertFalse(service.enabled)
        policy[0] = True
        self.assertTrue(service.enabled)

    async def test_invalid_entries_reject_entire_request_without_compressing(self):
        for mutation in ('hash', 'duplicate', 'unknown', 'oversize'):
            value = request(self.text)
            if mutation == 'hash': value['entries'][0]['original_sha256'] = '0' * 64
            if mutation == 'duplicate': value['entries'] *= 2
            if mutation == 'unknown': value['model'] = 'do-not-route'
            if mutation == 'oversize': value['entries'][0]['text'] = 'x' * (8 * 1024 * 1024 + 1)
            result = await self.service.transform(value)
            self.assertEqual(result['outcome'], 'error')
            self.assertEqual(result['replacements'], [])
        self.assertEqual(self.calls, 0)

    async def test_exact_nested_structured_and_existing_marker_are_unchanged(self):
        from exact_retrieval import sign_exact_response
        exact = sign_exact_response(self.text + 'ไทย\r\n', root=self.root)
        nested = json.dumps({'content': [{'type': 'text', 'text': exact}]})
        for text in (exact, nested, '<<ccr:abcdef123456,string,1KB>>', '{"private":"structured"}' * 150):
            result = await self.service.transform(request(text))
            self.assertEqual(result['replacements'], [])
        self.assertEqual(self.calls, 0)

    async def test_no_reduction_does_not_emit_reference(self):
        self.service.compressor = lambda text: text
        self.assertEqual((await self.service.transform(request(self.text)))['replacements'], [])

    async def test_only_durable_service_reference_is_exposed(self):
        self.service.compressor = lambda text: 'Useful summary. <<ccr:abcdef123456,2000->20>>'
        result = await self.service.transform(request(self.text))
        self.assertNotIn('abcdef123456', result['replacements'][0]['replacement'])

    async def test_circuit_opens_after_three_failures_and_recovers(self):
        now = [100.0]
        self.service.clock = lambda: now[0]
        self.service.compressor = lambda text: (_ for _ in ()).throw(ValueError('PRIVATE'))
        for index in range(3):
            await self.service.transform(request(self.text, scope_id='bad' + str(index)))
        self.assertEqual((await self.service.transform(request(self.text)))['reason'], 'circuit_open')
        now[0] += 31
        self.service.compressor = lambda text: 'Recovered summary.'
        self.assertEqual((await self.service.transform(request(self.text)))['outcome'], 'compressed')

    async def test_cache_never_returns_expired_original(self):
        first = await self.service.transform(request(self.text))
        again = await self.service.transform(request(self.text, request_id='r2'))
        self.assertEqual(first['replacements'], again['replacements'])
        self.assertEqual(self.calls, 1)
        self.now += 1801
        later = await self.service.transform(request(self.text, request_id='r3'))
        self.assertEqual(self.calls, 2)
        self.assertEqual(self.store.retrieve(later['replacements'][0]['retrieval_reference']), self.text)

    async def test_persist_failure_cannot_emit_compressed_text(self):
        self.store.put = lambda text: (_ for _ in ()).throw(OSError('PRIVATE'))
        result = await self.service.transform(request(self.text))
        self.assertEqual(result['replacements'], [])
        self.assertNotIn('PRIVATE', json.dumps(result))

    async def test_completed_work_after_timeout_is_reused_on_retry(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        def slow(text):
            self.calls += 1
            gate.wait(2)
            return 'Useful summary.'
        self.service.compressor = slow
        timed_out = await self.service.transform(request(self.text, budget_ms=10))
        self.assertEqual(timed_out['reason'], 'timeout')
        gate.set()
        async with asyncio.timeout(2):
            while self.service._active:
                await asyncio.sleep(.005)
        reply = await self.service.transform(request(self.text, request_id='retry'))
        self.assertEqual(reply['outcome'], 'compressed')
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.store.retrieve(reply['replacements'][0]['retrieval_reference']), self.text)

    async def test_growing_history_reuses_outputs_across_requests_and_ids(self):
        await self.service.transform(request(self.text))
        value = request(self.text, scope_id='another-request')
        value['entries'][0]['id'] = 'changed-position'
        value['entries'].append(request(self.text + 'New details.')['entries'][0])
        result = await self.service.transform(value)
        self.assertEqual(self.calls, 2)
        self.assertEqual([x['id'] for x in result['replacements']], ['changed-position', 'e1'])

    async def test_timeout_keeps_partial_savings_and_stops_starting_more_work(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        calls = []
        def compress(text):
            calls.append(text)
            if text.endswith('slow'):
                gate.wait(2)
            return 'Useful summary.'
        self.service.compressor = compress
        # Allow ordinary thread-pool scheduling before reaching the deliberately
        # blocked second output. The two-second gate still exceeds this budget.
        value = request(self.text, budget_ms=500)
        for suffix in ('slow', 'later'):
            entry = request(self.text + suffix)['entries'][0]
            entry['id'] = suffix
            value['entries'].append(entry)
        reply = await self.service.transform(value)
        self.assertEqual(reply['outcome'], 'compressed')
        self.assertEqual([x['id'] for x in reply['replacements']], ['e1'])
        gate.set()
        async with asyncio.timeout(2):
            while self.service._active:
                await asyncio.sleep(.005)
        self.assertEqual(len(calls), 2, 'Must not start another output after the deadline')
        reply = await self.service.transform(dict(value, budget_ms=500))
        self.assertEqual(len(reply['replacements']), 3)
        self.assertEqual(len(calls), 3)

    async def test_busy_workers_can_still_return_cached_savings(self):
        await self.service.transform(request(self.text))
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.service.compressor = lambda text: gate.wait(2) and 'Useful summary.'
        await asyncio.gather(
            self.service.transform(request(self.text + 'slow', budget_ms=10)),
            self.service.transform(request(self.text + 'slow2', budget_ms=10)))
        reply = await self.service.transform(request(self.text, scope_id='new-request'))
        self.assertEqual(reply['outcome'], 'compressed')
        gate.set()

    async def test_transient_failure_is_not_cached_for_thirty_minutes(self):
        self.service.compressor = lambda text: (_ for _ in ()).throw(ValueError('PRIVATE'))
        self.assertEqual((await self.service.transform(request(self.text)))['outcome'], 'bypassed')
        self.service.compressor = lambda text: 'Recovered summary.'
        self.assertEqual((await self.service.transform(request(self.text)))['outcome'], 'compressed')

    async def test_unchanged_output_is_also_reused_in_growing_history(self):
        calls = []
        self.service.compressor = lambda text: calls.append(text) or text
        await self.service.transform(request(self.text))
        await self.service.transform(request(self.text, scope_id='new-request'))
        self.assertEqual(calls, [self.text])

    async def test_entry_cache_rechecks_original_expiry_across_request_scopes(self):
        await self.service.transform(request(self.text))
        self.now += 1801
        reply = await self.service.transform(request(self.text, scope_id='later-request'))
        self.assertEqual(self.calls, 2)
        self.assertEqual(self.store.retrieve(reply['replacements'][0]['retrieval_reference']), self.text)

    async def test_pause_keeps_originals_and_restart_can_retrieve(self):
        reply = await self.service.transform(request(self.text))
        ref = reply['replacements'][0]['retrieval_reference']
        self.service.enabled = False
        self.assertEqual((await self.service.transform(request(self.text)))['outcome'], 'bypassed')
        reopened = module.OriginalStore(self.root / 'originals.db', clock=lambda: self.now)
        self.assertEqual(reopened.retrieve(ref), self.text)

    async def test_timeout_keeps_slots_occupied_until_workers_finish(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.service.compressor = lambda text: gate.wait(2) or 'summary'
        first, second = await asyncio.gather(
            self.service.transform(request(self.text, budget_ms=15)),
            self.service.transform(request(self.text, scope_id='s2', budget_ms=15)))
        self.assertEqual(first['outcome'], 'bypassed')
        self.assertEqual(second['outcome'], 'bypassed')
        third = await self.service.transform(request(self.text, scope_id='s3'))
        self.assertEqual(third['reason'], 'busy')
        gate.set()


if __name__ == '__main__':
    unittest.main()
