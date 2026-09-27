import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from install_command_hook import hook_group
from install_desktop_mcp import server_config
import tomlkit

try:
    import disable_bundle
except ImportError:
    disable_bundle = None


class DisableBundleTests(unittest.TestCase):
    def test_opencodex_disable_disconnects_only_extension_and_preserves_provider_route(self):
        from unittest.mock import Mock
        document = tomlkit.parse(self.config.read_text())
        document['model_provider'] = 'opencodex'
        document['model_providers'] = {'opencodex': {'name': 'OpenCodex', 'base_url': 'http://127.0.0.1:10100/v1'}}
        self.config.write_text(tomlkit.dumps(document))
        self.settings.write_text('{"installed":true,"enabled":false,"mode":"opencodex","custom":"keep"}')
        controller = Mock()
        controller.disconnect.return_value = {'effective_enabled': False, 'requested_enabled': False}
        with patch('opencodex_control.OpenCodexControl', return_value=controller), patch('disable_bundle.DesktopProxyControl') as native:
            self.run_disable()
            controller.disconnect.assert_called_once()
            native.assert_not_called()
        after = tomllib.loads(self.config.read_text())
        self.assertEqual(after['model_provider'], 'opencodex')
        self.assertEqual(after['model_providers'], document['model_providers'].unwrap())
        self.assertEqual(self.auth.read_bytes(), b'private-auth-do-not-touch')

    def setUp(self):
        self.assertIsNotNone(disable_bundle, 'The supported bundle disable helper is missing')
        temporary = tempfile.TemporaryDirectory(prefix='bundle disable ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / 'bundle'
        self.home = self.root.parent / 'codex'
        self.root.mkdir()
        self.home.mkdir()
        (self.root / 'proxy').mkdir()
        self.config = self.home / 'config.toml'
        document = tomlkit.parse('model = "keep-model"\nmodel_reasoning_effort = "high"\napproval_policy = "untrusted"\n')
        document['mcp_servers'] = {'headroom_desktop': server_config(self.root),
            'bundle_serena': {'command': str(self.root / 'headroom/.venv/Scripts/python.exe'),
                              'args': [str(self.root / 'serena_mcp.py')]},
            'other': {'command': 'other.exe', 'args': ['stay']}}
        self.config.write_text(tomlkit.dumps(document), encoding='utf-8')
        self.auth = self.home / 'auth.json'
        self.auth.write_bytes(b'private-auth-do-not-touch')
        self.hooks = self.home / 'hooks.json'
        self.other_hook = {'type': 'command', 'command': 'other-tool.exe'}
        group = hook_group(self.root)
        group['hooks'].append(self.other_hook)
        self.hooks.write_text(json.dumps({'hooks': {'PreToolUse': [group]}, 'custom': 7}))
        self.agents = self.home / 'AGENTS.md'
        self.agents.write_bytes(b'Keep my instructions.\n\n<!-- BEGIN CODEX TOKEN SAVER -->\nowned\n<!-- END CODEX TOKEN SAVER -->\n')
        self.settings = self.root / 'proxy/settings.json'
        self.settings.write_text(json.dumps({'installed': True, 'enabled': False, 'custom': 'keep'}))
        self.addCleanup(patch.stopall)
        patch('disable_bundle.assert_codex_closed').start()
        patch('desktop_proxy_control.DesktopProxyControl._fetch', return_value={}).start()

    def run_disable(self):
        return disable_bundle.disable(self.root, self.home)

    def test_disables_only_owned_integrations_and_retains_files_auth_and_settings(self):
        before = tomllib.loads(self.config.read_text())
        result = self.run_disable()
        after = tomllib.loads(self.config.read_text())
        expected = before.copy()
        expected['mcp_servers'] = dict(before['mcp_servers'])
        for name in ('headroom_desktop', 'bundle_serena'):
            expected['mcp_servers'][name] = dict(before['mcp_servers'][name], enabled=False)
        self.assertEqual(after, expected)
        self.assertEqual(self.auth.read_bytes(), b'private-auth-do-not-touch')
        hooks = json.loads(self.hooks.read_text())
        self.assertEqual(hooks['hooks']['PreToolUse'][0]['hooks'], [self.other_hook])
        self.assertEqual(hooks['custom'], 7)
        self.assertEqual(self.agents.read_bytes(), b'Keep my instructions.\n\n')
        self.assertEqual(json.loads(self.settings.read_text()), {'installed': False, 'enabled': False, 'custom': 'keep', 'upstream_mode': 'auto'})
        self.assertTrue(result['restart_windows_required'])
        self.assertTrue(Path(result['backup']).is_dir())
        self.assertFalse(any(json.loads((self.root / 'settings/components.json').read_text())['components'].values()))
        self.assertTrue(self.root.is_dir())

    def test_repeated_disable_is_idempotent(self):
        self.run_disable()
        files = [self.config, self.hooks, self.agents, self.settings]
        before = [p.read_bytes() for p in files]
        self.run_disable()
        self.assertEqual([p.read_bytes() for p in files], before)

    def test_unowned_mcp_name_is_refused_before_any_change(self):
        document = tomlkit.parse(self.config.read_text())
        document['mcp_servers']['bundle_serena']['command'] = 'another-python.exe'
        self.config.write_text(tomlkit.dumps(document))
        files = [self.config, self.hooks, self.agents, self.settings]
        before = [p.read_bytes() for p in files]
        with self.assertRaisesRegex(ValueError, 'owned'):
            self.run_disable()
        self.assertEqual([p.read_bytes() for p in files], before)

    def test_additional_mcp_referencing_bundle_must_be_reviewed_manually(self):
        for entry in (
            {'command': str(self.root / 'headroom/.venv/Scripts/headroom.exe').upper(), 'args': ['mcp']},
            {'command': 'uv.exe', 'args': ['--directory', self.root.as_posix(), 'run', 'headroom', 'mcp']},
            {'command': 'powershell.exe', 'args': ['-Command', "& '" + str(self.root / 'headroom/.venv/Scripts/headroom.exe') + "' mcp"]},
        ):
            with self.subTest(entry=entry):
                document = tomlkit.parse(self.config.read_text())
                document['mcp_servers']['extra_headroom'] = entry
                self.config.write_text(tomlkit.dumps(document))
                before = self.config.read_bytes(), self.settings.read_bytes()
                with self.assertRaisesRegex(ValueError, 'extra_headroom.*manually'):
                    self.run_disable()
                self.assertEqual((self.config.read_bytes(), self.settings.read_bytes()), before)

    def test_similarly_named_sibling_install_is_not_owned(self):
        document = tomlkit.parse(self.config.read_text())
        entry = {'command': str(self.root.parent / (self.root.name + '-other') / 'python.exe')}
        document['mcp_servers']['foreign_tool'] = entry
        self.config.write_text(tomlkit.dumps(document))
        self.run_disable()
        self.assertEqual(tomllib.loads(self.config.read_text())['mcp_servers']['foreign_tool'], entry)

    def test_manually_disabled_extra_mcp_is_preserved_and_allows_recovery(self):
        document = tomlkit.parse(self.config.read_text())
        entry = {'command': str(self.root / 'headroom/.venv/Scripts/headroom.exe'), 'args': ['mcp'], 'enabled': False}
        document['mcp_servers']['extra_headroom'] = entry
        self.config.write_text(tomlkit.dumps(document))
        self.run_disable()
        self.assertEqual(tomllib.loads(self.config.read_text())['mcp_servers']['extra_headroom'], entry)

    def test_running_codex_refuses_before_changes(self):
        before = self.config.read_bytes()
        with patch('disable_bundle.assert_codex_closed', side_effect=RuntimeError('Close Codex')):
            with self.assertRaisesRegex(RuntimeError, 'Close Codex'):
                self.run_disable()
        self.assertEqual(self.config.read_bytes(), before)

    def test_restores_owned_previous_route_and_preserves_other_config(self):
        document = tomlkit.parse(self.config.read_text())
        document['openai_base_url'] = 'http://127.0.0.1:8788/v1'
        self.config.write_text(tomlkit.dumps(document))
        receipt = {'schema': 1, 'config': str(self.config), 'url': 'http://127.0.0.1:8788/v1',
                   'previous_present': True, 'previous_value': 'https://previous.example/v1'}
        (self.root / 'proxy/route-receipt.json').write_text(json.dumps(receipt))
        self.run_disable()
        self.assertEqual(tomllib.loads(self.config.read_text())['openai_base_url'], 'https://previous.example/v1')

    def test_unowned_local_route_aborts_disabling_runtime_metadata(self):
        document = tomlkit.parse(self.config.read_text())
        document['openai_base_url'] = 'http://127.0.0.1:8788/v1'
        self.config.write_text(tomlkit.dumps(document))
        before = self.config.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'endpoint'):
            self.run_disable()
        self.assertEqual(self.config.read_bytes(), before)
        self.assertTrue(json.loads(self.settings.read_text())['installed'])

    def test_failed_file_write_rolls_back_only_its_own_changes(self):
        before = {p: p.read_bytes() for p in (self.config, self.hooks, self.agents)}
        original_replace = disable_bundle.replace_checked
        def fail_hooks(path, old, new):
            if path == self.hooks:
                raise OSError('simulated write failure')
            return original_replace(path, old, new)
        with patch('disable_bundle.replace_checked', side_effect=fail_hooks):
            with self.assertRaisesRegex(OSError, 'simulated'):
                self.run_disable()
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_concurrent_config_writer_survives_rollback(self):
        original_replace = disable_bundle.replace_checked
        concurrent = b'model = "external-update"\n'
        def fail_hooks(path, old, new):
            if path == self.hooks:
                self.config.write_bytes(concurrent)
                raise OSError('simulated write failure')
            return original_replace(path, old, new)
        with patch('disable_bundle.replace_checked', side_effect=fail_hooks):
            with self.assertRaisesRegex(OSError, 'simulated'):
                self.run_disable()
        self.assertEqual(self.config.read_bytes(), concurrent)

    def test_unfamiliar_owned_hook_refuses_before_route_or_config_changes(self):
        hooks = json.loads(self.hooks.read_text())
        hooks['hooks']['PreToolUse'][0]['hooks'][0]['command'] += ' -Unexpected'
        self.hooks.write_text(json.dumps(hooks))
        before = self.config.read_bytes(), self.settings.read_bytes()
        with self.assertRaisesRegex(ValueError, 'unfamiliar'):
            self.run_disable()
        self.assertEqual((self.config.read_bytes(), self.settings.read_bytes()), before)

    def test_plan_is_read_only_and_original_proxy_settings_are_backed_up(self):
        before = self.config.read_bytes(), self.settings.read_bytes()
        result = disable_bundle.disable(self.root, self.home, plan=True)
        self.assertTrue(result['plan'])
        self.assertEqual((self.config.read_bytes(), self.settings.read_bytes()), before)
        self.assertFalse((self.root / 'backups').exists())
        result = self.run_disable()
        self.assertEqual((Path(result['backup']) / 'before-route-settings.json').read_bytes(), before[1])

    def test_change_during_route_pause_is_not_adopted(self):
        original = disable_bundle.DesktopProxyControl.set_enabled
        changed = b'Other user guidance written during pause.\n'
        def pause_then_edit(control, enabled):
            result = original(control, enabled)
            self.agents.write_bytes(changed)
            return result
        with patch.object(disable_bundle.DesktopProxyControl, 'set_enabled', pause_then_edit):
            with self.assertRaisesRegex(RuntimeError, 'changed'):
                self.run_disable()
        self.assertEqual(self.agents.read_bytes(), changed)
        self.assertTrue(tomllib.loads(self.config.read_text())['mcp_servers']['headroom_desktop']['enabled'])

    def test_rollback_keeps_trying_after_one_restore_fails(self):
        paths = [self.root / f'fixture-{index}.txt' for index in range(3)]
        for path in paths:
            path.write_bytes(b'original')
        backup = self.root / 'rollback-backup'
        backup.mkdir()
        actual_replace = disable_bundle.replace_checked
        def faulty_replace(path, before, after):
            if path == paths[2] or (path == paths[1] and after == b'original'):
                raise OSError('injected failure')
            return actual_replace(path, before, after)
        with patch('disable_bundle.replace_checked', side_effect=faulty_replace):
            with self.assertRaisesRegex(RuntimeError, 'rollback'):
                disable_bundle.apply_changes([(p, b'original', b'updated') for p in paths], backup)
        self.assertEqual(paths[0].read_bytes(), b'original')


if __name__ == '__main__':
    unittest.main()
