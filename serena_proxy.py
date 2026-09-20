"""Small MCP bridge: read-only Serena navigation with live bundle controls."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
from time import monotonic

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent

from bundle_preferences import load_preferences
from desktop_proxy_control import atomic_write, routing_lock
from exact_retrieval import sign_exact_response
from serena_mcp import NAVIGATION_TOOLS, launch_spec

SERENA_INSTRUCTIONS = (
    'Use Serena implicitly for relevant coding navigation when enabled. Activate the current '
    'checkout with activate_project (absolute path), then prefer get_symbols_overview, find_symbol '
    'and find_referencing_symbols before whole-file reads. Fetch exact bodies with '
    'find_symbol(include_body=true) or native reads before edits. If off, unavailable or '
    'unsupported, use native tools. Skip irrelevant calls; no per-task setup prompt is needed.'
)

FAILURE_GUIDANCE = {
    'missing_path': 'Verify the relative path in the activated checkout. If needed, activate_project '
                    'with the correct absolute checkout. Use native file/search tools to continue.',
    'no_project': 'Activate the current checkout with activate_project using its absolute path. '
                  'If unavailable, continue with native file/search tools.',
    'timeout': 'The lookup timed out. Continue with native file/search tools; avoid repeating the same broad query.',
    'upstream_error': 'Continue with native file/search tools if Serena cannot resolve this lookup.',
}


def failure_kind(message):
    """Classify locally; never store free-form upstream errors or exception messages."""
    message = message.lower()
    if 'filenotfounderror' in message:
        return 'missing_path'
    if 'no active project' in message:
        return 'no_project'
    if 'timeouterror' in message or 'timed out' in message:
        return 'timeout'
    return 'upstream_error'


def _count(value):
    return value if type(value) is int and value >= 0 else 0


def _duration(value):
    try:
        return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else 0
    except OverflowError:
        return 0


class SerenaBridge:
    def __init__(self, root, session):
        self.root = Path(root).resolve()
        self.session = session

    def _record(self, outcome, *, tool=None, elapsed_ms=None, error_kind=None):
        """Aggregate only; never persist arguments, project paths or source text."""
        path = self.root / 'serena/activity.json'
        try:
            with routing_lock(path.with_suffix('.lock')):
                try:
                    value = json.loads(path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    value = {}
                if not isinstance(value, dict):
                    value = {}
                outcomes = ('completed', 'failed', 'blocked')
                counts = {key: _count(value.get(key)) for key in outcomes}
                counts[outcome] += 1
                now = datetime.now(timezone.utc).isoformat()
                counts.update(last_activity_at=now, last_outcome=outcome)
                previous = value.get('per_tool')
                previous = previous if isinstance(previous, dict) else {}
                per_tool = {}
                for name in NAVIGATION_TOOLS:
                    entry = previous.get(name)
                    if isinstance(entry, dict):
                        per_tool[name] = {key: _count(entry.get(key)) for key in outcomes}
                        per_tool[name]['elapsed_ms_total'] = _duration(entry.get('elapsed_ms_total'))
                if tool in NAVIGATION_TOOLS:
                    entry = per_tool.setdefault(tool, dict.fromkeys((*outcomes, 'elapsed_ms_total'), 0))
                    entry[outcome] += 1
                    entry['elapsed_ms_total'] = round(_duration(entry['elapsed_ms_total'] + _duration(elapsed_ms)), 3)
                    counts.update(last_tool=tool, last_elapsed_ms=_duration(elapsed_ms))
                counts['per_tool'] = per_tool
                failure = value.get('last_failure')
                if (isinstance(failure, dict) and failure.get('tool') in NAVIGATION_TOOLS
                        and isinstance(failure.get('kind'), str) and failure['kind'] in FAILURE_GUIDANCE
                        and isinstance(failure.get('at'), str)):
                    try:
                        at = datetime.fromisoformat(failure['at']).isoformat()
                        counts['last_failure'] = {'tool': failure['tool'], 'kind': failure['kind'], 'at': at}
                    except ValueError:
                        pass
                if outcome == 'failed' and tool in NAVIGATION_TOOLS:
                    counts['last_failure'] = {'tool': tool, 'kind': error_kind or 'upstream_error', 'at': now}
                atomic_write(path, (json.dumps(counts) + '\n').encode('utf-8'))
        except (OSError, ValueError, RuntimeError):
            pass  # Recording must not discard a successful source lookup.

    def _error(self, message, outcome='blocked', **diagnostics):
        self._record(outcome, **diagnostics)
        return CallToolResult(isError=True, content=[TextContent(type='text', text=message)])

    async def call_tool(self, name, arguments):
        if name not in NAVIGATION_TOOLS:
            return self._error('This bundle exposes only the four read-only Serena navigation tools.')
        if not load_preferences(self.root)['serena']:
            return self._error('Serena is off or its settings are unavailable. Use native file/search tools to continue.', tool=name)
        if name == 'activate_project':
            project = arguments.get('project')
            if not isinstance(project, str) or not Path(project).is_absolute():
                return self._error('Activate a specific checkout using its absolute directory path.', tool=name)
            project = Path(project).resolve()
            if not project.is_dir() or Path.home().resolve().is_relative_to(project) or project == Path(project.anchor):
                return self._error('Select a repository checkout, not a home directory or drive root.', tool=name)
        started = monotonic()
        try:
            result = await self.session.call_tool(name, arguments)
            if not result.isError and (name == 'find_referencing_symbols' or
                                      name == 'find_symbol' and arguments.get('include_body') is True):
                # Source bodies remain byte-exact through the managed Headroom request stage.
                result = result.model_copy(update={'content': [
                    item.model_copy(update={'text': sign_exact_response(item.text, root=self.root)})
                    if item.type == 'text' else item for item in result.content]})
        except Exception as exc:
            kind = failure_kind(type(exc).__name__)
            return self._error(f'Serena lookup failed. {FAILURE_GUIDANCE[kind]}', 'failed',
                               tool=name, error_kind=kind, elapsed_ms=round((monotonic() - started) * 1000, 3))
        kind = None
        if result.isError:
            kind = failure_kind('\n'.join(item.text for item in result.content if item.type == 'text'))
            result = result.model_copy(update={'content': [*result.content,
                TextContent(type='text', text=FAILURE_GUIDANCE[kind])]})
        self._record('failed' if result.isError else 'completed', tool=name, error_kind=kind,
                     elapsed_ms=round((monotonic() - started) * 1000, 3))
        return result


async def run_bridge(root):
    root = Path(root).resolve()
    command, environment = launch_spec(root)
    params = StdioServerParameters(command=command[0], args=command[1:], env=environment, cwd=str(root))
    async with stdio_client(params, errlog=sys.stderr) as (upstream_read, upstream_write):
        async with ClientSession(upstream_read, upstream_write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            if {tool.name for tool in tools} != set(NAVIGATION_TOOLS):
                raise RuntimeError('Serena navigation tool configuration changed; revalidate the managed runtime.')
            bridge = SerenaBridge(root, session)
            server = Server('bundle-serena', instructions=SERENA_INSTRUCTIONS)

            @server.list_tools()
            async def list_tools():
                # Freeze the verified schemas. Project activation cannot add editing tools.
                return tools

            @server.call_tool()
            async def call_tool(name, arguments):
                return await bridge.call_tool(name, arguments)

            async with stdio_server() as (read, write):
                await server.run(read, write, server.create_initialization_options())
