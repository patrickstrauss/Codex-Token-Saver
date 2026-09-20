"""Exercise real Serena MCP navigation and source freshness in temporary fixtures."""
import asyncio
import importlib.metadata
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from serena_mcp import NAVIGATION_TOOLS, launch_spec


async def verify():
    command, env = launch_spec(ROOT, python_path=Path(sys.executable))
    # Language server downloads stay inside the bundle and are reused on repeated smoke checks.
    env["SERENA_HOME"] = str(ROOT / "serena/smoke-state")
    with tempfile.TemporaryDirectory(prefix="serena-navigation-") as directory:
        fixture = Path(directory).resolve()
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
        with errors_path.open("w", encoding="utf-8") as errors:
            params = StdioServerParameters(command=command[0], args=command[1:], env=env, cwd=str(fixture))
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
                    return {"ok": True, "version": importlib.metadata.version("serena-agent"), "tools": sorted(NAVIGATION_TOOLS), "checks": checks}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(verify()), ensure_ascii=False))
