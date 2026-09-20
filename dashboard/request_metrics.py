"""Bounded, read-only windows over the request proxy's token-only event ledger."""
from datetime import datetime, timedelta
import json


def request_windows(path, now=None, max_bytes=2 * 1024 * 1024):
    now = now or datetime.now().astimezone()
    cutoffs = {'fifteen_minutes': now - timedelta(minutes=15),
               'today': now.replace(hour=0, minute=0, second=0, microsecond=0),
               'seven_days': now - timedelta(days=7)}
    windows = {key: {'requests': 0, 'input_tokens': 0, 'saved_tokens': 0,
                     'reduction_pct': None, 'last_recorded_at': None} for key in cutoffs}
    result = {'available': False, 'complete': False, 'truncated': False,
              'invalid_records': 0, 'scope': 'all_tasks',
              'collected_at': now.isoformat(), 'windows': windows}
    try:
        with path.open('rb') as stream:
            size = stream.seek(0, 2)
            offset = max(0, size - max_bytes)
            stream.seek(offset)
            if offset:
                stream.readline()  # Discard a possibly partial first record.
            raw = stream.read(max_bytes)
    except OSError:
        return result
    result['truncated'] = bool(offset)
    valid = 0
    for line in raw.splitlines():
        try:
            row = json.loads(line)
            stamp = datetime.fromisoformat(row['ts'].replace('Z', '+00:00'))
            before, after, saved = (row[k] for k in ('before', 'after', 'saved'))
            if (stamp.tzinfo is None or any(type(v) is not int for v in (before, after, saved))
                    or any(abs(v) > 2**53 - 1 for v in (before, after, saved))
                    or before < 0 or after < 0 or saved != before - after):
                raise ValueError('Invalid event')
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            result['invalid_records'] += 1
            continue
        valid += 1
        for key, cutoff in cutoffs.items():
            if cutoff <= stamp <= now:
                window = windows[key]
                window['requests'] += 1
                window['input_tokens'] += before
                window['saved_tokens'] += saved
                recorded = stamp.isoformat()
                previous = window['last_recorded_at']
                if previous is None or stamp > datetime.fromisoformat(previous):
                    window['last_recorded_at'] = recorded
    for window in windows.values():
        if window['input_tokens']:
            window['reduction_pct'] = round(100 * window['saved_tokens'] / window['input_tokens'], 1)
    result['available'] = bool(valid) or size == 0
    result['complete'] = not (result['truncated'] or result['invalid_records'])
    return result
