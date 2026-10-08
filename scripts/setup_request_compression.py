"""Validate a team's installed proxy locally, leaving Codex on its current route."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve()


def read(path):
    return path.read_bytes() if path.exists() else None


def encode(value):
    return (json.dumps(value, indent=2) + '\n').encode('utf-8')


def load_api(root):
    # The entry point may be in a newly extracted artifact; validate the code
    # actually installed on this machine, never the artifact's proxy modules.
    sys.path.insert(0, str(root))
    from desktop_proxy_control import DesktopProxyControl, CRITICAL_FILES, atomic_write, routing_lock
    from desktop_proxy_service import lifetime_lock
    from proxy_runtime import validate_proxy_runtime, validate_proxy_model
    from runtime_selection import selected_runtime
    from service_control import ServiceController
    # The isolated helper imports this module too; pin it to the installed
    # bundle before helper scripts temporarily add their own artifact path.
    import scripts.verify_backend_receipt  # noqa: F401
    return SimpleNamespace(control=DesktopProxyControl(root), critical=CRITICAL_FILES,
                           atomic=atomic_write, lock=routing_lock, lifetime=lifetime_lock,
                           validate_runtime=validate_proxy_runtime, validate_model=validate_proxy_model,
                           runtime=selected_runtime(root), cleanup=ServiceController.cleanup_created_process)


def source_hashes(root, names):
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}


def child_environment():
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'PYTHONHOME', 'OPENAI_BASE_URL'):
        env.pop(key, None)
    env['PYTHONUTF8'] = '1'
    return env


def run_worker(root, flag, timeout):
    from scripts.verify_backend_receipt import _windows_job
    from service_control import ServiceController
    process = subprocess.Popen(
        [str(root / 'headroom/.venv/Scripts/python.exe'), str(SCRIPT),
         '--bundle-root', str(root), flag], cwd=root, env=child_environment(),
        stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    close = None
    try:
        close = _windows_job(process)
        code = process.wait(timeout=timeout)
    finally:
        if close is not None:
            close()
        elif process.poll() is None:
            ServiceController.cleanup_created_process(process)
    if code:
        raise RuntimeError('Local setup validation failed; inspect the preceding diagnostic.')


def start_supervisor(root):
    (root / 'logs').mkdir(parents=True, exist_ok=True)
    with (root / 'logs/proxy-supervisor.stdout.log').open('ab') as output, \
            (root / 'logs/proxy-supervisor.stderr.log').open('ab') as errors:
        return subprocess.Popen(
            [str(root / 'headroom/.venv/Scripts/pythonw.exe'),
             str(root / 'desktop_proxy_service.py'), 'run'], cwd=root,
            env=child_environment(), stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def wait_ready(control, process):
    deadline = time.monotonic() + 45
    while True:
        if process is not None and process.poll() is not None:
            raise RuntimeError('The new supervisor exited before readiness.')
        status = control.status()
        if status.get('ready') and status.get('validated') and status.get('supervisor', {}).get('live'):
            return status
        if time.monotonic() >= deadline:
            raise RuntimeError('The local connection did not become ready; Codex routing was unchanged.')
        time.sleep(.25)


def install_startup(root):
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run(
        [str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
         '-File', str(root / 'Install-Startup.ps1'), '-Start'], cwd=root,
        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding='utf-8',
        errors='replace', timeout=90, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Tray startup setup failed; see install-startup-result.json. Codex routing was unchanged.')
    report = json.loads(result.stdout)
    if report.get('success') is not True or report.get('scheduled_task', {}).get('started') is not True:
        raise RuntimeError('Tray startup did not confirm success; inspect install-startup-result.json.')
    return report


def check_ports():
    for port in (8788, 8789):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError(f'Port {port} is already in use; the existing service was preserved.')


def setup(root, api):
    control = api.control
    # Share both locks with the existing updater and routing UI. No model,
    # runtime, or route can be switched midway through this validation.
    with api.lock(root / 'updates/operation.lock'), api.lock(root / 'proxy/routing.lock'):
        initial = control.status()
        if initial.get('enabled'):
            if not initial.get('validated'):
                raise RuntimeError('An enabled proxy needs repair; it was preserved. Pause it before running setup.')
            return {'ok': True, 'already_configured': True, 'enabled': True, 'route_changed': False}
        if initial.get('route_enabled'):
            raise RuntimeError('An existing local route was preserved. Use Restore Direct before fresh setup.')
        if initial.get('installed') and initial.get('validated') and initial.get('ready') and initial.get('supervisor', {}).get('live'):
            return {'ok': True, 'already_configured': True, 'enabled': False, 'route_changed': False}
        before_config = read(control.config_file)
        hashes = source_hashes(root, api.critical)
        print('Downloading and verifying the public compression model (up to 15 minutes)...', flush=True)
        run_worker(root, '--prefetch-worker', 930)
        with tempfile.TemporaryDirectory(prefix='token-saver-setup-') as temporary:
            state = Path(temporary)
            runtime = api.validate_runtime(api.runtime, state / 'runtime', timeout=60)
            model = api.validate_model(api.runtime, state / 'model', timeout=90)
        if not (runtime.get('ok') is True and runtime.get('request_invariants_preserved') is True
                and runtime.get('exact_retrieval_protected') is True and model.get('ok') is True
                and model.get('model_ready') is True and model.get('exact_original_recovered') is True
                and model.get('small_saving_recovered') is True
                and all(runtime.get(key) is False for key in (
                    'compress_user_messages', 'compress_system_messages', 'output_shaper',
                    'effort_router', 'model_router', 'log_requests'))):
            raise RuntimeError('Local compression or exact retrieval validation failed; nothing was enabled.')
        print('Checking the backend on an isolated local port...', flush=True)
        run_worker(root, '--probe-worker', 120)
        if hashes != source_hashes(root, api.critical) or read(control.config_file) != before_config:
            raise RuntimeError('Installed sources or Codex settings changed during validation; run setup again.')
        paths = (control.settings_file, root / 'proxy/validation.json')
        previous = {path: read(path) for path in paths}
        settings = json.loads(previous[paths[0]].decode('utf-8-sig')) if previous[paths[0]] else {}
        if (not isinstance(settings, dict) or settings.get('enabled') is True
                or any(key in settings and type(settings[key]) is not bool for key in ('installed', 'enabled'))):
            raise RuntimeError('Proxy settings changed or are invalid; they were preserved.')
        validation = {'schema': 1, 'passed': True, 'timestamp': datetime.now(timezone.utc).isoformat(),
                      'source_hashes': hashes, 'runtime': runtime, 'model': model,
                      'isolated_backend_verified': True, 'full_windows_reboot_tested': False,
                      'routing_enabled_by_setup': False}
        written = {paths[0]: encode(dict(settings, installed=True, enabled=False)), paths[1]: encode(validation)}
        process = None
        # Keep tray recovery from racing with our retained supervisor handle.
        with api.lifetime(root / 'proxy/recovery.lock') as acquired:
            if not acquired:
                raise RuntimeError('A supervisor recovery is running; retry setup shortly.')
            live = control.status().get('supervisor', {}).get('live') is True
            if not live:
                check_ports()
            try:
                for path in paths:
                    if read(path) != previous[path]:
                        raise RuntimeError('Proxy settings changed concurrently; they were preserved.')
                    api.atomic(path, written[path])
                if not live:
                    process = start_supervisor(root)
                status = wait_ready(control, process)
                if (read(control.config_file) != before_config or hashes != source_hashes(root, api.critical)
                        or any(read(path) != written[path] for path in paths)):
                    raise RuntimeError('Configuration changed during setup; concurrent changes were preserved.')
                # Last mutating step: the shared installer handles task-migration
                # rollback itself. Do not restart or replace existing tray tasks.
                install_startup(root)
            except Exception as failure:
                rollback_errors = []
                for path in reversed(paths):
                    try:
                        if read(path) == written[path]:
                            if previous[path] is None:
                                path.unlink()
                            else:
                                api.atomic(path, previous[path])
                    except OSError:
                        rollback_errors.append('Could not restore ' + path.name)
                if process is not None:
                    try:
                        cleanup = api.cleanup(process)
                        if cleanup.get('stopped') is not True:
                            rollback_errors.append('The new supervisor could not be confirmed stopped')
                    except Exception:
                        rollback_errors.append('The new supervisor cleanup failed')
                if rollback_errors:
                    raise RuntimeError('Setup failed; ' + '; '.join(rollback_errors) +
                                       '. Codex routing was unchanged.') from failure
                raise
        return {'ok': True, 'already_configured': False, 'enabled': False, 'route_changed': False,
                'ready': status['ready'], 'validated': True,
                'next_step': 'Refresh the dashboard, turn Request compression On, then restart Codex once.'}


def helper(name, root):
    spec = importlib.util.spec_from_file_location('_setup_helper', SCRIPT.parent / name)
    module = importlib.util.module_from_spec(spec)
    previous_path = sys.path[:]
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = previous_path
    module.ROOT = root
    return module


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle-root', type=Path, required=True)
    worker = parser.add_mutually_exclusive_group()
    worker.add_argument('--prefetch-worker', action='store_true')
    worker.add_argument('--probe-worker', action='store_true')
    args = parser.parse_args(argv)
    root = args.bundle_root.resolve()
    if root != (Path.home() / 'CodexTokenSaver').resolve():
        raise ValueError('Run setup against the installed USERPROFILE/CodexTokenSaver bundle.')
    api = load_api(root)
    if args.prefetch_worker:
        module = helper('prefetch_proxy_model.py', root)
        module.MODEL_CACHE = root / 'models/huggingface'
        module.main()
    elif args.probe_worker:
        module = helper('verify_backend_receipt.py', root)
        sys.argv = [str(SCRIPT), '--runtime', api.runtime['runtime']]
        module.main()
    else:
        print(json.dumps(setup(root, api)))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Setup failed ({type(exc).__name__}): {exc}', file=sys.stderr)
        raise SystemExit(1)
