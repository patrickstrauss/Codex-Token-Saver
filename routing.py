"""Inspect or remove the legacy global route; never enable global routing."""
import argparse
import json
import os
import tempfile
import tomllib
from datetime import datetime
from pathlib import Path

START = '# BEGIN CODEX TOKEN SAVER ROUTE'
END = '# END CODEX TOKEN SAVER ROUTE'
LOCAL_URL = 'http://127.0.0.1:8787/v1'
LEGACY_PROVIDER = {
    'name': 'OpenAI via local Headroom',
    'base_url': LOCAL_URL,
    'wire_api': 'responses',
    'supports_websockets': True,
    'requires_openai_auth': True,
}
ENABLE_ERROR = ('Global Headroom routing is disabled because it can prevent Codex from '
                'working when the local proxy stops. Use codex-headroom for an '
                'experimental per-process session. No Codex settings were changed.')


def _statements(content):
    """Yield complete TOML statements without mistaking multiline values for keys.

    Parse one accumulating statement at a time, retaining its original bytes as
    text. The caller validates the complete document first. Splitting only on LF
    is deliberate: Unicode line separators inside comments are not TOML lines.
    """
    pending = ''
    lines = content.split('\n')
    for index, line in enumerate(lines):
        pending += line + ('\n' if index < len(lines) - 1 else '')
        try:
            parsed = tomllib.loads(pending)
        except tomllib.TOMLDecodeError:
            continue
        yield pending, parsed
        pending = ''
    if pending:
        raise ValueError('Could not isolate a TOML statement; no settings changed.')


def _provider(config):
    providers = config.get('model_providers', {})
    return providers.get('headroom') if isinstance(providers, dict) else None


def _route_status(config):
    provider = _provider(config)
    return (config.get('openai_base_url') == LOCAL_URL or
            (config.get('model_provider') == 'headroom' and
             isinstance(provider, dict) and provider.get('base_url') == LOCAL_URL))


def set_route(content: str, enabled: bool) -> str:
    """Compatibility API: reject enable; conservatively remove our legacy route.

    Unmatched marker comments are harmless. They never delimit deletion ranges.
    Modified providers stay intact; only the exact generated provider is removed.
    """
    if enabled:
        raise ValueError(ENABLE_ERROR)
    config = tomllib.loads(content)
    statements = list(_statements(content))
    has_marker = any(raw.strip() in (START, END) for raw, _ in statements)
    provider = _provider(config)
    recognized = (isinstance(provider, dict) and
                  all(provider.get(key) == LEGACY_PROVIDER[key]
                      for key in ('name', 'base_url', 'wire_api')))
    pristine = (provider == LEGACY_PROVIDER and
                all(type(provider[key]) is type(value)
                    for key, value in LEGACY_PROVIDER.items()))
    remove_url = config.get('openai_base_url') == LOCAL_URL
    remove_selection = (config.get('model_provider') == 'headroom' and
                        (remove_url or recognized or (has_marker and provider is None)))
    output = []
    scope = 'root'
    for raw, parsed in statements:
        if raw.strip() in (START, END):
            continue
        if raw.lstrip().startswith('['):
            scope = ('headroom' if parsed == {'model_providers': {'headroom': {}}}
                     else 'other')
            if scope == 'headroom' and pristine:
                continue
        elif scope == 'root':
            if remove_url and parsed == {'openai_base_url': LOCAL_URL}:
                continue
            if remove_selection and parsed == {'model_provider': 'headroom'}:
                continue
        elif scope == 'headroom' and pristine and parsed:
            # A pristine provider contains exactly the generated scalar keys.
            continue
        output.append(raw)
    updated = ''.join(output)
    tomllib.loads(updated)
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['enable', 'disable', 'status'])
    args = parser.parse_args()
    # Refuse before touching files or attempting any service connection.
    if args.action == 'enable':
        raise SystemExit(ENABLE_ERROR)
    config_home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    config_file = config_home / 'config.toml'
    old_bytes = config_file.read_bytes() if config_file.exists() else b''
    content = old_bytes.decode('utf-8-sig')
    config = tomllib.loads(content)
    if args.action == 'status':
        enabled = _route_status(config)
        print(json.dumps({'enabled': enabled, 'global_route_enabled': enabled,
                          'config': str(config_file)}))
        return
    updated = set_route(content, False)
    changed = updated != content
    if changed:
        backup_dir = Path(__file__).parent / 'backups'
        backup_dir.mkdir(exist_ok=True)
        backup = backup_dir / ('config-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.toml')
        backup.write_bytes(old_bytes)
        if config_file.read_bytes() != old_bytes:
            raise RuntimeError('Codex config changed concurrently; retry.')
        fd, temp = tempfile.mkstemp(dir=config_file.parent, suffix='.token-saver.tmp')
        try:
            new_bytes = updated.encode('utf-8')
            if old_bytes.startswith(b'\xef\xbb\xbf'):
                new_bytes = b'\xef\xbb\xbf' + new_bytes
            with os.fdopen(fd, 'wb') as stream:
                stream.write(new_bytes)
            if config_file.read_bytes() != old_bytes:
                raise RuntimeError('Codex config changed concurrently; retry.')
            os.replace(temp, config_file)
        finally:
            Path(temp).unlink(missing_ok=True)
    enabled = _route_status(tomllib.loads(updated))
    print(json.dumps({'enabled': enabled, 'global_route_enabled': enabled,
                      'restart_codex': changed, 'changed': changed,
                      'config': str(config_file)}))


if __name__ == '__main__':
    main()
