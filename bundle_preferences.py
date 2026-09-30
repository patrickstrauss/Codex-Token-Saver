"""Small shared component preferences; malformed state bypasses optional work."""
from pathlib import Path
import json

from desktop_proxy_control import atomic_write, routing_lock

LEGACY_DEFAULTS = {'rtk': True, 'headroom_local': True, 'serena': False,
                   'local_summaries': False, 'llama_cpp': False}
EXTENSIONS = {'playwright_cli': False, 'ast_grep': False, 'laya_router': False}
DEFAULTS = LEGACY_DEFAULTS | EXTENSIONS
MAX_BYTES = 16384


def _read_preferences(path, defaults):
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('size')
        data = json.loads(raw.decode('utf-8-sig'))
        if (not isinstance(data, dict) or set(data) != {'schema_version', 'components'}
                or type(data['schema_version']) is not int or data['schema_version'] != 1
                or not isinstance(data['components'], dict)
                or not set(data['components']) <= defaults.keys()
                or any(type(value) is not bool for value in data['components'].values())):
            raise ValueError('schema')
        return {'values': dict(defaults, **data['components']), 'error': None}
    except FileNotFoundError:
        return {'values': dict(defaults), 'error': None}
    except (OSError, ValueError, UnicodeError, RecursionError):
        return {'values': dict.fromkeys(defaults, False),
                'error': 'Component settings could not be read; repair settings/' + path.name + '.'}


def preference_status(root):
    # Older loaded MCP workers reject unknown component keys. Keep their file
    # byte-for-byte unchanged when enabling new extensions during a live upgrade.
    legacy = _read_preferences(Path(root) / 'settings/components.json', LEGACY_DEFAULTS)
    extensions = _read_preferences(Path(root) / 'settings/extensions.json', EXTENSIONS)
    return {'values': legacy['values'] | extensions['values'], 'error': legacy['error'],
            'extension_error': extensions['error']}


def load_preferences(root):
    return preference_status(root)['values']


def set_preference(root, key, enabled):
    if not isinstance(key, str) or key not in DEFAULTS or type(enabled) is not bool:
        raise ValueError('Choose a known component and a boolean enabled value.')
    path = Path(root) / 'settings' / ('extensions.json' if key in EXTENSIONS else 'components.json')
    with routing_lock(Path(root) / 'settings/components.lock'):
        status = preference_status(root)
        error = status['extension_error'] if key in EXTENSIONS else status['error']
        if error:
            raise ValueError(error)
        values = status['values']
        values[key] = enabled
        keys = EXTENSIONS if key in EXTENSIONS else LEGACY_DEFAULTS
        selected = {name: values[name] for name in keys}
        atomic_write(path, (json.dumps({'schema_version': 1, 'components': selected}, indent=2) + '\n').encode())
    return values
