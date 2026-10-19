"""Exercise shared stdio MCP contracts without installing or logging into clients."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def qualify(source):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from bundle_preferences import set_preference
    from harness_clients import CLIENTS

    rows = []
    with tempfile.TemporaryDirectory(prefix='token-saver-protocol-') as temporary:
        root = Path(temporary)
        for path in source.glob('*.py'):
            shutil.copy2(path, root / path.name)
        (root / 'serena').mkdir()
        shutil.copy2(source / 'serena/tool-schemas.json', root / 'serena/tool-schemas.json')
        shutil.copytree(source / 'headroom/tokenizer-cache', root / 'headroom/tokenizer-cache')
        # Discovery probes interpreter metadata but does not load the Serena backend.
        runtime = root / 'serena/.venv'
        (runtime / 'Scripts').mkdir(parents=True)
        shutil.copy2(sys.executable, runtime / 'Scripts/python.exe')
        (runtime / 'pyvenv.cfg').write_text('home = ' + sys.base_prefix + '\ninclude-system-site-packages = false\n')
        set_preference(root, 'laya_router', True)
        fixture = root / 'sample.txt'
        fixture.write_text('HARNESS_EXACT_READ: unchanged\n', encoding='utf-8')
        cases = [(client, 'headroom_local', 'headroom_read_file') for client in CLIENTS]
        cases += [('opencode', 'laya_router', 'bundle_query'), ('vscode', 'serena', 'activate_project')]
        for client, component, expected in cases:
            params = StdioServerParameters(command=sys.executable,
                args=['-u', str(root / 'harness_mcp.py'), '--client', client, '--component', component],
                cwd=str(root), env={**os.environ, 'CODEX_THREAD_ID': 'foreign-session-test'})
            async with asyncio.timeout(60):
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        listing = await session.list_tools()
                        if expected not in {tool.name for tool in listing.tools}:
                            raise RuntimeError('Expected shared tool was not discovered')
                        exact = None
                        if component == 'headroom_local':
                            result = await session.call_tool(expected, {'path': str(fixture), 'compress': False})
                            text = '\n'.join(item.text for item in result.content if item.type == 'text')
                            exact = not result.isError and 'HARNESS_EXACT_READ: unchanged' in text
                            if not exact:
                                raise RuntimeError('Shared exact file read failed')
                        rows.append({'client': client, 'component': component, 'initialized': True,
                                     'tool_discovered': True, 'exact_read_passed': exact})
        if (root / '.codex').exists():
            raise RuntimeError('Foreign client created Codex state')
    return {'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
            'passed': True, 'checks': rows, 'external_client_sessions_tested': False,
            'model_calls': 0, 'daily_profile_modified': False,
            'scope': 'Shared server protocol only; actual client login, trust/reload and UI remain unqualified.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(qualify(args.root))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('PASS: ' + str(len(result['checks'])) + ' shared MCP protocol checks; no external client login claimed.')


if __name__ == '__main__':
    main()
