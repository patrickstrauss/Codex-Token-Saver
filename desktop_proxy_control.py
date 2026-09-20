"""Owned desktop endpoint changes and aggregate-only local proxy status."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import tomllib
from urllib.request import build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parent
LOCAL_URL = 'http://127.0.0.1:8788/v1'
CRITICAL_FILES = ('desktop_proxy.py', 'proxy_runtime.py', 'exact_retrieval.py', 'desktop_proxy_service.py', 'desktop_proxy_control.py')
MAX_BYTES = 4 * 1024 * 1024
WARMUP_SECONDS = 30


def _read(path):
    try:
        with Path(path).open('rb') as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('Managed file exceeds the size limit.')
        return data
    except FileNotFoundError:
        return None


def _json(path):
    return _decode_json(_read(path))


def _decode_json(raw):
    value = json.loads(raw.decode('utf-8-sig')) if raw is not None else {}
    if not isinstance(value, dict):
        raise ValueError('Managed state is invalid.')
    return value


def _encode(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def routing_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        try:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('Another desktop routing change is running.') from exc
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _config(raw):
    return tomllib.loads((raw or b'').decode('utf-8-sig'))


def _without_route(raw):
    """Remove one parsed root statement, preserving multiline and nested values."""
    text = raw.decode('utf-8-sig')
    _config(raw)
    pending, output, root_scope = '', [], True
    # TOML comments end only at LF; Unicode separators can be ordinary comment
    # text. splitlines() would mistake their following text for a root key.
    lines = text.split('\n')
    for index, line in enumerate(lines):
        line += '\n' if index < len(lines) - 1 else ''
        pending += line
        try:
            parsed = tomllib.loads(pending)
        except tomllib.TOMLDecodeError:
            continue
        if pending.lstrip().startswith('['):
            root_scope = False
        if not (root_scope and set(parsed) == {'openai_base_url'}):
            output.append(pending)
        pending = ''
    if pending:
        raise ValueError('Could not safely identify the owned endpoint setting.')
    updated = ''.join(output).encode('utf-8')
    return (b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'') + updated


def _with_route(raw, value):
    original = raw or b''
    bom = b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b''
    content = original[len(bom):]
    newline = '\r\n' if b'\r\n' in content else '\n'
    return bom + ('openai_base_url = ' + json.dumps(value) + newline).encode('utf-8') + content


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo is not None else None
    except ValueError:
        return None


def _savings(payload, historical=False):
    result = {'available': False, 'saved_tokens': None, 'input_tokens': None, 'output_tokens': None,
              'requests': None, 'estimated': True, 'last_recorded_at': None, 'historical': historical}
    persistent = payload.get('persistent_savings', {})
    if not isinstance(persistent, dict):
        persistent = {}
    lifetime = persistent.get('lifetime', {})
    if isinstance(lifetime, dict) and _count(lifetime.get('tokens_saved')) is not None:
        result.update(available=True, saved_tokens=lifetime['tokens_saved'],
                      input_tokens=_count(lifetime.get('total_input_tokens')), requests=_count(lifetime.get('requests')))
        history = persistent.get('recent_history', [])
        if isinstance(history, list):
            for item in reversed(history):
                stamp = item.get('timestamp') if isinstance(item, dict) else None
                if _timestamp(stamp):
                    result['last_recorded_at'] = stamp
                    break
        return result
    tokens = payload.get('tokens', {})
    requests = payload.get('requests', {})
    if isinstance(tokens, dict) and _count(tokens.get('proxy_compression_saved')) is not None:
        result.update(available=True, saved_tokens=tokens['proxy_compression_saved'],
                      input_tokens=_count(tokens.get('input')), output_tokens=_count(tokens.get('output')),
                      requests=_count(requests.get('total')) if isinstance(requests, dict) else None)
    return result


class DesktopProxyControl:
    def __init__(self, root=ROOT, *, config_home=None):
        self.root = Path(root).resolve()
        self.state = self.root / 'proxy'
        self.config_home = Path(config_home or os.environ.get('CODEX_HOME') or Path.home() / '.codex').resolve()
        self.config_file = self.config_home / 'config.toml'
        self.settings_file = self.state / 'settings.json'
        self.receipt_file = self.state / 'route-receipt.json'

    def _fetch(self, url):
        # Fixed loopback destinations only; never inherit an HTTP proxy setting.
        with build_opener(ProxyHandler({})).open(url, timeout=1) as response:
            if response.status != 200:
                return {}
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return {}
        value = json.loads(data)
        return value if isinstance(value, dict) else {}

    def validation(self):
        try:
            value = _json(self.state / 'validation.json')
            stamp = _timestamp(value.get('timestamp', value.get('validated_at')))
            now = datetime.now(timezone.utc)
            # Validation belongs to the exact tested sources, not a calendar
            # interval. Unchanged installed code does not expire after a week.
            if value.get('passed') is not True or stamp is None or stamp > now:
                return False
            hashes = value.get('source_hashes')
            if not isinstance(hashes, dict) or not set(CRITICAL_FILES).issubset(hashes):
                return False
            for name in CRITICAL_FILES:
                path = self.root / name
                if path.resolve().parent != self.root:
                    return False
                raw = _read(path)
                if raw is None or hashes[name] != hashlib.sha256(raw).hexdigest():
                    return False
            return True
        except (OSError, ValueError, TypeError, UnicodeError):
            return False

    def _owned(self, receipt):
        return (receipt.get('schema') == 1 and receipt.get('url') == LOCAL_URL
                and receipt.get('config') == str(self.config_file)
                and type(receipt.get('previous_present')) is bool
                and (not receipt['previous_present'] or isinstance(receipt.get('previous_value'), str)))

    def status(self):
        errors = []
        try:
            settings = _json(self.settings_file)
        except (OSError, ValueError, UnicodeError):
            settings = {}
            errors.append('Request compression settings could not be read.')
        try:
            config = _config(_read(self.config_file))
        except (OSError, ValueError, UnicodeError):
            config = {}
            errors.append('Codex configuration could not be read safely.')
        try:
            receipt = _json(self.receipt_file)
        except (OSError, ValueError, UnicodeError):
            receipt = {}
        snapshots = []
        for url in ('http://127.0.0.1:8788/health', 'http://127.0.0.1:8788/stats', 'http://127.0.0.1:8789/stats?cached=1'):
            try:
                value = self._fetch(url)
                snapshots.append(value if isinstance(value, dict) else {})
            except (OSError, ValueError, TypeError):
                snapshots.append({})
        health, relay, backend = snapshots
        ready = (health.get('service') == 'codex-token-saver-proxy' and health.get('status') == 'ok'
                 and health.get('ready') is True)
        relay_valid = relay.get('service') == 'codex-token-saver-proxy' and relay.get('status') == 'ok'
        backend_ready = ready and relay_valid and relay.get('backend_ready') is True
        request_values = relay.get('requests', {}) if relay_valid else {}
        requests = {key: _count(request_values.get(key)) if isinstance(request_values, dict) else None
                    for key in ('optimized', 'direct', 'failed', 'active')}
        savings = _savings(backend) if backend_ready else _savings({})
        if not savings['available']:
            try:
                saved = _json(self.state / 'backend-state' / 'proxy_savings.json')
                savings = _savings({'persistent_savings': {'lifetime': saved.get('lifetime', {}),
                                      'recent_history': saved.get('history', [])}}, historical=True)
            except (OSError, ValueError, UnicodeError):
                pass
        enabled = settings.get('enabled') is True
        route_enabled = config.get('openai_base_url') == LOCAL_URL
        validated = self.validation()
        if route_enabled and not self._owned(receipt):
            errors.append('The current local endpoint has no matching ownership record.')
        return {'installed': settings.get('installed') is True, 'enabled': enabled, 'route_enabled': route_enabled,
                'ready': ready, 'backend_ready': backend_ready,
                'mode': ('offline' if not ready else 'paused' if not enabled else 'optimized' if backend_ready else 'direct'),
                'validated': validated, 'last_error': ' '.join(errors) or None,
                'restart_required': self._owned(receipt) and receipt.get('restart_required') is True,
                'requests': requests, 'savings': savings}

    def _check_routes(self, config, receipt):
        def check_layer(layer):
            if not isinstance(layer, dict):
                raise ValueError('Codex profile settings are invalid.')
            if layer.get('model_provider', 'openai') != 'openai':
                raise ValueError('A custom provider is configured; no endpoint was changed.')
            if 'openai_base_url' in layer:
                if layer is not config or layer['openai_base_url'] != LOCAL_URL or not self._owned(receipt):
                    raise ValueError('An existing endpoint is configured; no endpoint was changed.')
            providers = layer.get('model_providers', {})
            if not isinstance(providers, dict) or 'openai' in providers:
                raise ValueError('The OpenAI provider has custom settings; no endpoint was changed.')
        check_layer(config)
        profiles = config.get('profiles', {})
        if not isinstance(profiles, dict):
            raise ValueError('Codex profiles are invalid.')
        for layer in profiles.values():
            check_layer(layer)
        selected = config.get('profile')
        if selected is not None:
            if not isinstance(selected, str) or Path(selected).name != selected or selected in ('.', '..') or '/' in selected or '\\' in selected:
                raise ValueError('The selected profile cannot be resolved safely.')
            path = self.config_home / (selected + '.config.toml')
            raw = _read(path)
            if raw is None and selected not in profiles:
                raise ValueError('The selected profile could not be resolved.')
            if raw is not None:
                check_layer(_config(raw))
        for name in ('OPENAI_BASE_URL', 'OPENAI_API_BASE', 'AZURE_OPENAI_ENDPOINT', 'CODEX_OSS_BASE_URL'):
            if os.environ.get(name):
                raise ValueError('An environment endpoint is already configured; no endpoint was changed.')

    def _replace_config(self, before, after):
        _config(after)
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.desktop-proxy-', suffix='.tmp', dir=self.config_file.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(after)
                stream.flush()
                os.fsync(stream.fileno())
            if _read(self.config_file) != before:
                raise RuntimeError('Codex settings changed concurrently; no endpoint was replaced.')
            os.replace(temporary, self.config_file)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Enabled must be a boolean.')
        with routing_lock(self.state / 'routing.lock'):
            old_settings = _read(self.settings_file)
            try:
                settings = _decode_json(old_settings)
            except (ValueError, UnicodeError):
                if enabled:
                    raise
                # A damaged settings file already makes the gateway pass direct.
                # Preserve that fallback on subsequent logins as well.
                settings = {'installed': True, 'enabled': False}
            if not enabled:
                self._pause(settings, old_settings)
                return self.status()
            before = _read(self.config_file)
            config = _config(before)
            receipt = _json(self.receipt_file)
            route_present = config.get('openai_base_url') == LOCAL_URL
            self._check_routes(config, receipt)
            if settings.get('installed') is not True:
                raise RuntimeError('The request compression service is not installed.')
            if not self.validation():
                raise RuntimeError('Request compression needs current validation before enabling.')
            status = self.status()
            if not status['validated']:
                raise RuntimeError('Request compression validation changed; no endpoint was enabled.')
            after = before if route_present else _with_route(before, LOCAL_URL)
            # Request a warmup through the existing supervisor. After a paused
            # Windows login the backend intentionally has not been started yet.
            settings_bytes = self._save_settings(settings, old_settings, True)
            try:
                self._wait_for_ready(status, settings_bytes)
                if not self.validation():
                    raise RuntimeError('Request compression validation changed; no endpoint was enabled.')
                if not route_present:
                    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
                    backup = self.state / 'backups' / ('config-' + stamp + '.toml')
                    atomic_write(backup, before or b'')
                    receipt = {'schema': 1, 'config': str(self.config_file), 'url': LOCAL_URL,
                               'previous_present': 'openai_base_url' in config, 'previous_value': config.get('openai_base_url'),
                               'backup': str(backup.relative_to(self.root)), 'restart_required': True,
                               'created_at': datetime.now(timezone.utc).isoformat()}
                    atomic_write(self.receipt_file, _encode(receipt))
                # Metadata writes can overlap a user edit or app update.
                if _read(self.settings_file) != settings_bytes:
                    raise RuntimeError('Request compression settings changed concurrently; no endpoint was enabled.')
                if not self.validation():
                    raise RuntimeError('Request compression validation changed; no endpoint was enabled.')
                if before != after:
                    self._replace_config(before, after)
            except Exception:
                # Restore only our own settings write; do not overwrite concurrent edits.
                if _read(self.settings_file) == settings_bytes:
                    try:
                        atomic_write(self.settings_file, old_settings or _encode({'installed': False, 'enabled': False}))
                    except OSError:
                        pass  # Relay stays available; the owned endpoint was not committed.
                raise
        return self.status()

    def _wait_for_ready(self, status, settings_bytes):
        deadline = time.monotonic() + WARMUP_SECONDS
        while True:
            if _read(self.settings_file) != settings_bytes:
                raise RuntimeError('Request compression settings changed concurrently; no endpoint was enabled.')
            if not status.get('validated'):
                raise RuntimeError('Request compression validation changed during warmup; no endpoint was enabled.')
            if status.get('ready') and status.get('backend_ready'):
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('The compression engine did not finish warming up; Codex routing was unchanged. Try enabling again.')
            time.sleep(min(.25, remaining))
            status = self.status()

    def _save_settings(self, settings, before, enabled):
        updated = dict(settings, installed=settings.get('installed') is True, enabled=enabled)
        updated.setdefault('upstream_mode', 'auto')
        data = _encode(updated)
        if _read(self.settings_file) != before:
            raise RuntimeError('Request compression settings changed concurrently; no settings were replaced.')
        atomic_write(self.settings_file, data)
        return data

    def _pause(self, settings, old_settings):
        # Switch cached clients to direct forwarding BEFORE inspecting Codex's
        # configuration. A broken config/receipt must not block local pause.
        self._save_settings(settings, old_settings, False)
        try:
            before = _read(self.config_file)
            config = _config(before)
            if config.get('openai_base_url') != LOCAL_URL:
                return
            receipt = _json(self.receipt_file)
            if not self._owned(receipt):
                raise ValueError('No matching ownership receipt')
            after = _without_route(before)
            if receipt['previous_present']:
                after = _with_route(after, receipt['previous_value'])
            receipt['restart_required'] = True
            atomic_write(self.receipt_file, _encode(receipt))
            self._replace_config(before, after)
        except (OSError, ValueError, RuntimeError, UnicodeError):
            raise RuntimeError(
                'Request compression is paused, but the Codex endpoint could not be restored safely. '
                'The current Codex configuration was preserved; cached local connections use direct forwarding.'
            ) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'enable', 'pause'))
    args = parser.parse_args()
    control = DesktopProxyControl()
    try:
        value = control.status() if args.action == 'status' else control.set_enabled(args.action == 'enable')
        print(json.dumps(value))
        return 0
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({'error': str(exc)}))
        return 1
    except OSError:
        print(json.dumps({'error': 'The routing operation could not be saved. Check the current state before retrying.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
