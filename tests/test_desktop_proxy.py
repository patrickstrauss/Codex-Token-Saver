import asyncio
import base64
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from desktop_proxy import create_app, forwarded_headers, resolve_upstream, target_url


class RoutingTests(unittest.TestCase):
    def test_auth_destinations_and_query_are_preserved(self):
        payload = base64.urlsafe_b64encode(json.dumps({'https://api.openai.com/auth': {'chatgpt_account_id': 'fixture'}}).encode()).decode().rstrip('=')
        self.assertEqual(resolve_upstream({'Authorization': 'Bearer x.' + payload + '.x'}), 'chatgpt')
        self.assertEqual(resolve_upstream({'Authorization': 'Bearer sk-fixture'}), 'api')
        self.assertEqual(target_url('https://chatgpt.com/backend-api/codex', '/v1/responses?x=a%2Bb'), 'https://chatgpt.com/backend-api/codex/responses?x=a%2Bb')
        with self.assertRaises(ValueError):
            resolve_upstream({'Authorization': 'Bearer unknown'})

    def test_custom_upstream_headers_cannot_override_official_destination(self):
        headers = forwarded_headers({'Authorization': 'Bearer sk-fixture', 'X-Headroom-Base-Url': 'https://untrusted.invalid', 'X-Headroom-Original-Path': '/collect'})
        self.assertEqual(dict(headers), {'Authorization': 'Bearer sk-fixture'})
        with self.assertRaises(ValueError):
            resolve_upstream({'ChatGPT-Account-ID': 'fixture'})
        with self.assertRaises(ValueError):
            resolve_upstream({'ChatGPT-Account-ID': 'fixture', 'Authorization': 'Bearer sk-fixture'})


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / 'proxy'
        self.state.mkdir()
        (self.state / 'settings.json').write_text('{"installed":true,"enabled":true}')
        self.seen = []
        self.backend_ready = True
        self.backend_status = 200
        self.servers = []

        async def health(request):
            return web.json_response({'service': 'headroom-proxy', 'status': 'healthy', 'ready': self.backend_ready})

        async def answer(request):
            destination = request.app['destination']
            if request.headers.get('Upgrade', '').lower() == 'websocket':
                ws = web.WebSocketResponse(max_msg_size=0)
                await ws.prepare(request)
                if request.headers.get('X-Fixture-Close'):
                    await ws.close(code=1011, message=b'fixture unavailable')
                    return ws
                async for message in ws:
                    self.seen.append((destination, 'ws', message.data))
                    if isinstance(message.data, bytes):
                        await ws.send_bytes(message.data)
                    else:
                        await ws.send_str(message.data)
                return ws
            body = await request.read()
            self.seen.append((destination, request.raw_path, body, request.headers.get('Authorization'), request.headers.get('X-Codex-Turn-Metadata')))
            if destination == 'backend' and self.backend_status != 200:
                return web.Response(status=self.backend_status, text='upstream failed')
            return web.Response(body=b'data: {"type":"response.completed"}\n\n', content_type='text/event-stream', headers={'x-request-id': 'fixture-id'})

        for destination in ('backend', 'direct'):
            app = web.Application(handler_args={'auto_decompress': False})
            app['destination'] = destination
            app.router.add_get('/health', health)
            app.router.add_route('*', '/{tail:.*}', answer)
            server = TestServer(app)
            await server.start_server()
            self.servers.append(server)
        backend, direct = [str(server.make_url('')).rstrip('/') for server in self.servers]
        self.relay = TestServer(create_app(self.root, backend_url=backend, upstreams={'api': direct + '/v1', 'chatgpt': direct + '/backend-api/codex'}, allow_test_host=True))
        await self.relay.start_server()
        self.session = ClientSession()
        self.headers = {'Authorization': 'Bearer sk-fixture', 'X-Codex-Turn-Metadata': 'preserve-me'}

    async def asyncTearDown(self):
        await self.session.close()
        await self.relay.close()
        for server in self.servers:
            await server.close()
        self.temp.cleanup()

    async def post(self):
        body = b'{"model":"gpt-6-astra","reasoning":{"effort":"ultra"},"input":"fixture","stream":true}'
        async with self.session.post(self.relay.make_url('/v1/responses?x=a%2Bb'), data=body, headers=self.headers) as response:
            return response.status, await response.read(), response.headers, body

    async def test_http_sse_preserves_body_headers_and_selected_settings(self):
        status, body, headers, original = await self.post()
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b'data:'))
        self.assertEqual(headers['x-request-id'], 'fixture-id')
        self.assertEqual(self.seen[0], ('backend', '/v1/responses?x=a%2Bb', original, 'Bearer sk-fixture', 'preserve-me'))

    async def test_unready_backend_uses_direct_once(self):
        self.backend_ready = False
        self.assertEqual((await self.post())[0], 200)
        self.assertEqual([item[0] for item in self.seen], ['direct'])

    async def test_backend_error_is_never_replayed_directly(self):
        self.backend_status = 503
        self.assertEqual((await self.post())[0], 503)
        self.assertEqual([item[0] for item in self.seen], ['backend'])

    async def test_pause_keeps_cached_endpoint_serving_direct(self):
        (self.state / 'settings.json').write_text('{"installed":true,"enabled":false}')
        self.assertEqual((await self.post())[0], 200)
        self.assertEqual(self.seen[0][0], 'direct')

    async def test_compressed_request_body_is_forwarded_byte_for_byte(self):
        original = gzip.compress(b'{"model":"gpt-6-astra","reasoning":{"effort":"ultra"},"input":"' + b'unchanged ' * 100 + b'"}')
        headers = dict(self.headers, **{'Content-Encoding': 'gzip', 'Content-Type': 'application/json'})
        async with asyncio.timeout(3):
            async with self.session.post(self.relay.make_url('/v1/responses'), headers=headers, data=original) as response:
                self.assertEqual(response.status, 200)
                await response.read()
        self.assertEqual(self.seen[0][2], original)

    async def test_large_websocket_binary_frame_is_not_truncated(self):
        original = b'x' * (5 * 1024 * 1024)
        # The fixture peer must also permit image-sized frames.
        async with self.session.ws_connect(self.relay.make_url('/v1/responses'), headers=self.headers, max_msg_size=0) as ws:
            await ws.send_bytes(original)
            result = await ws.receive(timeout=3)
        self.assertEqual(result.data, original)

    async def test_new_auxiliary_endpoint_uses_official_root(self):
        async with self.session.get(self.relay.make_url('/v1/models?client_version=fixture'), headers=self.headers) as response:
            self.assertEqual(response.status, 200)
            await response.read()
        self.assertEqual(self.seen[0][:2], ('direct', '/v1/models?client_version=fixture'))

    async def test_websocket_relays_multiple_frames_once(self):
        async with self.session.ws_connect(self.relay.make_url('/v1/responses'), headers=self.headers) as ws:
            for value in ('{"type":"response.create","model":"gpt-6-astra","reasoning":{"effort":"ultra"}}', '{"type":"response.create","previous_response_id":"fixture"}'):
                await ws.send_str(value)
                self.assertEqual((await ws.receive(timeout=2)).data, value)
        self.assertEqual(len(self.seen), 2)
        self.assertTrue(all(item[0] == 'backend' for item in self.seen))

    async def test_websocket_error_close_code_and_reason_reach_client(self):
        headers = dict(self.headers, **{'X-Fixture-Close': '1'})
        async with self.session.ws_connect(self.relay.make_url('/v1/responses'), headers=headers) as ws:
            result = await ws.receive(timeout=3)
        self.assertEqual(result.data, 1011)
        self.assertEqual(result.extra, 'fixture unavailable')

    async def test_client_disconnect_still_records_completed_connection(self):
        ws = await self.session.ws_connect(self.relay.make_url('/v1/responses'), headers=self.headers)
        await ws.send_str('fixture')
        self.assertEqual((await ws.receive(timeout=2)).data, 'fixture')
        ws._response.connection.transport.abort()
        await ws.close()
        async with asyncio.timeout(2):
            while True:
                async with self.session.get(self.relay.make_url('/stats')) as response:
                    stats = await response.json()
                if stats['requests']['active'] == 0:
                    break
                await asyncio.sleep(0.01)
        self.assertEqual(stats['requests']['optimized'], 1)
        self.assertEqual([item[0] for item in self.seen], ['backend'])

    async def test_web_origin_rejected_without_forwarding(self):
        async with self.session.post(self.relay.make_url('/v1/responses'), headers=dict(self.headers, Origin='https://untrusted.invalid'), data=b'{}') as response:
            self.assertEqual(response.status, 403)
        self.assertEqual(self.seen, [])


if __name__ == '__main__':
    unittest.main()
