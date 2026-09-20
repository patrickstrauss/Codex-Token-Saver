"""Read an existing proxy original through real MCP stdio; never send model traffic.

Usage: python tests/smoke_exact_mcp.py <existing-12-character-reference>
Only a bounded original lookup reaches the live backend. MCP accounting uses a
temporary state directory; the SDK transform runs in this isolated process.
"""
import asyncio
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import MethodType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def verify(reference):
    from exact_retrieval import exact_response_is_verified
    from proxy_retrieval import read_proxy_original
    from proxy_runtime import _guard_exact_responses
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from headroom.proxy.handlers.openai import OpenAIHandlerMixin
    from headroom.transforms.content_router import ContentRouter, ContentRouterConfig

    # Do not create any production signing/state files just for this probe.
    if not (ROOT / 'proxy/exact-retrieval.key').is_file():
        raise RuntimeError('The installed exact-response signing key is not initialized')
    original = read_proxy_original(reference)
    if len(original.splitlines()) > 10000:
        raise RuntimeError('Choose an existing original within the MCP full-window limit')
    with tempfile.TemporaryDirectory(prefix='headroom-mcp-exact-smoke-') as temporary:
        environment = dict(os.environ)
        environment['HEADROOM_WORKSPACE_DIR'] = temporary
        environment['HEADROOM_OFFLINE'] = '1'
        environment['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
        server = StdioServerParameters(command=sys.executable, args=[str(ROOT / 'desktop_mcp.py')],
                                       env=environment, cwd=str(ROOT))
        with open(os.devnull, 'w') as errors:
            async with stdio_client(server, errlog=errors) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    retrieve = next(tool for tool in listing.tools if tool.name == 'headroom_retrieve')
                    schema = retrieve.inputSchema['properties']['content_hash']['pattern']
                    if '{12}' not in schema or '{24}' not in schema:
                        raise RuntimeError('Real MCP process still exposes the old retrieval schema')
                    result = await session.call_tool('headroom_retrieve', {
                        'content_hash': reference, 'start_line': 1, 'max_lines': 10000})
        if result.isError or len(result.content) != 1 or result.content[0].type != 'text':
            raise RuntimeError('MCP exact retrieval failed')
        text = result.content[0].text
        body = text.split('\n\n', 1)[1]
        if body != original or not exact_response_is_verified(text):
            raise RuntimeError('MCP original bytes or source receipt did not verify')

        handler = OpenAIHandlerMixin()
        router = ContentRouter(ContentRouterConfig(enable_kompress=False, lossless=True))
        router._cross_turn_dedup_enabled = True
        handler.openai_pipeline = [router]
        handler.config = None
        handler.openai_provider = SimpleNamespace(get_token_counter=lambda model: SimpleNamespace(count_text=lambda value: len(value)))
        method = OpenAIHandlerMixin._compress_openai_responses_live_text_units_with_router
        handler._compress_openai_responses_live_text_units_with_router = MethodType(_guard_exact_responses(method), handler)
        wrapped = json.dumps(result.model_dump(mode='json'))
        prefix = 'Script completed\nWall time: 0.25 seconds\nOutput:\n'
        plain_prefix = 'Script completed\nWall time 0.9 seconds\nOutput:\n'
        payload = {'model': 'gpt-6-astra', 'reasoning': {'effort': 'ultra'}, 'input': [
            {'type': 'custom_tool_call', 'name': 'functions.exec', 'call_id': 'exact-live', 'input': 'nested MCP retrieval'},
            {'type': 'custom_tool_call_output', 'call_id': 'exact-live', 'output': wrapped},
            {'type': 'custom_tool_call_output', 'call_id': 'exact-opaque', 'output': text},
            {'type': 'custom_tool_call_output', 'call_id': 'exact-repeat', 'output': text},
            {'type': 'custom_tool_call_output', 'call_id': 'exact-prefixed-json', 'output': prefix + wrapped},
            {'type': 'custom_tool_call_output', 'call_id': 'exact-prefixed-raw', 'output': prefix + text},
            {'type': 'custom_tool_call_output', 'call_id': 'exact-prefixed-many', 'output': prefix + '{"notice":"first output"}\n' + wrapped},
            {'type': 'custom_tool_call_output', 'call_id': 'exact-no-colon-json', 'output': plain_prefix + wrapped},
            {'type': 'custom_tool_call_output', 'call_id': 'exact-no-colon-raw', 'output': plain_prefix + text},
        ]}
        before = json.dumps(payload, sort_keys=True)
        for turn in range(3):
            processed = handler._compress_openai_responses_payload(
                payload, model='gpt-4o', request_id=f'isolated-live-original-{turn}')
            if processed[0] != payload or processed[2] != 0:
                raise RuntimeError('Exact original was transformed or counted as savings')
            if processed[5] != processed[6] or before != json.dumps(payload, sort_keys=True):
                raise RuntimeError('Original request bytes were not preserved')
        return {'ok': True, 'reference': reference, 'source': 'existing live proxy original',
                'original_bytes': len(original.encode('utf-8')),
                'original_sha256': hashlib.sha256(original.encode('utf-8')).hexdigest(),
                'real_mcp_stdio': True, 'schema_accepts_12_and_24': True,
                'exact_body_verified': True, 'signed_receipt_verified': True,
                'real_outer_sdk_transform_verified': True, 'repeated_passes': 3,
                'exec_metadata_raw_json_and_multiblock_verified': True,
                'exec_wall_time_with_and_without_colon_verified': True,
                'exact_savings_claimed': 0, 'production_model_requests': 0}


if __name__ == '__main__':
    try:
        print(json.dumps(asyncio.run(verify(sys.argv[1])), sort_keys=True))
    except Exception as error:
        # Keep original contents, requests, and credentials out of the report.
        print(json.dumps({'ok': False, 'error_type': type(error).__name__, 'message': str(error)[:240]}))
        raise SystemExit(1)
