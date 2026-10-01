"""Live MCP/CLI qualification: disposable fixtures, diagnostic activity, no toggle changes."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify(root, source):
    env = dict(os.environ, PYTHONUTF8='1', CTS_ACTIVITY_KIND='diagnostic')
    with tempfile.TemporaryDirectory(prefix='cts-structural-') as directory:
        project = Path(directory)
        calls = [f'ipcMain.handle("channel{i}", async (event, payload) => payload);' for i in range(65)]
        (project / 'fixture.js').write_text('\n'.join(calls) + '\n// ipcMain.handle("comment", ignored);\n'
            + 'const text = \'ipcMain.handle("string", ignored)\';\n', encoding='utf-8')
        (project / 'fixture.py').write_text('import subprocess\nsubprocess.run(["echo", "example"], check=True)\n', encoding='utf-8')
        bootstrap = ('import asyncio,sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
            'import bundle_router_mcp as m; m.ROOT=Path(sys.argv[2]); asyncio.run(m.main())')
        params = StdioServerParameters(command=sys.executable, args=['-c', bootstrap, str(source), str(root)], cwd=str(project), env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                schema = (await session.list_tools()).tools[0].inputSchema
                assert 'max_matches' in schema['properties'] and 'offset' in schema['properties']
                request = dict(intent='Find Electron IPC handler registrations', project=str(project), path='fixture.js',
                    pattern='ipcMain.handle($$$ARGS)', language='javascript', exact=True)
                async def search(arguments):
                    result = await session.call_tool('bundle_query', arguments)
                    text = '\n'.join(item.text for item in result.content if item.type == 'text')
                    assert not result.isError, text
                    value = json.loads(text.split('\n', 1)[1])
                    assert value['sequence'] == ['laya', 'ast_grep']
                    assert value['routing_basis'] == 'explicit_structural_search'
                    assert value['routing_probability'] is None and value['routing_ms'] == 0
                    return value, json.loads(value['result'])
                started = time.monotonic()
                _, first = await search(request | {'max_matches': 7})
                elapsed = round((time.monotonic() - started) * 1000, 1)
                assert first['total_matches'] == 65 and first['returned_matches'] == 7
                assert first['next_offset'] == 7 and first['truncated'] is True
                _, second = await search(request | {'max_matches': 7, 'offset': first['next_offset']})
                assert second['matches'][0]['line'] == 8
                value, complete = await search(request | {'max_matches': 200, 'exact': False})
                assert complete['returned_matches'] == 65 and complete['next_offset'] is None
                assert [row['text'] for row in complete['matches']] == [call[:-1] for call in calls]
                _, empty = await search(request | {'pattern': 'missingFunction($$$ARGS)'})
                assert empty['total_matches'] == 0 and empty['matches'] == []
                _, python = await search(request | {'path': 'fixture.py', 'language': 'python', 'pattern': 'subprocess.run($$$ARGS)'})
                assert python['total_matches'] == 1 and python['matches'][0]['line'] == 2
        raw = subprocess.run([str(root / 'bin/ast-grep.exe'), 'run', '--lang', 'javascript', '--pattern', request['pattern'],
            '--json=compact', str(project / 'fixture.js')], cwd=project, env=env, capture_output=True, timeout=45, check=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
        compact = value['result'].encode('utf-8')
        assert len(json.loads(raw)) == complete['total_matches']
        print(json.dumps(dict(passed=True, mcp_cases=5, exact_matches=65, comments_and_strings_excluded=True,
            pagination_verified=True, empty_search_verified=True, languages=['javascript', 'python'],
            classifier_calls=0, first_mcp_call_ms=elapsed, raw_cli_bytes=len(raw), compact_result_bytes=len(compact),
            output_bytes_reduction_pct=round(100 * (1 - len(compact) / len(raw)), 1), activity_kind='diagnostic'), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle_root', type=Path)
    parser.add_argument('--source', type=Path, help='Candidate source; defaults to installed bundle.')
    args = parser.parse_args()
    asyncio.run(verify(args.bundle_root.resolve(), (args.source or args.bundle_root).resolve()))
