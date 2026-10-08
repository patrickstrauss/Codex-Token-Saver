"""Laya entry tool for bounded explicit bundle operations."""
import asyncio
import json
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from bundle_router import query
from exact_retrieval import sign_exact_response

ROOT = Path(__file__).resolve().parent
server = Server('codex-token-saver', instructions='Route explicit bundle work through bundle_query. For call shapes and code syntax, prefer ast-grep: supply pattern and language; Laya validates this typed route without model loading. Results contain exact matches and pagination. Use literal search for text, Serena for named symbols/references. Other intents use the classifier. Use exact=true before edits. Respect toggles. Automatic compression/hooks stay fast. Codex model routing is unchanged. Supply caller_task_id only when known.')


@server.list_tools()
async def list_tools():
    strings = {'path': 'Existing path inside project (file for reads; directory allowed for structural search).',
               'symbol': 'Optional exact symbol/name path for Serena.',
               'pattern': 'Structural syntax, not a regex. Example: console.log($$$ARGS) finds calls with any arguments, ignoring comments/strings. Pair with language; no symbol/git/browser fields.',
               'language': 'ast-grep language, for example javascript or python.',
               'browser_session': 'Existing named Playwright CLI session; read-only snapshot only.',
               'caller_task_id': 'Current caller chat UUID for activity attribution, if known. Never use another chat ID.'}
    properties = {'intent': {'type': 'string', 'maxLength': 1200}, 'project': {'type': 'string'},
                  **{key: {'type': 'string', 'description': description, 'maxLength': 500} for key, description in strings.items()},
                  'git_operation': {'enum': ['status', 'diff', 'log']},
                  'max_matches': {'type': 'integer', 'minimum': 1, 'maximum': 200, 'default': 50, 'description': 'Structural search page size; exact match text and 1-based locations are preserved.'},
                  'offset': {'type': 'integer', 'minimum': 0, 'maximum': 1000000, 'default': 0, 'description': 'Repeat the same structural query using next_offset to get more matches. Paging reruns search; results can change when files change.'},
                  'exact': {'type': 'boolean', 'default': False}}
    return [Tool(name='bundle_query', description='Main bundle entry. Prefer structural search for call shapes, nested expressions or repeated code: provide pattern + language (JavaScript ipcMain.handle($$$ARGS), Python subprocess.run($$$ARGS)). Exact, paged matches through Laya without classifier startup. For named symbols use symbol/path; file reads use path; Git reports use git_operation. Also supports existing browser snapshots. No arbitrary commands or source rewrites.',
                 inputSchema={'type': 'object', 'properties': properties, 'required': ['intent', 'project'], 'additionalProperties': False},
                 annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))]


@server.call_tool()
async def call_tool(name, arguments):
    try:
        if name != 'bundle_query':
            raise ValueError('Unknown bundle tool.')
        result = await asyncio.to_thread(query, ROOT, arguments or {})
        return CallToolResult(content=[TextContent(type='text', text=sign_exact_response(json.dumps(result, ensure_ascii=False), root=ROOT))])
    except Exception as error:
        return CallToolResult(isError=True, content=[TextContent(type='text', text=str(error))])


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == '__main__':
    asyncio.run(main())
