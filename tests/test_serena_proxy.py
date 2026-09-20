import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

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

    async def test_missing_path_preserves_error_and_adds_actionable_fallback(self):
        set_preference(self.root, 'serena', True)
        original = 'FileNotFoundError: File or directory secret/path.js does not exist in the project.'
        self.upstream.call_tool.return_value = CallToolResult(
            isError=True, content=[TextContent(type='text', text=original)])
        result = await self.bridge.call_tool('get_symbols_overview', {'relative_path': 'secret/path.js'})
        self.assertTrue(result.isError)
        self.assertEqual(result.content[0].text, original)
        self.assertIn('activated checkout', result.content[-1].text)
        self.assertIn('native', result.content[-1].text)
        activity_text = (self.root / 'serena/activity.json').read_text()
        self.assertNotIn('secret', activity_text)
        activity = json.loads(activity_text)
        self.assertEqual(activity['last_failure']['kind'], 'missing_path')
        self.assertEqual(activity['last_failure']['tool'], 'get_symbols_overview')
        self.assertEqual(activity['per_tool']['get_symbols_overview']['failed'], 1)
        self.assertGreaterEqual(activity['last_elapsed_ms'], 0)

    async def test_exception_is_classified_without_persisting_private_details(self):
        set_preference(self.root, 'serena', True)
        self.upstream.call_tool.side_effect = TimeoutError('private path and source body')
        result = await self.bridge.call_tool('find_symbol', {'name_path_pattern': 'private-symbol'})
        self.assertTrue(result.isError)
        self.assertIn('native', result.content[0].text)
        activity_text = (self.root / 'serena/activity.json').read_text()
        self.assertNotIn('private', activity_text)
        self.assertEqual(json.loads(activity_text)['last_failure']['kind'], 'timeout')

    async def test_success_preserves_failure_diagnostic_and_tracks_each_tool(self):
        set_preference(self.root, 'serena', True)
        self.upstream.call_tool.return_value = CallToolResult(isError=True, content=[])
        await self.bridge.call_tool('get_symbols_overview', {})
        self.upstream.call_tool.return_value = CallToolResult(content=[TextContent(type='text', text='symbols')])
        await self.bridge.call_tool('find_symbol', {})
        activity = json.loads((self.root / 'serena/activity.json').read_text())
        self.assertEqual(activity['last_failure']['kind'], 'upstream_error')
        self.assertEqual(activity['last_outcome'], 'completed')
        self.assertEqual(activity['last_tool'], 'find_symbol')
        self.assertEqual(activity['per_tool']['find_symbol']['completed'], 1)
        self.assertGreaterEqual(activity['per_tool']['find_symbol']['elapsed_ms_total'], 0)

    async def test_legacy_and_malformed_activity_does_not_break_success(self):
        set_preference(self.root, 'serena', True)
        activity_path = self.root / 'serena/activity.json'
        activity_path.parent.mkdir(exist_ok=True)
        activity_path.write_text(json.dumps({'completed': 4, 'per_tool': {'find_symbol': None}}))
        self.assertFalse((await self.bridge.call_tool('find_symbol', {})).isError)
        activity = json.loads(activity_path.read_text())
        self.assertEqual(activity['completed'], 5)
        self.assertEqual(activity['per_tool']['find_symbol']['completed'], 1)
        activity['per_tool']['find_symbol']['elapsed_ms_total'] = 10 ** 400
        activity_path.write_text(json.dumps(activity))
        self.assertFalse((await self.bridge.call_tool('find_symbol', {})).isError)
        activity['last_failure'] = {'tool': 'find_symbol', 'kind': {'private': 'details'}, 'at': 'invalid'}
        activity_path.write_text(json.dumps(activity))
        self.assertFalse((await self.bridge.call_tool('find_symbol', {})).isError)
        self.assertNotIn('private', activity_path.read_text())

    async def test_unrecognized_tool_does_not_create_a_dynamic_telemetry_key(self):
        set_preference(self.root, 'serena', True)
        await self.bridge.call_tool('private-untrusted-tool-name', {})
        activity_text = (self.root / 'serena/activity.json').read_text()
        self.assertNotIn('private-untrusted-tool-name', activity_text)

    async def test_missing_project_guidance_uses_existing_checkout_without_setup_prompt(self):
        set_preference(self.root, 'serena', True)
        self.upstream.call_tool.return_value = CallToolResult(
            isError=True, content=[TextContent(type='text', text='ValueError: No active project.')])
        result = await self.bridge.call_tool('find_symbol', {})
        self.assertIn('Activate the current checkout', result.content[-1].text)
        self.assertIn('absolute path', result.content[-1].text)
        activity = json.loads((self.root / 'serena/activity.json').read_text())
        self.assertEqual(activity['last_failure']['kind'], 'no_project')

    async def test_duration_accumulates_only_dispatched_calls(self):
        set_preference(self.root, 'serena', True)
        with patch('serena_proxy.monotonic', side_effect=[1, 1.125, 2, 2.050]):
            await self.bridge.call_tool('find_symbol', {})
            await self.bridge.call_tool('find_symbol', {})
        set_preference(self.root, 'serena', False)
        await self.bridge.call_tool('find_symbol', {})
        activity = json.loads((self.root / 'serena/activity.json').read_text())
        stats = activity['per_tool']['find_symbol']
        self.assertEqual(stats['completed'], 2)
        self.assertEqual(stats['blocked'], 1)
        self.assertEqual(stats['elapsed_ms_total'], 175)


if __name__ == '__main__':
    unittest.main()
