"""One optional bundle entry tool; direct MCP tools and Codex settings stay intact."""
import asyncio
import json
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations
from bundle_router import query
from exact_retrieval import sign_exact_response

ROOT = Path(__file__).resolve().parent
server = Server('codex-token-saver', instructions='Experimental Laya-first bundle query. Supply a bounded intent and explicit project/arguments. Laya selects among enabled tools; ambiguous decisions return without executing. This does not intercept other tools or change Codex models. Use exact=true before precise edits or quotations. Summary start requires an explicit user request; browsers must already have a named session.')


@server.list_tools()
async def list_tools():
    strings = {'path': 'Existing path inside project (file for reads; directory allowed for structural search).',
               'symbol': 'Optional exact symbol/name path for Serena.',
               'pattern': 'Literal ast-grep syntax pattern; never shell code.',
               'language': 'ast-grep language, for example javascript or python.',
               'browser_session': 'Existing named Playwright CLI session; read-only snapshot only.',
               'task_id': 'Explicit local task UUID for summaries.'}
    properties = {'intent': {'type': 'string', 'maxLength': 1200}, 'project': {'type': 'string'},
                  **{key: {'type': 'string', 'description': description, 'maxLength': 500} for key, description in strings.items()},
                  'git_operation': {'enum': ['status', 'diff', 'log']},
                  'summary_action': {'enum': ['read', 'start'], 'description': 'start only when the user explicitly requests summary generation.'},
                  'exact': {'type': 'boolean', 'default': False}}
    return [Tool(name='bundle_query', description='Ask local Laya to select and execute an enabled bundle tool sequence: Headroom file read, Serena, ast-grep, RTK Git report, existing browser snapshot, or explicitly selected task summary. No arbitrary commands or source rewrites.',
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
