"""Token-only measurements of transform replies, independent of native-proxy history."""
from datetime import datetime
import json
from pathlib import Path
import threading

_write_lock = threading.Lock()


def record_transform(root, token_counter, value, result, *, now=None):
    """Run after the HTTP response; a measurement failure cannot fail compression."""
    if result.get('outcome') not in ('compressed', 'unchanged', 'bypassed'):
        return False
    try:
        entries = {entry['id']: entry['text'] for entry in value['entries']}
        before = {key: token_counter(text) for key, text in entries.items()}
        after = dict(before)
        for replacement in result['replacements']:
            after[replacement['id']] = token_counter(replacement['replacement'])
        original, reduced = sum(before.values()), sum(after.values())
        if any(type(n) is not int or n < 0 for n in (*before.values(), *after.values())):
            return False
        row = {'ts': (now or datetime.now().astimezone()).isoformat(),
               'before': original, 'after': reduced, 'saved': original - reduced,
               'outcome': result['outcome']}
        path = Path(root) / 'proxy/transform-state/savings_events.jsonl'
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row, separators=(',', ':')) + '\n')
        return True
    except Exception:
        return False
