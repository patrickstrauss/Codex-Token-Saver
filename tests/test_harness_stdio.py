"""Real protocol smoke tests in a disposable bundle; no installed client needed."""
import asyncio
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from bundle_preferences import set_preference


class HarnessStdioTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_servers_discover_and_read_without_client_credentials(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for path in source.glob('*.py'):
                shutil.copy2(path, root / path.name)
            (root / 'serena').mkdir()
            shutil.copy2(source / 'serena/tool-schemas.json', root / 'serena/tool-schemas.json')
            shutil.copytree(source / 'headroom/tokenizer-cache', root / 'headroom/tokenizer-cache')
            # Discovery starts only the lightweight Serena gateway. Give its
            # metadata probe a real interpreter; no Serena backend is launched.
            runtime = root / 'serena/.venv'
            (runtime / 'Scripts').mkdir(parents=True)
            shutil.copy2(sys.executable, runtime / 'Scripts/python.exe')
            (runtime / 'pyvenv.cfg').write_text(
                'home = ' + sys.base_prefix + '\ninclude-system-site-packages = false\n', encoding='utf-8')
            set_preference(root, 'laya_router', True)
            fixture = root / 'sample.txt'
            fixture.write_text('HARNESS_EXACT_READ: unchanged\n', encoding='utf-8')
            cases = [('claude-code', 'headroom_local', 'headroom_read_file'),
                     ('opencode', 'laya_router', 'bundle_query'),
                     ('vscode', 'serena', 'activate_project')]
            for client, component, expected in cases:
                with self.subTest(client=client, component=component):
                    params = StdioServerParameters(command=sys.executable,
                        args=['-u', str(root / 'harness_mcp.py'), '--client', client,
                              '--component', component], cwd=str(root),
                        env={**os.environ, 'CODEX_THREAD_ID': 'foreign-session-test'})
                    async with asyncio.timeout(60):
                        async with stdio_client(params) as (read, write):
                            async with ClientSession(read, write) as session:
                                await session.initialize()
                                listing = await session.list_tools()
                                self.assertIn(expected, {tool.name for tool in listing.tools})
                                if component == 'headroom_local':
                                    result = await session.call_tool(expected,
                                        {'path': str(fixture), 'compress': False})
                                    self.assertFalse(result.isError, str(result.content))
                                    self.assertIn('HARNESS_EXACT_READ: unchanged',
                                        '\n'.join(item.text for item in result.content if item.type == 'text'))
            self.assertFalse((root / '.codex').exists())


if __name__ == '__main__':
    unittest.main()
