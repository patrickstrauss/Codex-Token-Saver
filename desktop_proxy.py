"""Fast Codex relay. Compression is optional; upstream requests are never replayed."""
from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

import aiohttp
from aiohttp import web
from multidict import CIMultiDict
from yarl import URL

ROOT = Path(__file__).resolve().parent
UPSTREAMS = {'api': 'https://api.openai.com/v1', 'chatgpt': 'https://chatgpt.com/backend-api/codex'}
HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
               'te', 'trailer', 'transfer-encoding', 'upgrade', 'host'}
WS_HEADERS = {'sec-websocket-key', 'sec-websocket-version', 'sec-websocket-extensions',
              'sec-websocket-protocol', 'sec-websocket-accept'}


def resolve_upstream(headers, mode='auto'):
    """Use explicit auth hints without storing or reporting credentials."""
    headers = CIMultiDict(headers)
    authorization = headers.get('Authorization', '')
    scheme, _, token = authorization.partition(' ')
    if scheme.lower() != 'bearer' or not token:
        raise ValueError('OpenAI authorization is required.')
    if token.startswith('sk-'):
        if headers.get('ChatGPT-Account-ID') or mode == 'chatgpt':
            raise ValueError('Conflicting API-key and ChatGPT routing hints.')
        return 'api'
    if headers.get('ChatGPT-Account-ID'):
        if mode == 'api':
            raise ValueError('Conflicting ChatGPT and API routing hints.')
        return 'chatgpt'
    if mode in ('api', 'chatgpt'):
        return mode
    if len(token) < 65536:
        try:
            payload = token.split('.')[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
            auth = claims.get('https://api.openai.com/auth', {})
            if isinstance(auth, dict) and auth.get('chatgpt_account_id'):
                return 'chatgpt'
        except (ValueError, IndexError, TypeError, AttributeError):
            pass
    raise ValueError('Credential type is not recognized. Select the correct upstream mode before routing this account.')


def target_url(base, raw_path):
    # Concatenation deliberately avoids urljoin, which can replace the host.
    suffix = raw_path[4:] if raw_path.startswith('/v1/') else raw_path.lstrip('/')
    return base.rstrip('/') + '/' + suffix.lstrip('/')


def forwarded_headers(headers, websocket=False):
    excluded = HOP_HEADERS | (WS_HEADERS if websocket else set())
    excluded |= {item.strip().lower() for item in headers.get('Connection', '').split(',')}
    return CIMultiDict((key, value) for key, value in headers.items()
                      if key.lower() not in excluded and not key.lower().startswith('x-headroom-'))


class Relay:
    def __init__(self, root, backend_url, upstreams, allow_test_host=False):
        self.root = Path(root)
        self.state = self.root / 'proxy'
        self.backend_url = backend_url.rstrip('/')
        self.upstreams = dict(upstreams)
        self.allow_test_host = allow_test_host
        self.session = None
        self.health_at = 0.0
        self.backend_ready = False
        self.health_lock = asyncio.Lock()
        self.active = 0
        self.counts = {'optimized': 0, 'direct': 0, 'failed': 0}
        try:
            value = json.loads((self.state / 'gateway-stats.json').read_text(encoding='utf-8'))
            for key in self.counts:
                count = value.get('requests', {}).get(key)
                if type(count) is int and count >= 0:
                    self.counts[key] = count
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def settings(self):
        try:
            path = self.state / 'settings.json'
            if path.stat().st_size > 65536:
                return {}
            value = json.loads(path.read_text(encoding='utf-8-sig'))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    async def check_backend(self):
        if time.monotonic() - self.health_at < 1:
            return self.backend_ready
        async with self.health_lock:
            if time.monotonic() - self.health_at < 1:
                return self.backend_ready
            ready = False
            try:
                async with self.session.get(self.backend_url + '/health', timeout=aiohttp.ClientTimeout(total=.8)) as response:
                    value = await response.json()
                    ready = response.status == 200 and value.get('service') == 'headroom-proxy' and value.get('ready') is True and value.get('status') == 'healthy'
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, AttributeError):
                pass
            self.backend_ready, self.health_at = ready, time.monotonic()
            return ready

    def snapshot(self):
        settings = self.settings()
        enabled = settings.get('enabled') is True
        return {'service': 'codex-token-saver-proxy', 'status': 'ok', 'ready': True,
                'pid': os.getpid(), 'enabled': enabled, 'backend_ready': self.backend_ready,
                'mode': 'optimized' if enabled and self.backend_ready else 'direct',
                'requests': dict(self.counts, active=self.active),
                'timestamp': datetime.now(timezone.utc).isoformat()}

    def record(self, destination, failed=False):
        self.counts[destination] += 1
        if failed:
            self.counts['failed'] += 1
        try:
            self.state.mkdir(parents=True, exist_ok=True)
            temporary = self.state / ('gateway-stats.' + str(os.getpid()) + '.tmp')
            temporary.write_text(json.dumps(self.snapshot()), encoding='utf-8')
            os.replace(temporary, self.state / 'gateway-stats.json')
        except OSError:
            pass  # Bookkeeping must not interrupt an already-delivered response.

    def validate_client(self, request):
        if not self.allow_test_host and request.host not in ('127.0.0.1:8788', 'localhost:8788'):
            raise web.HTTPForbidden(text='Unexpected relay host.')
        if request.headers.get('Origin'):
            raise web.HTTPForbidden(text='Browser-origin requests are not supported by this relay.')

    async def health(self, request):
        self.validate_client(request)
        return web.json_response(self.snapshot(), headers={'Cache-Control': 'no-store'})

    async def stats(self, request):
        self.validate_client(request)
        await self.check_backend()
        return web.json_response(self.snapshot(), headers={'Cache-Control': 'no-store'})

    async def handle(self, request):
        self.validate_client(request)
        try:
            settings = self.settings()
            kind = resolve_upstream(request.headers, settings.get('upstream_mode', 'auto'))
        except ValueError as error:
            return web.json_response({'error': {'message': str(error), 'type': 'relay_configuration_error'}}, status=400)
        direct = target_url(self.upstreams[kind], request.raw_path)
        eligible = request.path in ('/v1/responses', '/responses')
        optimize = eligible and settings.get('enabled') is True and await self.check_backend()
        target = self.backend_url + request.raw_path if optimize else direct
        self.active += 1
        try:
            if request.headers.get('Upgrade', '').lower() == 'websocket':
                return await self.websocket(request, target, direct, optimize)
            return await self.http(request, target, direct, optimize)
        finally:
            self.active -= 1

    async def http(self, request, target, direct, optimize):
        body = await request.read()
        headers = forwarded_headers(request.headers)
        destination = 'optimized' if optimize else 'direct'
        try:
            try:
                response = await self.session.request(request.method, URL(target, encoded=True), data=body, headers=headers, allow_redirects=False)
            except aiohttp.ClientConnectorError:
                if not optimize:
                    raise
                # No backend connection was established, so nothing was sent.
                self.backend_ready, self.health_at = False, time.monotonic()
                destination = 'direct'
                response = await self.session.request(request.method, URL(direct, encoded=True), data=body, headers=headers, allow_redirects=False)
            async with response:
                outgoing = web.StreamResponse(status=response.status, headers=forwarded_headers(response.headers))
                await outgoing.prepare(request)
                async for chunk in response.content.iter_any():
                    await outgoing.write(chunk)
                await outgoing.write_eof()
                self.record(destination, response.status >= 500)
                return outgoing
        except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError):
            self.record(destination, True)
            # No second dispatch after timeout, response headers or stream failure.
            if 'outgoing' in locals() and outgoing.prepared:
                if request.transport:
                    request.transport.close()
                return outgoing
            return web.json_response({'error': {'message': 'The upstream connection failed. The relay did not replay the request.', 'type': 'relay_upstream_error'}}, status=502)

    async def websocket(self, request, target, direct, optimize):
        headers = forwarded_headers(request.headers, websocket=True)
        protocols = tuple(value.strip() for value in request.headers.get('Sec-WebSocket-Protocol', '').split(',') if value.strip())
        destination = 'optimized' if optimize else 'direct'

        async def connect(url):
            websocket_url = URL(url, encoded=True).with_scheme('wss' if url.startswith('https:') else 'ws')
            return await self.session.ws_connect(websocket_url, headers=headers, protocols=protocols,
                                                 max_msg_size=0, heartbeat=None, autoping=True, autoclose=False)
        try:
            try:
                upstream = await connect(target)
            except aiohttp.ClientConnectorError:
                if not optimize:
                    raise
                self.backend_ready, self.health_at = False, time.monotonic()
                destination = 'direct'
                upstream = await connect(direct)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            self.record(destination, True)
            return web.json_response({'error': {'message': 'WebSocket upstream unavailable; no request was replayed.'}}, status=502)

        response_headers = getattr(getattr(upstream, '_response', None), 'headers', {})
        downstream = web.WebSocketResponse(protocols=(upstream.protocol,) if upstream.protocol else (), max_msg_size=0, heartbeat=None, autoclose=False)
        for key, value in forwarded_headers(response_headers, websocket=True).items():
            if key.lower().startswith('x-') or key.lower() in ('openai-version',):
                downstream.headers[key] = value
        failed = False
        try:
            await downstream.prepare(request)

            async def relay(source, target_socket):
                nonlocal failed
                while True:
                    message = await source.receive()
                    if message.type == aiohttp.WSMsgType.TEXT:
                        await target_socket.send_str(message.data)
                    elif message.type == aiohttp.WSMsgType.BINARY:
                        await target_socket.send_bytes(message.data)
                    elif message.type == aiohttp.WSMsgType.CLOSE:
                        code = message.data if isinstance(message.data, int) else 1000
                        if code in (1004, 1005, 1006, 1015):
                            code = 1011
                        failed = failed or code not in (1000, 1001)
                        await target_socket.close(code=code, message=str(message.extra or '').encode('utf-8'))
                        break
                    elif message.type == aiohttp.WSMsgType.ERROR:
                        failed = True
                        await target_socket.close(code=1011, message=b'Upstream connection ended unexpectedly')
                        break
                    elif message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                        code = source.close_code or 1000
                        if code in (1004, 1005, 1006, 1015):
                            code = 1011
                        failed = failed or code not in (1000, 1001)
                        if not target_socket.closed:
                            await target_socket.close(code=code)
                        break

            jobs = [asyncio.create_task(relay(downstream, upstream)), asyncio.create_task(relay(upstream, downstream))]
            try:
                done, _ = await asyncio.wait(jobs, return_when=asyncio.FIRST_COMPLETED)
                for job in done:
                    if not job.cancelled() and job.exception():
                        failed = True
                        if not downstream.closed:
                            await downstream.close(code=1011, message=b'Relay connection ended unexpectedly')
            finally:
                for job in jobs:
                    job.cancel()
                await asyncio.gather(*jobs, return_exceptions=True)
        finally:
            # Native Codex may close its socket without a close frame. aiohttp
            # then cancels this handler, but the completed connection still counts.
            self.record(destination, failed or bool(upstream.exception() or downstream.exception()))
            await upstream.close()
            await downstream.close()
        return downstream


def create_app(root=ROOT, *, backend_url='http://127.0.0.1:8789', upstreams=None, allow_test_host=False):
    relay = Relay(root, backend_url, upstreams or UPSTREAMS, allow_test_host)
    # Preserve encoded payload bytes and their Content-Encoding/Content-Length.
    # aiohttp otherwise transparently inflates bodies before request.read().
    app = web.Application(client_max_size=64 * 1024 * 1024,
                          handler_args={'auto_decompress': False})

    async def lifecycle(app):
        relay.session = aiohttp.ClientSession(auto_decompress=False, trust_env=False,
                                             timeout=aiohttp.ClientTimeout(total=None, sock_connect=10),
                                             connector=aiohttp.TCPConnector(limit=0), skip_auto_headers={'User-Agent', 'Content-Type'})
        yield
        await relay.session.close()

    app.cleanup_ctx.append(lifecycle)
    app.router.add_get('/health', relay.health)
    app.router.add_get('/stats', relay.stats)
    app.router.add_route('*', '/{path:.*}', relay.handle)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8788)
    parser.add_argument('--backend-port', type=int, default=8789)
    args = parser.parse_args()
    if args.port != 8788 or args.backend_port != 8789:
        parser.error('The installed relay uses fixed loopback ports 8788 and 8789.')
    web.run_app(create_app(), host='127.0.0.1', port=args.port, access_log=None,
                print=None, handler_cancellation=True)


if __name__ == '__main__':
    main()
