"""Checked OpenCodex-to-native handoff; worker lifetime belongs to the lead."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tomllib

from desktop_proxy_control import (DesktopProxyControl, LOCAL_URL, _config, _encode,
                                   _json, _read, _with_route, atomic_write, routing_lock)
from opencodex_control import OpenCodexControl


def _hash(raw):
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def _clean(raw):
    """Remove only complete root routing/catalog statements, retaining other bytes."""
    pending, output, root = '', [], True
    lines = raw.decode('utf-8-sig').split('\n')
    for index, line in enumerate(lines):
        line += '\n' if index < len(lines) - 1 else ''
        pending += line
        try:
            parsed = tomllib.loads(pending)
        except tomllib.TOMLDecodeError:
            continue
        if pending.lstrip().startswith('['):
            root = False
        if not (root and set(parsed) in ({'openai_base_url'}, {'model_catalog_json'},
                                       {'experimental_realtime_ws_base_url'})):
            output.append(pending)
        pending = ''
    if pending:
        raise ValueError('Could not identify complete owned routing statements')
    result = ''.join(output).encode('utf-8')
    if raw.startswith(b'\xef\xbb\xbf'):
        result = b'\xef\xbb\xbf' + result
    expected = _config(raw)
    for key in ('openai_base_url', 'model_catalog_json', 'experimental_realtime_ws_base_url'):
        expected.pop(key, None)
    if _config(result) != expected:
        raise ValueError('Unrelated parsed settings would change')
    return result


class Migration:
    def __init__(self, root, home=None, *, native=None, control=None):
        self.root = Path(root).resolve()
        self.home = Path(home or os.environ.get('CODEX_HOME') or Path.home() / '.codex').resolve()
        self.state = self.root / 'proxy'
        self.receipt = self.state / 'native-handoff-receipt.json'
        self.native = native or DesktopProxyControl(self.root, config_home=self.home)
        self.control = control or OpenCodexControl(self.root, config_home=self.home)

    def _profiles(self, config):
        snapshots = {}
        layers = [config, *config.get('profiles', {}).values()]
        selected = config.get('profile')
        if selected is not None:
            # The native controller validates the profile name first.
            path = self.home / (selected + '.config.toml')
            raw = _read(path)
            snapshots[str(path)] = _hash(raw)
            if raw is not None:
                if selected in config.get('profiles', {}):
                    raise ValueError('Conflicting embedded and external profiles')
                layers.append(_config(raw))
        for layer in layers:
            model = layer.get('model')
            if model is not None and (not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', model)):
                raise ValueError('A routed model is configured')
            if layer is not config and 'model_catalog_json' in layer:
                raise ValueError('A profile catalog conflicts with native routing')
            if 'experimental_realtime_ws_base_url' in layer:
                raise ValueError('A profile realtime override conflicts with native routing')
        return snapshots

    def _verify(self):
        receipt = _json(self.receipt)
        backup = self.state / 'backups/native-handoff-config.toml'
        if (receipt.get('schema') != 1 or receipt.get('kind') != 'native-handoff'
                or receipt.get('root') != str(self.root) or receipt.get('home') != str(self.home)
                or receipt.get('backup') != str(backup)
                or receipt.get('phase') not in ('preparing', 'prepared', 'connecting', 'complete')
                or _hash(_read(backup)) != receipt.get('before_sha256')):
            raise RuntimeError('Native handoff receipt or exact backup is invalid')
        if (_hash(_clean(_read(backup))) != receipt.get('prepared_sha256')
                or _hash(_encode(receipt['paused_settings'])) != receipt.get('settings_sha256')):
            raise RuntimeError('Native handoff receipt settings are invalid')
        if receipt['phase'] != 'complete':
            if (_hash(_read(self.home / 'auth.json')) != receipt.get('auth_sha256')
                    or any(_hash(_read(path)) != digest for path, digest in receipt['profiles'].items())):
                raise RuntimeError('Credentials or profile settings changed concurrently')
        return receipt

    def _save(self, receipt):
        atomic_write(self.receipt, _encode(receipt))

    def prepare(self):
        with routing_lock(self.state / 'native-handoff.lock'):
            if self.receipt.exists():
                receipt = self._verify()
                if receipt['phase'] != 'preparing':
                    if receipt['phase'] == 'prepared':
                        self._prepared(receipt)
                    return receipt
                before = _read(Path(receipt['backup']))
                after = _clean(before)
            else:
                before = _read(self.home / 'config.toml')
                config = _config(before)
                info = self.control.discovery()
                endpoint = info.get('endpoint')
                if (info.get('ready') is not True or info.get('routing_matches') is not True
                        or not isinstance(endpoint, str)
                        or not re.fullmatch(r'http://127\.0\.0\.1:[0-9]+/v1', endpoint)
                        or config.get('openai_base_url') != endpoint):
                    raise RuntimeError('The root route is not the discovered active OpenCodex route')
                catalog = config.get('model_catalog_json')
                if catalog is not None and (not isinstance(catalog, str)
                        or Path(catalog).resolve() != self.home / 'opencodex-catalog.json'):
                    raise ValueError('A foreign model catalog is configured')
                if ('experimental_realtime_ws_base_url' in config
                        and config['experimental_realtime_ws_base_url'] not in (endpoint, 'ws' + endpoint[4:])):
                    raise ValueError('A foreign realtime override is configured')
                after = _clean(before)
                clean = _config(after)
                self.native._check_routes(clean, {})
                profiles = self._profiles(clean)
                owned = self.control._receipt()
                if not owned:
                    if (info.get('extension_enabled') is not None
                            or info.get('transform_protocol') is not None
                            or info.get('control_protocol') is not None):
                        raise RuntimeError('The OpenCodex extension has no owned receipt')
                else:
                    self.control._check(owned)
                    self.control._owned_state(owned)
                settings = _read(self.state / 'settings.json')
                settings_value = _json(self.state / 'settings.json')
                if _read(self.state / 'settings.json') != settings:
                    raise RuntimeError('Request settings changed concurrently')
                paused = dict(settings_value, installed=True, enabled=False, mode='native')
                backup = self.state / 'backups/native-handoff-config.toml'
                atomic_write(backup, before)
                receipt = {'schema': 1, 'kind': 'native-handoff', 'phase': 'preparing',
                    'root': str(self.root), 'home': str(self.home), 'backup': str(backup),
                    'before_sha256': _hash(before), 'prepared_sha256': _hash(after),
                    'auth_sha256': _hash(_read(self.home / 'auth.json')), 'profiles': profiles,
                    'settings_before_sha256': _hash(settings), 'settings_sha256': _hash(_encode(paused)),
                    'settings_pause_sha256': [_hash(_encode(dict(settings_value, enabled=False))),
                        _hash(_encode(dict(settings_value, installed=True, enabled=False, mode='opencodex')))],
                    'paused_settings': paused, 'extension_paused': not bool(owned)}
                self._save(receipt)
            self._verify()
            current = _read(self.home / 'config.toml')
            if current not in (before, after):
                raise RuntimeError('Codex settings changed concurrently; nothing was restored')
            permitted_settings = (receipt['settings_before_sha256'], receipt['settings_sha256'],
                                  *receipt.get('settings_pause_sha256', []))
            if _hash(_read(self.state / 'settings.json')) not in permitted_settings:
                raise RuntimeError('Request settings changed concurrently')
            if not receipt['extension_paused']:
                self.control.set_enabled(False)
                receipt['extension_paused'] = True
                self._save(receipt)
            with routing_lock(self.state / 'routing.lock'):
                self._verify()
                settings = _read(self.state / 'settings.json')
                if _hash(settings) not in permitted_settings:
                    raise RuntimeError('Request settings changed concurrently')
                current = _read(self.home / 'config.toml')
                if current not in (before, after):
                    raise RuntimeError('Codex settings changed concurrently; nothing was restored')
                if current != after:
                    self.native._replace_config(before, after)
                if _read(self.state / 'settings.json') != settings:
                    raise RuntimeError('Request settings changed concurrently')
                atomic_write(self.state / 'settings.json', _encode(receipt['paused_settings']))
                receipt['phase'] = 'prepared'
                self._save(receipt)
            return receipt

    def _prepared(self, receipt):
        if (_hash(_read(self.home / 'config.toml')) != receipt['prepared_sha256']
                or _hash(_read(self.state / 'settings.json')) != receipt['settings_sha256']):
            raise RuntimeError('Prepared settings changed concurrently')

    def connect(self):
        with routing_lock(self.state / 'native-handoff.lock'):
            receipt = self._verify()
            if receipt['phase'] == 'complete':
                return dict(self.native.status(), phase='complete')
            if receipt['phase'] not in ('prepared', 'connecting'):
                raise RuntimeError('Prepare the native handoff first')
            prepared = _clean(_read(Path(receipt['backup'])))
            connected = _with_route(prepared, LOCAL_URL)
            active_settings = dict(receipt['paused_settings'], enabled=True)
            active_settings.setdefault('upstream_mode', 'auto')
            active_settings_hash = _hash(_encode(active_settings))
            paused_native_hash = _hash(_encode(dict(active_settings, enabled=False)))
            permitted_settings = (receipt['settings_sha256'], active_settings_hash, paused_native_hash)
            if receipt['phase'] == 'prepared':
                self._prepared(receipt)
                receipt['phase'] = 'connecting'
                self._save(receipt)
            current = _read(self.home / 'config.toml')
            if (current not in (prepared, connected)
                    or _hash(_read(self.state / 'settings.json')) not in
                    permitted_settings):
                raise RuntimeError('Connecting settings changed concurrently')
            if current == connected and not self.native._owned(_json(self.native.receipt_file)):
                raise RuntimeError('Native route ownership could not be verified')
            try:
                result = self.native.set_enabled(True)
                self._verify()
                if (_read(self.home / 'config.toml') != connected
                        or _hash(_read(self.state / 'settings.json')) != active_settings_hash):
                    raise RuntimeError('Selected settings changed during native activation')
                if not (result.get('enabled') is True and result.get('route_enabled') is True
                        and result.get('backend_ready') is True):
                    raise RuntimeError('Native activation did not become ready')
            except Exception:
                # The owned pause preserves concurrent edits and never restores backups.
                if (_read(self.home / 'config.toml') in (prepared, connected)
                        and _hash(_read(self.state / 'settings.json')) in
                        permitted_settings):
                    self.native.set_enabled(False)
                raise
            receipt['phase'] = 'complete'
            self._save(receipt)
            return dict(result, phase='complete')

    def status(self):
        receipt = self._verify() if self.receipt.exists() else {'phase': 'unprepared'}
        return dict(self.native.status(), phase=receipt['phase'], handoff='native')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'connect', 'status'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--home', type=Path)
    args = parser.parse_args(argv)
    migration = Migration(args.root, args.home)
    print(json.dumps(getattr(migration, args.action)()))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
