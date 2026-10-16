"""Rolling 24-hour totals over the proxy's token-only savings ledger.

Headroom 0.37 writes positive savings only, not every request. ``complete``
describes parsing coverage of that ledger, not coverage of all model traffic.
Signed deltas remain supported if a future producer includes expansion costs.
"""
from datetime import datetime, timedelta, timezone
import json


def _lines(stream, remaining):
    """Bound both scan size and line allocation, even for malformed ledgers."""
    while remaining > 0:
        line = stream.readline(min(remaining, 64 * 1024))
        if not line:
            break
        remaining -= len(line)
        yield line


def request_windows(path, now=None, max_bytes=32 * 1024 * 1024):
    # Calculate elapsed time in UTC, including across local midnight and DST.
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoffs = {'last_24_hours': now - timedelta(hours=24)}
    windows = {key: {'requests': 0, 'input_tokens': 0, 'saved_tokens': 0,
                     'reduction_pct': None, 'last_recorded_at': None} for key in cutoffs}
    result = {'available': False, 'complete': False, 'truncated': False,
              'invalid_records': 0, 'scope': 'all_tasks',
              'collected_at': now.isoformat(), 'windows': windows}
    valid = 0
    try:
        with path.open('rb') as stream:
            size = stream.seek(0, 2)
            offset = max(0, size - max_bytes)
            stream.seek(offset)
            if offset:
                stream.readline(64 * 1024)  # Discard a possibly partial first record.
            result['truncated'] = bool(offset)
            for line in _lines(stream, size - stream.tell()):
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
    except OSError:
        return result
    for window in windows.values():
        if window['input_tokens']:
            window['reduction_pct'] = round(100 * window['saved_tokens'] / window['input_tokens'], 1)
    result['available'] = bool(valid) or size == 0
    result['complete'] = not (result['truncated'] or result['invalid_records'])
    return result
