"""Exercise real Serena MCP navigation and source freshness in temporary fixtures."""
import asyncio
import argparse
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from serena_mcp import NAVIGATION_TOOLS
from bundle_preferences import set_preference
from exact_retrieval import exact_response_is_verified


async def verify(bridge_python=None):
    with tempfile.TemporaryDirectory(prefix="serena-navigation-") as directory:
        temporary = Path(directory).resolve()
        bundle = temporary / 'bundle'
        bundle.mkdir()
        for name in ('serena_mcp.py', 'serena_proxy.py', 'bundle_preferences.py',
                     'desktop_proxy_control.py', 'exact_retrieval.py'):
            shutil.copy2(ROOT / name, bundle / name)
        runtime = bundle / 'serena/.venv'
        (runtime / 'Scripts').mkdir(parents=True)
        (runtime / 'Lib/site-packages').mkdir(parents=True)
        for name in ('navigation.yml', 'navigation-mode.yml'):
            shutil.copy2(ROOT / 'serena' / name, bundle / 'serena' / name)
        shutil.copy2(Path(sys.prefix) / 'pyvenv.cfg', runtime / 'pyvenv.cfg')
        shutil.copy2(sys.executable, runtime / 'Scripts/python.exe')
        # An isolated venv fixture reads the already installed dependencies. No production config changes.
        (runtime / 'Lib/site-packages/installed-test-runtime.pth').write_text(
            f'import site; site.addsitedir({str(Path(sys.prefix) / "Lib/site-packages")!r})\n', encoding='utf-8')
        set_preference(bundle, 'serena', True)
        command = [str(bridge_python or runtime / 'Scripts/python.exe'), str(bundle / 'serena_mcp.py'), '--bundle-root', str(bundle)]
        fixture = temporary / 'project'
        fixture.mkdir()
        (fixture / ".serena").mkdir()
        (fixture / ".serena/project.yml").write_text(
            "project_name: token_saver_smoke\nlanguage_servers: [python, typescript]\n"
            "encoding: utf-8\nread_only: true\n", encoding="utf-8",
        )
        python_before = 'def combine(value: int) -> int:\n    return value + 17\n\ndef caller() -> int:\n    return combine(4)\n'
        python_after = python_before.replace("value + 17", "value + 29")
        ts_before = 'export function combine(value: number): number {\n  return value + 17;\n}\nexport function caller(): number { return combine(4); }\n'
        ts_after = ts_before.replace("value + 17", "value + 29")
        (fixture / "sample.py").write_text(python_before, encoding="utf-8")
        (fixture / "sample.ts").write_text(ts_before, encoding="utf-8")
        (fixture / "tsconfig.json").write_text('{"compilerOptions":{"target":"ES2020","strict":true},"include":["*.ts"]}', encoding="utf-8")
        errors_path = ROOT / "logs/serena-navigation-stderr.log"
        errors_path.parent.mkdir(parents=True, exist_ok=True)
        with errors_path.open("w", encoding="utf-8") as errors:
            params = StdioServerParameters(command=command[0], args=command[1:], cwd=str(fixture))
            async with stdio_client(params, errlog=errors) as (read, write):
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    tools = await session.list_tools()
                    assert {tool.name for tool in tools.tools} == set(NAVIGATION_TOOLS)

                    async def call(name, args):
                        result = await session.call_tool(name, args)
                        text = "\n".join(item.text for item in result.content if item.type == "text")
                        assert not result.isError, f"{name}: {text}"
                        return text

                    activated = await call("activate_project", {"project": str(fixture)})
                    assert "error" not in activated.lower(), activated
                    assert {tool.name for tool in (await session.list_tools()).tools} == set(NAVIGATION_TOOLS)
                    checks = []
                    for file_name, before, after in (("sample.py", python_before, python_after), ("sample.ts", ts_before, ts_after)):
                        overview = await call("get_symbols_overview", {"relative_path": file_name, "depth": 1})
                        assert "combine" in overview and "caller" in overview, overview
                        source = await call("find_symbol", {"name_path_pattern": "combine", "relative_path": file_name, "include_body": True})
                        assert "value + 17" in source, source
                        assert exact_response_is_verified(source, root=bundle)
                        references = await call("find_referencing_symbols", {"name_path": "combine", "relative_path": file_name})
                        assert "caller" in references, references
                        assert (fixture / file_name).read_text(encoding="utf-8") == before
                        (fixture / file_name).write_text(after, encoding="utf-8")
                        for attempt in range(20):
                            refreshed = await call("find_symbol", {"name_path_pattern": "combine", "relative_path": file_name, "include_body": True})
                            if "value + 29" in refreshed and "value + 17" not in refreshed:
                                break
                            await asyncio.sleep(0.25)
                        else:
                            raise AssertionError(f"Stale symbol body after editing {file_name}")
                        assert (fixture / file_name).read_text(encoding="utf-8") == after
                        checks.append({"file": file_name, "overview": True, "body": True, "references": True, "freshness": True})
                    set_preference(bundle, 'serena', False)
                    blocked = await session.call_tool('find_symbol', {'name_path_pattern': 'combine', 'relative_path': 'sample.py'})
                    assert blocked.isError and any('off' in item.text for item in blocked.content if item.type == 'text')
                    assert {tool.name for tool in (await session.list_tools()).tools} == set(NAVIGATION_TOOLS)
                    set_preference(bundle, 'serena', True)
                    resumed = await call('find_symbol', {'name_path_pattern': 'combine', 'relative_path': 'sample.py'})
                    assert 'combine' in resumed
                    return {"ok": True, "version": importlib.metadata.version("serena-agent"), "tools": sorted(NAVIGATION_TOOLS), "checks": checks,
                            "live_toggle": True, "exact_bodies_protected": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge-python', type=Path, help='Interpreter used by Codex for the bridge; official Serena uses the isolated fixture runtime.')
    print(json.dumps(asyncio.run(verify(parser.parse_args().bridge_python)), ensure_ascii=False))
