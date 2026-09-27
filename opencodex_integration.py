"""Read-only OpenCodex discovery; installation is not proof of active routing."""
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import tomllib
from urllib.parse import urlsplit

MAX_BYTES = 65536


@dataclass(frozen=True)
class OpenCodexProbe:
    installed: bool = False
    version: str | None = None
    config_home: Path | None = None
    endpoint: str | None = None
    ready: bool = False
    transform_protocol: int | None = None
    control_protocol: int | None = None
    extension_enabled: bool | None = None
    reason: str | None = None


def _run(argv, timeout_seconds):
    # Bound memory even if an incompatible executable emits excessive output.
    # Disk capture is private, short-lived, and never returned without validation.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=output,
                                stderr=subprocess.DEVNULL, timeout=timeout_seconds,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                shell=False)
        output.seek(0)
        text = output.read(MAX_BYTES + 1).decode('utf-8')
    return subprocess.CompletedProcess(argv, result.returncode, text, '')


def _json(result):
    if result.returncode != 0 or not isinstance(result.stdout, str):
        raise ValueError('OpenCodex command failed')
    if len(result.stdout.encode('utf-8')) > MAX_BYTES:
        raise ValueError('OpenCodex result exceeds limit')
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError('OpenCodex result is not an object')
    return value


def probe_opencodex(*, executable, run=_run):
    if executable is None or not Path(executable).is_file():
        return OpenCodexProbe(reason='OpenCodex is not installed.')
    base = {'installed': True}
    try:
        resolved = _json(run([str(executable), 'resolve', '--json'], 2.0))
        if resolved.get('schema') != 'ocx-resolve/1':
            raise ValueError('Unsupported discovery schema')
        version = resolved.get('cliVersion')
        if isinstance(version, str) and re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][\w.-]+)?', version):
            base['version'] = version
        home = resolved.get('configHome')
        if not isinstance(home, str) or not Path(home).is_absolute():
            raise ValueError('Invalid configuration home')
        base['config_home'] = Path(home)
        port = resolved.get('port', {}).get('effective')
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Invalid port')
        base['endpoint'] = f'http://127.0.0.1:{port}/v1'
        live = resolved.get('liveness', {})
        if live.get('status') != 'live':
            return OpenCodexProbe(**base, reason='OpenCodex is not confirmed running.')
        ready = _json(run([str(executable), 'ready', '--json'], 2.0))
        if (ready.get('ready') is not True or ready.get('status') != 'ready'
                or type(live.get('pid')) is not int or live['pid'] <= 0
                or ready.get('pid') != live['pid'] or ready.get('port') != port):
            return OpenCodexProbe(**base, reason='OpenCodex readiness or process identity does not match.')
        extension = ready.get('tokenSaver', {})
        protocol = extension.get('protocol') if isinstance(extension, dict) else None
        protocol = protocol if type(protocol) is int and protocol == 1 else None
        control = extension.get('control') if isinstance(extension, dict) else None
        control = control if protocol == 1 and type(control) is int and control == 1 else None
        enabled = extension.get('enabled') if isinstance(extension, dict) else None
        enabled = enabled if type(enabled) is bool else None
        return OpenCodexProbe(**base, ready=True, transform_protocol=protocol,
                              control_protocol=control, extension_enabled=enabled,
                              reason=None if protocol else 'OpenCodex integration required.')
    except (OSError, ValueError, TypeError, AttributeError, RecursionError, subprocess.SubprocessError):
        # Never return raw process output, which can contain configuration or secrets.
        return OpenCodexProbe(**base, reason='OpenCodex status could not be verified.')


def _toml(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Configuration exceeds limit')
    return tomllib.loads(raw.decode('utf-8-sig'))


def routing_uses_opencodex(probe, config_home, environ):
    """Compare effective on-disk routing, never claim an open chat reloaded it."""
    if not probe.endpoint:
        return None
    try:
        path = Path(config_home) / 'config.toml'
        config = _toml(path) if path.exists() else {}
        selected = config.get('profile')
        layer = dict(config)
        if selected is not None:
            if not isinstance(selected, str) or not re.fullmatch(r'[\w.-]+', selected) or selected in ('.', '..'):
                return None
            profiles = config.get('profiles', {})
            if not isinstance(profiles, dict):
                return None
            embedded = profiles.get(selected)
            external_path = Path(config_home) / (selected + '.config.toml')
            if external_path.exists():
                if embedded is not None:
                    return None  # Ambiguous profile precedence; do not guess.
                embedded = _toml(external_path)
            if not isinstance(embedded, dict):
                return None
            layer.update(embedded)
        provider = layer.get('model_provider', 'openai')
        providers = layer.get('model_providers', {})
        if not isinstance(providers, dict):
            return None
        if provider == 'openai':
            endpoint = environ.get('OPENAI_BASE_URL') or layer.get('openai_base_url')
            if any(environ.get(key) for key in ('OPENAI_API_BASE', 'AZURE_OPENAI_ENDPOINT', 'CODEX_OSS_BASE_URL')):
                return None
            if 'openai' in providers:
                return None
        else:
            entry = providers.get(provider, {})
            endpoint = entry.get('base_url') if isinstance(entry, dict) else None
        if endpoint is None:
            return False if provider == 'openai' else None
        if not isinstance(endpoint, str):
            return None
        actual, expected = urlsplit(endpoint), urlsplit(probe.endpoint)
        return (actual.scheme == expected.scheme and actual.hostname == expected.hostname
                and actual.port == expected.port and not actual.username and not actual.password
                and not actual.query and not actual.fragment
                and actual.path.rstrip('/') in ('/v1', '/backend-api/codex'))
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        return None


class OpenCodexDiscovery:
    """Cache subprocess probes; dashboard polling must not spawn them repeatedly."""
    def __init__(self, *, probe=probe_opencodex, clock=time.monotonic):
        self.probe, self.clock = probe, clock
        self._at, self._value, self._key = float('-inf'), None, None
        self._lock = threading.Lock()

    def __call__(self):
        executable = shutil.which('ocx.exe')
        if not executable:
            candidate = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'OpenCodex/ocx.exe'
            executable = candidate if candidate.is_file() else None
        home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
        key = (str(executable), str(home))
        with self._lock:
            if self._value is None or self._key != key or self.clock() - self._at >= 30:
                self._value = self.probe(executable=executable)
                self._at, self._key = self.clock(), key
            observed = asdict(self._value)
            observed['config_home'] = str(self._value.config_home) if self._value.config_home else None
            observed['routing_matches'] = routing_uses_opencodex(self._value, home, os.environ)
            return observed


discovery_status = OpenCodexDiscovery()
