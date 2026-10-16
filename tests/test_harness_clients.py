import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import harness_clients as clients


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root, self.home, self.project = (self.base / n for n in ('bundle with spaces', 'home', 'project'))
        self.home.mkdir(); self.project.mkdir()
        for runtime in ('headroom', 'serena', 'laya'):
            path = self.root / runtime / '.venv/Scripts/python.exe'
            path.parent.mkdir(parents=True)
            path.touch()
        for script in ('harness_mcp.py', *(v[1] for v in clients.SCRIPTS.values())):
            (self.root / script).touch()

    def connect(self, name, **kwargs):
        return clients.change(self.root, name, home=self.home, **kwargs)

    def test_every_adapter_roundtrip_preserves_user_settings(self):
        for name in clients.CLIENTS:
            with self.subTest(client=name):
                config = self.project / (name + '.jsonc')
                original = '// keep this comment\r\n{"model":"leave-me", "env":{"secret":"private"},\r\n"' + clients.CLIENTS[name][1] + '": {"other":{"command":"other"},},}\r\n'
                config.write_bytes(original.encode())
                options = {'scope': 'project', 'project': self.project}
                if name in ('vscode', 'generic', 'cline', 'windsurf-cascade'):
                    options['config'] = config
                else:
                    config = clients.config_path(name, 'project', self.project, home=self.home)
                    config.parent.mkdir(parents=True, exist_ok=True)
                    config.write_bytes(original.encode())
                plan = self.connect(name, **options)
                self.assertFalse(plan['applied'])
                self.assertEqual(config.read_bytes(), original.encode())
                self.connect(name, apply=True, **options)
                text = config.read_text()
                value = clients.JsonDocument(text).root.value
                self.assertEqual(value['model'], 'leave-me')
                self.assertEqual(value['env'], {'secret': 'private'})
                self.assertIn('// keep this comment', text)
                first = config.read_bytes()
                self.connect(name, apply=True, **options)
                self.assertEqual(config.read_bytes(), first)
                self.connect(name, remove=True, apply=True, **options)
                result = clients.JsonDocument(config.read_text()).root.value
                self.assertEqual(result, clients.JsonDocument(original).root.value)
                self.assertIn('// keep this comment', config.read_text())

    def test_format_contracts_and_literal_argv(self):
        for name in clients.CLIENTS:
            result = clients.export_config(self.root, name)
            servers = result[clients.CLIENTS[name][1]]
            self.assertEqual(len(servers), 3)
            server = servers['bundle_laya_router']
            if name in clients.ARRAY_CLIENTS:
                self.assertEqual(server['type'], 'local')
                command = server['command']
                self.assertIn('environment', server)
            else:
                command = [server['command'], *server['args']]
                self.assertIn('env', server)
            self.assertEqual(command[0], str(self.root / 'headroom/.venv/Scripts/python.exe'))
            self.assertEqual(command[2], str(self.root / 'harness_mcp.py'))
            self.assertEqual(command[-1], 'laya_router')

    def test_unowned_and_modified_servers_are_never_adopted(self):
        path = clients.config_path('cursor', home=self.home)
        path.parent.mkdir()
        path.write_text('{"mcpServers":{"bundle_laya_router":{"command":"not-ours"}}}')
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            self.connect('cursor', apply=True)
        self.assertEqual(before, path.read_bytes())
        path.write_text('{}')
        self.connect('cursor', apply=True)
        value = json.loads(path.read_bytes())
        value['mcpServers']['bundle_laya_router']['args'].append('user-change')
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            self.connect('cursor', remove=True, apply=True)

    def test_disconnect_all_uses_recorded_paths_not_current_home(self):
        self.connect('cursor', apply=True)
        self.connect('gemini-cli', apply=True)
        with patch('pathlib.Path.home', return_value=self.base / 'different-home'):
            clients.disconnect_all(self.root, apply=True)
        self.assertEqual(clients.registrations(self.root), [])
        self.assertFalse((self.base / 'different-home').exists())

    def test_atomic_rollback_when_receipt_cannot_be_written(self):
        path = clients.config_path('cursor', home=self.home)
        path.parent.mkdir()
        path.write_bytes(b'{"model":"native"}\r\n')
        original = path.read_bytes()
        writer = clients.atomic_write
        def fail_receipt(destination, data):
            if Path(destination).name == 'clients.json':
                raise OSError('Injected write failure')
            return writer(destination, data)
        with patch.object(clients, 'atomic_write', side_effect=fail_receipt):
            with self.assertRaises(OSError):
                self.connect('cursor', apply=True)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(clients.registrations(self.root), [])

    def test_invalid_configs_and_duplicate_keys_fail_closed(self):
        for text in ('{"a":1,"a":2}', '{"mcpServers":null}', '{', '{"x":NaN}', '[]'):
            with self.subTest(text=text):
                path = clients.config_path('cursor', home=self.home)
                path.parent.mkdir(exist_ok=True)
                path.write_text(text)
                with self.assertRaises(ValueError):
                    self.connect('cursor', apply=True)
                self.assertEqual(path.read_text(), text)

    def test_bom_and_unrelated_comments_survive(self):
        path = clients.config_path('cursor', home=self.home)
        path.parent.mkdir()
        path.write_bytes(b'\xef\xbb\xbf{ "mcpServers": {/* comment */}, "x": "https://foo/*bar*/" }\r\n')
        self.connect('cursor', apply=True)
        self.assertTrue(path.read_bytes().startswith(b'\xef\xbb\xbf'))
        self.assertIn('/* comment */', path.read_text(encoding='utf-8-sig'))
        self.connect('cursor', remove=True, apply=True)
        self.assertEqual(clients.JsonDocument(path.read_text(encoding='utf-8-sig')).root.value['x'], 'https://foo/*bar*/')

    def test_launcher_does_not_pass_foreign_thread_ids_or_shell_parse_argv(self):
        import harness_mcp
        with patch.dict(os.environ, {'CODEX_THREAD_ID': 'foreign'}), patch('harness_mcp.os.chdir'), patch('harness_mcp.sys.argv', []), patch('harness_mcp.runpy.run_path') as run:
            harness_mcp.launch('cursor', 'headroom_local', self.root)
            self.assertNotIn('CODEX_THREAD_ID', os.environ)
            self.assertEqual(os.environ['CTS_CLIENT'], 'cursor')
            run.assert_called_once_with(str(self.root / 'desktop_mcp.py'), run_name='__main__')

    def test_standalone_opt_out_is_explicit(self):
        self.assertTrue(clients.codex_enabled(self.root))
        (self.root / 'team-install-result.json').write_text('{"codex_integration":false}')
        self.assertFalse(clients.codex_enabled(self.root))

    def test_missing_launcher_or_shared_runtime_is_not_exported(self):
        for relative in ('harness_mcp.py', 'desktop_mcp.py', 'headroom/.venv/Scripts/python.exe'):
            path = self.root / relative
            path.unlink()
            with self.assertRaises(ValueError):
                clients.export_config(self.root, 'cursor')
            path.touch()

    def test_current_status_reports_external_changes(self):
        self.connect('cursor', apply=True)
        self.assertEqual(clients.registrations(self.root)[0]['status'], 'configured')
        path = clients.config_path('cursor', home=self.home)
        path.write_text('{}')
        status = clients.registrations(self.root)[0]
        self.assertEqual(status['status'], 'changed_or_missing')
        self.assertFalse(status['live_verified'])

    def test_kilo_config_ambiguity_requires_explicit_selection(self):
        first = self.project / 'kilo.json'
        first.write_text('{}')
        self.assertEqual(clients.config_path('kilo', 'project', self.project), first)
        second = self.project / 'kilo.jsonc'
        second.write_text('{}')
        with self.assertRaises(ValueError):
            clients.config_path('kilo', 'project', self.project)
        self.assertEqual(clients.config_path('kilo', config=second), second)

    def test_cline_profile_override_and_legacy_cascade_are_explicit(self):
        path = self.home / 'cline-profile.json'
        with patch.dict(os.environ, {'CLINE_MCP_SETTINGS_PATH': str(path)}):
            self.assertEqual(clients.config_path('cline'), path)
        with self.assertRaises(ValueError):
            clients.config_path('cline', 'project', self.project)
        with self.assertRaises(ValueError):
            clients.config_path('windsurf-cascade', home=self.home)

    def test_receipt_commit_failure_restores_existing_ownership(self):
        self.connect('cursor', apply=True)
        path = clients.config_path('cursor', home=self.home)
        original, receipt = path.read_bytes(), (self.root / 'integrations/clients.json').read_bytes()
        writer = clients.atomic_write
        def commit_then_fail(destination, data):
            writer(destination, data)
            if Path(destination).name == 'clients.json' and data != receipt:
                raise OSError('Injected post-commit failure')
        with patch.object(clients, 'atomic_write', side_effect=commit_then_fail):
            with self.assertRaises(OSError):
                self.connect('cursor', remove=True, apply=True)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual((self.root / 'integrations/clients.json').read_bytes(), receipt)


if __name__ == '__main__':
    unittest.main()
