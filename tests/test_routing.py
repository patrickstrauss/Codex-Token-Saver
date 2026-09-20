import io
import json
import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import routing
from routing import set_route

LEGACY_TOP = ('# BEGIN CODEX TOKEN SAVER ROUTE\n'
              'model_provider = "headroom"\n'
              'openai_base_url = "http://127.0.0.1:8787/v1"\n'
              '# END CODEX TOKEN SAVER ROUTE\n')
LEGACY_PROVIDER = ('# BEGIN CODEX TOKEN SAVER ROUTE\n'
                   '[model_providers.headroom]\n'
                   'name = "OpenAI via local Headroom"\n'
                   'base_url = "http://127.0.0.1:8787/v1"\n'
                   'wire_api = "responses"\n'
                   'supports_websockets = true\n'
                   'requires_openai_auth = true\n'
                   '# END CODEX TOKEN SAVER ROUTE\n')


class RoutingTests(unittest.TestCase):
    def test_enable_never_produces_global_route(self):
        for original in ('', 'model = "gpt-6-astra"\n', LEGACY_TOP + LEGACY_PROVIDER):
            with self.subTest(original=original), self.assertRaisesRegex(ValueError, 'codex-headroom'):
                set_route(original, True)

    def test_removes_legacy_route_preserving_original_and_later_sections(self):
        original = 'model = "gpt-6-astra"\nmodel_reasoning_effort = "ultra"\n[features]\nhooks = true\n'
        later = '\n[mcp_servers.example]\ncommand = "example"\n'
        cleaned = set_route(LEGACY_TOP + original + LEGACY_PROVIDER + later, False)
        self.assertEqual(cleaned, original + later)
        self.assertEqual(set_route(cleaned, False), cleaned)

    def test_orphan_and_empty_markers_preserve_every_setting(self):
        original = ('# BEGIN CODEX TOKEN SAVER ROUTE\n# END CODEX TOKEN SAVER ROUTE\n'
                    'model = "gpt-6-astra"\n[features]\nhooks = true\n'
                    '# BEGIN CODEX TOKEN SAVER ROUTE\n')
        self.assertEqual(set_route(original, False), 'model = "gpt-6-astra"\n[features]\nhooks = true\n')
        self.assertEqual(tomllib.loads(set_route(original, False)), tomllib.loads(original))

    def test_user_edits_inside_markers_are_preserved(self):
        original = LEGACY_TOP.replace('# END', 'model = "gpt-6-astra"\n# END')
        original += LEGACY_PROVIDER.replace('# END', '# Keep my comment\n# END')
        cleaned = set_route(original, False)
        self.assertEqual(cleaned, 'model = "gpt-6-astra"\n# Keep my comment\n')

    def test_known_route_without_markers_is_recoverable(self):
        original = LEGACY_TOP + LEGACY_PROVIDER
        original = original.replace('# BEGIN CODEX TOKEN SAVER ROUTE\n', '').replace('# END CODEX TOKEN SAVER ROUTE\n', '')
        self.assertEqual(set_route(original, False), '')

    def test_custom_provider_and_route_remain_untouched(self):
        originals = [
            'model_provider = "company"\nopenai_base_url = "https://example.org"\n',
            'model_provider = "headroom"\n[model_providers.headroom]\nname = "My custom provider"\nbase_url = "https://example.org"\n',
            'model_provider = "headroom"\n[model_providers.headroom]\nname = "My proxy"\nbase_url = "http://127.0.0.1:8787/v1"\n',
        ]
        for original in originals:
            with self.subTest(original=original):
                self.assertEqual(set_route(original, False), original)

    def test_modified_provider_is_preserved_while_legacy_global_route_is_removed(self):
        modified = LEGACY_PROVIDER.replace('# END', 'custom_header = "keep-me"\n# END')
        cleaned = tomllib.loads(set_route(LEGACY_TOP + modified, False))
        self.assertNotIn('model_provider', cleaned)
        self.assertNotIn('openai_base_url', cleaned)
        self.assertEqual(cleaned['model_providers']['headroom'], tomllib.loads(modified)['model_providers']['headroom'])

    def test_marker_and_key_lookalikes_inside_multiline_strings_are_preserved(self):
        original = '''description = """
# BEGIN CODEX TOKEN SAVER ROUTE
model_provider = "headroom"
openai_base_url = "http://127.0.0.1:8787/v1"
[model_providers.headroom]
# END CODEX TOKEN SAVER ROUTE
"""
[other]
model_provider = "headroom"
openai_base_url = "http://127.0.0.1:8787/v1"
'''
        self.assertEqual(set_route(original, False), original)

    def test_cleanup_preserves_crlf_and_quoted_table_names(self):
        original = (LEGACY_TOP + 'model = "gpt-6-astra"\n' + LEGACY_PROVIDER).replace('[model_providers.headroom]', '["model_providers"."headroom"]')
        original = original.replace('\n', '\r\n')
        self.assertEqual(set_route(original, False), 'model = "gpt-6-astra"\r\n')

    def test_near_marker_comments_and_inline_lookalikes_remain_untouched(self):
        original = ('# BEGIN CODEX TOKEN SAVER ROUTE extra user note\n'
                    '# END CODEX TOKEN SAVER ROUTE: keep this\n'
                    'model = "gpt-6-astra" # BEGIN CODEX TOKEN SAVER ROUTE\n')
        self.assertEqual(set_route(original, False), original)

    def test_custom_provider_remains_selected_despite_orphan_marker(self):
        original = ('# BEGIN CODEX TOKEN SAVER ROUTE\n'
                    'model_provider = "headroom"\n'
                    '[model_providers.headroom]\n'
                    'name = "My own local proxy"\n'
                    'base_url = "http://127.0.0.1:8787/v1"\n')
        cleaned = set_route(original, False)
        self.assertEqual(tomllib.loads(cleaned), tomllib.loads(original))

    def test_invalid_toml_is_not_rewritten(self):
        with self.assertRaises(tomllib.TOMLDecodeError):
            set_route(LEGACY_TOP + 'invalid = [\n', False)

    def run_main(self, home, action):
        output = io.StringIO()
        with patch.dict(os.environ, {'CODEX_HOME': str(home)}), \
             patch.object(sys, 'argv', ['routing.py', action]), \
             patch.object(routing, '__file__', str(Path(home) / 'routing.py')), \
             patch('sys.stdout', output):
            routing.main()
        return json.loads(output.getvalue())

    def test_enable_cli_refuses_without_writing_config_or_contacting_service(self):
        with tempfile.TemporaryDirectory() as home:
            config_file = Path(home) / 'config.toml'
            original = b'\xef\xbb\xbfmodel = "gpt-6-astra"\r\n'
            config_file.write_bytes(original)
            # Any attempt at the old health request fails the no-service contract.
            with patch('socket.create_connection', side_effect=AssertionError('network access forbidden')):
                with self.assertRaisesRegex((SystemExit, ValueError), 'codex-headroom'):
                    self.run_main(home, 'enable')
            self.assertEqual(config_file.read_bytes(), original)
            self.assertEqual(list(Path(home).iterdir()), [config_file])

    def test_missing_config_status_and_disable_are_noops(self):
        with tempfile.TemporaryDirectory() as home:
            for action in ('status', 'disable'):
                result = self.run_main(home, action)
                self.assertFalse(result['enabled'])
                self.assertFalse(result['global_route_enabled'])
            self.assertEqual(list(Path(home).iterdir()), [])

    def test_default_config_home_is_used_when_environment_is_missing(self):
        with tempfile.TemporaryDirectory() as home:
            output = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), \
                 patch.object(Path, 'home', return_value=Path(home)), \
                 patch.object(sys, 'argv', ['routing.py', 'status']), \
                 patch('sys.stdout', output):
                routing.main()
            result = json.loads(output.getvalue())
            self.assertEqual(Path(result['config']), Path(home) / '.codex' / 'config.toml')
            self.assertFalse(result['enabled'])
            self.assertEqual(list(Path(home).iterdir()), [])

    def test_concurrent_edit_before_replace_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as home:
            config_file = Path(home) / 'config.toml'
            original = LEGACY_TOP.encode()
            user_edit = b'model = "user-selected-model"\n'
            config_file.write_bytes(original)
            make_temp = tempfile.mkstemp

            def concurrent_edit(*args, **kwargs):
                config_file.write_bytes(user_edit)
                return make_temp(*args, **kwargs)

            with patch.object(routing.tempfile, 'mkstemp', side_effect=concurrent_edit):
                with self.assertRaisesRegex(RuntimeError, 'concurrently'):
                    self.run_main(home, 'disable')
            self.assertEqual(config_file.read_bytes(), user_edit)
            self.assertEqual(list(Path(home).glob('*.token-saver.tmp')), [])

    def test_status_distinguishes_real_route_from_string_lookalike(self):
        with tempfile.TemporaryDirectory() as home:
            config_file = Path(home) / 'config.toml'
            config_file.write_text(LEGACY_TOP + LEGACY_PROVIDER, encoding='utf-8')
            self.assertTrue(self.run_main(home, 'status')['enabled'])
            config_file.write_text('note = \'openai_base_url = "http://127.0.0.1:8787/v1"\'\n', encoding='utf-8')
            self.assertFalse(self.run_main(home, 'status')['enabled'])

    def test_disable_backs_up_exact_original_bytes_and_preserves_bom(self):
        with tempfile.TemporaryDirectory() as home:
            config_file = Path(home) / 'config.toml'
            original = b'\xef\xbb\xbf' + (LEGACY_TOP + 'model = "gpt-6-astra"\n' + LEGACY_PROVIDER).replace('\n', '\r\n').encode()
            config_file.write_bytes(original)
            result = self.run_main(home, 'disable')
            self.assertFalse(result['enabled'])
            self.assertEqual(config_file.read_bytes(), b'\xef\xbb\xbfmodel = "gpt-6-astra"\r\n')
            backups = list((Path(home) / 'backups').glob('config-*.toml'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), original)


if __name__ == '__main__':
    unittest.main()

