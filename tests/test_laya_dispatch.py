"""Typed calls use central Laya dispatch, never neural inference."""
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import bundle_router
from bundle_preferences import DEFAULTS, set_preference
import laya_dispatch as gate


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        for component in DEFAULTS:
            set_preference(self.root, component, True)
        self.predict = self.enterContext(patch('bundle_router.classify', side_effect=AssertionError('Typed requests must not use inference')))
        self.validate = self.enterContext(patch('bundle_router.validate_decision', side_effect=AssertionError('Do not fabricate confidence')))
        self.activity = self.enterContext(patch.object(gate, 'record_activity'))

    def test_every_supported_operation_routes_without_neural_inference_or_confidence(self):
        for component, operations in gate.OPERATIONS.items():
            route = next(key for key, value in bundle_router.COMPONENT.items() if value == component)
            for operation in operations:
                with self.subTest(component=component, operation=operation):
                    result = gate.authorize_explicit(self.root, component, operation)
                    self.assertEqual(result['route'], route)
                    self.assertEqual(result['status'], 'typed_route')
                    self.assertEqual(result['exact'], operation == 'headroom_retrieve')
                    self.assertNotIn('confidence', result)
        self.predict.assert_not_called()
        self.validate.assert_not_called()

    def test_router_off_blocks_public_calls_but_preserves_original_retrieval(self):
        set_preference(self.root, 'laya_router', False)
        for component, operation in (('headroom_local', 'headroom_read_file'), ('serena', 'find_symbol'),
                                     ('rtk', 'command')):
            with self.assertRaisesRegex(RuntimeError, 'Laya router is Off'):
                gate.authorize_explicit(self.root, component, operation)
        result = gate.authorize_explicit(self.root, 'headroom_local', 'headroom_retrieve')
        self.assertEqual(result['status'], 'retrieval_recovery')
        self.assertTrue(result['exact'])
        self.assertIn('router is Off', result['notice'])

    def test_component_toggle_is_checked_on_every_public_call(self):
        for component, operation in (('headroom_local', 'headroom_read_file'), ('serena', 'activate_project'),
                                     ('playwright_cli', 'click')):
            self.assertEqual(gate.authorize_explicit(self.root, component, operation)['status'], 'typed_route')
            set_preference(self.root, component, False)
            with self.assertRaisesRegex(RuntimeError, 'component is Off'):
                gate.authorize_explicit(self.root, component, operation)
        self.assertEqual(gate.authorize_explicit(self.root, 'headroom_local', 'headroom_retrieve')['status'], 'retrieval_recovery')

    def test_unknown_wrong_family_and_malformed_operations_never_route(self):
        for component, operation in (('serena', 'headroom_retrieve'), ('serena', 'replace_symbol_body'),
                                     ('ast_grep', 'unknown-command'), ('playwright_cli', 'unsupported'),
                                     ('rtk', ''), ('unknown', 'command'), ({}, 'command'),
                                     ('serena', []), ('rtk', None), ('headroom_local', 1)):
            with self.subTest(component=component, operation=operation), self.assertRaises(gate.AuthorizationError):
                gate.authorize_explicit(self.root, component, operation)
        self.predict.assert_not_called()

    def test_cli_arguments_never_enter_routing_records(self):
        for component, operation in (('ast_grep', 'run private-pattern'), ('playwright_cli', 'click private-target'), ('rtk', 'git status')):
            with patch.object(bundle_router, 'record') as record:
                gate.authorize_explicit(self.root, component, operation)
                self.assertNotIn('private', repr(record.call_args_list))

    @unittest.skipUnless((Path.home() / 'CodexTokenSaver/bin/playwright-cli.exe').is_file(), 'Packaged CLI not installed')
    def test_playwright_allowlist_covers_installed_help_commands(self):
        executable = Path.home() / 'CodexTokenSaver/bin/playwright-cli.exe'
        result = subprocess.run([str(executable), '--help'], capture_output=True, text=True, timeout=15, check=True)
        commands = set(re.findall(r'^  ([a-z][a-z0-9-]*)\b', result.stdout, re.MULTILINE))
        self.assertGreater(len(commands), 50)
        self.assertFalse(commands - gate.OPERATIONS['playwright_cli'], commands - gate.OPERATIONS['playwright_cli'])

    def test_stats_outcomes_are_informational_including_gateway(self):
        import bundle_activity
        with patch.object(gate, 'record_activity', side_effect=bundle_activity.record), patch.object(bundle_router, 'record') as legacy:
            for component, operation in (('headroom_local', 'headroom_stats'),):
                with gate.explicit_call(self.root, component, operation):
                    pass
            legacy.assert_not_called()
        events = bundle_activity.snapshot(self.root)['recent']
        self.assertEqual(len(events), 2)
        self.assertTrue(all(event['kind'] == 'informational' for event in events))

    def test_internal_context_scopes_component_root_and_lifetime(self):
        with patch.object(bundle_router, 'record') as record:
            with gate.routed_call(self.root, 'headroom_local'):
                self.assertEqual(gate.authorize_explicit(self.root, 'headroom_local', 'headroom_read_file')['status'], 'already_routed')
                record.assert_not_called()
                gate.authorize_explicit(self.root, 'serena', 'find_symbol')
                record.assert_called_once()
                with self.assertRaisesRegex(RuntimeError, 'Off'):
                    gate.authorize_explicit(self.root / 'unconfigured', 'headroom_local', 'headroom_read_file')
            gate.authorize_explicit(self.root, 'headroom_local', 'headroom_read_file')
            self.assertEqual(record.call_count, 3)

    def test_internal_context_preserves_authorized_work_without_rechecking(self):
        with gate.routed_call(self.root, 'serena'), patch.object(gate, 'load_preferences', side_effect=AssertionError('duplicate check')):
            self.assertEqual(gate.authorize_explicit(self.root, 'serena', 'find_symbol')['status'], 'already_routed')

    def test_internal_explicit_call_leaves_success_and_failure_ledger_to_parent(self):
        with gate.routed_call(self.root, 'headroom_local'):
            with gate.explicit_call(self.root, 'headroom_local', 'headroom_read_file') as authorization:
                self.assertEqual(authorization['status'], 'already_routed')
            with self.assertRaisesRegex(RuntimeError, 'source failed'):
                with gate.explicit_call(self.root, 'headroom_local', 'headroom_read_file'):
                    raise RuntimeError('source failed')
        self.activity.assert_not_called()
        self.assertEqual(bundle_router.status(self.root)['activity']['completed'], 0)

    def test_private_child_marker_applies_only_to_cli_families(self):
        with patch.dict(os.environ, CTS_LAYA_INTERNAL='1'), patch.object(bundle_router, 'record') as record:
            self.assertEqual(gate.authorize_explicit(self.root, 'playwright_cli', 'snapshot')['status'], 'already_routed')
            record.assert_not_called()
            self.assertEqual(gate.authorize_explicit(self.root, 'headroom_local', 'headroom_read_file')['status'], 'typed_route')
            record.assert_called_once()
            set_preference(self.root, 'laya_router', False)
            with self.assertRaisesRegex(RuntimeError, 'Off'):
                gate.authorize_explicit(self.root, 'serena', 'find_symbol')

    def test_routing_updates_legacy_counter_with_zero_inference_time(self):
        with patch.object(bundle_router, 'record', wraps=bundle_router.record) as record:
            gate.authorize_explicit(self.root, 'headroom_local', 'headroom_read_file')
            record.assert_called_once_with(self.root, 'completed', ['laya', 'headroom_local'], 0, task_id=None)
        status = bundle_router.status(self.root)
        self.assertEqual(status['activity']['completed'], 1)
        self.assertEqual(status['last_route_ms'], 0)

    def test_activity_is_sanitized_and_caller_uuid_is_explicit_only(self):
        valid = '01a0e142-bea9-7e43-a984-77da94ac1faa'
        with gate.explicit_call(self.root, 'headroom_local', 'headroom_read_file', task_id=valid):
            pass
        self.assertEqual(self.activity.call_args.kwargs['task_id'], valid)
        with patch.dict(os.environ, CODEX_THREAD_ID=valid), self.assertRaisesRegex(ValueError, 'private'):
            with gate.explicit_call(self.root, 'headroom_local', 'headroom_read_file', task_id='private path'):
                raise ValueError('private original contents')
        self.assertEqual(self.activity.call_args.args[2], 'failed')
        self.assertIsNone(self.activity.call_args.kwargs['task_id'])
        self.assertEqual(self.activity.call_args.kwargs['error_code'], 'execution_failed')
        self.assertNotIn('private', repr(self.activity.call_args_list))

    def test_rtk_script_is_silent_on_success_and_returns_126_on_failure(self):
        with patch.object(gate, 'authorize_explicit') as authorize, \
                patch('sys.stdout', new_callable=io.StringIO) as stdout, \
                patch('sys.stderr', new_callable=io.StringIO) as stderr:
            self.assertEqual(gate.main(['--authorize', 'rtk', 'git', 'status']), 0)
            self.assertEqual(stdout.getvalue(), '')
            self.assertEqual(stderr.getvalue(), '')
            self.assertEqual(authorize.call_args.args[1:], ('rtk', 'command'))
            authorize.side_effect = gate.AuthorizationError('Laya router is Off.', 'disabled')
            self.assertEqual(gate.main(['--authorize', 'rtk', 'rg', 'private-source']), 126)
            self.assertEqual(stdout.getvalue(), '')
            self.assertEqual(stderr.getvalue().strip(), 'Laya router is Off.')

    def test_real_authorize_helper_ignores_inherited_internal_marker(self):
        script = self.root / 'laya_dispatch.py'
        shutil.copy2(gate.__file__, script)
        environment = dict(os.environ, CTS_LAYA_INTERNAL='1',
                           PYTHONPATH=str(Path(gate.__file__).resolve().parent))
        for router_on, rtk_on, expected in ((False, True, 126), (True, False, 126), (True, True, 0)):
            with self.subTest(router_on=router_on, rtk_on=rtk_on):
                set_preference(self.root, 'laya_router', router_on)
                set_preference(self.root, 'rtk', rtk_on)
                result = subprocess.run([sys.executable, str(script), '--authorize', 'rtk', 'git', 'status'],
                                        env=environment, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertEqual(result.stdout, '')
                if expected:
                    self.assertIn('Off', result.stderr)
                else:
                    self.assertEqual(result.stderr, '')
        self.assertEqual(bundle_router.status(self.root)['activity']['completed'], 1)

    def test_recovery_is_counted_as_bypass_in_real_ledger(self):
        import bundle_activity
        set_preference(self.root, 'laya_router', False)
        with patch.object(gate, 'record_activity', side_effect=bundle_activity.record):
            with gate.explicit_call(self.root, 'headroom_local', 'headroom_retrieve'):
                pass
        self.assertEqual(bundle_activity.snapshot(self.root)['bypass_reasons'], {'disabled': 1})
        self.assertEqual(bundle_router.status(self.root)['activity']['completed'], 0)

    def test_record_rtk_completion_is_silent_sanitized_and_does_not_authorize_again(self):
        valid = '01a0e142-bea9-7e43-a984-77da94ac1faa'
        with patch.object(gate, 'authorize_explicit') as authorize, \
                patch('sys.stdout', new_callable=io.StringIO) as stdout, \
                patch('sys.stderr', new_callable=io.StringIO) as stderr:
            with patch.dict(os.environ, CODEX_THREAD_ID=valid, CTS_ACTIVITY_KIND='diagnostic'):
                self.assertEqual(gate.main(['--record-rtk', '0']), 0)
                self.assertEqual(self.activity.call_args.args[1:], ('rtk', 'completed'))
                self.assertEqual(self.activity.call_args.kwargs['task_id'], valid)
                self.assertEqual(self.activity.call_args.kwargs['kind'], 'diagnostic')
                self.assertIsNone(self.activity.call_args.kwargs['error_code'])
            with patch.dict(os.environ, CODEX_THREAD_ID='private path', CTS_ACTIVITY_KIND='private kind'):
                self.assertEqual(gate.main(['--record-rtk', '7']), 0)
                self.assertEqual(self.activity.call_args.args[1:], ('rtk', 'failed'))
                self.assertIsNone(self.activity.call_args.kwargs['task_id'])
                self.assertEqual(self.activity.call_args.kwargs['kind'], 'operation')
                self.assertEqual(self.activity.call_args.kwargs['error_code'], 'nonzero_exit')
            self.assertEqual(stdout.getvalue(), '')
            self.assertEqual(stderr.getvalue(), '')
            self.assertNotIn('private', repr(self.activity.call_args_list))
            authorize.assert_not_called()


class MCPGatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        for component in DEFAULTS:
            set_preference(self.root, component, True)
        self.real_record_activity = gate.record_activity
        self.activity = self.enterContext(patch.object(gate, 'record_activity'))
        self.predict = self.enterContext(patch('bundle_router.classify', side_effect=AssertionError('Typed calls do not classify')))

    async def test_diagnostic_mcp_events_override_operation_and_informational_kinds(self):
        import bundle_activity
        import desktop_mcp
        from serena_mcp import GatedSerenaBridge
        from mcp.types import CallToolResult, TextContent
        self.activity.side_effect = self.real_record_activity
        backend = Mock()
        backend.stats.return_value = {}
        upstream = AsyncMock()
        upstream.call_tool.return_value = CallToolResult(content=[TextContent(type='text', text='symbol')])
        with patch.dict(os.environ, CTS_ACTIVITY_KIND='diagnostic', CODEX_THREAD_ID='01a0e142-bea9-7e43-a984-77da94ac1faa'), \
                patch.object(desktop_mcp, 'ROOT', self.root), patch.object(desktop_mcp, 'get_backend', return_value=backend):
            self.assertIsInstance(await desktop_mcp.call_tool('headroom_stats', {}), list)
            self.assertFalse((await GatedSerenaBridge(self.root, upstream).call_tool('find_symbol', {})).isError)
        events = bundle_activity.snapshot(self.root)['recent']
        self.assertEqual(len(events), 4)
        self.assertTrue(all(event['kind'] == 'diagnostic' for event in events), events)
        self.assertTrue(all(event['task_id'] is None for event in events))

    async def test_headroom_routes_each_call_before_backend_and_respects_toggle(self):
        import desktop_mcp
        backend = Mock()
        backend.stats.return_value = {}
        backend.read_file.return_value = 'source'
        with patch.object(desktop_mcp, 'ROOT', self.root), patch.object(desktop_mcp, 'get_backend', return_value=backend), \
                patch.object(bundle_router, 'record', wraps=bundle_router.record) as record:
            await desktop_mcp.call_tool('headroom_stats', {})
            await desktop_mcp.call_tool('headroom_read_file', {'path': 'private-path'})
            self.assertEqual(record.call_count, 1)
            self.assertNotIn('private-path', repr(record.call_args_list))
            set_preference(self.root, 'laya_router', False)
            self.assertTrue((await desktop_mcp.call_tool('headroom_read_file', {'path': 'private-path'})).isError)
            backend.read_file.assert_called_once()
        self.predict.assert_not_called()

    async def test_exact_recovery_retains_original_bytes_and_signed_status(self):
        import desktop_mcp
        from exact_retrieval import exact_response_is_verified
        original = 'original\r\nexact ฯ€ text\r\n'
        backend = Mock()
        backend.retrieve.return_value = original
        set_preference(self.root, 'laya_router', False)
        with patch.object(desktop_mcp, 'ROOT', self.root), patch.object(desktop_mcp, 'get_backend', return_value=backend):
            result = await desktop_mcp.call_tool('headroom_retrieve', {'content_hash': 'a'*24})
        self.assertIsInstance(result, list)
        self.assertTrue(result[0].text.endswith(original))
        self.assertIn('retrieval recovery', result[0].text)
        self.assertTrue(exact_response_is_verified([x.model_dump() for x in result], root=self.root))


    async def test_serena_routes_every_tool_and_preserves_exact_bodies(self):
        from serena_mcp import GatedSerenaBridge, NAVIGATION_TOOLS
        from mcp.types import CallToolResult, TextContent
        from exact_retrieval import exact_response_is_verified
        upstream = AsyncMock()
        upstream.call_tool.return_value = CallToolResult(content=[TextContent(type='text', text='exact-body')])
        bridge = GatedSerenaBridge(self.root, upstream)
        for name in NAVIGATION_TOOLS:
            args = {'project': str(self.root)} if name == 'activate_project' else {'include_body': True}
            result = await bridge.call_tool(name, args)
            self.assertFalse(result.isError)
            if name == 'find_symbol':
                self.assertTrue(exact_response_is_verified(result.model_dump(), root=self.root))
        self.assertEqual(bundle_router.status(self.root)['activity']['completed'], 4)
        self.assertTrue((await bridge.call_tool('replace_symbol_body', {})).isError)
        set_preference(self.root, 'laya_router', False)
        self.assertTrue((await bridge.call_tool('find_symbol', {})).isError)
        self.assertEqual(upstream.call_tool.await_count, 4)
        self.predict.assert_not_called()

    async def test_public_handlers_reject_nonobject_arguments_without_dispatch(self):
        import desktop_mcp
        from serena_mcp import GatedSerenaBridge
        backend, upstream = Mock(), AsyncMock()
        with patch.object(desktop_mcp, 'ROOT', self.root), patch.object(desktop_mcp, 'get_backend', return_value=backend):
            bridge = GatedSerenaBridge(self.root, upstream)
            for arguments in ([], '', False, 1):
                for handler, name in ((desktop_mcp.call_tool, 'headroom_stats'), (bridge.call_tool, 'find_symbol')):
                    with self.subTest(name=name, arguments=arguments):
                        self.assertTrue((await handler(name, arguments)).isError)
            backend.stats.assert_not_called()
            upstream.call_tool.assert_not_called()

    async def test_router_owned_serena_child_avoids_duplicate_routing(self):
        from serena_mcp import GatedSerenaBridge
        from mcp.types import CallToolResult, TextContent
        upstream = AsyncMock()
        upstream.call_tool.return_value = CallToolResult(content=[TextContent(type='text', text='source')])
        bridge = GatedSerenaBridge(self.root, upstream, already_routed=True)
        self.assertFalse((await bridge.call_tool('find_symbol', {})).isError)
        self.assertEqual(bundle_router.status(self.root)['activity']['completed'], 0)
        upstream.call_tool.return_value = CallToolResult(isError=True, content=[TextContent(type='text', text='lookup failed')])
        self.assertTrue((await bridge.call_tool('find_symbol', {})).isError)
        upstream.call_tool.side_effect = TimeoutError('lookup timed out')
        self.assertTrue((await bridge.call_tool('find_symbol', {})).isError)
        self.assertTrue((await bridge.call_tool('find_symbol', [])).isError)
        self.activity.assert_not_called()
        # Serena's existing aggregate counters still describe the child lookups.
        stats = json.loads((self.root / 'serena/activity.json').read_text())
        self.assertEqual(stats['completed'], 1)
        self.assertEqual(stats['failed'], 2)
        self.assertEqual(upstream.call_tool.await_count, 3)

    async def test_serena_inprocess_routed_context_also_suppresses_new_ledger(self):
        from serena_mcp import GatedSerenaBridge
        from mcp.types import CallToolResult, TextContent
        upstream = AsyncMock()
        upstream.call_tool.return_value = CallToolResult(content=[TextContent(type='text', text='source')])
        bridge = GatedSerenaBridge(self.root, upstream)
        with gate.routed_call(self.root, 'serena'):
            self.assertFalse((await bridge.call_tool('find_symbol', {})).isError)
            upstream.call_tool.side_effect = TimeoutError('lookup timed out')
            self.assertTrue((await bridge.call_tool('find_symbol', {})).isError)
        self.activity.assert_not_called()


if __name__ == '__main__':
    unittest.main()
