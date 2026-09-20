"""Optional local Headroom file tools for Codex desktop; no proxy or credentials."""
import asyncio
import json
import logging
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
from runtime_selection import activate_headroom_runtime
activate_headroom_runtime(ROOT)
STATE = Path(os.environ.get('HEADROOM_WORKSPACE_DIR', ROOT / 'headroom/desktop-state'))
# These settings apply only to this local tool process, before any SDK import.
os.environ.update({'HEADROOM_WORKSPACE_DIR': str(STATE), 'HEADROOM_OFFLINE': '1',
    'HEADROOM_TELEMETRY': 'off', 'HEADROOM_LOG_PAYLOAD_PREVIEW': '0',
    'HF_HUB_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1', 'TRANSFORMERS_OFFLINE': '1',
    'LITELLM_LOCAL_MODEL_COST_MAP': 'True',
    'TIKTOKEN_CACHE_DIR': str(ROOT / 'headroom/tokenizer-cache')})

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from jsonschema import ValidationError, validate

RETRIEVAL_HELP = (
    'Use {"content_hash":"abcdef123456","start_line":1,"max_lines":1200}. '
    'Copy only the 12-character proxy or 24-character local hexadecimal reference; '
    'do not pass the full <<ccr:...>> marker or use id/hash aliases. '
    'start_line is a 1-based positive integer; max_lines is a count from 1 to 10000, '
    'not an ending line number. No end_line argument is supported.'
)

INSTRUCTIONS = (
    'Prefer headroom_read_file for initial inspection of large local JSON, CSV, and logs. '
    'Use absolute paths. Compressed overviews can omit details; use headroom_retrieve or '
    'compress=false before precise edits, quotations, or completeness-sensitive decisions. '
    'For retrieval, pass the reference as content_hash, not id or hash. '
    'If these tools fail or are unavailable, continue with ordinary file tools. '
    'All compression is local; these tools never route Codex requests or change its model.'
)
server = Server('headroom-desktop', version='1.0.0', instructions=INSTRUCTIONS)
backend = None

def get_backend():
    global backend
    if backend is None:
        from desktop_headroom import DesktopHeadroom
        backend = DesktopHeadroom(STATE)
    return backend

RANGE_FIELDS = {
    'start_line': {'type': 'integer', 'minimum': 1, 'default': 1,
                   'description': 'First original line to return, starting at 1.'},
    'max_lines': {'type': 'integer', 'minimum': 1, 'maximum': 10000, 'default': 1200,
                  'description': 'Number of original lines to return, not an ending line number.'},
}
ANNOTATIONS = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
    idempotentHint=True, openWorldHint=False)

@server.list_tools()
async def list_tools():
    return [
        Tool(name='headroom_read_file', description='Read a large local UTF-8 file through Headroom. '
             'JSON/log overviews may be compressed. Use compress=false for exact content. Maximum file size 2 MB.',
             inputSchema={'type':'object', 'properties': {
                 'path': {'type':'string', 'description':'Absolute local file path'},
                 **RANGE_FIELDS, 'compress': {'type':'boolean', 'default':True}},
                 'required':['path'], 'additionalProperties':False}, annotations=ANNOTATIONS),
        Tool(name='headroom_retrieve', description='Retrieve exact original text using a 24-character local content_hash '
             'or the 12-character reference in a proxy <<ccr:...>> marker. Line numbers refer to the original. '
             'Local originals expire after 24 hours; proxy originals normally expire after 30 minutes. '
             + RETRIEVAL_HELP,
             inputSchema={'type':'object', 'properties': {
                 'content_hash': {'type':'string', 'pattern':'^(?:[0-9a-fA-F]{12}|[0-9a-fA-F]{24})$',
                                  'description':'Bare reference from content_hash=... or <<ccr:REFERENCE,...>>; no marker or URL.'},
                 **RANGE_FIELDS},
                 'required':['content_hash'], 'additionalProperties':False}, annotations=ANNOTATIONS),
        Tool(name='headroom_stats', description='Read local Headroom file-tool savings estimates. '
             'Net savings subtract returned headers and subsequent retrievals; not account usage or billing.',
             inputSchema={'type':'object','properties':{},'additionalProperties':False}, annotations=ANNOTATIONS),
    ]

def invoke(name, arguments):
    service = get_backend()
    if name == 'headroom_read_file':
        return service.read_file(**arguments)
    if name == 'headroom_retrieve':
        return service.retrieve(**arguments)
    if name == 'headroom_stats':
        if arguments:
            raise ValueError('headroom_stats takes no arguments')
        return json.dumps(service.stats())
    raise ValueError('Unknown Headroom tool')

@server.call_tool(validate_input=False)
async def call_tool(name, arguments):
    try:
        # Keep schema validation for every tool, with corrective retrieval guidance
        # instead of treating caller mistakes as a service outage.
        tool = next((tool for tool in await list_tools() if tool.name == name), None)
        if tool is None:
            raise ValueError('Unknown Headroom tool')
        try:
            validate(arguments or {}, tool.inputSchema)
        except ValidationError as exc:
            message = ('Invalid headroom_retrieve arguments. ' + RETRIEVAL_HELP
                       if name == 'headroom_retrieve' else f'Invalid {name} arguments: {exc.message}')
            return CallToolResult(isError=True, content=[TextContent(type='text', text=message)])
        result = await asyncio.to_thread(invoke, name, arguments or {})
        return [TextContent(type='text', text=result)]
    except Exception as exc:
        return CallToolResult(isError=True, content=[TextContent(type='text',
            text=f'Headroom file tool unavailable: {exc}. Continue with ordinary file tools.')])

async def main():
    logging.basicConfig(level=logging.WARNING)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == '__main__':
    asyncio.run(main())
