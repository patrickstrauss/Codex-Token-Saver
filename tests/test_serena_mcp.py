"""Runtime selection must stay local; navigation must not expose write tools."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SerenaLauncherTests(unittest.TestCase):
    def module(self):
        path = ROOT / "serena_mcp.py"
        self.assertTrue(path.is_file(), "Managed Serena launcher is not implemented")
        spec = importlib.util.spec_from_file_location("managed_serena_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_default_runtime_and_state_are_bundle_local(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            expected = root / "serena/.venv/Scripts/python.exe"
            expected.parent.mkdir(parents=True)
            expected.touch()
            spec = module.launch_spec(root, environ={"SERENA_HOME": "C:/unrelated"})
            self.assertEqual(Path(spec[0][0]), expected)
            self.assertEqual(spec[1]["SERENA_HOME"], str(root / "serena/state"))
            self.assertNotIn("--project-from-cwd", spec[0])
            self.assertNotIn("--project", spec[0])
            self.assertIn("--enable-web-dashboard", spec[0])

    def test_javascript_backend_receives_private_node_without_global_changes(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            python = root / 'serena/.venv/Scripts/python.exe'
            python.parent.mkdir(parents=True)
            python.touch()
            (root / 'packaging').mkdir()
            (root / 'packaging/dependencies.json').write_text('{"node":{"version":"24.21.0"}}')
            (root / 'packaging/package-lock.json').write_text('{}')
            node = root / 'tools/node-v24.21.0-win-x64'
            node.mkdir(parents=True)
            for name in ('node.exe', 'npm.cmd'):
                (node / name).touch()
            original = {'Path': 'caller-path', 'PYTHONPATH': 'foreign'}
            _, env = module.launch_spec(root, environ=original)
            self.assertEqual(env['PATH'], str(node) + os.pathsep + 'caller-path')
            self.assertNotIn('Path', env)
            self.assertNotIn('PYTHONPATH', env)
            self.assertEqual(original, {'Path': 'caller-path', 'PYTHONPATH': 'foreign'})

    def test_manifest_can_select_an_isolated_updated_runtime(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            candidate = root / "serena/runtimes/1.8.0/Scripts/python.exe"
            candidate.parent.mkdir(parents=True)
            candidate.touch()
            (root / "serena/runtime.json").write_text(json.dumps({
                "schema_version": 1, "python_path": "serena/runtimes/1.8.0/Scripts/python.exe",
                "version": "1.8.0",
            }), encoding="utf-8")
            self.assertEqual(module.runtime_python(root), candidate)

    def test_manifest_never_selects_outside_runtime_directory(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "serena").mkdir()
            for value in ("../outside.exe", "dashboard/.venv/Scripts/python.exe", "C:/Windows/python.exe"):
                with self.subTest(value=value):
                    (root / "serena/runtime.json").write_text(json.dumps({
                        "schema_version": 1, "python_path": value, "version": "1.8.0",
                    }), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        module.runtime_python(root)

    def test_invalid_manifest_fails_instead_of_silently_using_other_runtime(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "serena").mkdir()
            (root / "serena/runtime.json").write_text('{"schema_version": 99}', encoding="utf-8")
            with self.assertRaises(ValueError):
                module.runtime_python(root)

    def test_official_context_uses_four_navigation_tools_only(self):
        module = self.module()
        expected = {"activate_project", "get_symbols_overview", "find_symbol", "find_referencing_symbols"}
        self.assertEqual(set(module.NAVIGATION_TOOLS), expected)
        context = (ROOT / "serena/navigation.yml").read_text(encoding="utf-8")
        self.assertIn("fixed_tools:", context)
        for name in expected:
            self.assertIn("  - " + name + "\n", context)
        self.assertNotIn("planning mode", context)

    def test_navigation_schema_validation_accepts_sdk_protocol_aliases(self):
        module = self.module()
        module.validate_navigation_tools(ROOT, module.navigation_tools(ROOT))

    def test_navigation_schema_validation_rejects_changed_input(self):
        from mcp.types import Tool
        module = self.module()
        tools = module.navigation_tools(ROOT)
        record = tools[0].model_dump(by_alias=True)
        record['inputSchema'] = {'type': 'object', 'required': ['unexpected_argument']}
        tools[0] = Tool.model_validate(record)
        with self.assertRaises(RuntimeError):
            module.validate_navigation_tools(ROOT, tools)

    def test_new_activation_session_field_keeps_public_schema(self):
        from mcp.types import Tool
        module = self.module()
        tools = module.navigation_tools(ROOT)
        index = next(i for i, tool in enumerate(tools) if tool.name == 'activate_project')
        record = tools[index].model_dump(by_alias=True)
        record['inputSchema']['properties']['session_id'] = {'type': 'string'}
        record['inputSchema'].setdefault('required', []).append('session_id')
        tools[index] = Tool.model_validate(record)
        module.validate_navigation_tools(ROOT, tools)

    def test_navigation_description_change_preserves_input_contract(self):
        from mcp.types import Tool
        module = self.module()
        tools = module.navigation_tools(ROOT)
        record = tools[0].model_dump(by_alias=True)
        field = next(iter(record['inputSchema']['properties'].values()))
        field['description'] = 'Updated upstream documentation.'
        tools[0] = Tool.model_validate(record)
        module.validate_navigation_tools(ROOT, tools)

    def test_new_serena_keeps_navigation_tools_interface(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            python = root / 'serena/.venv/Scripts/python.exe'
            python.parent.mkdir(parents=True)
            python.touch()
            for version in ('1.7.0', '2.0.0'):
                metadata = python.parent.parent / ('Lib/site-packages/serena_agent-' + version + '.dist-info/METADATA')
                metadata.parent.mkdir(parents=True)
                metadata.write_text('Name: serena-agent\nVersion: ' + version + '\n')
                command, _ = module.launch_spec(root, environ={})
                if version.startswith('2.'):
                    self.assertIn('--agent-interface', command)
                    self.assertEqual(command[command.index('--agent-interface') + 1], 'tools')
                else:
                    self.assertNotIn('--agent-interface', command)
                metadata.unlink()

    @unittest.skipUnless((ROOT / "serena/.venv/Scripts/python.exe").exists(), "Serena not installed")
    def test_actual_mcp_probe_verifies_declared_navigation_tools(self):
        module = self.module()
        self.assertTrue(hasattr(module, "probe_runtime"), "MCP compatibility probe is not implemented")
        report = module.probe_runtime(ROOT)
        self.assertTrue(report["ok"])
        self.assertEqual(set(report["tools"]), set(module.NAVIGATION_TOOLS))
        selected = json.loads((ROOT / 'serena/runtime.json').read_text())
        self.assertEqual(report["version"], selected['version'])


if __name__ == "__main__":
    unittest.main()
