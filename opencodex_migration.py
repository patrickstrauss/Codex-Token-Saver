"""Explicit native-to-OpenCodex handoff using each application's owned controls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import tomllib

from desktop_proxy_control import DesktopProxyControl, _json, _read, _encode, atomic_write, routing_lock
from opencodex_control import OpenCodexControl
from desktop_proxy_service import ensure_supervisor


PROTECTED = ('model', 'model_provider', 'profile', 'model_reasoning_effort',
             'model_reasoning_summary', 'approval_policy', 'sandbox_mode')


def protected(home):
    config = tomllib.loads((_read(home / 'config.toml') or b'').decode('utf-8-sig'))
    result = {'root': {key: config.get(key) for key in PROTECTED},
        'profiles': {name: {key: profile.get(key) for key in PROTECTED}
            for name, profile in config.get('profiles', {}).items()}}
    auth = _read(home / 'auth.json')
    result['auth_sha256'] = hashlib.sha256(auth).hexdigest() if auth is not None else None
    return result


class Migration:
    def __init__(self, root, home=None, *, native=None, control=None, ensure_worker=None):
        self.root = Path(root).resolve()
        self.home = Path(home or os.environ.get('CODEX_HOME') or Path.home() / '.codex').resolve()
        self.receipt = self.root / 'proxy/migration-receipt.json'
        self.native = native or DesktopProxyControl(self.root, config_home=self.home)
        self.control = control or OpenCodexControl(self.root, config_home=self.home)
        self.ensure_worker = ensure_worker or ensure_supervisor

    def verify(self):
        receipt = _json(self.receipt)
        if (receipt.get('schema') != 1 or receipt.get('home') != str(self.home)
                or receipt.get('phase') not in ('preparing', 'prepared', 'connected')
                or (receipt['phase'] != 'connected' and receipt.get('protected') != protected(self.home))):
            raise RuntimeError('Selected settings or credentials changed; inspect before continuing. No old settings were restored.')
        return receipt

    def prepare(self):
        with routing_lock(self.root / 'proxy/migration.lock'):
            # Verify the patched binary's offline control API before touching a route.
            state = self.control.bridge.read()
            if self.receipt.exists():
                receipt = self.verify()
                if receipt['phase'] != 'preparing':
                    return receipt
            else:
                if state['value'] is not None:
                    raise RuntimeError('An existing extension must be managed by its original owner')
                receipt = {'schema': 1, 'home': str(self.home), 'protected': protected(self.home), 'phase': 'preparing'}
                atomic_write(self.receipt, _encode(receipt))
            self.native.set_enabled(False)
            self.verify()
            receipt['phase'] = 'prepared'
            atomic_write(self.receipt, _encode(receipt))
            return receipt

    def connect(self):
        with routing_lock(self.root / 'proxy/migration.lock'):
            receipt = self.verify()
            before = protected(self.home)
            info = self.control.discovery()
            if (not info.get('ready') or info.get('routing_matches') is not True
                    or info.get('transform_protocol') != 1 or info.get('control_protocol') != 1):
                raise RuntimeError('Start the patched OpenCodex and enable its Codex integration; its owned route must be active.')
            result = self.control.set_enabled(True)
            if protected(self.home) != before:
                try:
                    self.control.set_enabled(False)
                finally:
                    raise RuntimeError('Selected settings changed during activation; compression was paused.')
            self.verify()
            receipt['phase'] = 'connected'
            atomic_write(self.receipt, _encode(receipt))
            # Enabling records intent; a tray or logon task may not be running.
            # Use the existing lifetime-lock recovery path, never start/kill a
            # listener directly or change the user's startup preferences here.
            worker = self.ensure_worker(self.root)
            if not worker.get('live') and not worker.get('starting') and not result.get('effective_enabled'):
                result = dict(result, reason=worker.get('last_error') or 'The managed transform worker could not be started.')
            return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'connect', 'status'))
    parser.add_argument('--start', action='store_true', help='Start OpenCodex through its normal CLI after preparing the handoff')
    args = parser.parse_args()
    migration = Migration(Path(__file__).resolve().parent)
    if args.action == 'prepare':
        result = migration.prepare()
    elif args.action == 'status':
        migration.verify()
        result = migration.control.status()
    else:
        migration.prepare()
        if args.start and not migration.control.discovery().get('ready'):
            executable = migration.control.bridge.executable
            flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            # The server inherits the user's effective config homes. No shell, credentials,
            # model overrides, process kills, or global environment writes here.
            child = subprocess.Popen([str(executable), 'start'], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline and not migration.control.discovery().get('ready'):
                if child.poll() is not None:
                    break
                time.sleep(1)
        result = migration.connect()
    print(json.dumps(result))
    if args.action == 'status' and result.get('effective_enabled') is not True:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
