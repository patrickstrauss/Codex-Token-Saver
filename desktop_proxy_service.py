"""Own and supervise the local Codex gateway independently of its tray UI.

The gateway stays available in direct mode while optimization is paused. A
running backend is retained on pause so existing streams can finish. Only an
explicit supervisor shutdown stops its retained child process handles. This
module never edits Codex routing, scans for process IDs, or imports Headroom.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import threading
import time
from urllib.request import ProxyHandler, build_opener

from service_control import ServiceController

ROOT = Path(__file__).resolve().parent
BACKOFF = (1, 2, 5, 15, 30)
HEARTBEAT_SECONDS = 30


@contextmanager
def lifetime_lock(path):
    """Nonblocking, process-lifetime lock; the lock file is never unlinked."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        acquired = False
        try:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            pass
        try:
            yield acquired
        finally:
            if acquired:
                stream.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)


def _read_json(path, limit=16384):
    with Path(path).open('rb') as source:
        data = source.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Local status/configuration file exceeds its size limit')
    value = json.loads(data.decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('Expected a JSON object')
    return value


def process_identity(pid):
    """Read process creation identity without signaling or claiming that PID."""
    if type(pid) is not int or pid <= 0 or os.name != 'nt':
        return None
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
            return None
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(v) for v in (created, exited, system, user))):
            return None
        return {'created': (created.dwHighDateTime << 32) | created.dwLowDateTime}
    finally:
        kernel.CloseHandle(handle)


def read_status(root=ROOT):
    try:
        result = _read_json(Path(root) / 'proxy/service-status.json')
    except (OSError, ValueError, UnicodeError):
        result = {'service': 'codex-token-saver-proxy-supervisor', 'available': False}
    try:
        stamp = datetime.fromisoformat(result['timestamp'].replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
    except (KeyError, TypeError, ValueError, AttributeError):
        age = None
    identity = result.get('process_identity')
    live = (identity is not None and process_identity(result.get('pid')) == identity
            and age is not None and 0 <= age <= HEARTBEAT_SECONDS)
    result.update(live=live, available=live, heartbeat_age_seconds=round(age, 1) if age is not None else None,
                  last_error=None if live else 'Supervisor is missing or its heartbeat is stale.')
    return result


def ensure_supervisor(root=ROOT):
    """Called by the existing tray refresh; never stops or adopts workers."""
    root = Path(root)
    status = read_status(root)
    try:
        if _read_json(root / 'proxy/settings.json').get('installed') is not True or status['live']:
            return status
        with lifetime_lock(root / 'proxy/recovery.lock') as recovering:
            if not recovering:
                return status
            with lifetime_lock(root / 'proxy/supervisor.lock') as absent:
                if not absent:
                    status['last_error'] = 'Supervisor lock is held; heartbeat is stale. Existing processes were preserved.'
                    return status
            attempt_path = root / 'proxy/recovery-attempt.json'
            try:
                previous = _read_json(attempt_path).get('attempted_at', 0)
            except (OSError, ValueError, UnicodeError):
                previous = 0
            now = time.time()
            if type(previous) in (int, float) and 0 <= now - previous < 60:
                return dict(status, starting=True)
            runtime = root / 'headroom/.venv/Scripts/pythonw.exe'
            if not runtime.is_file():
                return dict(status, last_error='Managed supervisor runtime is unavailable.')
            # Persist cooldown before spawning; the lifetime lock resolves logon/tray races.
            _write_json(attempt_path, {'attempted_at': now})
            logs = root / 'logs'
            logs.mkdir(parents=True, exist_ok=True)
            environment = os.environ.copy()
            for key in ('PYTHONPATH', 'PYTHONHOME', 'OPENAI_BASE_URL'):
                environment.pop(key, None)
            with (logs / 'proxy-supervisor.stdout.log').open('ab') as stdout, \
                 (logs / 'proxy-supervisor.stderr.log').open('ab') as stderr:
                subprocess.Popen([str(runtime), str(root / 'desktop_proxy_service.py'), 'run'],
                                 cwd=root, env=environment, stdin=subprocess.DEVNULL,
                                 stdout=stdout, stderr=stderr,
                                 creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            return dict(status, starting=True)
    except FileNotFoundError:
        return status
    except Exception as exc:
        return dict(status, last_error=f'Supervisor recovery failed ({type(exc).__name__}); check local service files.')


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@dataclass
class Worker:
    process: object = None
    failures: int = 0
    retry_at: float = 0.0
    started_at: float = 0.0
    last_error: str | None = None
    ready: bool = False


class DesktopProxyService:
    def __init__(self, root=ROOT, *, clock=time.monotonic):
        self.root = Path(root).resolve()
        self.settings_path = self.root / 'proxy/settings.json'
        self.status_path = self.root / 'proxy/service-status.json'
        self.ports = {'frontdoor': 8788, 'backend': 8789}
        self.workers = {name: Worker() for name in self.ports}
        self.clock = clock
        self._opener = build_opener(ProxyHandler({}))
        self._frontdoor_was_started = False
        self._identity = process_identity(os.getpid())

    def _settings(self):
        try:
            settings = _read_json(self.settings_path)
            if type(settings.get('installed', False)) is not bool or type(settings.get('enabled', False)) is not bool:
                raise ValueError('Settings flags must be booleans')
            installed = settings.get('installed') is True
            return installed, installed and settings.get('enabled') is True, None
        except FileNotFoundError:
            return False, False, None
        except (OSError, ValueError, UnicodeError):
            # The gateway also treats malformed settings as direct mode.
            # Preserve existing worker handles; never turn optimization on.
            return False, False, 'Proxy settings are unreadable or invalid; optimization is paused.'

    def probe(self, name):
        try:
            with self._opener.open(f'http://127.0.0.1:{self.ports[name]}/health', timeout=.4) as response:
                raw = response.read(16385)
            if len(raw) > 16384:
                return False
            value = json.loads(raw)
            if not isinstance(value, dict):
                return False
            if name == 'frontdoor':
                return (value.get('service') == 'codex-token-saver-proxy' and
                        value.get('status') == 'ok' and value.get('ready') is True)
            return ServiceController.valid_health('headroom', value)
        except (OSError, ValueError):
            return False

    def port_in_use(self, name):
        try:
            with socket.create_connection(('127.0.0.1', self.ports[name]), timeout=.2):
                return True
        except OSError:
            return False

    def _command(self, name):
        if name == 'frontdoor':
            command = [str(self.root / 'headroom/.venv/Scripts/python.exe'), '-u',
                       str(self.root / 'desktop_proxy.py'), '--port', str(self.ports[name]),
                       '--backend-port', str(self.ports['backend'])]
        else:
            # These modules expose stdlib-only builders. Import the SDK only in
            # the backend child, keeping startup of the gateway independent.
            from proxy_runtime import build_proxy_command
            from runtime_selection import selected_runtime
            command = build_proxy_command(selected_runtime(self.root), host='127.0.0.1', port=self.ports[name])
        if not Path(command[0]).is_file():
            raise FileNotFoundError('Managed Python executable is unavailable')
        return command

    def _environment(self, name):
        if name == 'backend':
            from proxy_runtime import build_proxy_environment
            return build_proxy_environment(self.root / 'proxy/backend-state', inherited=os.environ.copy())
        environment = os.environ.copy()
        for key in ('PYTHONPATH', 'PYTHONHOME', 'OPENAI_BASE_URL'):
            environment.pop(key, None)
        environment['PYTHONUTF8'] = '1'
        return environment

    def _retry(self, worker, message):
        worker.failures += 1
        worker.retry_at = self.clock() + BACKOFF[min(worker.failures - 1, len(BACKOFF) - 1)]
        worker.last_error = message

    def _tick_worker(self, name, required):
        worker = self.workers[name]
        now = self.clock()
        if worker.process is not None:
            exit_code = worker.process.poll()
            if exit_code is not None:
                # Do not target an exited launcher's PID: it no longer proves
                # ownership of any remaining descendant or a reused PID.
                worker.process = None
                self._retry(worker, f'{name} exited with code {exit_code}; restart pending.' if required else
                            f'{name} exited with code {exit_code}; optimization is paused.')
        worker.ready = self.probe(name)
        if worker.ready:
            worker.last_error = None
            if worker.process is None or now - worker.started_at >= 30:
                worker.failures = 0
                worker.retry_at = 0
            return
        if worker.process is not None:
            # A slow model import or busy response stream is not proof that a
            # child is dead. The gateway handles unavailable optimization by
            # forwarding new requests directly, without killing active work.
            return
        if not required or now < worker.retry_at:
            return
        if self.port_in_use(name):
            self._retry(worker, f'Port {self.ports[name]} is occupied by an unready or different service; left untouched.')
            return
        try:
            command = self._command(name)
            environment = self._environment(name)
            log_dir = self.root / 'logs'
            log_dir.mkdir(parents=True, exist_ok=True)
            with (log_dir / f'proxy-{name}.stdout.log').open('ab') as stdout, \
                 (log_dir / f'proxy-{name}.stderr.log').open('ab') as stderr:
                worker.process = subprocess.Popen(
                    command, cwd=self.root, env=environment, stdin=subprocess.DEVNULL,
                    stdout=stdout, stderr=stderr,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                )
            worker.started_at = now
            worker.last_error = None
            worker.ready = self.probe(name)
        except Exception as exc:
            # Do not persist command lines, environment or arbitrary exception
            # strings, which can contain credentials or request payloads.
            self._retry(worker, f'{name} could not start ({type(exc).__name__}); check its local service files.')

    def step(self):
        installed, enabled, settings_error = self._settings()
        if installed:
            self._frontdoor_was_started = True
        # After installation, preserve the cached local URL even if someone
        # removes the settings file. Only explicit shutdown tears it down.
        self._tick_worker('frontdoor', installed or self._frontdoor_was_started)
        self._tick_worker('backend', enabled)
        result = {
            'schema': 1, 'service': 'codex-token-saver-proxy-supervisor',
            'available': True, 'pid': os.getpid(),
            'process_identity': self._identity,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'installed': installed, 'enabled': enabled, 'settings_error': settings_error,
        }
        for name, worker in self.workers.items():
            result[name] = {
                'ready': worker.ready,
                'running': worker.process is not None and worker.process.poll() is None,
                'owned': worker.process is not None,
                'pid': worker.process.pid if worker.process is not None else None,
                'last_error': worker.last_error,
                'restart_attempts': worker.failures,
                'retry_in_seconds': max(0, round(worker.retry_at - self.clock(), 1)),
            }
        result['phase'] = ('unavailable' if not result['frontdoor']['ready'] else
                           'optimized' if enabled and result['backend']['ready'] else 'direct')
        try:
            _write_json(self.status_path, result)
        except OSError:
            # A full/read-only disk must not take down a functioning gateway.
            result['status_error'] = 'The supervisor could not save its status.'
        return result

    def shutdown(self):
        results = {}
        for name in ('backend', 'frontdoor'):
            worker = self.workers[name]
            if worker.process is not None:
                results[name] = ServiceController.cleanup_created_process(worker.process)
                if results[name].get('stopped'):
                    worker.process = None
        return results

    def run(self, stop_event=None):
        stop_event = stop_event or threading.Event()
        with lifetime_lock(self.root / 'proxy/supervisor.lock') as acquired:
            if not acquired:
                return 0
            logger = logging.getLogger('codex-token-saver-supervisor.' + str(id(self)))
            logger.setLevel(logging.INFO)
            logger.propagate = False
            handler = None
            try:
                (self.root / 'logs').mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(self.root / 'logs/proxy-supervisor.log',
                                              maxBytes=262144, backupCount=2, encoding='utf-8')
                handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
                logger.addHandler(handler)
            except OSError:
                pass  # A logging failure must not interrupt active connections.
            try:
                logger.info('Supervisor started pid=%s', os.getpid())
                while not stop_event.is_set():
                    try:
                        self.step()
                    except Exception as exc:
                        # Only the exception class is safe to log, not arbitrary payloads.
                        logger.error('Supervisor step failed (%s); retrying without stopping workers', type(exc).__name__)
                        stop_event.wait(5)
                    else:
                        stop_event.wait(1)
            finally:
                # Supervisor exit is not authorization to tear down active streams.
                # A later owner reuses healthy listeners; shutdown() is explicit only.
                logger.info('Supervisor stopped; existing worker processes preserved')
                if handler:
                    logger.removeHandler(handler)
                    handler.close()
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('run', 'status'), default='run')
    args = parser.parse_args()
    if args.action == 'status':
        print(json.dumps(read_status()))
        return 0
    stop_event = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop_event.set())
    return DesktopProxyService().run(stop_event)


if __name__ == '__main__':
    raise SystemExit(main())
