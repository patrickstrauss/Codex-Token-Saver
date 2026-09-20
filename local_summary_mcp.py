"""Optional explicit local summaries; never changes the active Codex context."""
import asyncio
import json
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

from exact_retrieval import sign_exact_response
from local_summaries import LocalSummaries

ROOT = Path(__file__).resolve().parent
controller = LocalSummaries(ROOT)
server = Server('bundle-local-summaries', instructions=(
    'Experimental local reference summaries, only when the user requests one for an explicit task. '
    'Do not automatically replace context or native compaction. Summaries can omit details; '
    'original transcripts remain authoritative. No cloud model or provider key is used.'))


@server.list_tools()
async def list_tools():
    empty = {'type': 'object', 'properties': {}, 'additionalProperties': False}
    selected = {'type': 'object', 'properties': {'task_id': {'type': 'string',
        'description': 'Exact task UUID returned by list_local_summary_tasks'}},
        'required': ['task_id'], 'additionalProperties': False}
    return [Tool(name='list_local_summary_tasks', description='List local task IDs and project names for explicit selection. Does not read conversation text.',
                 inputSchema=empty, annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False)),
            Tool(name='refresh_local_summary', description='Summarize the pending history of an explicitly selected task in automatic local batches. Returns job status immediately; completed batches are saved and cancellation keeps them. Requires summaries and llama.cpp enabled; never changes Codex history.',
                 inputSchema=selected, annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)),
            Tool(name='get_local_summary', description='Read the selected task summary, coverage and job status. A local size reduction is not actual Codex token savings.',
                 inputSchema=selected, annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))]


def invoke(name, arguments):
    if not isinstance(arguments, dict):
        raise ValueError('Tool arguments must be an object.')
    if name == 'list_local_summary_tasks' and not arguments:
        return {'tasks': controller.list_tasks(), **controller.status()}
    if set(arguments) != {'task_id'}:
        raise ValueError('Select one explicit task_id.')
    if name == 'refresh_local_summary':
        return controller.start(arguments['task_id'])
    if name == 'get_local_summary':
        return {**controller.get_summary(arguments['task_id']), 'job': controller.status()['job']}
    raise ValueError('Unknown local summary tool.')


@server.call_tool()
async def call_tool(name, arguments):
    try:
        value = await asyncio.to_thread(invoke, name, arguments or {})
        text = sign_exact_response(json.dumps(value, ensure_ascii=False), root=ROOT)
        return CallToolResult(content=[TextContent(type='text', text=text)], isError=False)
    except (ValueError, LookupError, RuntimeError) as exc:
        return CallToolResult(content=[TextContent(type='text', text=str(exc))], isError=True)
    except Exception:
        return CallToolResult(content=[TextContent(type='text', text='Local summary unavailable; originals retained.')], isError=True)


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == '__main__':
    asyncio.run(main())
