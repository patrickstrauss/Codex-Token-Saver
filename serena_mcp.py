"""Run the bundle's isolated, read-only Serena MCP server over stdio."""
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from serena_lifecycle import LazySerenaSession

ROOT = Path(__file__).resolve().parent
NAVIGATION_TOOLS = (
    "activate_project", "get_symbols_overview", "find_symbol", "find_referencing_symbols",
)


def navigation_tools(root: Path):
    """Advertise verified schemas without importing or starting Serena."""
    from mcp.types import Tool
    record = json.loads((Path(root) / 'serena/tool-schemas.json').read_text(encoding='utf-8'))
    tools = [Tool.model_validate(tool) for tool in record['tools']]
    if (record.get('schema_version') != 1 or len(tools) != len(NAVIGATION_TOOLS)
            or {tool.name for tool in tools} != set(NAVIGATION_TOOLS)):
        raise ValueError('Invalid managed Serena navigation schemas; repair the bundle.')
    return tools


def validate_navigation_tools(root, tools):
    # MCP 2 uses snake_case attributes; wire aliases stay stable across SDKs.
    expected = {tool.name: tool.model_dump(by_alias=True)['inputSchema'] for tool in navigation_tools(root)}
    actual = {tool.name: tool.model_dump(by_alias=True)['inputSchema'] for tool in tools}
    activation = actual.get('activate_project', {})
    session_field = activation.get('properties', {}).pop('session_id', None)
    if session_field is not None:
        if session_field.get('type') != 'string':
            raise RuntimeError('Unsupported Serena activation session schema.')
        activation['required'] = [name for name in activation.get('required', []) if name != 'session_id']
    for schemas in (expected, actual):
        for schema in schemas.values():
            # The gateway advertises our verified descriptions; compare input contracts.
            schema.pop('description', None)
            for field in schema.get('properties', {}).values():
                field.pop('description', None)
    if len(tools) != len(expected) or actual != expected:
        raise RuntimeError('Serena navigation schemas changed; revalidate the managed runtime.')


def runtime_python(root: Path = ROOT) -> Path:
    root = Path(root).resolve()
    manifest = root / "serena/runtime.json"
    relative = "serena/.venv/Scripts/python.exe"
    if manifest.exists():
        try:
            record = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or record.get("schema_version") != 1:
                raise ValueError("Unsupported Serena runtime manifest")
            relative = record["python_path"]
            if not isinstance(relative, str) or not relative:
                raise ValueError("Serena interpreter path must be a relative string")
        except (KeyError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid Serena runtime manifest") from exc
    path = Path(relative)
    if path.is_absolute() or path.drive:
        raise ValueError("Serena interpreter path must be bundle-relative")
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root / "serena"):
        raise ValueError("Serena interpreter must remain inside its managed directory")
    if not candidate.is_file():
        raise FileNotFoundError(f"Managed Serena interpreter is missing: {candidate}")
    return candidate


def launch_spec(root: Path = ROOT, *, environ=None, python_path: Path | None = None):
    root = Path(root).resolve()
    python = Path(python_path).resolve() if python_path else runtime_python(root)
    if not python.is_relative_to(root / "serena") or not python.is_file():
        raise ValueError("Candidate Serena interpreter must exist inside its managed directory")
    env = dict(os.environ if environ is None else environ)
    for key in ('PYTHONPATH', 'PYTHONHOME'):
        env.pop(key, None)
    env["SERENA_HOME"] = str(root / "serena/state")
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    command = [
        str(python), "-c", "from serena.cli import top_level; top_level()",
        "start-mcp-server", "--transport", "stdio", "--language-backend", "LSP",
        "--context", str(root / "serena/navigation.yml"),
        "--mode", str(root / "serena/navigation-mode.yml"),
        "--enable-web-dashboard", "false", "--enable-gui-log-window", "false",
        "--open-web-dashboard", "false", "--log-level", "WARNING",
        "--trace-lsp-communication", "false", "--tool-timeout", "90",
    ]
    from component_runtime import _package_version
    version = _package_version(python, 'serena-agent')
    if version and int(version.split('.')[0]) >= 2:
        # Serena 2 defaults to a REPL; retain the four read-only named tools.
        command.extend(['--agent-interface', 'tools'])
    return command, env


def describe_runtime(root: Path = ROOT) -> dict:
    root = Path(root).resolve()
    python = runtime_python(root)
    result = subprocess.run(
        [str(python), "-c", "import importlib.metadata; print(importlib.metadata.version('serena-agent'))"],
        capture_output=True, text=True, timeout=15, check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    command, _ = launch_spec(root)
    return {
        "version": result.stdout.strip(), "python_path": str(python),
        "manifest_path": str(root / "serena/runtime.json"),
        "state_dir": str(root / "serena/state"), "command": command,
        "tools": list(NAVIGATION_TOOLS), "source_edits_enabled": False,
        "automatic_project_activation": False,
    }


async def _probe_session(root: Path) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    command, env = launch_spec(root, python_path=Path(sys.executable))
    with tempfile.TemporaryDirectory(prefix="serena-probe-") as directory:
        env["SERENA_HOME"] = str(Path(directory) / "state")
        with open(Path(directory) / "stderr.log", "w", encoding="utf-8") as errors:
            params = StdioServerParameters(command=command[0], args=command[1:], env=env, cwd=str(root))
            async with stdio_client(params, errlog=errors) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    validate_navigation_tools(root, result.tools)
                    names = sorted(tool.name for tool in result.tools)
                    if set(names) != set(NAVIGATION_TOOLS):
                        raise RuntimeError(f"Unexpected Serena tools: {names}")
                    return {
                        "ok": True, "version": importlib.metadata.version("serena-agent"),
                        "tools": names, "schema_chars": len(result.model_dump_json()),
                    }


def probe_runtime(root: Path = ROOT, python_path: Path | None = None) -> dict:
    root = Path(root).resolve()
    python = python_path or runtime_python(root)
    launch_spec(root, python_path=python)  # Validate candidate before executing it.
    result = subprocess.run(
        [str(python), str(root / "serena_mcp.py"), "--probe-child", "--bundle-root", str(root)],
        capture_output=True, text=True, encoding="utf-8", timeout=60, check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    report = json.loads(result.stdout)
    if report.get("ok") is not True or set(report.get("tools", [])) != set(NAVIGATION_TOOLS):
        raise RuntimeError("Serena compatibility probe did not pass")
    return report


class GatedSerenaBridge:
    """Reuse the existing navigation/toggle bridge behind per-call routing."""
    def __init__(self, root, session, *, already_routed=False):
        from serena_proxy import SerenaBridge
        self.root = Path(root).resolve()
        self.bridge = SerenaBridge(self.root, session)
        self.already_routed = already_routed

    async def call_tool(self, name, arguments):
        from contextlib import nullcontext
        from laya_dispatch import AuthorizationError, authorize_explicit, record_activity, routed_call
        from mcp.types import CallToolResult, TextContent
        arguments = {} if arguments is None else arguments
        if not isinstance(arguments, dict):
            if not self.already_routed:
                record_activity(self.root, 'serena', 'blocked', kind='operation', error_code='invalid_input')
            return CallToolResult(isError=True, content=[TextContent(type='text', text='Tool arguments must be an object.')])
        try:
            scope = routed_call(self.root, 'serena') if self.already_routed else nullcontext()
            with scope:
                authorization = await asyncio.to_thread(authorize_explicit, self.root, 'serena', name)
        except AuthorizationError as exc:
            if not self.already_routed:
                record_activity(self.root, 'serena', 'blocked', kind='operation', error_code=exc.code)
            return CallToolResult(isError=True, content=[TextContent(type='text', text=str(exc))])
        owns_event = authorization['status'] != 'already_routed'
        try:
            result = await self.bridge.call_tool(name, arguments)
        except Exception:
            if owns_event:
                record_activity(self.root, 'serena', 'failed', kind='operation', error_code='execution_failed')
            raise
        if owns_event:
            record_activity(self.root, 'serena', 'failed' if result.isError else 'completed',
                            kind='operation', error_code='execution_failed' if result.isError else None)
        return result


async def run_gateway(root, *, already_routed=False, idle_seconds=120):
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server
    from serena_proxy import SERENA_INSTRUCTIONS

    root = Path(root).resolve()
    launch_spec(root)  # Check availability without launching the runtime.
    tools = navigation_tools(root)
    session = LazySerenaSession(root, idle_seconds=idle_seconds)
    bridge = GatedSerenaBridge(root, session, already_routed=already_routed)
    server = Server('bundle-serena', instructions=SERENA_INSTRUCTIONS)

    @server.list_tools()
    async def list_tools():
        return tools

    @server.call_tool()
    async def call_tool(name, arguments):
        return await bridge.call_tool(name, arguments)

    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await session.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--probe-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--bundle-root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--python", type=Path, help="Probe a candidate interpreter inside serena/")
    parser.add_argument("--idle-seconds", type=float, default=120, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.probe_child:
        print(json.dumps(asyncio.run(_probe_session(args.bundle_root)), ensure_ascii=False))
        return 0
    if args.probe:
        print(json.dumps(probe_runtime(args.bundle_root, args.python), ensure_ascii=False))
        return 0
    if args.describe:
        print(json.dumps(describe_runtime(args.bundle_root), ensure_ascii=False))
        return 0
    # Only the router sets this marker on its private, already-routed child.
    # It is consumed at this entry point and never interpreted by the public API.
    already_routed = os.environ.pop('CTS_LAYA_INTERNAL', None) == '1'
    asyncio.run(run_gateway(args.bundle_root, already_routed=already_routed, idle_seconds=args.idle_seconds))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Managed Serena unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1)
