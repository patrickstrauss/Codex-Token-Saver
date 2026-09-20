"""Small shared component preferences; malformed state bypasses optional work."""
from pathlib import Path
import json

from desktop_proxy_control import atomic_write, routing_lock

DEFAULTS = {'rtk': True, 'headroom_local': True, 'serena': False,
            'local_summaries': False, 'llama_cpp': False}
MAX_BYTES = 16384


def preference_status(root):
    path = Path(root) / 'settings/components.json'
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('size')
        data = json.loads(raw.decode('utf-8-sig'))
        if (not isinstance(data, dict) or set(data) != {'schema_version', 'components'}
                or type(data['schema_version']) is not int or data['schema_version'] != 1
                or not isinstance(data['components'], dict)
                or not set(data['components']) <= DEFAULTS.keys()
                or any(type(value) is not bool for value in data['components'].values())):
            raise ValueError('schema')
        return {'values': dict(DEFAULTS, **data['components']), 'error': None}
    except FileNotFoundError:
        return {'values': dict(DEFAULTS), 'error': None}
    except (OSError, ValueError, UnicodeError, RecursionError):
        return {'values': dict.fromkeys(DEFAULTS, False),
                'error': 'Component settings could not be read. Compression is bypassed; repair settings/components.json.'}


def load_preferences(root):
    return preference_status(root)['values']


def set_preference(root, key, enabled):
    if not isinstance(key, str) or key not in DEFAULTS or type(enabled) is not bool:
        raise ValueError('Choose a known component and a boolean enabled value.')
    path = Path(root) / 'settings/components.json'
    with routing_lock(path.with_suffix('.lock')):
        status = preference_status(root)
        if status['error']:
            raise ValueError(status['error'])
        values = status['values']
        values[key] = enabled
        atomic_write(path, (json.dumps({'schema_version': 1, 'components': values}, indent=2) + '\n').encode())
    return values
