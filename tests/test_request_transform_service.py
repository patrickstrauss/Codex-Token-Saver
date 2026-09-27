import hashlib
import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import request_transform as core
    import request_transform_service as module
except ImportError:
    core = module = None


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    def test_file_policy_requires_explicit_typed_enable_and_fails_closed(self):
        from request_transform_service import transform_enabled
        root = Path(self.folder.name)
        policy = root / 'proxy/opencodex-policy.json'
        self.assertFalse(transform_enabled(root))
        policy.parent.mkdir()
        for text, expected in (
            ('{"schema":1,"enabled":true}', True),
            ('{"schema":1,"enabled":false}', False),
            ('{"schema":true,"enabled":true}', False),
            ('{"schema":1,"enabled":"true"}', False), ('[]', False), ('broken', False),
            (' ' * 1025, False),
        ):
            policy.write_text(text)
            self.assertIs(transform_enabled(root), expected)

    def test_tool_config_does_not_reapply_recent_conversation_protection(self):
        config = module.tool_compression_config()
        self.assertEqual(config.protect_recent, 0)
        self.assertIsNone(config.savings_profile)
        self.assertFalse(config.compress_user_messages)
        self.assertFalse(config.compress_system_messages)

    async def asyncSetUp(self):
        self.assertIsNotNone(module, 'Transform endpoints are missing')
        import httpx
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        self.service = core.TransformService(lambda text: 'summary', core.OriginalStore(root / 'originals.db'),
                                             root=root, token_counter=len)
        self.addCleanup(self.service.close)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=module.create_transform_app(self.service, token='t' * 64)),
                                       base_url='http://127.0.0.1:8789')
        self.addAsyncCleanup(self.client.aclose)
        self.headers = {'Authorization': 'Bearer ' + 't' * 64}

    async def test_capabilities_and_transform_require_token(self):
        self.assertEqual((await self.client.get('/v1/transform/capabilities')).status_code, 401)
        result = await self.client.get('/v1/transform/capabilities', headers=self.headers)
        self.assertEqual(result.json()['protocol'], 1)
        self.assertEqual((await self.client.post('/v1/transform/tool-results', json={})).status_code, 401)

    async def test_does_not_have_a_provider_forwarding_route(self):
        for path in ('/v1/responses', '/responses', '/v1/chat/completions'):
            self.assertEqual((await self.client.post(path, json={}, headers=self.headers)).status_code, 404)

    async def test_retrieval_survives_pause_and_checks_auth(self):
        text = 'A long original diagnostic.\r\n' * 200
        payload = {'protocol': 1, 'request_id': 'r', 'scope_id': 's', 'budget_ms': 500,
                   'entries': [{'id': 'a', 'original_sha256': hashlib.sha256(text.encode()).hexdigest(), 'text': text}]}
        response = await self.client.post('/v1/transform/tool-results', json=payload, headers=self.headers)
        ref = response.json()['replacements'][0]['retrieval_reference']
        import json
        ledger = Path(self.folder.name) / 'proxy/transform-state/savings_events.jsonl'
        first = json.loads(ledger.read_text().splitlines()[0])
        self.assertGreater(first['saved'], 0)
        self.assertEqual(first['before'], len(text))
        await self.client.post('/v1/transform/tool-results', json=payload, headers=self.headers)
        self.assertEqual(len(ledger.read_text().splitlines()), 2)  # Cached replies count too.
        self.service.enabled = False
        self.assertEqual((await self.client.get('/v1/retrieve/' + ref)).status_code, 401)
        exact = await self.client.get('/v1/retrieve/' + ref, headers=self.headers)
        self.assertEqual(exact.json()['original_content'], text)
        self.assertEqual((await self.client.get('/v1/retrieve/' + '0' * 12, headers=self.headers)).status_code, 404)


if __name__ == '__main__':
    unittest.main()
