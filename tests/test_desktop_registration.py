import importlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

class RegistrationTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('install_desktop_mcp'), 'Desktop MCP registration is not implemented')
        return importlib.import_module('install_desktop_mcp')

    def test_adds_optional_tools_without_changing_model_route_or_existing_servers(self):
        module = self.module()
        source = '# user comment\r\nmodel="gpt-6-astra"\r\nmodel_reasoning_effort="ultra"\r\n[mcp_servers.existing]\r\ncommand="existing"\r\n'
        before = tomllib.loads(source)
        result = module.merge_config(source, Path('C:/fixture bundle'))
        data = tomllib.loads(result)
        entry = data['mcp_servers'].pop('headroom_desktop')
        self.assertEqual(data, before)
        self.assertFalse(entry['required'])
        self.assertEqual(entry['startup_timeout_sec'], 20)
        self.assertNotIn('openai_base_url', data)
        self.assertIn('# user comment', result)
        self.assertIn('\r\n', result)

    def test_second_install_is_idempotent(self):
        module = self.module()
        root = Path('C:/fixture bundle')
        first = module.merge_config('model="chosen"\n', root)
        self.assertEqual(module.merge_config(first, root), first)

    def test_refuses_unrelated_server_name_collision(self):
        module = self.module()
        with self.assertRaisesRegex(ValueError, 'already belongs'):
            module.merge_config('[mcp_servers.headroom_desktop]\ncommand="somebody-else"\n', Path('C:/bundle'))

if __name__ == '__main__':
    unittest.main()
