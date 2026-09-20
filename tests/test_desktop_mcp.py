import asyncio
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]

class DesktopMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_discovery_compression_retrieval_and_error(self):
        self.assertTrue((ROOT / 'desktop_mcp.py').is_file(), 'Desktop stdio server is not implemented')
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / 'records.json'
            records = [{'id': i, 'service': 'checkout', 'region': 'test', 'status': 'healthy',
                        'details': 'Routine operation completed successfully with unchanged configuration.'}
                       for i in range(150)]
            records[73]['status'] = 'CRITICAL_FAILURE_73'
            source.write_text(json.dumps(records, indent=2), encoding='utf-8')
            env = os.environ.copy()
            env['HEADROOM_WORKSPACE_DIR'] = str(base / 'state')
            params = StdioServerParameters(command=str(ROOT / 'headroom/.venv/Scripts/python.exe'),
                args=['-u', str(ROOT / 'desktop_mcp.py')], env=env)
            async with asyncio.timeout(40):
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        listing = await session.list_tools()
                        self.assertEqual({tool.name for tool in listing.tools},
                            {'headroom_read_file', 'headroom_retrieve', 'headroom_stats'})
                        self.assertTrue(all(tool.annotations.readOnlyHint for tool in listing.tools))
                        retrieval_tool = next(tool for tool in listing.tools if tool.name == 'headroom_retrieve')
                        self.assertIn('content_hash', retrieval_tool.description)
                        self.assertIn('{"content_hash":', retrieval_tool.description)
                        read_result = await session.call_tool('headroom_read_file', {'path': str(source)})
                        self.assertFalse(read_result.isError)
                        content = '\n'.join(item.text for item in read_result.content if item.type == 'text')
                        self.assertIn('CRITICAL_FAILURE_73', content)
                        key = re.search(r'\b[0-9a-f]{24}\b', content)
                        self.assertIsNotNone(key, content[:400])
                        exact = await session.call_tool('headroom_retrieve',
                            {'content_hash': key.group(), 'start_line': 1, 'max_lines': 10000})
                        self.assertFalse(exact.isError)
                        exact_text = '\n'.join(item.text for item in exact.content if item.type == 'text')
                        self.assertTrue(exact_text.endswith(source.read_bytes().decode('utf-8')),
                                        'Retrieved original must preserve the file text and CRLF endings')
                        for arguments in (
                            {'id': key.group()},
                            {'hash': key.group()},
                            {'content_hash': key.group(), 'id': 'abcdef123456'},
                            {'content_hash': '<<ccr:abcdef123456,string,1KB>>'},
                            {'content_hash': key.group(), 'start_line': 0},
                            {'content_hash': key.group(), 'max_lines': True},
                            {'content_hash': key.group(), 'max_lines': 10001},
                            {'content_hash': key.group(), 'end_line': 10},
                        ):
                            with self.subTest(arguments=arguments):
                                rejected = await session.call_tool('headroom_retrieve', arguments)
                                self.assertTrue(rejected.isError)
                                message = rejected.content[0].text
                                self.assertIn('Invalid headroom_retrieve arguments', message)
                                self.assertIn('{"content_hash":', message)
                                self.assertIn('max_lines', message)
                                self.assertNotIn('unavailable', message)
                        for name, arguments in (
                            ('headroom_read_file', {'path': str(source), 'compress': 'false'}),
                            ('headroom_read_file', {'path': str(source), 'unexpected': True}),
                            ('headroom_stats', {'unexpected': True}),
                        ):
                            with self.subTest(name=name, arguments=arguments):
                                rejected = await session.call_tool(name, arguments)
                                self.assertTrue(rejected.isError)
                                self.assertIn(f'Invalid {name} arguments', rejected.content[0].text)
                        invalid = await session.call_tool('headroom_read_file', {'path': str(base/'missing.json')})
                        self.assertTrue(invalid.isError)
                        stats_result = await session.call_tool('headroom_stats', {})
                        stats = json.loads(stats_result.content[0].text)
                        self.assertEqual(stats['read_count'], 1)
                        self.assertEqual(stats['retrieve_count'], 1)
                        self.assertGreater(stats['gross_saved'], 0)
                        self.assertGreater(stats['retrieval_tokens'], 0)
                        self.assertLess(stats['total_saved'], stats['gross_saved'])

if __name__ == '__main__':
    unittest.main()
