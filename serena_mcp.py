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

ROOT = Path(__file__).resolve().parent
NAVIGATION_TOOLS = (
    "activate_project", "get_symbols_overview", "find_symbol", "find_referencing_symbols",
)


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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--probe-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--bundle-root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--python", type=Path, help="Probe a candidate interpreter inside serena/")
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
    from serena_proxy import run_bridge
    asyncio.run(run_bridge(args.bundle_root))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Managed Serena unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1)
