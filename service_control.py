"""Independent local services. Normal startup never requires Headroom."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


@contextmanager
def startup_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        if os.name == 'nt':
            import msvcrt
            deadline = time.monotonic() + 75
            while True:
                try:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Another service startup is still running.')
                    time.sleep(.2)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


class ServiceController:
    def __init__(self, root):
        self.root = Path(root)
        self.ports = {'dashboard': 8095, 'headroom': 8787}
        self.logs = self.root / 'logs'

    @staticmethod
    def valid_health(name, value):
        if not isinstance(value, dict):
            return False
        if name == 'headroom':
            return value.get('service') == 'headroom-proxy' and value.get('status') == 'healthy' and value.get('ready') is True
        return value.get('service') == 'codex-token-saver-dashboard' and value.get('status') == 'ok'

    def probe(self, name):
        try:
            with urlopen(f'http://127.0.0.1:{self.ports[name]}/health', timeout=1) as response:
                return self.valid_health(name, json.load(response))
        except Exception:
            return False

    def port_in_use(self, name):
        try:
            with socket.create_connection(('127.0.0.1', self.ports[name]), timeout=.5):
                return True
        except OSError:
            return False

    def status(self):
        return {'dashboard': self.probe('dashboard'), 'headroom': self.probe('headroom'), 'headroom_optional': True}

    def record(self, name, ready, error=None, pid=None, cleanup=None):
        result = {'service': name, 'ready': ready, 'error': error, 'pid': pid, 'timestamp': datetime.now(timezone.utc).isoformat()}
        if cleanup is not None:
            result['cleanup'] = cleanup
        self.logs.mkdir(parents=True, exist_ok=True)
        (self.logs / f'{name}-status.json').write_text(json.dumps(result), encoding='utf-8')
        return result

    @staticmethod
    def cleanup_created_process(process):
        """Bounded cleanup of this call's Popen tree, never a discovered listener/PID."""
        result = {'attempted': False, 'stopped': False, 'error': None}
        if process.poll() is not None:
            result['error'] = 'Owned launcher exited before cleanup; no PID was targeted and descendant exit could not be confirmed.'
            return result
        if os.name != 'nt':
            result['error'] = 'Automatic process-tree cleanup is only supported on Windows.'
            return result
        # Keep the Popen object (and its Windows process handle) alive throughout
        # taskkill. The retained handle prevents this PID being reused. /T also
        # stops the actual interpreter spawned by Windows' venv python launcher.
        result['attempted'] = True
        try:
            taskkill = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/taskkill.exe'
            completed = subprocess.run(
                [str(taskkill), '/PID', str(process.pid), '/T', '/F'],
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                timeout=5, creationflags=subprocess.CREATE_NO_WINDOW, check=False,
            )
            if completed.returncode:
                detail = (completed.stderr or completed.stdout or '').strip()[:500]
                result['error'] = f'Owned process-tree cleanup failed (exit {completed.returncode}): {detail}'
                return result
            process.wait(timeout=3)
            result['stopped'] = True
        except subprocess.TimeoutExpired:
            result['error'] = 'Owned process-tree cleanup timed out; the process may still be running.'
        except Exception as exc:
            result['error'] = f'Owned process-tree cleanup failed: {exc}'
        return result

    def ensure(self, name):
        if name not in self.ports:
            raise ValueError('Unknown service')
        try:
            with startup_lock(self.root / 'service-start.lock'):
                if self.probe(name):
                    return self.record(name, True)
                if self.port_in_use(name):
                    return self.record(name, False, f'Port {self.ports[name]} is occupied by an unready or different service; it was left untouched.')
                folder = self.root / name
                command = [str(folder / '.venv/Scripts/python.exe')]
                if name == 'dashboard':
                    command += ['-u', str(folder / 'app.py')]
                else:
                    command += ['-m', 'headroom.cli', 'proxy', '--host', '127.0.0.1', '--port', str(self.ports[name]), '--mode', 'cache', '--no-telemetry', '--no-subscription-tracking', '--disable-kompress', '--no-rate-limit']
                if not Path(command[0]).is_file():
                    return self.record(name, False, f'{name} runtime is missing: {command[0]}')
                environment = os.environ.copy()
                environment.update({'PYTHONUTF8': '1', 'HOST': '127.0.0.1', 'PORT': str(self.ports['dashboard']),
                    'HEADROOM_WORKSPACE_DIR': str(self.root / 'headroom/state'),
                    'TIKTOKEN_CACHE_DIR': str(self.root / 'headroom/tokenizer-cache'),
                    'HEADROOM_TELEMETRY': 'off', 'HEADROOM_EFFORT_ROUTER': '0',
                    'LITELLM_LOCAL_MODEL_COST_MAP': 'True'})
                self.logs.mkdir(parents=True, exist_ok=True)
                with (self.logs / f'{name}.stdout.log').open('ab') as stdout, (self.logs / f'{name}.stderr.log').open('ab') as stderr:
                    process = subprocess.Popen(command, cwd=folder, env=environment, stdin=subprocess.DEVNULL,
                        stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                deadline = time.monotonic() + (60 if name == 'headroom' else 15)
                while time.monotonic() < deadline:
                    if self.probe(name):
                        return self.record(name, True, pid=process.pid)
                    if process.poll() is not None:
                        return self.record(name, False, f'{name} exited with code {process.returncode}; see logs.', process.pid)
                    time.sleep(.25)
                cleanup = self.cleanup_created_process(process)
                error = f'{name} startup timed out; no Codex settings were changed.'
                if cleanup['error']:
                    error += ' ' + cleanup['error']
                else:
                    error += ' Its newly started process tree was stopped.'
                return self.record(name, False, error, process.pid, cleanup=cleanup)
        except Exception as exc:
            return self.record(name, False, str(exc))

    def start_default(self):
        return self.ensure('dashboard')


def main():
    control = ServiceController(Path(__file__).resolve().parent)
    action = sys.argv[1] if len(sys.argv) > 1 else 'start'
    if action == 'status':
        result = control.status()
    elif action == 'start':
        result = control.start_default()
    elif action == 'start-headroom':
        result = control.ensure('headroom')
    else:
        raise ValueError('Use start, status, or start-headroom')
    print(json.dumps(result))
    return 0 if result.get('ready', True) else 1


if __name__ == '__main__':
    sys.exit(main())
