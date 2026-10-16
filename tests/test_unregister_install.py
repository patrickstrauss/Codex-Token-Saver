from pathlib import Path
import tempfile
import tomllib
import unittest
import tomlkit
from install_desktop_mcp import server_config
from unregister_install import unregister


class UnregisterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'bundle'
        self.home = Path(self.temp.name) / 'codex'
        self.home.mkdir()
        self.path = self.home / 'config.toml'
        self.settings = {'model': 'user-model', 'openai_base_url': 'https://user.example/v1',
                         'mcp_servers': {'headroom_desktop': dict(server_config(self.root), enabled=False),
                                         'unrelated': {'command': 'user-tool', 'enabled': True}}}

    def write(self):
        self.path.write_text(tomlkit.dumps(self.settings), encoding='utf-8')

    def test_only_disabled_owned_registration_removed(self):
        self.write()
        unregister(self.root, self.home)
        result = tomllib.loads(self.path.read_text())
        self.assertEqual(result, {'model': 'user-model', 'openai_base_url': 'https://user.example/v1',
                                  'mcp_servers': {'unrelated': {'command': 'user-tool', 'enabled': True}}})
        self.assertTrue(list((self.root / 'backups').glob('unregister-*')))

    def test_active_or_unowned_registration_blocks_without_writes(self):
        for change in ({'enabled': True}, {'command': 'someone-else'}):
            self.settings['mcp_servers']['headroom_desktop'] = dict(server_config(self.root), enabled=False, **{})
            self.settings['mcp_servers']['headroom_desktop'].update(change)
            self.write()
            before = self.path.read_bytes()
            with self.assertRaises((ValueError, RuntimeError)):
                unregister(self.root, self.home)
            self.assertEqual(self.path.read_bytes(), before)

    def test_missing_config_is_not_created(self):
        unregister(self.root, self.home)
        self.assertFalse(self.path.exists())
