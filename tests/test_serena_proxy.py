import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from mcp.types import CallToolResult, TextContent
from bundle_preferences import set_preference
from serena_proxy import SerenaBridge, SERENA_INSTRUCTIONS


class SerenaProxyTests(unittest.IsolatedAsyncioTestCase):
    def test_initialization_instructions_fit_codex_server_guidance_limit(self):
        from mcp.server.lowlevel import Server
        server = Server('bundle-serena', instructions=SERENA_INSTRUCTIONS)
        self.assertEqual(server.create_initialization_options().instructions, SERENA_INSTRUCTIONS)
        self.assertLessEqual(len(SERENA_INSTRUCTIONS), 512)
        for phrase in ('implicitly', 'activate_project', 'get_symbols_overview', 'include_body=true', 'off', 'native'):
            self.assertIn(phrase, SERENA_INSTRUCTIONS)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.upstream = AsyncMock()
        self.upstream.call_tool.return_value = CallToolResult(content=[TextContent(type='text', text='exact-symbol')])
        self.bridge = SerenaBridge(self.root, self.upstream)

    async def test_toggle_is_checked_for_every_call_in_the_existing_session(self):
        first = await self.bridge.call_tool('find_symbol', {'name_path_pattern': 'private-name'})
        self.assertTrue(first.isError)
        self.upstream.call_tool.assert_not_called()
        set_preference(self.root, 'serena', True)
        second = await self.bridge.call_tool('find_symbol', {'name_path_pattern': 'private-name'})
        self.assertFalse(second.isError)
        set_preference(self.root, 'serena', False)
        self.assertTrue((await self.bridge.call_tool('find_symbol', {})).isError)
        self.upstream.call_tool.assert_awaited_once()
        self.assertNotIn('private-name', (self.root / 'serena/activity.json').read_text())

    async def test_bad_settings_and_edit_tools_never_reach_upstream(self):
        set_preference(self.root, 'serena', True)
        self.assertTrue((await self.bridge.call_tool('replace_symbol_body', {})).isError)
        (self.root / 'settings/components.json').write_text('{broken')
        self.assertTrue((await self.bridge.call_tool('activate_project', {'project': str(self.root)})).isError)
        self.upstream.call_tool.assert_not_called()

    async def test_disabling_preserves_already_dispatched_call(self):
        set_preference(self.root, 'serena', True)
        started, resume = asyncio.Event(), asyncio.Event()
        async def call(*args, **kwargs):
            started.set()
            await resume.wait()
            return CallToolResult(content=[TextContent(type='text', text='completed')])
        self.upstream.call_tool.side_effect = call
        pending = asyncio.create_task(self.bridge.call_tool('find_symbol', {}))
        await started.wait()
        set_preference(self.root, 'serena', False)
        self.assertTrue((await self.bridge.call_tool('find_symbol', {})).isError)
        resume.set()
        self.assertFalse((await pending).isError)
        self.upstream.call_tool.assert_awaited_once()

    async def test_activation_requires_specific_absolute_checkout(self):
        set_preference(self.root, 'serena', True)
        for project in ('registered-name', str(Path.home()), Path.home().anchor):
            self.assertTrue((await self.bridge.call_tool('activate_project', {'project': project})).isError)
        self.upstream.call_tool.assert_not_called()

    async def test_exact_symbol_bodies_are_protected_from_request_recompression(self):
        from exact_retrieval import exact_response_is_verified
        set_preference(self.root, 'serena', True)
        result = await self.bridge.call_tool('find_symbol', {'include_body': True})
        self.assertTrue(exact_response_is_verified(result.model_dump(), root=self.root))
        self.assertTrue(result.content[0].text.endswith('exact-symbol'))


if __name__ == '__main__':
    unittest.main()
