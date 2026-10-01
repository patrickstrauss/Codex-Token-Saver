"""Real MCP -> Laya typed structural route -> ast-grep, in a test checkout."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bundle_preferences import load_preferences, set_preference


async def verify(root):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    old = load_preferences(root)
    for component in ('laya_router', 'ast_grep'):
        set_preference(root, component, True)
    try:
        with tempfile.TemporaryDirectory(prefix='CTS router fixture ') as directory:
            project = Path(directory)
            (project / 'fixture.js').write_text('console.log(answer);\n// console.log(comment);\n')
            params = StdioServerParameters(command=sys.executable, args=[str(root / 'bundle_router_mcp.py')],
                                           env=dict(os.environ, PYTHONUTF8='1'), cwd=str(project))
            async with stdio_client(params, errlog=sys.stderr) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    assert [tool.name for tool in (await session.list_tools()).tools] == ['bundle_query']
                    result = await session.call_tool('bundle_query', {'intent': 'Find source code matching the structural JavaScript syntax pattern console.log($A).',
                        'project': str(project), 'pattern': 'console.log($A)', 'language': 'javascript'})
                    assert not result.isError, result
                    text = '\n'.join(item.text for item in result.content if item.type == 'text')
                    assert 'ast_grep' in text and 'console.log(answer)' in text and 'console.log(comment)' not in text, text
                    print(text)
                    set_preference(root, 'laya_router', False)
                    blocked = await session.call_tool('bundle_query', {'intent': 'Find code', 'project': str(project)})
                    assert blocked.isError
                    print(json.dumps({'mcp_route_verified': True, 'off_blocks_loaded_connection': True}))
    finally:
        for component in ('laya_router', 'ast_grep'):
            set_preference(root, component, old[component])


if __name__ == '__main__':
    asyncio.run(verify(Path(sys.argv[1]).resolve()))
