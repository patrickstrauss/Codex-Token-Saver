import importlib.util
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class TeamRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'bundle with spaces'
        self.home = Path(self.tmp.name) / 'codex'
        self.home.mkdir()
        for name in ('bin', 'dashboard', 'data/rtk'):
            (self.root / name).mkdir(parents=True)
        self.root = self.root.resolve()
        (self.root / 'bin/rtk.exe').touch()
        (self.root / 'team-install-source.json').write_text(json.dumps({'version': 'ci-11', 'package_sha256': 'a' * 64}))
        self.config = self.home / 'config.toml'
        self.config.write_text('model="keep-model"\nmodel_reasoning_effort="high"\napproval_policy="untrusted"\n')
        self.env = self.root / 'dashboard/.env'
        self.env.write_text('CUSTOM_SETTING=keep\nRTK_DB_PATH=wrong\n')
        with closing(sqlite3.connect(self.root / 'data/rtk/history.db')) as conn:
            conn.execute('CREATE TABLE commands (id INTEGER PRIMARY KEY)')
            conn.commit()
        spec = importlib.util.spec_from_file_location('repair_team_setup', ROOT / 'repair_team_setup.py')
        self.assertTrue((ROOT / 'repair_team_setup.py').is_file(), 'Team repair entry point is missing')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_repairs_existing_install_without_changing_preferences_or_route(self):
        from dotenv import dotenv_values
        before = self.config.read_bytes()
        with patch.object(self.module.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '{}'
            result = self.module.repair(self.root, self.home)
        values = dotenv_values(self.env)
        self.assertEqual(values['RTK_DB_PATH'], str(self.root / 'data/rtk/history.db'))
        self.assertEqual(values['RTK_BIN'], str(self.root / 'bin/rtk.exe'))
        self.assertEqual(values['CUSTOM_SETTING'], 'keep')
        self.assertTrue(result['repaired'])
        self.assertEqual(result['recorded_commands'], 0)
        self.assertIn(before, self.config.read_bytes())
        self.assertNotIn('openai_base_url', self.config.read_text())
        self.assertTrue(json.loads((self.root / 'desktop-integration.json').read_text())['configured'])
        self.assertTrue((Path(result['backup']) / 'dashboard.env').is_file())
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][1:], ['gain', '--all', '--format', 'json'])

    def test_failed_registration_restores_existing_dashboard_configuration(self):
        self.config.write_text('[mcp_servers.headroom_desktop]\ncommand="somebody-elses-tool"\n')
        before_env, before_config = self.env.read_bytes(), self.config.read_bytes()
        with patch.object(self.module.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '{}'
            with self.assertRaises(ValueError):
                self.module.repair(self.root, self.home)
        self.assertEqual(self.env.read_bytes(), before_env)
        self.assertEqual(self.config.read_bytes(), before_config)
        self.assertFalse((self.root / 'desktop-integration.json').exists())

    def test_refuses_non_team_install_before_changes(self):
        (self.root / 'team-install-source.json').unlink()
        before = self.env.read_bytes()
        with patch.object(self.module.subprocess, 'run') as run:
            with self.assertRaises(ValueError):
                self.module.repair(self.root, self.home)
            run.assert_not_called()
        self.assertEqual(self.env.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
