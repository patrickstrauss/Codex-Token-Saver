import importlib
import json
from pathlib import Path
import unittest


class AutomaticRegistrationTests(unittest.TestCase):
    def test_adds_one_command_hook_and_preserves_others(self):
        module = importlib.import_module('install_command_hook')
        original = {'description': 'My hooks', 'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'existing'}]}]}}
        merged = module.merge_hooks(json.dumps(original), Path('C:/fixture bundle'))
        parsed = json.loads(merged)
        added = parsed['hooks'].pop('PreToolUse')
        self.assertEqual(parsed, original)
        self.assertEqual(added[0]['matcher'], '^Bash$')
        self.assertEqual(added[0]['hooks'][0]['type'], 'command')
        self.assertLessEqual(added[0]['hooks'][0]['timeout'], 5)
        self.assertNotIn('PermissionRequest', merged)
        self.assertNotIn('dangerously', merged)

    def test_second_install_is_idempotent(self):
        module = importlib.import_module('install_command_hook')
        root = Path('C:/fixture bundle')
        first = module.merge_hooks('{}', root)
        self.assertEqual(module.merge_hooks(first, root), first)

    def test_invalid_existing_file_is_not_replaced(self):
        module = importlib.import_module('install_command_hook')
        with self.assertRaises((ValueError, TypeError)):
            module.merge_hooks('{broken', Path('C:/bundle'))

