"""Runtime selection must stay local; navigation must not expose write tools."""
import importlib.util
import json
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

    @unittest.skipUnless((ROOT / "serena/.venv/Scripts/python.exe").exists(), "Serena not installed")
    def test_actual_mcp_probe_verifies_declared_navigation_tools(self):
        module = self.module()
        self.assertTrue(hasattr(module, "probe_runtime"), "MCP compatibility probe is not implemented")
        report = module.probe_runtime(ROOT)
        self.assertTrue(report["ok"])
        self.assertEqual(set(report["tools"]), set(module.NAVIGATION_TOOLS))
        self.assertEqual(report["version"], "1.7.0")


if __name__ == "__main__":
    unittest.main()
