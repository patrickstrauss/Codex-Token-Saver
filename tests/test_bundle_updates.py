"""Update jobs are explicit, staged, verified, and reversible without real downloads."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import os
import subprocess
import sys
import unittest
from unittest.mock import patch
import zipfile

import bundle_updates as updates


def archive(name="rtk.exe", content=b"MZfixture"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as handle:
        handle.writestr(name, content)
    return output.getvalue()


class BundleUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bundle updater test ")
        self.root = Path(self.tmp.name)
        (self.root / "tools").mkdir()
        (self.root / "tools/rtk.exe").write_bytes(b"MZold")
        metadata = self.root / "headroom/.venv/Lib/site-packages/headroom_ai-0.37.0.dist-info"
        metadata.mkdir(parents=True)
        (metadata / "METADATA").write_text("Name: headroom-ai\nVersion: 0.37.0\n")
        self.versions = patch.object(updates.BundleUpdater, "_current_versions", return_value={"headroom": "0.37.0", "rtk": "0.49.0"})
        self.versions.start()
        self.addCleanup(self.versions.stop)
        self.addCleanup(self.tmp.cleanup)
        self.manager = updates.BundleUpdater(self.root)

    def wait(self, manager=None):
        manager = manager or self.manager
        deadline = time.monotonic() + 5
        while manager.status()["busy"] and time.monotonic() < deadline:
            time.sleep(.01)
        value = manager.status()
        self.assertFalse(value["busy"])
        return value

    def metadata(self, url, limit):
        if url == updates.PYPI_URL:
            return json.dumps({"info": {"version": "0.38.0"}}).encode()
        return json.dumps({"tag_name": "v0.50.0", "draft": False, "prerelease": False,
                           "assets": [{"name": updates.RTK_ASSET, "digest": "sha256:" + "a" * 64}]}).encode()

    def checked(self):
        with patch.object(updates, "fetch_bytes", side_effect=self.metadata):
            self.manager.start("check")
            result = self.wait()
        self.assertIsNone(result["error"])
        return result

    def test_status_does_not_access_network_and_exposes_only_safe_fields(self):
        with patch.object(updates, "fetch_bytes", side_effect=AssertionError("network forbidden")):
            state = self.manager.status()
        self.assertFalse(state["busy"])
        self.assertEqual([x["current"] for x in state["components"][:2]], ["0.37.0", "0.49.0"])
        self.assertNotIn(str(self.root), json.dumps(state))

    def test_stable_versions_only(self):
        for value in ("1.2.3", "0.38.0", "1.2"):
            self.assertIsNotNone(updates.stable_version(value))
        for value in ("1.2.3rc1", "v1.2.3", "../1.2.3", "1.2.3+evil", "01.2.3", "1.2.3\n", None):
            self.assertIsNone(updates.stable_version(value))

    def test_manual_check_finds_official_releases_only(self):
        state = self.checked()
        self.assertEqual([x["latest"] for x in state["components"][:2]], ["0.38.0", "0.50.0"])
        self.assertTrue(all(x["update_available"] for x in state["components"][:2]))
        self.assertIsNotNone(state["last_checked"])

    def test_install_requires_checked_candidate_and_rejects_arbitrary_input(self):
        for action, component in (("install", "headroom"), ("install", "rtk")):
            with self.assertRaises(RuntimeError):
                self.manager.start(action, component)
        for action, component in (("shell", "rtk"), ("install", "../evil"), ("check", "rtk")):
            with self.assertRaises(ValueError):
                self.manager.start(action, component)

    def test_failed_check_invalidates_previously_checked_install_plan(self):
        self.checked()
        with patch.object(updates, "fetch_bytes", side_effect=OSError("secret-url-and-token")):
            self.manager.start("check")
            state = self.wait()
        self.assertTrue(all(x["error"] for x in state["components"]))
        self.assertNotIn("secret-url", json.dumps(state))
        with self.assertRaises(RuntimeError):
            self.manager.start("install", "rtk")

    def test_same_headroom_release_offers_explicit_dependency_refresh_only(self):
        def same(url, limit):
            if url == updates.PYPI_URL:
                return b'{"info":{"version":"0.37.0"}}'
            return self.metadata(url, limit).replace(b"0.50.0", b"0.49.0")
        with patch.object(updates, "fetch_bytes", side_effect=same):
            self.manager.start("check")
            state = self.wait()
        self.assertFalse(any(x["update_available"] for x in state["components"]))
        self.assertTrue(state["components"][0]["refresh_available"])
        self.assertFalse(state["components"][1]["refresh_available"])
        with patch.object(self.manager, "_install_headroom") as installer:
            self.manager.start("install", "headroom")
            self.wait()
            installer.assert_called_once()
        with self.assertRaises(RuntimeError):
            self.manager.start("install", "rtk")

    def test_package_environment_discards_index_and_python_overrides(self):
        with patch.dict(os.environ, {"UV_INDEX_URL":"https://bad.invalid", "PIP_EXTRA_INDEX_URL":"https://bad.invalid", "PYTHONPATH":"bad", "UV_CONFIG_FILE":"bad"}):
            environment = self.manager._environment()
        self.assertNotIn("UV_INDEX_URL", environment)
        self.assertNotIn("PIP_EXTRA_INDEX_URL", environment)
        self.assertNotIn("PYTHONPATH", environment)
        self.assertEqual(environment["UV_PYTHON_DOWNLOADS"], "never")
        self.assertEqual(environment["UV_NO_CONFIG"], "1")

    def test_expired_release_plan_is_not_offered_and_idle_versions_are_refreshed(self):
        self.checked()
        state = self.manager._read_state()
        for plan in state["plans"].values():
            plan["checked_at"] = time.time() - updates.PLAN_MAX_AGE - 1
        self.manager._write_state(state)
        with patch.object(self.manager, "_current_versions", return_value={"headroom":"0.38.0", "rtk":"0.50.0"}):
            snapshot = self.manager.status()
        self.assertEqual([x["current"] for x in snapshot["components"][:2]], ["0.38.0", "0.50.0"])
        self.assertFalse(any(x["update_available"] or x["refresh_available"] for x in snapshot["components"]))

    def test_runtime_fallback_descriptor_uses_effective_baseline(self):
        (self.root / "updates/active.json").write_text(json.dumps({"schema":1, "headroom": {
            "version":"0.99.0", "runtime":"updates/runtimes/headroom-0.99.0-missing"}}))
        descriptor = self.manager._current_headroom_descriptor()
        self.assertEqual(descriptor, {"version":"0.37.0", "runtime":None})

    def test_single_file_lock_blocks_other_instances(self):
        gate = threading.Event()
        entered = threading.Event()
        def blocked(url, limit):
            entered.set()
            gate.wait(4)
            return self.metadata(url, limit)
        with patch.object(updates, "fetch_bytes", side_effect=blocked):
            self.manager.start("check")
            self.assertTrue(entered.wait(2))
            other = updates.BundleUpdater(self.root)
            self.assertTrue(other.status()["busy"])
            with self.assertRaises(RuntimeError):
                other.start("check")
            gate.set()
            self.wait()

    def test_interrupted_job_is_reported_without_activation_or_network(self):
        state = self.manager._read_state()
        state.update(busy=True, operation="install", stage="staging", component="headroom")
        self.manager._write_state(state)
        with patch.object(updates, "fetch_bytes", side_effect=AssertionError("network forbidden")):
            other = updates.BundleUpdater(self.root)
            snapshot = other.status()
        self.assertFalse(snapshot["busy"])
        self.assertEqual(snapshot["stage"], "interrupted")
        self.assertFalse((self.root / "updates/active.json").exists())

    def test_recovery_does_not_overwrite_a_just_completed_job(self):
        state = self.manager._read_state()
        state.update(busy=True, stage="validating")
        self.manager._write_state(state)
        claim = self.manager._claim_lock
        def completed_before_lock():
            completed = self.manager._read_state()
            completed.update(busy=False, stage="complete")
            self.manager._write_state(completed)
            return claim()
        with patch.object(self.manager, "_claim_lock", side_effect=completed_before_lock):
            self.manager._recover_interrupted()
        self.assertEqual(self.manager._read_state()["stage"], "complete")

    def test_file_lock_is_shared_with_another_process(self):
        handle = self.manager._claim_lock()
        self.assertIsNotNone(handle)
        script = "from bundle_updates import BundleUpdater; import sys; u=BundleUpdater(sys.argv[1]); assert u.status()['busy']; "
        script += "\ntry: u.start('check')\nexcept RuntimeError: print('LOCKED')\nelse: raise AssertionError('Lock was bypassed')\n"
        try:
            result = subprocess.run([sys.executable, "-c", script, str(self.root)], capture_output=True, timeout=15,
                                    cwd=Path(updates.__file__).resolve().parent)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            self.assertEqual(result.stdout.strip(), b"LOCKED")
        finally:
            self.manager._release_lock(handle)

    def test_corrupt_download_and_checksum_missing_are_rejected(self):
        plan = {"version": "0.50.0", "tag": "v0.50.0", "sha256": "0" * 64}
        with patch.object(updates, "fetch_bytes", return_value=archive()):
            with self.assertRaises(updates.UpdateError):
                self.manager._download_rtk(plan)
        release = {"tag_name": "v0.50.0", "assets": [{"name": updates.RTK_ASSET}]}
        with patch.object(updates, "fetch_bytes", return_value=json.dumps(release).encode()):
            with self.assertRaises(updates.UpdateError):
                self.manager._check_rtk()

    def test_zip_traversal_symlink_and_oversize_are_rejected(self):
        for name in ("../rtk.exe", "C:/rtk.exe", "/rtk.exe", "safe/../../rtk.exe"):
            with self.subTest(name=name), self.assertRaises(updates.UpdateError):
                updates.extract_rtk(archive(name))
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as handle:
            item = zipfile.ZipInfo("rtk.exe")
            item.create_system = 3
            item.external_attr = (0o120777 << 16)
            handle.writestr(item, "target")
        with self.assertRaises(updates.UpdateError):
            updates.extract_rtk(data.getvalue())
        with patch.object(updates, "MAX_BINARY_BYTES", 4), self.assertRaises(updates.UpdateError):
            updates.extract_rtk(archive())
        self.assertEqual(updates.extract_rtk(archive()), b"MZfixture")

    def test_official_network_allowlist_rejects_arbitrary_hosts_and_plain_http(self):
        for url in ("http://pypi.org/pypi/headroom-ai/json", "https://bad.invalid/file.zip",
                    "https://github.com/other/project/releases/download/v1/file.zip", "https://user:secret@github.com/rtk-ai/rtk/releases/download/v1/file.zip"):
            with self.subTest(url=url), self.assertRaises(updates.UpdateError):
                updates.fetch_bytes(url, 1024)

    def test_release_plan_rejects_arbitrary_versions_before_download(self):
        with patch.object(updates, "fetch_bytes", side_effect=AssertionError("unexpected download")):
            for plan in ({"version":"../0.50.0", "tag":"v0.50.0", "sha256":"a"*64},
                         {"version":"0.50.0", "tag":"other", "sha256":"a"*64},
                         {"version":"0.50.0", "tag":"v0.50.0", "sha256":"missing"}):
                with self.assertRaises(updates.UpdateError):
                    self.manager._download_rtk(plan)

    def test_headroom_activation_and_baseline_rollback_use_atomic_manifest(self):
        runtime = self.root / "updates/runtimes/headroom-0.38.0-fixture"
        runtime.mkdir(parents=True)
        candidate = {"version": "0.38.0", "runtime": runtime.relative_to(self.root).as_posix()}
        with patch.object(self.manager, "_validate_headroom"), \
             patch.object(self.manager, "_current_headroom_descriptor", side_effect=[{"version":"0.37.0","runtime":None}, candidate]):
            self.manager._activate_headroom(candidate)
            manifest = json.loads((self.root / "updates/active.json").read_text())
            self.assertEqual(manifest["headroom"]["version"], "0.38.0")
            self.assertEqual(manifest["headroom"]["previous"], {"version": "0.37.0", "runtime": None})
            self.manager._rollback_headroom()
            manifest = json.loads((self.root / "updates/active.json").read_text())
            self.assertIsNone(manifest["headroom"])
            self.assertEqual(manifest["headroom_previous"]["version"], "0.38.0")

    def test_failed_headroom_validation_never_changes_active_runtime(self):
        runtime = self.root / "updates/runtimes/headroom-0.38.0-fixture"
        runtime.mkdir(parents=True)
        candidate = {"version": "0.38.0", "runtime": runtime.relative_to(self.root).as_posix()}
        with patch.object(self.manager, "_stage_headroom", return_value=candidate), \
             patch.object(self.manager, "_validate_headroom", side_effect=updates.UpdateError("Candidate validation failed.")):
            with self.assertRaises(updates.UpdateError):
                self.manager._install_headroom({"version": "0.38.0"})
        self.assertFalse((self.root / "updates/active.json").exists())

    def test_rtk_activation_keeps_backup_and_busy_failure_keeps_old_binary(self):
        candidate = self.root / "updates/rtk-stage.exe"
        candidate.parent.mkdir(exist_ok=True)
        candidate.write_bytes(b"MZnew")
        original_replace = updates.os.replace
        def busy(source, destination):
            if Path(destination).resolve() == (self.root / "tools/rtk.exe").resolve():
                raise PermissionError("busy")
            return original_replace(source, destination)
        with patch.object(updates.os, "replace", side_effect=busy):
            with self.assertRaises(updates.UpdateError):
                self.manager._activate_rtk(candidate, "0.50.0")
        self.assertEqual((self.root / "tools/rtk.exe").read_bytes(), b"MZold")
        self.assertFalse((self.root / "updates/rtk.json").exists())
        self.manager._activate_rtk(candidate, "0.50.0")
        self.assertEqual((self.root / "tools/rtk.exe").read_bytes(), b"MZnew")
        metadata = json.loads((self.root / "updates/rtk.json").read_text())
        backup = self.root / metadata["previous"]["path"]
        self.assertEqual(backup.read_bytes(), b"MZold")
        self.assertEqual(metadata["sha256"], hashlib.sha256(b"MZnew").hexdigest())

    def test_rtk_journal_recovers_after_binary_swap_before_metadata_commit(self):
        candidate = self.root / "updates/rtk-stage.exe"
        candidate.parent.mkdir(exist_ok=True)
        candidate.write_bytes(b"MZnew")
        original = updates._atomic_json
        def failed_metadata(path, value):
            if path.name == "rtk.json":
                raise OSError("simulated metadata disk failure")
            return original(path, value)
        with patch.object(updates, "_atomic_json", side_effect=failed_metadata):
            with self.assertRaises(OSError):
                self.manager._activate_rtk(candidate, "0.50.0")
        self.assertEqual((self.root / "tools/rtk.exe").read_bytes(), b"MZnew")
        recovered = self.manager._rtk_metadata()
        self.assertEqual(recovered["version"], "0.50.0")
        previous, path = self.manager._rtk_backup()
        self.assertEqual(previous["version"], "0.49.0")
        self.assertEqual(path.read_bytes(), b"MZold")

    def test_headroom_validation_checks_both_launch_paths_and_reverse_cache_compatibility(self):
        runtime = self.root / "updates/runtimes/headroom-0.38.0-fixture"
        metadata = runtime / "Lib/site-packages/headroom_ai-0.38.0.dist-info"
        metadata.mkdir(parents=True)
        (metadata / "METADATA").write_text("Name: headroom-ai\nVersion: 0.38.0\n")
        (runtime / "Scripts").mkdir()
        (runtime / "Scripts/python.exe").write_bytes(b"fixture")
        (runtime / "pyvenv.cfg").write_text("version_info = 3.13\n")
        descriptor = {"version":"0.38.0", "runtime":runtime.relative_to(self.root).as_posix()}
        with patch.object(self.manager, "_run", return_value='{"validated": true}') as run:
            self.manager._validate_headroom(descriptor)
        calls = [x.args[0] for x in run.call_args_list]
        self.assertEqual([x[5] for x in calls], ["seed", "candidate-native", "candidate-selected", "backcheck", "mcp"])
        self.assertEqual(Path(calls[1][0]).resolve(), (runtime / "Scripts/python.exe").resolve())
        self.assertEqual(Path(calls[2][0]).resolve(), (self.root / "headroom/.venv/Scripts/python.exe").resolve())
        self.assertTrue(json.loads((runtime / "update-receipt.json").read_text())["validated"])

    def proxy_candidate(self):
        runtime = self.root / 'updates/runtimes/headroom-0.38.0-proxy'
        metadata = runtime / 'Lib/site-packages/headroom_ai-0.38.0.dist-info'
        metadata.mkdir(parents=True)
        (metadata / 'METADATA').write_text('Name: headroom-ai\nVersion: 0.38.0\n')
        (runtime / 'Scripts').mkdir()
        (runtime / 'Scripts/python.exe').write_bytes(b'fixture')
        (runtime / 'pyvenv.cfg').write_text('version_info = 3.13\n')
        (self.root / 'proxy_runtime.py').write_text('# Managed proxy marker\n')
        report = {'ok': True, 'version': '0.38.0', 'mode': 'token', 'profile': 'coding',
                  'compress_user_messages': False, 'compress_system_messages': False,
                  'read_maturation': True, 'output_shaper': False, 'effort_router': False,
                  'model_router': False, 'code_aware': True, 'log_requests': False, 'savings_flush_every': 1,
                  'request_invariants_preserved': True, 'exact_retrieval_protected': True}
        descriptor = {'version': '0.38.0', 'runtime': runtime.relative_to(self.root).as_posix()}
        return runtime, descriptor, report

    def test_proxy_candidate_validation_uses_candidate_and_isolated_model_state(self):
        runtime, candidate, config = self.proxy_candidate()
        (self.root / 'models').mkdir()
        (self.root / 'models/headroom-proxy-model.json').write_text('{"assets":[]}')
        model = {'ok': True, 'model_ready': True, 'exact_original_recovered': True,
                 'small_saving_recovered': True, 'tokens_before': 1250, 'tokens_after': 1085}
        with patch.object(self.manager, '_run', return_value='{"validated": true}'), \
             patch('proxy_runtime.validate_proxy_runtime', return_value=config) as config_probe, \
             patch('proxy_runtime.validate_proxy_model', return_value=model) as model_probe:
            self.manager._validate_headroom(candidate)
        config_probe.assert_called_once()
        model_probe.assert_called_once()
        for probe in (config_probe, model_probe):
            self.assertEqual(probe.call_args.args[0].resolve(), runtime.resolve())
            self.assertTrue(Path(probe.call_args.args[1]).resolve().is_relative_to((self.root / 'updates/validation').resolve()))
            self.assertEqual(probe.call_args.kwargs['timeout'], 45)
        self.assertNotEqual(config_probe.call_args.args[1], model_probe.call_args.args[1])
        receipt = json.loads((runtime / 'update-receipt.json').read_text())
        self.assertEqual(receipt['validation_phases'][-2:], ['proxy-config', 'proxy-model'])
        self.assertEqual(receipt['proxy_validation']['configuration']['version'], '0.38.0')
        self.assertFalse((self.root / 'updates/active.json').exists())
        self.assertFalse((self.root / 'proxy/validation.json').exists())

    def test_failed_proxy_candidate_blocks_install_and_rollback_activation(self):
        runtime, candidate, config = self.proxy_candidate()
        config['output_shaper'] = True
        manifest = {'schema': 1, 'headroom': None, 'headroom_previous': candidate}
        path = self.root / 'updates/active.json'
        path.write_text(json.dumps(manifest))
        original = path.read_bytes()
        with patch.object(self.manager, '_stage_headroom', return_value=candidate), \
             patch.object(self.manager, '_run', return_value='{"validated": true}'), \
             patch('proxy_runtime.validate_proxy_runtime', return_value=config):
            for action in (lambda: self.manager._install_headroom({'version': '0.38.0'}),
                           self.manager._rollback_headroom):
                with self.assertRaisesRegex(updates.UpdateError, 'desktop proxy'):
                    action()
                self.assertEqual(path.read_bytes(), original)
        self.assertFalse((runtime / 'update-receipt.json').exists())

    def test_proxy_model_failure_blocks_candidate_and_absent_optional_model_skips_probe(self):
        runtime, candidate, config = self.proxy_candidate()
        with patch.object(self.manager, '_run', return_value='{"validated": true}'), \
             patch('proxy_runtime.validate_proxy_runtime', return_value=config), \
             patch('proxy_runtime.validate_proxy_model', side_effect=AssertionError('Unexpected model probe')):
            self.manager._validate_headroom(candidate)
        (self.root / 'models').mkdir()
        (self.root / 'models/headroom-proxy-model.json').write_text('{}')
        with patch.object(self.manager, '_run', return_value='{"validated": true}'), \
             patch('proxy_runtime.validate_proxy_runtime', return_value=config), \
             patch('proxy_runtime.validate_proxy_model', return_value={'ok': False, 'error': 'native ABI failure'}):
            with self.assertRaisesRegex(updates.UpdateError, 'Kompress'):
                self.manager._validate_headroom(candidate)
        self.assertFalse((self.root / 'updates/active.json').exists())

    def test_proxy_candidate_requires_verified_exact_retrieval_protection(self):
        runtime, candidate, config = self.proxy_candidate()
        for value in (None, False, 'true', 1):
            invalid = dict(config)
            if value is None:
                invalid.pop('exact_retrieval_protected')
            else:
                invalid['exact_retrieval_protected'] = value
            with self.subTest(value=value), \
                 patch.object(self.manager, '_run', return_value='{"validated": true}'), \
                 patch('proxy_runtime.validate_proxy_runtime', return_value=invalid), \
                 self.assertRaises(updates.UpdateError):
                self.manager._validate_headroom(candidate)

    def test_proxy_candidate_requires_version_and_critical_fields(self):
        runtime, candidate, config = self.proxy_candidate()
        for change in ({'version': '0.37.0'}, {'ok': False}, {'effort_router': True},
                       {'model_router': True}, {'compress_user_messages': True},
                       {'request_invariants_preserved': False}, {'read_maturation': None}):
            invalid = dict(config, **change)
            with self.subTest(change=change), \
                 patch.object(self.manager, '_run', return_value='{"validated": true}'), \
                 patch('proxy_runtime.validate_proxy_runtime', return_value=invalid), \
                 self.assertRaises(updates.UpdateError):
                self.manager._validate_headroom(candidate)


if __name__ == "__main__":
    unittest.main()
