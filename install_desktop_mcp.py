"""Register optional Headroom file tools; never change Codex's model or route."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import tomllib
import tomlkit

SERVER = 'headroom_desktop'

def server_config(root):
    root = Path(root)
    return {
        'command': str(root / 'headroom/.venv/Scripts/python.exe'),
        'args': ['-u', str(root / 'desktop_mcp.py')],
        'cwd': str(root),
        'enabled': True,
        'required': False,
        'startup_timeout_sec': 20,
        'tool_timeout_sec': 60,
        'enabled_tools': ['headroom_read_file', 'headroom_retrieve', 'headroom_stats'],
        'env': {
            'HEADROOM_WORKSPACE_DIR': str(root / 'headroom/desktop-state'),
            'HEADROOM_OFFLINE': '1', 'HEADROOM_TELEMETRY': 'off',
            'HEADROOM_LOG_PAYLOAD_PREVIEW': '0',
            'TIKTOKEN_CACHE_DIR': str(root / 'headroom/tokenizer-cache'),
            'HF_HUB_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1',
            'TRANSFORMERS_OFFLINE': '1', 'LITELLM_LOCAL_MODEL_COST_MAP': 'True',
            'PYTHONUTF8': '1',
        },
    }

def merge_config(source, root):
    desired = server_config(root)
    before = tomllib.loads(source)
    servers = before.get('mcp_servers', {})
    old = servers.get(SERVER)
    if old is not None:
        if old.get('command') != desired['command'] or old.get('args') != desired['args']:
            raise ValueError('headroom_desktop already belongs to another server; nothing changed.')
        if old == desired:
            return source
        # Preserve additional user options while keeping this integration optional.
        desired = dict(old) | desired
    document = tomlkit.parse(source)
    if 'mcp_servers' not in document:
        document['mcp_servers'] = tomlkit.table()
    document['mcp_servers'][SERVER] = desired
    output = tomlkit.dumps(document)
    if '\r\n' in source and '\n' not in source.replace('\r\n', ''):
        output = output.replace('\r\n', '\n').replace('\n', '\r\n')
    after = tomllib.loads(output)
    expected = dict(before)
    expected['mcp_servers'] = dict(servers) | {SERVER: desired}
    if after != expected:
        raise RuntimeError('Unexpected configuration change; installation stopped.')
    return output

def replace_checked(path, before, after):
    if path.read_bytes() != before:
        raise RuntimeError(f'{path.name} changed concurrently; retry installation.')
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.headroom.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != before:
            raise RuntimeError(f'{path.name} changed concurrently; retry installation.')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)

def main():
    root = Path(__file__).resolve().parent
    for relative in ('desktop_mcp.py', 'desktop_headroom.py', 'headroom/.venv/Scripts/python.exe', 'bin/rtk.exe'):
        if not (root / relative).is_file():
            raise RuntimeError(f'Installation file is missing: {relative}')
    config_home = Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
    config = config_home / 'config.toml'
    original = config.read_bytes()
    merged = merge_config(original.decode('utf-8-sig'), root).encode('utf-8')
    if original.startswith(b'\xef\xbb\xbf'):
        merged = b'\xef\xbb\xbf' + merged
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = root / 'backups' / ('desktop-mcp-' + stamp)
    backup.mkdir(parents=True)
    (backup / 'config.toml').write_bytes(original)
    if merged != original:
        replace_checked(config, original, merged)
    instructions = config_home / 'AGENTS.md'
    old_instructions = instructions.read_bytes()
    text = old_instructions.decode('utf-8-sig')
    updated = text.replace('$env:USERPROFILE\\CodexTokenSaver\\bin\\rtk.cmd', '$env:USERPROFILE\\CodexTokenSaver\\bin\\rtk.exe')
    start, end = '<!-- BEGIN HEADROOM DESKTOP -->', '<!-- END HEADROOM DESKTOP -->'
    guidance = (start + '\nPrefer headroom_read_file for initial inspection of large local JSON, CSV, and log files. '
        'Use absolute paths. Headroom runs locally and returns compressed overviews; retrieve exact content with '
        'headroom_retrieve or compress=false before edits, precise quotations, or completeness-sensitive decisions. '
        'Do not resend already-read text for compression. If Headroom tools are absent or fail, continue with normal file tools. '
        'Keep Codex desktop on its normal connection; never enable global proxy routing.\n' + end)
    if start in updated and end in updated:
        left, rest = updated.split(start, 1)
        _, right = rest.split(end, 1)
        updated = left + guidance + right
    else:
        updated = updated.rstrip() + '\n\n' + guidance + '\n'
    if updated != text:
        (backup / 'AGENTS.md').write_bytes(old_instructions)
        replace_checked(instructions, old_instructions, updated.encode('utf-8'))
    state = tomllib.loads(config.read_text(encoding='utf-8-sig'))
    receipt = {'configured': True, 'server': SERVER, 'transport': 'stdio', 'required': False,
        'scope': 'large local file reads', 'timestamp': datetime.now(timezone.utc).isoformat(),
        'config': str(config), 'backup': str(backup), 'model': state.get('model'),
        'reasoning': state.get('model_reasoning_effort'), 'provider': state.get('model_provider', 'openai'),
        'global_proxy_route_added': False, 'restart_existing_desktop_session_to_load_tools': True}
    (root / 'desktop-integration.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt))

if __name__ == '__main__':
    main()
