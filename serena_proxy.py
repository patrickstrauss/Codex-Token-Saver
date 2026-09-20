"""Small MCP bridge: read-only Serena navigation with live bundle controls."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

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


class SerenaBridge:
    def __init__(self, root, session):
        self.root = Path(root).resolve()
        self.session = session

    def _record(self, outcome):
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
                counts = {key: value.get(key, 0) for key in ('completed', 'failed', 'blocked')}
                counts = {key: count if type(count) is int and count >= 0 else 0 for key, count in counts.items()}
                counts[outcome] += 1
                counts.update(last_activity_at=datetime.now(timezone.utc).isoformat(), last_outcome=outcome)
                atomic_write(path, (json.dumps(counts) + '\n').encode('utf-8'))
        except (OSError, ValueError, RuntimeError):
            pass  # Recording must not discard a successful source lookup.

    def _error(self, message, outcome='blocked'):
        self._record(outcome)
        return CallToolResult(isError=True, content=[TextContent(type='text', text=message)])

    async def call_tool(self, name, arguments):
        if name not in NAVIGATION_TOOLS:
            return self._error('This bundle exposes only the four read-only Serena navigation tools.')
        if not load_preferences(self.root)['serena']:
            return self._error('Serena is off or its settings are unavailable. Enable Serena in the bundle dashboard to run new queries.')
        if name == 'activate_project':
            project = arguments.get('project')
            if not isinstance(project, str) or not Path(project).is_absolute():
                return self._error('Activate a specific checkout using its absolute directory path.')
            project = Path(project).resolve()
            if not project.is_dir() or Path.home().resolve().is_relative_to(project) or project == Path(project.anchor):
                return self._error('Select a repository checkout, not a home directory or drive root.')
        try:
            result = await self.session.call_tool(name, arguments)
            if not result.isError and (name == 'find_referencing_symbols' or
                                      name == 'find_symbol' and arguments.get('include_body') is True):
                # Source bodies remain byte-exact through the managed Headroom request stage.
                result = result.model_copy(update={'content': [
                    item.model_copy(update={'text': sign_exact_response(item.text, root=self.root)})
                    if item.type == 'text' else item for item in result.content]})
        except Exception as exc:
            return self._error(f'Serena lookup failed ({type(exc).__name__}). Use native source tools or retry.', 'failed')
        self._record('failed' if result.isError else 'completed')
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
