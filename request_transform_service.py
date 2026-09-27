"""Private loopback ASGI endpoints, with no model-provider forwarding routes."""
import hmac
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

from request_transform import MAX_BYTES


def ensure_transform_token(root):
    path = Path(root) / 'proxy/transform-token'
    if path.exists():
        token = path.read_text(encoding='ascii')
        if len(token) != 64 or any(c not in '0123456789abcdef' for c in token):
            raise ValueError('Invalid transform token')
        return token
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.transform-token-', dir=path.parent)
    try:
        os.close(fd)
        if os.name == 'nt':
            import csv
            system = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32'
            identity = subprocess.run([str(system / 'whoami.exe'), '/user', '/fo', 'csv', '/nh'],
                capture_output=True, text=True, check=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW)
            sid = next(csv.reader([identity.stdout.strip()]))[1]
            subprocess.run([str(system / 'icacls.exe'), temporary, '/inheritance:r', '/grant:r', '*' + sid + ':(F)'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.chmod(temporary, 0o600)
        with open(temporary, 'w', encoding='ascii') as stream:
            stream.write(secrets.token_hex(32))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        os.unlink(temporary)
    return ensure_transform_token(root)


def create_transform_app(service, *, token):
    from starlette.applications import Starlette
    from starlette.requests import ClientDisconnect
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    if not isinstance(token, str) or len(token) != 64:
        raise ValueError('A private transform token is required')

    def authorized(request):
        supplied = request.headers.get('authorization', '')
        return hmac.compare_digest(supplied.encode('utf-8'), ('Bearer ' + token).encode('ascii'))

    async def health(request):
        return JSONResponse({'service': 'headroom-proxy', 'status': 'healthy',
                             'mode': 'transform-only', 'ready': service.ready,
                             'pid': os.getpid()})

    async def capabilities(request):
        if not authorized(request):
            return JSONResponse({'error': 'unauthorized'}, status_code=401)
        return JSONResponse({'protocol': 1, 'ready': service.ready, 'enabled': service.enabled,
                             'max_bytes': MAX_BYTES, 'max_entries': 128, 'budget_ms': 500,
                             'outcomes': dict(service.counts)})

    async def transform(request):
        if not authorized(request):
            return JSONResponse({'error': 'unauthorized'}, status_code=401)
        body = bytearray()
        try:
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_BYTES:
                    return JSONResponse({'error': 'request_too_large'}, status_code=413)
                body.extend(chunk)
            payload = json.loads(body)
        except (ValueError, RecursionError, ClientDisconnect):
            return JSONResponse({'error': 'invalid_request'}, status_code=400)
        result = await service.transform(payload)
        return JSONResponse(result, status_code=400 if result['outcome'] == 'error' else 200)

    async def retrieve(request):
        if not authorized(request):
            return JSONResponse({'error': 'unauthorized'}, status_code=401)
        ref = request.path_params['ref']
        try:
            original = service.store.retrieve(ref)
        except (KeyError, ValueError):
            return JSONResponse({'error': 'original_unavailable'}, status_code=404)
        return JSONResponse({'hash': ref, 'original_content': original})

    return Starlette(routes=[Route('/health', health),
        Route('/v1/transform/capabilities', capabilities),
        Route('/v1/transform/tool-results', transform, methods=['POST']),
        Route('/v1/retrieve/{ref}', retrieve)])


def tool_compression_config():
    from headroom import CompressConfig
    from headroom.agent_savings import apply_agent_savings_profile
    config = CompressConfig()
    apply_agent_savings_profile(config, 'coding')
    config.protect_recent = 0  # The caller selected eligible tool text, not a conversation.
    config.compress_user_messages = False
    config.compress_system_messages = False
    config.savings_profile = None  # Prevent compress() from overwriting these final guards.
    return config


def create_sdk_service(root):
    """Initialize the pinned offline SDK once in the supervised backend child."""
    import threading
    import headroom
    from desktop_headroom import DesktopHeadroom
    from headroom.transforms.kompress_compressor import warm_kompress_model
    from request_transform import OriginalStore, TransformService

    root = Path(root)
    counter = DesktopHeadroom(root / 'proxy/transform-state/tokenizer', bundle_root=root)
    counter._load_local_encoding()
    if not warm_kompress_model(allow_download=False):
        raise RuntimeError('Local compression model is unavailable')
    lock = threading.Lock()
    config = tool_compression_config()

    def compress(text):
        # The public SDK singleton is shared within this worker, never replicated.
        with lock:
            result = headroom.compress([{'role': 'tool', 'content': text}], model='gpt-4o', config=config)
        if not result.messages or result.tokens_before <= 0:
            raise ValueError('Invalid SDK measurements')
        return result.messages[0].get('content')

    return TransformService(compress, OriginalStore(root / 'proxy/transform-state/originals.db'),
                            root=root, token_counter=counter._count)


def serve_transform(root, *, host='127.0.0.1', port=8789):
    from contextlib import asynccontextmanager
    import uvicorn
    from proxy_runtime import _configure_sdk
    if host != '127.0.0.1' or port != 8789:
        raise ValueError('Protocol v1 binds only to 127.0.0.1:8789')
    _configure_sdk(host, port)
    service = create_sdk_service(root)
    token = ensure_transform_token(root)
    app = create_transform_app(service, token=token)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            service.close()

    app.router.lifespan_context = lifespan
    uvicorn.run(app, host=host, port=port, workers=1, access_log=False, log_level='warning')
