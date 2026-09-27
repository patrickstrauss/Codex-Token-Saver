"""Owned OpenCodex extension transactions. Never edits provider routes or stops OpenCodex."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from desktop_proxy_control import atomic_write, routing_lock, _encode, _json, _read
from opencodex_integration import _json as command_json, _run, probe_opencodex, routing_uses_opencodex


def fingerprint(value):
    canonical = [value['protocol'], value['enabled'], value['endpoint'], value['tokenFile']] if value else None
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def _setting(value):
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {'protocol', 'enabled', 'endpoint', 'tokenFile'}
            or type(value['protocol']) is not int or value['protocol'] != 1 or type(value['enabled']) is not bool
            or value['endpoint'] != 'http://127.0.0.1:8789'
            or not isinstance(value['tokenFile'], str) or not Path(value['tokenFile']).is_absolute()):
        raise RuntimeError('OpenCodex extension settings are invalid')
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class OpenCodexBridge:
    def __init__(self, executable, *, run=_run):
        self.executable, self.run = executable, run

    def _call(self, arguments):
        if not self.executable:
            raise RuntimeError('OpenCodex executable is unavailable')
        try:
            value = command_json(self.run([str(self.executable), 'config', *arguments, '--json'], 5.0))
            configured = _setting(value.get('value'))
            if (type(value.get('protocol')) is not int or value['protocol'] != 1
                    or value.get('fingerprint') != fingerprint(configured)):
                raise ValueError('Invalid response')
            return {'protocol': 1, 'value': configured, 'fingerprint': value['fingerprint']}
        except Exception:
            raise RuntimeError('OpenCodex extension command failed or its reply is invalid') from None

    def read(self):
        return self._call(['token-saver-state'])

    def write(self, expected, value):
        return self._call(['token-saver-set', expected, json.dumps(value, ensure_ascii=False, separators=(',', ':'))])


class OpenCodexControl:
    def __init__(self, root, *, config_home=None, bridge=None, discovery=None, backend=None):
        import shutil
        self.root = Path(root).resolve()
        self.home = Path(config_home or os.environ.get('CODEX_HOME') or Path.home() / '.codex').resolve()
        self.state = self.root / 'proxy'
        self.receipt_file = self.state / 'opencodex-receipt.json'
        self.policy_file = self.state / 'opencodex-policy.json'
        self.settings_file = self.state / 'settings.json'
        self.token_file = self.state / 'transform-token'
        executable = shutil.which('ocx.exe')
        if not executable:
            candidate = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'OpenCodex/ocx.exe'
            executable = candidate if candidate.is_file() else None
        self.bridge = bridge or OpenCodexBridge(executable)

        def inspect():
            observed = probe_opencodex(executable=executable)
            result = asdict(observed)
            result['config_home'] = str(observed.config_home) if observed.config_home else None
            result['routing_matches'] = routing_uses_opencodex(observed, self.home, os.environ)
            return result
        self.discovery = discovery or inspect
        self.backend = backend or self._backend

    def _backend(self):
        try:
            with self.token_file.open('r', encoding='ascii') as source:
                token = source.read(65)
            if not re.fullmatch('[a-f0-9]{64}', token):
                return {}
            opener = build_opener(ProxyHandler({}), NoRedirect())
            def get(path, auth=False):
                request = Request('http://127.0.0.1:8789' + path,
                    headers={'Authorization': 'Bearer ' + token} if auth else {})
                with opener.open(request, timeout=.6) as response:
                    data = response.read(16385)
                return json.loads(data) if len(data) <= 16384 else {}
            health = get('/health')
            if (health.get('service') != 'headroom-proxy' or health.get('mode') != 'transform-only'
                    or health.get('ready') is not True):
                return {}
            capability = get('/v1/transform/capabilities', True)
            return dict(capability, mode='transform-only')
        except Exception:
            return {}

    def _receipt(self):
        value = _json(self.receipt_file)
        if value and (type(value.get('schema')) is not int or value['schema'] != 1
                      or value.get('codex_home') != str(self.home) or value.get('token_file') != str(self.token_file)
                      or not isinstance(value.get('ocx_home'), str)
                      or value.get('phase') not in ('prepared', 'warming', 'extension_pending', 'complete', 'conflict', 'disconnected')
                      or any(not isinstance(value.get(key), str) or not re.fullmatch('[a-f0-9]{64}', value[key])
                             for key in ('before_fingerprint', 'owned_fingerprint'))
                      or ('target_fingerprint' in value and (not isinstance(value['target_fingerprint'], str)
                          or not re.fullmatch('[a-f0-9]{64}', value['target_fingerprint'])))):
            raise RuntimeError('OpenCodex ownership receipt does not match this installation')
        return value

    def _save(self, receipt):
        atomic_write(self.receipt_file, _encode(receipt))

    def _policy(self, enabled):
        atomic_write(self.policy_file, _encode({'schema': 1, 'enabled': enabled}))

    def status(self):
        receipt = self._receipt()
        service = self.backend()
        configured = self.discovery()
        requested = receipt.get('requested_enabled') is True and receipt.get('phase') != 'disconnected'
        ready = service.get('ready') is True and service.get('mode') == 'transform-only' and service.get('protocol') == 1
        effective = (requested and ready and service.get('enabled') is True and configured.get('ready') is True
                     and configured.get('routing_matches') is True
                     and configured.get('extension_enabled') is True and _json(self.policy_file).get('enabled') is True)
        counts = service.get('outcomes', {})
        counts = counts if isinstance(counts, dict) else {}
        return {'mode': 'opencodex', 'managed': bool(receipt), 'requested_enabled': requested,
                'effective_enabled': effective, 'ready': ready, 'phase': receipt.get('phase', 'unmanaged'),
                'needs_reload': requested and ready and configured.get('extension_enabled') is not True,
                'reason': None if effective else 'Compression is paused or waiting for the managed transform worker.',
                'outcomes': {key: counts[key] for key in ('compressed', 'unchanged', 'bypassed', 'error')
                             if type(counts.get(key)) is int and counts[key] >= 0}}

    def _check(self, receipt, *, enabling=False):
        info = self.discovery()
        if (info.get('ready') is not True or info.get('transform_protocol') != 1 or info.get('control_protocol') != 1
                or (enabling and info.get('routing_matches') is not True)):
            raise RuntimeError('A ready OpenCodex integration and matching active route are required')
        if receipt and receipt.get('ocx_home') != info.get('config_home'):
            raise RuntimeError('OpenCodex configuration home changed; no extension update applied')
        return info

    def _owned_state(self, receipt):
        current = self.bridge.read()
        permitted = {receipt.get('owned_fingerprint')}
        if receipt.get('phase') == 'extension_pending':
            permitted.add(receipt.get('target_fingerprint'))
        if current['fingerprint'] not in permitted:
            receipt['phase'] = 'conflict'
            self._save(receipt)
            raise RuntimeError('OpenCodex extension changed outside this installation; it was preserved')
        if receipt.get('phase') == 'extension_pending' and current['fingerprint'] == receipt.get('target_fingerprint'):
            receipt['owned_fingerprint'] = current['fingerprint']
            self._save(receipt)
        return current

    def _apply(self, receipt, target):
        current = self._owned_state(receipt)
        receipt.update(target_fingerprint=fingerprint(target), phase='extension_pending')
        self._save(receipt)  # A lost response is recoverable from the persisted target fingerprint.
        if current['fingerprint'] != receipt['target_fingerprint']:
            current = self.bridge.write(current['fingerprint'], target)
        if current['fingerprint'] != receipt['target_fingerprint']:
            raise RuntimeError('OpenCodex extension update could not be verified')
        receipt['owned_fingerprint'] = current['fingerprint']
        self._save(receipt)

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Enabled must be a boolean')
        with routing_lock(self.state / 'routing.lock'):
            if not enabled:
                self._policy(False)  # Pause remains effective even if OpenCodex is unreachable.
            receipt = self._receipt()
            if not enabled:
                if not receipt:
                    return self.status()
                receipt['requested_enabled'] = False
                self._save(receipt)  # Offline pause must also cancel supervisor warmup.
            info = self._check(receipt, enabling=enabled)
            if not receipt:
                current = self.bridge.read()
                if current['value'] is not None:
                    raise RuntimeError('Existing OpenCodex extension is not owned by this installation')
                receipt = {'schema': 1, 'phase': 'prepared', 'codex_home': str(self.home),
                    'token_file': str(self.token_file), 'ocx_home': info.get('config_home'),
                    'before_fingerprint': current['fingerprint'], 'owned_fingerprint': current['fingerprint']}
            else:
                self._owned_state(receipt)
            receipt['requested_enabled'] = enabled
            self._save(receipt)
            before = _read(self.home / 'config.toml')
            if enabled:
                from request_transform_service import ensure_transform_token
                ensure_transform_token(self.root)
                self._policy(False)
                settings = _json(self.settings_file)
                settings.update(installed=True, enabled=False, mode='opencodex')
                atomic_write(self.settings_file, _encode(settings))
                service = self.backend()
                if not (service.get('ready') is True and service.get('mode') == 'transform-only' and service.get('protocol') == 1):
                    receipt['phase'] = 'warming'
                    self._save(receipt)
                    return self.status()
            target = {'protocol': 1, 'enabled': enabled, 'endpoint': 'http://127.0.0.1:8789',
                      'tokenFile': str(self.token_file)}
            self._apply(receipt, target)
            if _read(self.home / 'config.toml') != before:
                receipt['phase'] = 'conflict'
                self._save(receipt)
                raise RuntimeError('Codex settings changed during the operation; compression remains paused')
            self._policy(enabled)
            receipt['phase'] = 'complete'
            self._save(receipt)
            return self.status()


    def disconnect(self):
        with routing_lock(self.state / 'routing.lock'):
            self._policy(False)
            receipt = self._receipt()
            if not receipt:
                return self.status()
            receipt['requested_enabled'] = False
            self._save(receipt)
            self._check(receipt)
            self._apply(receipt, None)
            receipt.update(phase='disconnected', requested_enabled=False)
            self._save(receipt)
            # Keep the local retrieval worker available for unexpired originals.
            return self.status()


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'enable', 'pause', 'disconnect'))
    args = parser.parse_args()
    control = OpenCodexControl(Path(__file__).resolve().parent)
    try:
        result = (control.status() if args.action == 'status' else control.disconnect() if args.action == 'disconnect'
                  else control.set_enabled(args.action == 'enable'))
        print(json.dumps(result))
        return 0
    except (OSError, ValueError, RuntimeError):
        print(json.dumps({'error': 'OpenCodex operation could not be verified; inspect the local integration status.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
